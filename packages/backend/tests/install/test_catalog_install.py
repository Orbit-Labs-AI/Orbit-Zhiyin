"""B16: catalog hooks become installable when self-contained; the rest plan as link_only."""

import json
from types import SimpleNamespace

from tandem_backend.install.plan import catalog_item

from .test_service import CATALOG, run, svc  # noqa: F401

ONE = {"hooks": {"PostToolUse": [{"matcher": "Edit|Write", "hooks": [{"type": "command", "command": "ruff format"}]}],
                 "Stop": [{"hooks": [{"type": "command", "command": "ruff format"}]}]}}
PLUGIN_HOOKS = {"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "sh \"${CLAUDE_PLUGIN_ROOT}/h.sh\""}]}]}}


def hook_resource(item_id, manifest):
    return {"resource": {"item_id": item_id, "type": "hook", "name": item_id, "url": "https://x/h",
                         "license": "MIT", "manifest": manifest, "agents": ["claude_code"]}}


def test_hook_manifest_maps_to_payload():
    item = catalog_item(hook_resource("hook:fmt", ONE))
    hook = item["install"]["hook"]
    assert hook["command"] == "ruff format" and hook["event"] == "PostToolUse"
    assert hook["event_bindings"] == [{"event": "PostToolUse", "matcher": "Edit|Write"},
                                      {"event": "Stop", "matcher": None}]
    plugin_only = catalog_item({**hook_resource("hook:p", PLUGIN_HOOKS), "parents": ["plugin:p"]})
    assert plugin_only["install"] is None and plugin_only["install_via"] == "plugin:p"
    two = {"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "a"}, {"type": "command", "command": "b"}]}]}}
    assert catalog_item(hook_resource("hook:2", two))["install"] is None


def test_catalog_hook_installs_and_unsupported_items_are_link_only(svc, fake_home):  # noqa: F811
    CATALOG["hook:fmt"] = catalog_item(hook_resource("hook:fmt", ONE))
    CATALOG["hook:p"] = catalog_item({**hook_resource("hook:p", PLUGIN_HOOKS), "parents": ["plugin:p"]})
    CATALOG["wf:1"] = {"id": "wf:1", "kind": "workflow", "name": "wf", "url": "https://w", "install": None}
    try:
        _, preview, result = run(svc, {"type": "catalog", "id": "hook:fmt"}, agents=["claude_code"])
        hooks = json.loads((fake_home / ".claude/settings.json").read_text())["hooks"]
        assert set(hooks) == {"PostToolUse", "Stop"}
        assert svc.revert(result["install_id"])["ok"]
        link = svc.plan({"type": "catalog", "id": "hook:p"})
        assert link["status"] == "link_only" and link["targets"] == [] and link["links"] == ["https://x/h"]
        assert link["link_reason"] == "needs_plugin" and link["install_via"] == "plugin:p"
        wf = svc.plan({"type": "catalog", "id": "wf:1"})
        assert wf["status"] == "link_only" and wf["link_reason"] == "kind_not_installable"
    finally:
        for key in ("hook:fmt", "hook:p", "wf:1"):
            CATALOG.pop(key, None)


def test_route_lookup_uses_lean_install_view(tmp_path):
    from tandem_backend.services.routes_install import _catalog_lookup

    def boom(_):
        raise AssertionError("detail() builds the related-items index")

    store = SimpleNamespace(detail=boom, install_view=lambda i: hook_resource(i, ONE))
    lookup = _catalog_lookup(SimpleNamespace(catalog=SimpleNamespace(store=store), home=tmp_path))
    assert lookup("hook:fmt")["install"]["hook"]["command"] == "ruff format"
