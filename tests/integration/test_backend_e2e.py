"""Backend end to end through one gateway: synthetic Codex sessions → features → recommendations
→ labels → install / outcome / revert, AI generate (FakeEngine) → install, plus catalog, search,
health, realtime, session exclusion and an eval smoke run.

Everything lives under ``tmp_path``: the Tandem home, the agent home (HOME and
TANDEM_INSTALL_HOME) and the synthetic transcripts. No real agent home, CLI, model or network.
"""

from __future__ import annotations

import io
import json
import sys
import tarfile
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "packages/backend/tests/services"))

from synthetic import write_codex_tree  # noqa: E402

from tandem_backend import install  # noqa: E402
from tandem_backend.ai import engines  # noqa: E402
from tandem_backend.ai.engines import FakeEngine  # noqa: E402
from tandem_backend.ai.service import service as ai_service  # noqa: E402
from tandem_backend.install import env as envmod  # noqa: E402
from tandem_backend.services.gateway import Gateway  # noqa: E402
from tandem_backend.services.supervisor import SupervisorConfig  # noqa: E402

TOKEN = "synthetic-test-token-0123456789abcdef"
BASE = "http://127.0.0.1:8765"
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


def wait_for(predicate, timeout=90.0, interval=0.05, what=""):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(interval)
    raise AssertionError(f"timed out waiting for {what or predicate}")


def ok(response, status=200):
    assert response.status_code == status, response.text
    return response.json()


@pytest.fixture
def e2e(tmp_path, monkeypatch):
    user_home = tmp_path / "user-home"
    (user_home / ".claude").mkdir(parents=True)
    (user_home / ".codex").mkdir()
    bindir = tmp_path / "bin"
    bindir.mkdir()
    monkeypatch.setenv("HOME", str(user_home))
    monkeypatch.setenv("TANDEM_INSTALL_HOME", str(user_home))
    monkeypatch.setenv("PATH", f"{bindir}:/usr/bin:/bin")
    for name in ("CLAUDE_CONFIG_DIR", "CODEX_HOME", "ANTHROPIC_API_KEY", "XDG_DATA_HOME"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(engines, "FALLBACK_DIRS", ())
    monkeypatch.setattr("tandem_catalog.network.HttpClient.get", _no_network)
    envmod._memo.clear()

    codex_root = tmp_path / "agents" / "codex"
    write_codex_tree(codex_root, 12)
    write_failing_sessions(codex_root)
    config = SupervisorConfig(heartbeat_s=0.3, stale_s=3.0, term_grace_s=1.0,
                              backoff_s=(0.1, 0.2, 0.4, 0.8), tick_s=0.05,
                              light_timeout_s=60.0, heavy_timeout_s=120.0)
    gateway = Gateway(tmp_path / "tandem", config=config, discovery=lambda: [],
                      prewarm_debounce_s=3600.0)
    app = gateway.app(token=TOKEN, port=8765)
    svc = install.get_default_service()
    # Agent detection only looks at the temporary home and an empty bin dir; nothing is spawned.
    svc.env = envmod.Env(home=user_home, environ={"PATH": str(bindir)}, search_dirs=[bindir],
                         run=_no_spawn)
    svc.fetcher = FakeGithub()
    with TestClient(app, base_url=BASE, headers={"Authorization": f"Bearer {TOKEN}"}) as client:
        yield client, gateway, codex_root, user_home
    if getattr(gateway, "_ai", None) is not None:
        gateway._ai.close()
    install.set_default_service(None)


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


def _no_network(*args, **kwargs):
    raise AssertionError("e2e tests must not reach the network")


def _no_spawn(argv, **kwargs):
    raise AssertionError(f"e2e tests must not spawn {argv}")


def import_sessions(client, root: Path) -> None:
    source = ok(client.post("/v1/app/sources", json={"agent": "codex", "root": str(root)}))["id"]
    job = ok(client.post("/v1/app/jobs", json={"kind": "import", "source_ids": [source]}), 202)

    def finished():
        state = client.get(f"/v1/app/jobs/{job['id']}").json()
        return state if state["status"] not in ("queued", "running") else None

    assert wait_for(finished, 120, 0.1, "import job")["status"] == "completed"


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

    # Features and recommendations; the second call reuses the persisted run.
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

    # Install the top candidate under the temporary HOME, then follow it through to revert.
    card = next(i for i in items if i["source"]["origin"] == "catalog")
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
