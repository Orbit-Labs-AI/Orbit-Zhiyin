"""IN-06 lifecycle transitions over a real install in a fabricated home."""

import pytest

from tandem_backend.appdb import AppDB
from tandem_backend.install import lifecycle, store
from tandem_backend.install.errors import InstallError
from tandem_backend.install.service import InstallService

PERM = {"kind": "permission_rule", "id": "ro-ls", "payload": {"allow": ["ls"]}}


@pytest.fixture
def installed(tmp_path, env):
    db = AppDB(tmp_path / "tandem" / "app.db")
    svc = InstallService(db, tmp_path / "tandem", env=env)
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
    svc, iid = installed
    state = store.state_get(svc.appdb, iid)
    assert lifecycle.sweep(svc, state["installed_at"] + 29 * 86_400_000) == 0
    assert lifecycle.sweep(svc, state["installed_at"] + 31 * 86_400_000) == 1
    assert store.state_get(svc.appdb, iid)["state"] == "idle"
    assert ledger_actions(svc, iid)[-1] == "disable"
    woke = lifecycle.mark_triggered(svc, iid, state["installed_at"] + 32 * 86_400_000)
    assert woke["state"] == "installed" and woke["last_triggered_at"] == state["installed_at"] + 32 * 86_400_000
    assert store.ledger_for(svc.appdb, iid)[-1]["actor"] == "agent"
    with pytest.raises(InstallError) as missing:
        lifecycle.mark_triggered(svc, "in_nope", 1)
    assert missing.value.http == 404
