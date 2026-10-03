"""recommend_inputs in the analysis worker: no FeatureService is bound there, so the
linked inventory is read directly from ``home`` (read-only) instead of the raw scan."""

from __future__ import annotations

from orbit_backend import features
from orbit_backend.recommend import section


def test_unbound_worker_reads_linked_inventory(world, monkeypatch):
    monkeypatch.setattr(features, "_service", None)
    world.item("cat-notes", "skill", "note-taker")
    world.inventory("claude_code", [{"inv_id": "sk1", "type": "skill", "name": "note-taker",
                                     "config_path": "/nonexistent/SKILL.md"}])
    diagnostics: list = []
    rows = section._inventory(None, diagnostics, world.home)
    assert diagnostics == []
    assert [r["inv_id"] for r in rows] == ["sk1"]
    assert rows[0]["catalog_item_id"] == "cat-notes"  # gates "已装同一条目"
    assert "resident" in rows[0] and "status" in rows[0]
    # read-only: nothing persisted into app.db
    assert world.a.execute("SELECT COUNT(*) FROM inv_link").fetchone()[0] == 0
