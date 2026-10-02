"""Rerunning import without flags must not learn the evaluation conversation."""

import json

import pytest

from tandem_backend.cli import demo_home
from tandem_backend.store import Store, import_codex


def test_omitted_flags_preserve_snapshot_and_held_out_sessions(tmp_path):
    home = demo_home(tmp_path / "codex")
    store = Store(tmp_path / "data.sqlite")
    policy = import_codex(store, home, before="2026-01-01T00:00:05Z", exclude_sessions={"demo-0"}).sample_policy
    replay = import_codex(store, home)
    assert replay.sample_policy == policy
    assert "demo-0" not in {s["id"] for s in store.sessions()}
    assert replay.unchanged == 2
    path = home / "sessions" / "future.jsonl"
    path.write_text(json.dumps({"type": "session_meta", "timestamp": "2026-02-01T00:00:00Z",
                                "payload": {"id": "future", "source": "cli", "cwd": "/fictional/p"}}) + "\n")
    import_codex(store, home)
    assert "future" not in {s["id"] for s in store.sessions()}


def test_expansion_requires_explicit_reset_and_keeps_homes_separate(tmp_path):
    first = demo_home(tmp_path / "first")
    store = Store(tmp_path / "data.sqlite")
    import_codex(store, first, before="2025-12-31T00:00:00Z")
    with pytest.raises(ValueError, match="reset-sample-policy"):
        import_codex(store, first, before="2026-12-01T00:00:00Z")
    assert store.counts()["sessions"] == 0
    import_codex(store, first, reset_sample_policy=True)
    assert store.counts()["sessions"] == 3
    another = demo_home(tmp_path / "another")
    assert import_codex(store, another).sample_policy == {"before": None, "exclude": []}


def test_existing_per_file_filters_are_adopted_when_policy_table_is_empty(tmp_path):
    home = demo_home(tmp_path / "codex")
    store = Store(tmp_path / "data.sqlite")
    import_codex(store, home, exclude_sessions={"demo-0"})
    with store.connect() as conn:
        conn.execute("DELETE FROM sample_policies")
    result = import_codex(store, home)
    assert result.sample_policy["exclude"] == ["demo-0"]
    assert "demo-0" not in {s["id"] for s in store.sessions()}


def test_tightened_policy_survives_a_later_import_failure(tmp_path, monkeypatch):
    home = demo_home(tmp_path / "codex")
    store = Store(tmp_path / "data.sqlite")
    import_codex(store, home)

    def cannot_read(*args, **kwargs):
        raise OSError("source temporarily unavailable")

    monkeypatch.setattr("tandem_backend.legacy.store.parse_rollout", cannot_read)
    with pytest.raises(OSError):
        import_codex(store, home, exclude_sessions={"demo-0"})
    assert store.counts()["sessions"] == 0
    with store.connect() as conn:
        saved = json.loads(conn.execute("SELECT data FROM sample_policies").fetchone()[0])
    assert saved["exclude"] == ["demo-0"]


@pytest.mark.parametrize("policy", [{"before": "", "exclude": []}, {"before": None, "exclude": "demo-0"}, {"exclude": []}])
def test_corrupt_policy_does_not_silently_widen_the_sample(tmp_path, policy):
    home = demo_home(tmp_path / "codex")
    store = Store(tmp_path / "data.sqlite")
    import_codex(store, home, exclude_sessions={"demo-0"})
    with store.connect() as conn:
        conn.execute("UPDATE sample_policies SET data=?", (json.dumps(policy),))
    with pytest.raises(ValueError, match="配置损坏"):
        import_codex(store, home)
    assert "demo-0" not in {s["id"] for s in store.sessions()}
