"""IN-06 lifecycle transitions over a real install in a fabricated home."""

import contextlib
import sqlite3

import pytest

from orbit_backend.appdb import AppDB
from orbit_backend.install import lifecycle, store
from orbit_backend.install.errors import InstallError
from orbit_backend.install.service import InstallService

PERM = {"kind": "permission_rule", "id": "ro-ls", "payload": {"allow": ["ls"]}}
SKILL = {"kind": "skill", "id": "pdf-fill", "payload": {"name": "pdf-fill",
                                                        "files": [{"rel": "SKILL.md", "text": "# pdf\n"}]}}
DAY = 86_400_000


class ToolCalls:
    """Minimal orbit.db read pool: only the tool_call columns lifecycle.record_usage reads."""

    def __init__(self, path):
        self.path = path
        with contextlib.closing(sqlite3.connect(path)) as db, db:
            db.execute("CREATE TABLE tool_call (call_uid TEXT PRIMARY KEY, name TEXT, skill TEXT, "
                       "mcp_server TEXT, started_at INTEGER, ended_at INTEGER)")

    def add(self, uid, ts, *, skill=None, mcp_server=None, name="Skill"):
        with contextlib.closing(sqlite3.connect(self.path)) as db, db:
            db.execute("INSERT INTO tool_call VALUES (?,?,?,?,?,?)", (uid, name, skill, mcp_server, ts, None))

    @contextlib.contextmanager
    def read(self):
        db = sqlite3.connect(self.path)
        try:
            yield db
        finally:
            db.close()


def install(svc, spec):
    plan = svc.plan({"type": "spec", "spec": spec}, agents=["claude_code"])
    return svc.apply(plan["plan_id"], svc.preview(plan["plan_id"])["preview_digest"])["install_id"]


@pytest.fixture
def installed(tmp_path, env):
    db = AppDB(tmp_path / "orbit" / "app.db")
    svc = InstallService(db, tmp_path / "orbit", env=env)
    plan = svc.plan({"type": "spec", "spec": PERM}, agents=["claude_code"])
    result = svc.apply(plan["plan_id"], svc.preview(plan["plan_id"])["preview_digest"])
    yield svc, result["install_id"]
    db.close()


def ledger_actions(svc, install_id):
    return [r["action"] for r in store.ledger_for(svc.appdb, install_id)]


def test_transition_table(installed):
    svc, iid = installed
    assert lifecycle.transition(svc, iid, "kept")["state"] == "kept"
    with pytest.raises(InstallError) as bad:
        lifecycle.transition(svc, iid, "observing")
    assert (bad.value.code, bad.value.http) == ("bad_transition", 409)
    with pytest.raises(InstallError):
        lifecycle.transition(svc, iid, "nonsense")
    archived = lifecycle.transition(svc, iid, "archived")
    assert archived["state"] == "archived" and archived["archived_at"]
    assert ledger_actions(svc, iid)[-2:] == ["enable", "archive"]
    restored = lifecycle.transition(svc, iid, "installed")
    assert restored["state"] == "installed" and restored["archived_at"] is None
    assert lifecycle.transition(svc, iid, "reverted")["state"] == "reverted"
    with pytest.raises(InstallError):
        lifecycle.transition(svc, iid, "installed")  # reverted is terminal except archive
    assert lifecycle.transition(svc, iid, "archived")["state"] == "archived"


def test_sweep_and_mark_triggered(installed):
    svc, perm = installed
    iid = install(svc, SKILL)
    state = store.state_get(svc.appdb, iid)
    assert lifecycle.sweep(svc, state["installed_at"] + 29 * DAY) == {"idle": 0, "kept": 0}
    # Only the skill idles; a permission rule leaves no per-use record, so it never idles on silence.
    assert lifecycle.sweep(svc, state["installed_at"] + 31 * DAY) == {"idle": 1, "kept": 0}
    assert store.state_get(svc.appdb, iid)["state"] == "idle"
    assert store.state_get(svc.appdb, perm)["state"] == "installed"
    assert ledger_actions(svc, iid)[-1] == "disable"
    woke = lifecycle.mark_triggered(svc, iid, state["installed_at"] + 32 * DAY)
    assert woke["state"] == "installed" and woke["last_triggered_at"] == state["installed_at"] + 32 * DAY
    assert store.ledger_for(svc.appdb, iid)[-1]["actor"] == "agent"
    with pytest.raises(InstallError) as missing:
        lifecycle.mark_triggered(svc, "in_nope", 1)
    assert missing.value.http == 404


def test_record_usage_keeps_used_skill_alive(installed, tmp_path):
    svc, _ = installed
    iid = install(svc, SKILL)
    t0 = store.state_get(svc.appdb, iid)["installed_at"]
    calls = ToolCalls(tmp_path / "orbit.db")
    calls.add("before", t0 - DAY, skill="pdf-fill")          # before install: not evidence of this install
    calls.add("other", t0 + 20 * DAY, skill="other-skill")
    assert lifecycle.record_usage(svc, calls) == 0
    calls.add("used", t0 + 20 * DAY, skill="anthropic:pdf-fill")  # plugin-namespaced skill name
    assert lifecycle.record_usage(svc, calls) == 1
    assert store.state_get(svc.appdb, iid)["last_triggered_at"] == t0 + 20 * DAY
    assert lifecycle.record_usage(svc, calls) == 0  # nothing newer
    # 31 days after install but only 11 after the last use: stays installed.
    assert lifecycle.sweep(svc, t0 + 31 * DAY) == {"idle": 0, "kept": 0}
    assert store.state_get(svc.appdb, iid)["state"] == "installed"
    # 30 days of silence after the last use: idle.
    assert lifecycle.sweep(svc, t0 + 51 * DAY) == {"idle": 1, "kept": 0}


def test_record_usage_without_orbit_db(installed):
    svc, _ = installed
    assert lifecycle.record_usage(svc, None) == 0  # service.reads is None in the fixture


def _observing(svc, iid, until):
    with svc.appdb.write() as db:
        store.state_update(db, iid, state="observing", observe_until=until)


def test_observing_window_expires_to_kept_or_idle(installed, tmp_path):
    svc, perm = installed
    used, unused = install(svc, SKILL), install(svc, {**SKILL, "id": "csv", "payload": {**SKILL["payload"],
                                                                                        "name": "csv"}})
    t0 = store.state_get(svc.appdb, used)["installed_at"]
    for iid in (used, unused, perm):
        _observing(svc, iid, t0 + 7 * DAY)
    calls = ToolCalls(tmp_path / "orbit.db")
    calls.add("c1", t0 + 2 * DAY, skill="pdf-fill")
    assert lifecycle.record_usage(svc, calls) == 1
    assert lifecycle.sweep(svc, t0 + 6 * DAY) == {"idle": 0, "kept": 0}  # window still open
    assert lifecycle.sweep(svc, t0 + 7 * DAY) == {"idle": 1, "kept": 2}
    states = {i: store.state_get(svc.appdb, i) for i in (used, unused, perm)}
    assert states[used]["state"] == "kept" and states[used]["observe_until"] is None
    assert states[unused]["state"] == "idle"
    assert states[perm]["state"] == "kept"  # unobservable kind: no proof of disuse
    assert store.ledger_for(svc.appdb, used)[-1]["note"] == "observing->kept"
    assert store.ledger_for(svc.appdb, unused)[-1]["action"] == "disable"
