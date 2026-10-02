"""A9-17 / A9-18: materialize artifact files and add passing artifacts to the library."""

from __future__ import annotations

import json
import stat

import pytest
from fakectx import FakeCtx, hook_pack

from tandem_backend.ai.generate import TASKS
from tandem_backend.ai.runner import Runner

HOOK = {"matcher": "Bash", "threshold": 3, "message": "测试已连续失败，先看错误输出再重试。",
        "command_heads": ["pnpm test"]}
RULE = {"title": "失败先查因",
        "rules": [{"text": "pnpm test 连续失败两次就停下读错误输出", "dimension": "verification"}]}


def generated(task_id: str, response: dict) -> dict:
    ctx = FakeCtx(hook_pack(), [response], task=TASKS[task_id])
    return TASKS[task_id]["run"](ctx, hook_pack())["artifact"]


def save(gateway, artifact: dict, job_id: str = "job-1") -> str:
    with gateway.appdb.write() as db:
        return Runner._save_artifact(None, db, {"job_id": job_id}, artifact, False)


@pytest.fixture
def hook_id(gateway):
    return save(gateway, generated("generate.hook", HOOK))


def test_materialize_writes_private_files(client, gateway, home, hook_id):
    body = client.post(f"/v1/ai/artifacts/{hook_id}/materialize").json()
    folder = home / "exports" / "artifacts" / hook_id
    assert body["artifact_id"] == hook_id and body["dir"] == str(folder.resolve())
    assert stat.S_IMODE(folder.stat().st_mode) == 0o700
    names = [p.split("/")[-1] for p in (f["path"] for f in body["files"])]
    assert names and len(names) == len(set(names))
    artifact = client.get(f"/v1/ai/artifacts/{hook_id}").json()
    for file, written in zip(artifact["files"], body["files"], strict=True):
        path = folder / written["path"].split("/")[-1]
        assert path.parent == folder.resolve() and written["target"] == file["target"]
        assert path.read_text() == file["content"] and written["bytes"] == len(file["content"].encode())
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
    again = client.post(f"/v1/ai/artifacts/{hook_id}/materialize").json()
    assert again == body  # Idempotent.


def test_materialize_names_stay_inside(gateway, client, home):
    artifact = generated("generate.rule", RULE)
    artifact["files"] = [{"target": "../../etc/passwd", "content": "x"},
                         {"target": "a/..", "content": "y"}, {"target": "a/SKILL.md", "content": "1"},
                         {"target": "b/SKILL.md", "content": "2"}]
    artifact_id = save(gateway, artifact, "job-2")
    body = client.post(f"/v1/ai/artifacts/{artifact_id}/materialize").json()
    folder = (home / "exports" / "artifacts" / artifact_id).resolve()
    paths = [folder.joinpath(f["path"].split("/")[-1]) for f in body["files"]]
    assert all(p.parent == folder and p.is_file() for p in paths) and len(set(paths)) == 4
    assert not (home / "etc").exists()


def test_to_library_maps_kind(client, gateway, hook_id):
    response = client.post(f"/v1/ai/artifacts/{hook_id}/to_library")
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["created"] is True and body["item_id"].startswith("local:")
    assert client.post(f"/v1/ai/artifacts/{hook_id}/to_library").json() == {
        "item_id": body["item_id"], "created": False}
    item = client.get(f"/v1/catalog/items/{body['item_id']}").json()
    assert item["kind"] == "hook" and item["origin"] == "local"
    rule_id = save(gateway, generated("generate.rule", RULE), "job-3")
    assert client.post(f"/v1/ai/artifacts/{rule_id}/to_library").status_code == 201


def test_glue_maps_to_workflow():
    from tandem_backend.ai import artifact_ops

    artifact = {"kind": "glue", "name": "g", "files": [{"target": "x", "content": "do"}],
                "checks": {"lint": {"status": "warn"}, "scan": {"status": "ok"}}}
    assert artifact_ops.library_item(artifact)["kind"] == "workflow"


def test_to_library_refuses_failed_self_check(client, gateway):
    artifact = generated("generate.hook", HOOK)
    artifact["checks"] = {**artifact["checks"], "scan": {"status": "hit"}}
    artifact["content_hash"] = "sha256:blocked"
    blocked = save(gateway, artifact, "job-4")
    response = client.post(f"/v1/ai/artifacts/{blocked}/to_library")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "self_check_failed"
    assert client.post("/v1/ai/artifacts/af_missing/to_library").status_code == 404
    assert client.post("/v1/ai/artifacts/af_missing/materialize").status_code == 404


def test_saved_rows_are_json(gateway, hook_id):
    with gateway.appdb.read() as db:
        files = json.loads(db.execute("SELECT files FROM ai_artifact WHERE artifact_id = ?",
                                      (hook_id,)).fetchone()[0])
    assert files and all("content" in f for f in files)
