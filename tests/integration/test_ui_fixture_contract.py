"""The prototype stubs must describe what the real gateway answers.

``prototypes/shared/fixtures/**/routes.json`` drive the Playwright suites (``stubGateway``): the UI
is only ever tested against those hand-written bodies. Here a real gateway imports synthetic
sessions and every ``GET`` route in those manifests is fetched for real; each fixture's key tree
must be a subset of the real response's key tree with matching JSON types. A backend change
that drops or retypes a field the UI was built against therefore fails ``pnpm check`` instead
of silently leaving the App without data.

Comparison rules (``shape_mismatches``):

- every key in a fixture object must exist in the real object;
- JSON types must match (int and float are both "number"); ``null`` on either side is
  compatible with anything, because a nullable field is legitimately null in one capture;
- lists compare their first elements when both sides are non-empty;
- objects whose keys are data (dates, ids, agent names — see ``DATA_KEYED``) compare the union
  of their values' shapes instead of their key names.

Fixture-only ids (``session_fx016``, ``proj_alpha``) are replaced by real ids of the same kind.
Routes that cannot be reproduced on a fresh home are listed in ``NOT_REPRODUCIBLE`` with the
reason; the list must stay in sync with the manifests.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from gateway_support import wait_for
from synthetic import write_codex_tree

pytestmark = pytest.mark.serial

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "prototypes/shared/fixtures"

# Route → reason it cannot be fetched from a freshly imported home.
NOT_REPRODUCIBLE = {
    "/v1/install/plans/plan-fx-1/preview": "needs a stored install plan created by POST /v1/install/plans",
}
# Divergences that exist today, keyed by "<fixture dir>/<file>" → {problem: why it is known}.
# Each one is a real contract bug (the UI reads the field, the gateway does not send it, or the
# types differ) and is tracked as a follow-up; the test fails when one disappears so the entry
# is removed together with the fix, and fails on any new divergence.
KNOWN_DRIFT = {
    "core/status.json": {
        "$.jobs_active: fixture number vs real array":
            "GET /v1/status sends the active job list; the stub sends a count",
    },
    "core/facts.json": {
        "$.meta.contract: missing in real response":
            "the stub declares a contract version the gateway never sends",
    },
    "s5/recs-full.json": {
        "$.items[0].routes.feature: missing in real response": "stub-only route hint",
        "$.items[0].feature_overlap: missing in real response":
            "97-live-recs.js reads feature_overlap.matched; the gateway never sends it",
        "$.items[0].gates.checks.license_ok: fixture boolean vs real string":
            "gate checks are strings in the gateway, booleans in the stub",
        "$.items[0].ui.evq.session_uids: missing in real response": "stub-only evidence ids",
    },
    "s7/persona-reveal.json": {
        "$.meta.window: fixture array vs real object":
            "reveal window is an object in the gateway, a [from, until] pair in the stub",
    },
}
# Object paths whose keys are data rather than field names (dates, ids, enum values).
DATA_KEYED = re.compile(
    r"(^|\.)(dicts|constants|by_[a-z_]+|counts|per_[a-z_]+|agents|daily|series|buckets|"
    r"hist[a-z_]*|histogram|models|mix|reasons|qualities|families|kinds|states|status_counts)$"
)


def manifest_routes() -> list[tuple[str, Path, str]]:
    routes = []
    for manifest in sorted(FIXTURES.glob("**/routes.json")):
        for key, name in json.loads(manifest.read_text()).items():
            if key.startswith("_") or not key.startswith("GET "):
                continue
            routes.append((key[4:], manifest.parent / name, manifest.parent.name))
    return routes


def unwrap(body):
    """``{status, body}`` wrappers are stub-only envelopes (202 / 503 cases)."""
    if isinstance(body, dict) and body and set(body) <= {"status", "body", "headers", "delay"}:
        return body.get("status", 200), body.get("body")
    return 200, body


def kind(value) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int | float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    return "object"


def merged(values):
    """One representative object for data-keyed maps: the union of the value objects."""
    out = {}
    for value in values:
        if isinstance(value, dict):
            for key, item in value.items():
                if out.get(key) is None:
                    out[key] = item
    return out


def shape_mismatches(fixture, real, path="$") -> list[str]:
    if fixture is None or real is None:
        return []
    if kind(fixture) != kind(real):
        return [f"{path}: fixture {kind(fixture)} vs real {kind(real)}"]
    if isinstance(fixture, list):
        if fixture and real:
            return shape_mismatches(fixture[0], real[0], path + "[0]")
        return []
    if not isinstance(fixture, dict):
        return []
    if DATA_KEYED.search(path.removeprefix("$")):
        values_f = list(fixture.values())
        values_r = list(real.values())
        if not values_f or not values_r:
            return []
        if all(isinstance(v, dict) for v in values_f + values_r):
            return shape_mismatches(merged(values_f), merged(values_r), path + ".*")
        return shape_mismatches(values_f[0], values_r[0], path + ".*")
    problems = []
    for key, value in fixture.items():
        if key not in real:
            problems.append(f"{path}.{key}: missing in real response")
            continue
        problems += shape_mismatches(value, real[key], f"{path}.{key}")
    return problems


def test_shape_mismatches_reports_missing_and_retyped_fields():
    fixture = {"a": 1, "b": {"c": "x"}, "rows": [{"d": True}], "n": None, "by_day": {"2026-10-01": {"v": 1}}}
    real = {"a": 2.5, "b": {}, "rows": [{"d": "yes"}], "n": [1], "by_day": {"2026-10-02": {"w": 1}}}
    assert shape_mismatches(fixture, real) == [
        "$.b.c: missing in real response",
        "$.rows[0].d: fixture boolean vs real string",
        "$.by_day.*.v: missing in real response",
    ]
    assert shape_mismatches(fixture, {**real, "b": {"c": "y"}, "rows": [], "by_day": {}}) == []


def test_not_reproducible_routes_are_still_in_the_manifests():
    paths = {path for path, _, _ in manifest_routes()}
    assert set(NOT_REPRODUCIBLE) <= paths, set(NOT_REPRODUCIBLE) - paths


@pytest.fixture
def live(tmp_path, gateway_harness):
    harness = gateway_harness()
    root = tmp_path / "agents/codex"
    write_codex_tree(root, 8)
    harness.import_source("codex", root)
    wait_for(lambda: harness.client.get("/v1/catalog/status").json()["first_sync"]["state"]
             != "pending", 120, 0.1, "catalog seed import")
    return harness


def real_ids(client) -> dict[str, str]:
    session = client.get("/v1/sessions", params={"limit": 2}).json()
    projects = client.get("/v1/uiview/projects").json()["projects"]
    assert len(session) == 2 and projects, (session, projects)
    return {"session": session[0]["id"], "other_session": session[1]["id"],
            "project": projects[0]["project_id"]}


def resolve(path: str, ids: dict[str, str]) -> tuple[str, dict]:
    path = re.sub(r"/v1/(uiview/)?sessions/session_fx\w+?(?=/|$)",
                  lambda m: f"/v1/{m.group(1) or ''}sessions/{ids['session']}", path)
    path = re.sub(r"/v1/uiview/projects/proj_\w+", f"/v1/uiview/projects/{ids['project']}", path)
    params = {"a": ids["session"], "b": ids["other_session"]} if path.endswith("/compare") else {}
    return path, params


def fetch_settled(client, path, params):
    """Analysis-backed views answer 202 while computing; wait for the settled 200 body."""
    def settled():
        response = client.get(path, params={**params, "wait_ms": 3000} if path.startswith(
            "/v1/recommendations") else params or None)
        return response if response.status_code != 202 else None

    return wait_for(settled, 120, 0.2, f"GET {path}")


def test_ui_fixtures_match_real_gateway_responses(live):
    client = live.client
    ids = real_ids(client)
    problems, compared = {}, 0
    for route, fixture_file, folder in manifest_routes():
        if route in NOT_REPRODUCIBLE:
            continue
        status, body = unwrap(json.loads(fixture_file.read_text()))
        if status != 200 or body is None:
            continue  # error / computing envelopes describe transport, not the payload.
        path, params = resolve(route, ids)
        response = fetch_settled(client, path, params)
        name = f"{folder}/{fixture_file.name}"
        label = f"{name} ← GET {path}"
        if response.status_code != 200:
            problems[label] = [f"HTTP {response.status_code}: {response.text[:200]}"]
            continue
        compared += 1
        found = shape_mismatches(body, response.json())
        known = KNOWN_DRIFT.get(name, {})
        if stale := sorted(set(known) - set(found)):
            problems[label] = [f"fixed, remove from KNOWN_DRIFT: {p}" for p in stale]
        if new := [p for p in found if p not in known]:
            problems.setdefault(label, []).extend(new)
    assert compared >= 30, compared
    assert not problems, "UI fixtures diverge from the gateway:\n" + "\n".join(
        f"- {label}\n    " + "\n    ".join(items[:15]) for label, items in problems.items())
