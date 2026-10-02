"""recs-B11 / a4a6-B8 on real log shapes (synthetic rows): shell-wrapped command heads,
failures without error_class, and denied approvals."""

import json
import sqlite3

from fact_db import SCHEMA, FakeStore

from tandem_backend.recommend import problems, section


def _db(tmp_path):
    path = tmp_path / "tandem.db"
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    conn.execute("INSERT INTO source VALUES ('src', 'codex')")
    rows = []

    def call(uid, n, head, command, *, status="completed", approval=None, out="ok", code=0):
        cid = f"{uid}-c{n}"
        conn.execute("INSERT INTO event (event_uid, session_uid, kind, actor, seq, attrs) VALUES (?,?,?,?,?,?)",
                     (f"{cid}-call", uid, "tool.call", "tool", n * 2, json.dumps({"input": {"cmd": command}})))
        conn.execute("INSERT INTO event (event_uid, session_uid, kind, actor, seq, text) VALUES (?,?,?,?,?,?)",
                     (f"{cid}-res", uid, "tool.result", "tool", n * 2 + 1, out))
        conn.execute("INSERT INTO tool_call (call_uid, session_uid, call_event_uid, result_event_uid, name_raw, "
                     "name, kind, command_head, status, exit_code, approval) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                     (cid, uid, f"{cid}-call", f"{cid}-res", "exec_command", "exec_command", "shell", head,
                      status, code, approval))

    for i in range(6):
        uid = f"s{i}"
        conn.execute("INSERT INTO session (session_uid, source_id, kind, project_id, started_at) "
                     "VALUES (?,?,?,?,?)", (uid, "src", "main", "p1", 1_780_000_000_000 + i))
        rows.append({"session_uid": uid, "project_id": "p1", "started_at": 1_780_000_000_000 + i})
        call(uid, 1, "/bin/zsh", '/bin/zsh -lc "cd repo && git status"', approval="approved")
        call(uid, 2, "cd", "cd repo && ls -la", approval="denied", status="declined")
        if i < 4:
            call(uid, 3, "cd", "cd repo && wrangler deploy", status="failed", code=1,
                 out="zsh: command not found: wrangler")
            # cat prints file text; a "timeout" inside it is not a failure class
            call(uid, 4, "cd", "cd repo && cat notes.md", status="failed", code=1, out="request timeout: 30s")
    conn.commit()
    conn.close()
    return FakeStore(path), rows


def _facts(tmp_path):
    store, rows = _db(tmp_path)
    root_of = {r["session_uid"]: r["session_uid"] for r in rows}
    with store.connect() as conn:
        facts, _ = section._facts(conn, root_of, rows, [], [], None)
    return facts


def test_unwrap_command_finds_the_real_command():
    assert section.unwrap_command('/bin/zsh -lc "cd x && git status -s"') == "git status -s"
    assert section.unwrap_command(["bash", "-lc", "cd a; FOO=1 uv run pytest -q"]) == "uv run pytest -q"
    assert section.unwrap_command('cd "/a b" && (gh pr view 12)') == "gh pr view 12"
    assert section.unwrap_command("cd x") is None
    assert section.unwrap_command("for f in a b; do git status $f; done") == "git status $f"
    assert section.unwrap_command("if [ -f x ]; then rg foo; fi") == "rg foo"
    assert section.unwrap_command("bash -lc 'cd /x && FOO=\"a b\" uv run pytest -q'") == "uv run pytest -q"
    assert section.unwrap_command('echo "a && b"') is None
    assert section.real_head("cd", None) is None and section.real_head("git status", None) == "git status"


def test_wrapped_heads_feed_readonly_and_software_facts(tmp_path):
    facts = _facts(tmp_path)
    heads = {row["command_head"]: row for row in facts["readonly_prompts"]}
    assert set(heads) == {"git status"} and heads["git status"]["sessions"] == 6
    assert facts["readonly_denied"] == {"ls": 6}
    failures = {row["software"]: row for row in facts["failures_by_software"]}
    assert failures["wrangler"]["error_class"] == "command_not_found" and failures["wrangler"]["sessions"] == 4
    assert "cat" not in failures
    assert facts["scope_sessions"]["software"]["git"] == 6 and facts["scope_sessions"]["projects"] == {"p1": 6}


def test_denied_heads_never_become_allowlist_candidates():
    facts = {"readonly_prompts": [{"command_head": "git status", "count": 9, "sessions": 6,
                                   "session_uids": [f"s{i}" for i in range(6)]},
                                  {"command_head": "ls", "count": 4, "sessions": 3, "denied": 1,
                                   "session_uids": ["a", "b", "c"]},
                                  {"command_head": "pwd", "count": 1, "sessions": 1, "session_uids": ["z"]}],
             "readonly_prompt_sessions": 9}
    out = {p["key"]: p for p in problems.build({"sessions": {"main": 20, "weeks": 2}, "facts": facts})}
    perm = out["would_prompt:readonly_shell"]
    assert perm["vars"]["head_list"] == ["git status"] and perm["sessions"] == 6
