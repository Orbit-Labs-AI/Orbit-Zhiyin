import stat

from conftest import NOW

from orbit_backend.features.search_index import SearchIndex


def kinds(index):
    return dict(index.db.execute("SELECT kind, COUNT(*) FROM doc_meta GROUP BY kind").fetchall())


def seeded(world):
    world.project("p1", "Orbit 前端")
    world.session("s1", project="p1", title="修复登录页面的样式问题", started=NOW - 1000)
    world.message("s1", "请帮我修复登录页面的样式问题")
    world.message("s1", "assistant reply", actor="assistant", kind="message.assistant")
    world.call("s1", command="git status", files=["/repo/src/app/login.tsx"])
    world.call("s1", command="git status")
    return SearchIndex(world.home)


def test_full_build_counts_and_file_mode(world):
    index = seeded(world)
    assert index.status()["state"] == "empty"
    result = index.sync(world.orbit, data_rev=7)
    assert result["mode"] == "full"
    assert kinds(index) == {"session": 1, "message": 1, "command": 1, "file": 1}
    assert index.status() == {"state": "ready", "docs": 4, "data_rev": "7"}
    assert stat.S_IMODE(index.path.stat().st_mode) == 0o600
    text = index.db.execute("SELECT text FROM doc_file").fetchone()[0]
    assert text == "app/login.tsx"


def test_incremental_messages_and_session_rebuild(world):
    index = seeded(world)
    index.sync(world.orbit)
    world.message("s1", "第二条消息")
    world.session("s2", title="new session")
    result = index.sync(world.orbit)
    assert result["mode"] == "incremental" and result["sessions"] == 1
    assert kinds(index) == {"session": 2, "message": 2, "command": 1, "file": 1}
    # Nothing new: no duplicate rows.
    assert index.sync(world.orbit)["sessions"] == 0
    assert kinds(index)["message"] == 2
    # A session that gained a tool call is rebuilt without duplicating its docs.
    world.call("s1", command="npm test")
    index.sync(world.orbit)
    assert kinds(index) == {"session": 2, "message": 2, "command": 1, "file": 1}
    text = index.db.execute("SELECT text FROM doc_command").fetchone()[0]
    assert sorted(text.split("\n")) == ["git status", "npm test"]


def test_run_change_triggers_full_rebuild(world):
    index = seeded(world)
    index.sync(world.orbit)
    world.t.execute("INSERT INTO projection_run VALUES (2, 0, 0)")
    assert index.sync(world.orbit)["mode"] == "full"
    assert kinds(index) == {"session": 1, "message": 1, "command": 1, "file": 1}
