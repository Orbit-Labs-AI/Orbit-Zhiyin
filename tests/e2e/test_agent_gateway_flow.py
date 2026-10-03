"""App-level flow for non-Codex agents: native files → gateway import job → analysis →
``/v1/uiview/*`` and ``/v1/features/profile``; then an appended session is imported
incrementally, and default-directory discovery under a temporary HOME feeds the first import.

Native rows come from ``tandem_data.validation.fixtures.create_sources`` (one session, one
user prompt and one tool call per agent), re-dated to the last hour so the default UI ranges
(30 / 90 days) include them, and copied to further session ids. Expected counts follow from
the number of copies: every copy contributes exactly one session and one tool call.
"""

from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

import pytest
from tandem_data.validation.fixtures import ISO, T, create_sources

pytestmark = pytest.mark.serial  # real worker heartbeats, like test_backend_e2e

NOW_MS = int(time.time() * 1000) - 3_600_000
NOW_ISO = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(NOW_MS / 1000))


def redate(rows: list[dict]) -> list[dict]:
    """Move the fixture clock (T ms / ISO) to an hour ago, keeping relative offsets."""
    text = json.dumps(rows, ensure_ascii=False).replace(ISO, NOW_ISO)
    rows = json.loads(text)

    def shift(value):
        if isinstance(value, dict):
            return {k: (v - T + NOW_MS if k in ("time", "created_at", "createdAt")
                        and isinstance(v, int) and v >= T else shift(v)) for k, v in value.items()}
        if isinstance(value, list):
            return [shift(v) for v in value]
        return value

    return shift(rows)


def read_rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def write_rows(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))


def unique_ids(template: list[dict], sid: str, names: tuple[str, ...]) -> list[dict]:
    """Native ids are globally unique in real logs (Claude ``toolu_…`` / ``msg_…``, Kimi uuids);
    the one-session fixture uses short ids, so every copy gets its own."""
    text = json.dumps(template, ensure_ascii=False)
    for name in names:
        text = text.replace(json.dumps(name), json.dumps(f"{sid}-{name}"))
    return json.loads(text)


def claude_session(root: Path, template: list[dict], sid: str) -> None:
    rows = unique_ids(template, sid, ("demo", "u", "a", "o", "c", "r"))
    write_rows(root / f"projects/demo/{sid}.jsonl", rows)


def kimi_session(root: Path, template: list[dict], sid: str) -> None:
    rows = unique_ids(template, sid, ("u", "c", "r"))
    write_rows(root / f"sessions/wd_demo/{sid}/agents/main/wire.jsonl", rows)


AGENTS = {
    # agent: (template file inside the fixture root, writer of one more session)
    "claude_code": ("projects/demo/demo.jsonl", claude_session),
    "kimi": ("sessions/wd_demo/demo/agents/main/wire.jsonl", kimi_session),
}


def build_root(tmp_path: Path, agent: str, target: Path, sessions: int):
    fixture = create_sources(tmp_path / f"fixture-{target.name}")[agent]
    rel, writer = AGENTS[agent]
    template = redate(read_rows(fixture / rel))
    if target.exists():
        shutil.rmtree(target)
    for n in range(sessions):
        writer(target, template, f"s{n}")
    return template, writer


def settled(harness, path, **params):
    def ready():
        response = harness.client.get(path, params=params or None)
        if response.status_code == 202:
            return None
        body = response.json()
        # A stale body is the last good result while the new revision is computed
        # (uiview: meta.freshness; features profile: cache="stale" with an async rebuild).
        fresh = (body.get("meta") or {}).get("freshness") in (None, "fresh")
        return response if fresh and body.get("cache") != "stale" else None

    return harness.ok(harness.wait_for(ready, 120, 0.2, f"GET {path}"))


def assert_counts(harness, sessions: int, agent: str) -> None:
    overview = settled(harness, "/v1/uiview/overview")
    assert overview["header"]["n"] == sessions
    assert overview["tools"]["calls_total"] == sessions
    persona = settled(harness, "/v1/uiview/persona")
    assert persona["n"] == sessions and persona["fp"]["agents"] == [agent]
    tools = settled(harness, "/v1/uiview/tools")
    assert tools["header"]["calls"] == sessions and tools["header"]["sessions"] == sessions
    listed = settled(harness, "/v1/uiview/sessions")
    assert listed["total"] == sessions and len(listed["rows"]) == sessions
    profile = settled(harness, "/v1/features/profile")
    assert profile["n_sessions"] == sessions
    assert profile["coverage"]["with_features"] == sessions


@pytest.mark.parametrize("agent", sorted(AGENTS))
def test_agent_import_reaches_uiview_and_increments(tmp_path, gateway_harness, agent):
    harness = gateway_harness()
    root = tmp_path / "agents" / agent
    template, writer = build_root(tmp_path, agent, root, 2)
    first = harness.import_source(agent, root)
    assert first["results"][0]["changed"] == 2 and first["results"][0]["capture_errors"] == 0
    assert_counts(harness, 2, agent)

    writer(root, template, "s2")
    second = harness.run_job(first["source_ids"])
    result = second["results"][0]
    assert (result["files"], result["changed"]) == (3, 1)  # only the appended session
    assert second["published"][-1]["data_rev"] > first["published"][-1]["data_rev"]
    assert_counts(harness, 3, agent)


def test_default_home_directories_are_discovered_and_imported(tmp_path, gateway_harness):
    """No discovery stub: the gateway's default discovery scans the temporary HOME."""
    harness = gateway_harness(discovery=None, agent_dirs=())
    build_root(tmp_path, "claude_code", harness.home / ".claude", 2)
    build_root(tmp_path, "kimi", harness.home / ".kimi-code", 1)
    found = {row["agent"]: row for row in harness.get("/v1/app/discovery")}
    assert set(found) == {"claude_code", "kimi"}
    assert (found["claude_code"]["files"], found["kimi"]["files"]) == (2, 1)
    assert all(row["status"] == "available" and not row["enabled"] for row in found.values())
    sources = [harness.configure(agent, row["root"]) for agent, row in sorted(found.items())]
    assert sources == [found["claude_code"]["id"], found["kimi"]["id"]]
    job = harness.run_job(sources)
    assert sorted(r["changed"] for r in job["results"]) == [1, 2]
    overview = settled(harness, "/v1/uiview/overview")
    assert overview["header"]["n"] == 3 and overview["header"]["agents_n"] == 2
    assert settled(harness, "/v1/features/profile")["n_sessions"] == 3
