import io
import sqlite3

import pytest

from tandem_backend.appdb import AppDB
from tandem_backend.evalrun import labels
from tandem_backend.evalrun.cli import main
from tandem_backend.recommend import store as rec_store

NOW = 1_800_000_000_000
PROBLEMS = [
    {"key": "permission_friction", "type": "permission_friction", "reason": "反复确认权限",
     "evidence": {"event_ids": ["e1", "e2", "e3", "e4"]}, "vars": {"tool": "Bash"}},
    {"key": "repeated_instruction", "type": "repeated_instruction", "reason": "重复叮嘱",
     "evidence": {"event_ids": ["e5"]}},
]
CANDS = [
    {"rec_key": "kb:allow-git@1", "title": "放行只读 git 命令", "rank": 1, "kind": "rule",
     "problem": {"key": "permission_friction", "type": "permission_friction"}},
    {"rec_key": "catalog:prompt-x", "title": "提示词模板", "rank": 2, "kind": "prompt",
     "problem": {"key": "repeated_instruction", "type": "repeated_instruction"}},
]


@pytest.fixture
def home(tmp_path):
    db = AppDB(tmp_path / "app.db")
    run = {"run_id": "run1", "scope_hash": "s", "scope": {}, "inputs_digest": "d", "engine_version": "t",
           "status": "ready", "problems": PROBLEMS, "created_at": NOW}
    with db.write() as conn:
        rec_store.insert_run(conn, run, CANDS)
    db.close()
    tandem = sqlite3.connect(tmp_path / "tandem.db")
    tandem.execute("CREATE TABLE event (event_uid TEXT PRIMARY KEY, text TEXT)")
    long_text = "前文" * 200 + " 请用 Bash 跑 git status，token sk-abcdefghijklmnopqrstu " + "后文" * 200
    tandem.executemany("INSERT INTO event VALUES (?,?)",
                       [("e1", long_text), ("e2", "又要确认 Bash"), ("e3", None), ("e4", "第三条"),
                        ("e5", "再说一遍：别改测试")])
    tandem.commit()
    tandem.close()
    return tmp_path


def _labels(home):
    db = AppDB(home / "app.db")
    with db.read() as conn:
        rows = [dict(r) for r in conn.execute("SELECT target_kind, target_id, rec_key, label FROM label ORDER BY ts")]
    db.close()
    return rows


def test_label_cli_confirms_and_skips_labelled(home):
    answers = iter(["x", "c", "i"])
    out = io.StringIO()
    assert main(["label", "--home", str(home)], input_fn=lambda _: next(answers), out=out) == 0
    text = out.getvalue()
    assert "放行只读 git 命令" in text and "问题类型：permission_friction" in text
    assert "【Bash】" in text and "sk-abcdefghijklmnopqrstu" not in text
    snippet = next(line for line in text.splitlines() if "【Bash】" in line and "前文" in line)
    assert len(snippet) <= 300 + 10
    assert [(r["rec_key"], r["label"]) for r in _labels(home)] == [
        ("kb:allow-git@1", "confirm"), ("catalog:prompt-x", "inaccurate")]
    out = io.StringIO()
    main(["label", "--home", str(home)], input_fn=lambda _: pytest.fail("asked again"), out=out)
    assert "没有待标注" in out.getvalue()


def test_label_problems_skip_and_quit(home):
    answers = iter(["s", "q"])
    main(["label", "--kind", "problem", "--home", str(home)], input_fn=lambda _: next(answers),
         out=io.StringIO())
    assert _labels(home) == []
    answers = iter(["c"])
    main(["label", "--kind", "problem", "--limit", "1", "--home", str(home)],
         input_fn=lambda _: next(answers), out=io.StringIO())
    assert _labels(home) == [{"target_kind": "problem", "target_id": "permission_friction",
                              "rec_key": None, "label": "confirm"}]


def test_label_without_app_db(tmp_path):
    out = io.StringIO()
    assert main(["label", "--home", str(tmp_path)], out=out) == 0 and not (tmp_path / "app.db").exists()


def test_mark_centres_the_match():
    text = "a" * 500 + "MATCH" + "b" * 500
    marked = labels.mark(text, ["match"], width=100)
    assert "【MATCH】" in marked and marked.startswith("…") and marked.endswith("…")
    assert len(marked) == 100 + 4
    assert labels.mark("short", ["zz"]) == "short"


def _seed(conn, rec_key, kind, confirm, inaccurate, *, ts=NOW, undone=None):
    for i in range(confirm + inaccurate):
        conn.execute("INSERT INTO label VALUES (?,?,?,?,?,?,?,?,?)",
                     (f"{rec_key}-{kind}-{i}-{ts}-{undone}", kind, f"t{i}", rec_key, "user",
                      "confirm" if i < confirm else "inaccurate", None, ts, undone))


def test_summary_wilson_and_insufficient(tmp_path):
    db = AppDB(tmp_path / "app.db")
    with db.write() as conn:
        _seed(conn, "kb:allow-git@1", "candidate", 36, 4)
        _seed(conn, None, "problem", 5, 5)
        _seed(conn, "kb:allow-git@1", "candidate", 9, 0, undone=NOW)  # Undone: ignored.
        _seed(conn, "kb:allow-git@1", "candidate", 9, 0, ts=NOW - 200 * 86_400_000)  # Too old.
        conn.execute("INSERT INTO label VALUES ('u','candidate','x','kb:allow-git@1','user','useful',NULL,?,NULL)",
                     (NOW,))
    with db.read() as conn:
        result = labels.summary(conn, 90, now=NOW)
    db.close()
    assert result["total_labels"] == 50
    candidate, problem = result["rows"]
    assert candidate == {"target_kind": "candidate", "rule_id": "kb:allow-git@1", "n_labeled": 40,
                         "n_confirm": 36, "n_inaccurate": 4, "precision": 0.9,
                         "lo": 0.7695, "hi": 0.9604, "status": "ok"}
    assert problem["rule_id"] is None and problem["status"] == "insufficient"
    assert problem["precision"] is None and problem["lo"] is None and problem["n_labeled"] == 10


def test_summary_groups_catalog_keys():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE label (target_kind, rec_key, label, ts, undone_at)")
    conn.executemany("INSERT INTO label VALUES ('candidate', ?, 'confirm', ?, NULL)",
                     [("catalog:a", NOW), ("catalog:b", NOW)])
    (row,) = labels.summary(conn, 90, now=NOW)["rows"]
    assert row["rule_id"] == "catalog" and row["n_labeled"] == 2
