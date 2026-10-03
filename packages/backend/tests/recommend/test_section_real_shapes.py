"""recs-B11 / a4a6-B8 on real log shapes (synthetic rows): shell-wrapped command heads,
failures without error_class, and denied approvals."""

import json
import sqlite3

import pytest
from fact_db import SCHEMA, FakeStore

from orbit_backend.recommend import handoff, problems, section
from orbit_backend.recommend.engine import build_slate


def _db(tmp_path):
    path = tmp_path / "orbit.db"
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


def test_sequences_see_unwrapped_short_heads(tmp_path):
    store, rows = _db(tmp_path)
    root_of = {r["session_uid"]: r["session_uid"] for r in rows}
    with store.connect() as conn:
        seqs = section._call_sequences(conn, json.dumps(sorted(root_of)), root_of)
        calls = section._calls_by_root(conn, root_of)
    assert [head for _, head, _, _ in seqs["s0"]][:2] == ["git status", "ls"]
    assert [call["head"] for call in calls["s0"]][:3] == ["git status", "ls", "wrangler"]


@pytest.mark.parametrize("native_class", [None, "command_not_found"])
def test_compound_shell_failures_keep_the_actual_missing_program(tmp_path, native_class):
    store, roots = _db(tmp_path)
    root_of = {r["session_uid"]: r["session_uid"] for r in roots}
    with store.connect() as db:
        db.execute("UPDATE tool_call SET status='completed'")
        # Same absent dependency, different command heads. No literal benchmark logs.
        commands = [("python3", "python3 --version; unzip input.docx"),
                    ("rm", "rm -f old.txt && unzip input.docx"),
                    ("unzip", "unzip input.docx"),
                    ("python3", "python3 -c 'print(1)'\nunzip input.docx"),
                    ("rm", "rm -f old.txt; mkdir -p output; unzip input.docx")]
        for n, (head, command) in enumerate(commands):
            cid = f"s{n}-c3"
            db.execute("UPDATE event SET attrs=? WHERE event_uid=?",
                       (json.dumps({"input": {"command": command}}), cid + "-call"))
            db.execute("UPDATE event SET text=? WHERE event_uid=?",
                       ("bash: line 2: unzip: command not found\n\nCommand exited with code 127", cid + "-res"))
            if n == 4:  # _db only adds c3 for the first four sessions.
                db.execute("INSERT INTO event(event_uid,session_uid,kind,attrs) VALUES (?,?,'tool.call',?)",
                           (cid + "-call", f"s{n}", json.dumps({"input": {"command": command}})))
                db.execute("INSERT INTO event(event_uid,session_uid,kind,text) VALUES (?,?,'tool.result',?)",
                           (cid + "-res", f"s{n}", "bash: line 2: unzip: command not found"))
                db.execute("INSERT INTO tool_call(call_uid,session_uid,name,kind,call_event_uid,result_event_uid) "
                           "VALUES (?,?,'bash','shell',?,?)", (cid, f"s{n}", cid + "-call", cid + "-res"))
            db.execute("UPDATE tool_call SET command_head=?,status='failed',exit_code=NULL,error_class=? "
                       "WHERE call_uid=?", (head, native_class, cid))
        facts, agents = section._facts(db, root_of, roots, [], [])
    assert facts["failures_by_software"] == [{"software": "unzip", "error_class": "command_not_found",
                                             "count": 5, "sessions": 5,
                                             "session_uids": [f"s{i}" for i in range(5)]}]
    assert "unzip" not in facts["scope_sessions"]["software"]  # incomplete head-only exposure
    inputs = {"sessions": {"main": 6, "weeks": 1}, "facts": facts, "agents": agents,
              "profile": {"tools": ["shell", "file.write"]}, "inventory": []}
    problem = next(p for p in problems.build(inputs) if p["key"] == "tool_env_failure:unzip")
    assert (problem["status"], problem["denominator"]) == ("active", 6)
    slate = build_slate(inputs, {"settings": {"ai_generate": True}})
    assert any(c["rec_key"] == "kb:retry-breaker" and c["rank"] for c in slate["candidates"])


def test_ambiguous_compound_or_dumped_text_is_not_attributed_to_first_program():
    assert section.failure_software("rm", "rm old; python3 work.py", "missing_dependency",
                                    "ModuleNotFoundError: No module named 'pandas'") is None
    assert section.failure_software("cat", "cat log.txt", "command_not_found",
                                    "bash: line 1: unzip: command not found") == "cat"
    assert section.failure_software("rm", "rm old; a; b", "command_not_found",
                                    "bash: line 1: a: command not found\nbash: line 1: b: command not found") is None


def test_pi_and_canonical_write_kinds_reach_all_edit_consumers(tmp_path):
    store, roots = _db(tmp_path)
    root_of = {r["session_uid"]: r["session_uid"] for r in roots}
    with store.connect() as db:
        for i, name in enumerate(["write", "Write", "custom_write"]):
            db.execute("INSERT INTO model_call VALUES (?,?,'k3','max',10,5,0)", (f"m{i}", f"s{i}"))
            for n in range(6):
                db.execute("INSERT INTO tool_call(call_uid,session_uid,name,kind,files,status,started_at) "
                           "VALUES (?,?,?,'file.write',?,'completed',?)",
                           (f"edit-{i}-{n}", f"s{i}", name, json.dumps([f"output/a{n}.py"]), n + 100))
        facts, _ = section._facts(db, root_of, roots, [], [])
        calls = section._calls_by_root(db, root_of)
        prompt = handoff.build(db, "s0")
        task_types = section._task_kinds(db, json.dumps(list(root_of)), root_of, None)
    assert facts["model_mix"][0]["readonly_sessions"] == 0
    assert facts["unverified_edits"]["sessions"] == 3
    assert all(section._is_edit(c) for seq in calls.values() for c in seq if c["kind"] == "file.write")
    assert prompt["parts"]["verify_pending"] and len(prompt["parts"]["recent_files"]) == 6
    assert task_types["s0"]["tasks"] > 0
