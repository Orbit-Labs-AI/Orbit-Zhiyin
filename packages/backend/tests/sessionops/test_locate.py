import os


def test_source_location(orbit, client, tmp_path):
    orbit.session("s1")
    orbit.raw_file("s1", "claude_code", "projects/a.jsonl", content="{}\n")
    orbit.raw_file("s1", "claude_code", "projects/gone.jsonl")
    outside = tmp_path / "outside.jsonl"
    outside.write_text("secret")
    link = orbit.roots / "claude_code" / "projects" / "link.jsonl"
    os.symlink(outside, link)
    orbit.raw_file("s1", "claude_code", "projects/link.jsonl")
    orbit.raw_file("s1", "claude_code", "../escape.jsonl")
    first = orbit.event("s1", ts=1, record="rec-first")
    assert first
    body = client.get("/v1/sessions/s1/source_location").json()
    assert body["first_record_uid"] == "rec-first"
    files = {os.path.basename(f["path"]): f for f in body["files"]}
    assert files["a.jsonl"] | {"path": ""} == {
        "path": "", "exists": True, "size": 3, "revealable": True, "source_id": "src-claude_code",
        "agent": "claude_code"}
    assert files["gone.jsonl"]["exists"] is False and files["gone.jsonl"]["size"] is None
    assert files["gone.jsonl"]["revealable"] is False
    for name in ("link.jsonl", "escape.jsonl"):
        assert files[name]["revealable"] is False and files[name]["size"] is None
    assert "secret" not in str(body)
    assert client.get("/v1/sessions/none/source_location").status_code == 404
