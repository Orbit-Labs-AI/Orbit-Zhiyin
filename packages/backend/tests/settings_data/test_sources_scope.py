"""SET-07: a disabled source hides its sessions from default scopes."""

from __future__ import annotations

from dataclasses import asdict

from tandem_backend.appdata import sources_scope
from tandem_backend.services.routes_analytics import analytics_scope
from tandem_backend.services.snapshots import scope_hash


def scope(**kw):
    defaults = {"display_timezone": "UTC", "project_ids": None, "legacy_project_ids": None,
                "model_ids": None, "effort_raw": None, "from_ts": None, "until_ts": None,
                "root_session_uids": None, "excluded_session_uids": None,
                "include_children": True, "scene": None, "source_ids": None}
    return analytics_scope(**{**defaults, **kw})


def test_disabled_source_limits_default_scope(client, gateway, tmp_path):
    roots = []
    for name in ("a", "b"):
        root = tmp_path / "agents" / name
        root.mkdir(parents=True)
        roots.append(root)
    a = client.post("/v1/app/sources", json={"agent": "codex", "root": str(roots[0])}).json()
    b = client.post("/v1/app/sources", json={"agent": "claude_code", "root": str(roots[1])}).json()
    everything = scope()
    assert everything.source_ids is None  # All enabled: scope (and its hash) unchanged.
    client.post("/v1/app/sources", json={"agent": "claude_code", "root": str(roots[1]),
                                         "enabled": False})
    limited = scope()
    assert limited.source_ids == [a["id"]] and b["id"] not in limited.source_ids
    assert sources_scope.enabled_source_ids() == [a["id"]]
    # An explicit selection wins over the default.
    assert scope(source_ids=[b["id"]]).source_ids == [b["id"]]
    client.post("/v1/app/sources", json={"agent": "claude_code", "root": str(roots[1]),
                                         "enabled": True})
    assert scope().source_ids is None


def test_all_enabled_keeps_scope_hash():
    sources_scope.set_provider(None)
    unbound = asdict(scope())
    sources_scope.set_provider(lambda: [{"id": "x", "enabled": True}])
    try:
        assert scope_hash(asdict(scope()), {}) == scope_hash(unbound, {})
        sources_scope.set_provider(lambda: [{"id": "x", "enabled": False}])
        assert scope().source_ids == []  # Every source disabled: nothing is shown.
    finally:
        sources_scope.set_provider(None)
