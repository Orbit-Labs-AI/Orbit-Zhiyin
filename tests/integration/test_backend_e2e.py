"""Backend end to end through one gateway: synthetic Codex sessions → features → recommendations
→ labels → install / outcome / revert, AI generate (FakeEngine) → install, plus catalog, search,
health, realtime, session exclusion and an eval smoke run.

Everything lives under ``tmp_path``: the Orbit home, the agent home (HOME and
ORBIT_INSTALL_HOME) and the synthetic transcripts. No real agent home, CLI, model or network.
"""

from __future__ import annotations

import io
import json
import tarfile
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest
from gateway_support import ok, wait_for
from synthetic import write_codex_tree

from orbit_backend.ai.engines import FakeEngine
from orbit_backend.ai.service import service as ai_service

# Real worker heartbeats (0.3 s) and a 3 s stale window: running next to the whole parallel
# suite can starve a heartbeat, so these run in the serial pass of scripts/check.sh.
pytestmark = pytest.mark.serial

SKILL = {"name": "flaky-test-triage", "description": "测试反复失败时，先读错误输出再决定是否重跑。",
         "steps": ["读最近一次失败的完整输出", "定位第一条报错", "只修改相关文件后重跑"],
         "dont": ["不要盲目重试"], "verify": "pytest -q 通过", "allowed_tools": ["Read", "Grep", "Bash"]}


def write_failing_sessions(root: Path, count: int = 4) -> None:
    """Codex rollouts where ``pytest`` keeps failing: enough friction for real recommendations."""
    now = time.time()
    for n in range(count):
        started = now - n * 6 * 3600 - 600
        uid = f"00000000-0000-4000-9000-{n:012d}"
        rows = [{"type": "session_meta", "payload": {"id": uid, "source": "cli",
                                                     "cwd": "/synthetic/flaky"}},
                {"type": "event_msg", "payload": {"type": "task_started", "turn_id": "t"}},
                {"type": "event_msg", "payload": {"type": "item_completed", "turn_id": "t", "item": {
                    "id": "user", "type": "UserMessage",
                    "content": [{"type": "text", "text": "排查构造项目中的测试失败"}]}}}]
        for i in range(10):
            failed = i < 4
            rows.append({"type": "event_msg", "payload": {"type": "item_completed", "turn_id": "t", "item": {
                "id": f"command-{i}", "type": "CommandExecution", "command": ["pytest", f"case-{i}"],
                "status": "failed" if failed else "completed", "exit_code": 1 if failed else 0,
                "duration_ms": 10, "aggregated_output": "synthetic output"}}})
        for i, row in enumerate(rows):
            row["timestamp"] = datetime.fromtimestamp(started + i, UTC).isoformat().replace("+00:00", "Z")
        path = root / "sessions" / f"rollout-flaky-{n}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(json.dumps(row) + "\n" for row in rows))


@pytest.fixture
def e2e(tmp_path, gateway_harness):
    harness = gateway_harness(fetcher=FakeGithub())
    codex_root = tmp_path / "agents" / "codex"
    write_codex_tree(codex_root, 12)
    write_failing_sessions(codex_root)
    return harness.client, harness.gateway, codex_root, harness.home


class FakeGithub:
    """Serves any ``owner/repo`` as one MIT repo whose archive holds a single skill."""

    def __init__(self):
        self.calls: list[str] = []

    def get(self, url, *, max_bytes, headers=None):
        self.calls.append(url)
        if url.startswith("https://api.github.com/repos/") and "/commits/" not in url:
            return json.dumps({"license": {"spdx_id": "MIT"}}).encode()
        if url.startswith("https://codeload.github.com/"):
            commit = url.rsplit("/", 1)[1]
            body = b"---\nname: systematic-debugging\n---\n# Systematic debugging\n"
            buffer = io.BytesIO()
            with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
                info = tarfile.TarInfo(f"repo-{commit}/skills/systematic-debugging/SKILL.md")
                info.size = len(body)
                archive.addfile(info, io.BytesIO(body))
            return buffer.getvalue()
        raise AssertionError(f"unexpected fetch {url}")


def import_sessions(client, root: Path) -> None:
    source = ok(client.post("/v1/app/sources", json={"agent": "codex", "root": str(root)}))["id"]
    job = ok(client.post("/v1/app/jobs", json={"kind": "import", "source_ids": [source]}), 202)

    def finished():
        state = client.get(f"/v1/app/jobs/{job['id']}").json()
        return state if state["status"] not in ("queued", "running") else None

    assert wait_for(finished, 120, 0.1, "import job")["status"] == "completed"


def catalog_settled(client) -> None:
    """The refresher imports the bundled library seed once the gateway starts; every source it
    publishes moves the catalog generation, which keys the recommendation run. It reports the
    first-sync state (``disabled`` here) only after that import, so wait for it before runs."""
    wait_for(lambda: client.get("/v1/catalog/status").json()["first_sync"]["state"] != "pending",
             120, 0.1, "catalog seed import")


def plan_status(client, candidate_id: str) -> str | None:
    response = client.post("/v1/install/plans", json={
        "source": {"type": "candidate", "id": candidate_id}, "agents": ["claude_code"], "fetch": True})
    return response.json().get("status") if response.status_code == 201 else None


def recommendations(client) -> dict:
    def ready():
        response = client.get("/v1/recommendations", params={"wait_ms": 3000})
        return response.json() if response.status_code == 200 else None

    return wait_for(ready, 120, 0.2, "recommendations")


def install_and_check(client, source: dict, user_home: Path) -> dict:
    """plan (fetching through the fake fetcher) → preview → apply with the preview digest."""
    plan = ok(client.post("/v1/install/plans", json={"source": source, "agents": ["claude_code"],
                                                     "fetch": True}), 201)
    assert plan["status"] == "ready", plan
    preview = ok(client.get(f"/v1/install/plans/{plan['plan_id']}/preview"))
    assert preview["can_apply"], preview
    applied = ok(client.post("/v1/install/apply", json={"plan_id": plan["plan_id"],
                                                        "preview_digest": preview["preview_digest"]}))
    assert applied["install_id"] and applied["written"]
    for item in applied["written"]:
        assert Path(item["path"]).resolve().is_relative_to(user_home.resolve()), item
        assert Path(item["path"]).exists()
    return applied


def test_backend_end_to_end(e2e):
    client, gateway, codex_root, user_home = e2e
    import_sessions(client, codex_root)
    catalog_settled(client)

    # Features and recommendations; with unchanged inputs the second call reuses the run.
    profile = ok(client.get("/v1/features/profile"))
    assert profile["n_sessions"] > 0 and profile["scope_hash"]
    first = recommendations(client)
    again = ok(client.get("/v1/recommendations"))
    assert again["run"]["run_id"] == first["run"]["run_id"]

    # Exposure, a label and its undo.
    items = first["items"]
    seen = items[-1]["candidate_id"]
    ok(client.post(f"/v1/recommendations/{seen}/exposure",
                   json={"surface": "A7", "position": len(items) - 1, "action": "view"}))
    label = ok(client.post("/v1/labels", json={"target_kind": "candidate", "target_id": seen,
                                                "label": "not_applicable", "reason": "other"}))
    detail = ok(client.get(f"/v1/recommendations/{seen}"))
    assert detail["exposures"]["count"] >= 1 and detail["labels"][0]["label_id"] == label["label_id"]
    ok(client.delete(f"/v1/labels/{label['label_id']}"))
    assert ok(client.get(f"/v1/recommendations/{seen}"))["labels"][0]["undone_at"]

    # Install an evidence-backed card (not a「资料库推荐」catalog_only filler, which is often
    # link-only) under the temporary HOME, then follow it through to revert.
    backed = [i for i in items if i.get("basis") != "catalog_only" and i["evidence"]["session_uids"]]
    assert backed, items
    # Remedies Orbit writes itself (KB allowlist / hook) plan from the card, never link_only.
    own = [i for i in backed if (i.get("source") or {}).get("origin") == "kb"
           and i["kind"] in ("permission_rule", "hook") and "…" not in json.dumps(i.get("file"))]
    assert own and all(plan_status(client, i["candidate_id"]) == "ready" for i in own), own
    card = next((i for i in backed if plan_status(client, i["candidate_id"]) == "ready"), None)
    assert card is not None, [(i["candidate_id"], i["source"]) for i in backed]
    candidate = card["candidate_id"]

    before = {p: p.read_bytes() for p in user_home.rglob("*") if p.is_file()}
    applied = install_and_check(client, {"type": "candidate", "id": candidate}, user_home)
    install_id = applied["install_id"]
    assert applied["tracking_id"]
    tracked = ok(client.get(f"/v1/recommendations/{candidate}"))
    assert tracked["tracking"]["tracking_id"] == applied["tracking_id"]
    assert tracked["state"]["status"] == "installed"
    ledger = ok(client.get("/v1/install/ledger", params={"install_id": install_id}))["entries"]
    assert ledger and all(e["install_id"] == install_id for e in ledger)
    outcome = ok(client.get(f"/v1/outcomes/{install_id}"))
    assert outcome["candidate_id"] == candidate and outcome["effect_status"]
    reverted = ok(client.post(f"/v1/install/{install_id}/revert", json={}))
    assert reverted["ok"]
    assert {p: p.read_bytes() for p in user_home.rglob("*") if p.is_file()} == before
    assert ok(client.get(f"/v1/outcomes/{install_id}"))["effect_status"] == "reverted"

    # AI: consent → preview → generate.skill → artifact → install plan from the artifact.
    ai = ai_service(gateway)
    ai.register_engine("fake", FakeEngine({"generate.skill": SKILL}))
    ok(client.put("/v1/ai/consent", json={"mode": "agent", "default_engine": "fake", "grants": {
        "fake": {"summary": True, "snippets": True, "rules": True}}}))
    evidence = items[0]["problem"]["evidence"]["session_uids"]
    ask = {"task_id": "generate.skill", "engine": "fake", "goal": "测试反复失败时先诊断",
           "goal_source": "workflow", "params": {"session_uids": evidence}}
    preview = ok(client.post("/v1/ai/preview", json=ask))
    assert preview["preview_digest"] and preview["items"]
    job = ok(client.post("/v1/ai/jobs", json={**ask, "preview_digest": preview["preview_digest"]}), 202)

    def job_done():
        state = client.get(f"/v1/ai/jobs/{job['job_id']}").json()
        return state if state["status"] not in ("queued", "running") else None

    state = wait_for(job_done, 60, 0.05, "ai job")
    assert state["status"] == "ok" and state["artifact_id"], state
    artifact = ok(client.get(f"/v1/ai/artifacts/{state['artifact_id']}"))
    assert artifact["kind"] == "skill" and artifact["name"] == SKILL["name"]
    plan = ok(client.post("/v1/install/plans", json={
        "source": {"type": "artifact", "id": artifact["artifact_id"]}, "agents": ["claude_code"]}), 201)
    assert plan["status"] == "ready" and plan["targets"], plan


def test_reads_platform_and_ops(e2e):
    client, gateway, codex_root, _ = e2e
    import_sessions(client, codex_root)

    catalog = ok(client.get("/v1/catalog/items", params={"limit": 5}))
    assert "items" in catalog
    found = ok(client.get("/v1/search", params={"q": "synthetic"}))
    assert found["index"]["state"] == "ready" and found["results"]
    health = ok(client.get("/v1/platform/health"))
    assert health["status"] in ("ok", "degraded") and health["checks"]
    realtime = ok(client.get("/v1/analytics/realtime"))
    assert {"status", "sessions", "counts"} <= realtime.keys()

    # Session exclusion round trip.
    sessions = ok(client.get("/v1/sessions", params={"limit": 1}))
    uid = sessions[0]["id"]
    ok(client.post(f"/v1/sessions/{uid}/exclude", json={}))
    excluded = ok(client.get("/v1/sessions/excluded"))
    assert [i["session_uid"] for i in excluded["items"]] == [uid]
    ok(client.delete(f"/v1/sessions/{uid}/exclude"))
    assert ok(client.get("/v1/sessions/excluded"))["count"] == 0

    # Eval runner smoke with the smallest built-in suite.
    run = ok(client.post("/v1/eval/runs", json={"suites": ["readability"]}), 202)

    def eval_done():
        report = client.get(f"/v1/eval/runs/{run['run_id']}").json()
        return report if report["status"] in ("done", "failed", "cancelled") else None

    report = wait_for(eval_done, 60, 0.1, "eval run")
    assert report["status"] == "done" and report["suites"][0]["suite"] == "readability", report
