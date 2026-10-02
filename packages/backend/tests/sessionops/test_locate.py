import os


def test_source_location(tandem, client, tmp_path):
    tandem.session("s1")
    tandem.raw_file("s1", "claude_code", "projects/a.jsonl", content="{}\n")
    tandem.raw_file("s1", "claude_code", "projects/gone.jsonl")
    outside = tmp_path / "outside.jsonl"
    outside.write_text("secret")
    link = tandem.roots / "claude_code" / "projects" / "link.jsonl"
    os.symlink(outside, link)
    tandem.raw_file("s1", "claude_code", "projects/link.jsonl")
    tandem.raw_file("s1", "claude_code", "../escape.jsonl")
    first = tandem.event("s1", ts=1, record="rec-first")
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
