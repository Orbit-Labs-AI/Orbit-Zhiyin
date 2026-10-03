import json
import os

import pytest

from orbit_data import insights
from orbit_data.insights import match_sessions, numeric_summary, read_usage_data
from orbit_data.service import ImportRequest, ImportService
from orbit_data.store import Store
from orbit_data.validation.fixtures import create_sources

SECRET = "sk-ant-" + "Z9y8X7w6V5u4T3s2R1q0"


def usage_tree(tmp_path):
    root = tmp_path / "claude-config" / "usage-data"
    (root / "session-meta").mkdir(parents=True)
    (root / "facets").mkdir()
    meta = {
        "session_id": "demo",
        "tool_counts": {"Bash": 1},
        "user_interruptions": 0,
        "bash_would_prompt_count": 1,
        "duration_minutes": 2.5,
        "is_resumed": False,
        "first_prompt": f"check repo with key {SECRET}",
    }
    (root / "session-meta" / "demo.json").write_text(json.dumps(meta))
    (root / "facets" / "demo.json").write_text(
        json.dumps({"session_id": "demo", "outcome": "fully_achieved", "brief": "ok"})
    )
    (root / "session-meta" / "orphan.json").write_text(json.dumps({"tool_counts": {"Read": 2}}))
    (root / "facets" / "broken.json").write_text("{not json")
    (root / "facets" / "list.json").write_text("[1, 2]")
    (root / "facets" / "notes.txt").write_text("ignored")
    outside = tmp_path / "outside.json"
    outside.write_text(json.dumps({"session_id": "leak"}))
    (root / "facets" / "link.json").symlink_to(outside)
    (root / "session-meta" / "huge.json").write_text(" " * (insights.MAX_FILE_BYTES + 1) + "{}")
    return root


def test_reads_meta_and_facets_tolerantly(tmp_path):
    root = usage_tree(tmp_path)
    before = {p: p.stat().st_mtime_ns for p in root.rglob("*") if p.is_file()}
    report = read_usage_data(root)
    assert report["counts"]["session-meta"] == 2 and report["counts"]["facets"] == 1
    assert report["counts"]["sessions"] == 2
    errors = {item["file"]: item["error"] for item in report["errors"]}
    assert errors == {
        "facets/broken.json": "unreadable: JSONDecodeError",
        "facets/link.json": "not a regular file",
        "facets/list.json": "top level is not an object",
        "session-meta/huge.json": "file too large",
    }
    demo = next(item for item in report["sessions"] if item["session_id"] == "demo")
    assert demo["facets"]["outcome"] == "fully_achieved"
    assert SECRET not in json.dumps(report)
    assert "leak" not in json.dumps(report)
    assert {p: p.stat().st_mtime_ns for p in root.rglob("*") if p.is_file()} == before


def test_parent_directory_is_accepted(tmp_path):
    root = usage_tree(tmp_path)
    assert read_usage_data(root.parent)["path"] == str(root)


def test_explicit_path_is_required(tmp_path):
    with pytest.raises(ValueError):
        read_usage_data("")
    with pytest.raises(FileNotFoundError):
        read_usage_data(tmp_path / "missing")
    empty = tmp_path / "empty"
    empty.mkdir()
    assert read_usage_data(empty)["counts"]["sessions"] == 0


def test_numeric_summary():
    summary = numeric_summary({"a": 1, "b": True, "c": {"x": 1}, "d": {"y": "s"}, "e": "t"})
    assert summary == {"a": 1, "c": {"x": 1}}
    assert numeric_summary(None) == {}


def test_match_with_orbit_sessions(tmp_path):
    roots = create_sources(tmp_path / "fixtures")
    home = tmp_path / "home"
    with Store(home) as store:
        ImportService(store).import_source(ImportRequest("claude_code", roots["claude_code"]))
    rows = {
        row["session_id"]: row
        for row in match_sessions(home, read_usage_data(usage_tree(tmp_path)))
    }
    assert rows["demo"]["orbit"]["tool_calls"] == 1
    assert rows["demo"]["orbit"]["human_messages"] >= 1
    assert rows["demo"]["insights"]["tool_counts"] == {"Bash": 1}
    assert rows["demo"]["outcome"] == "fully_achieved"
    assert rows["orphan"]["orbit"] is None
    with pytest.raises(FileNotFoundError):
        match_sessions(tmp_path / "nohome", {"sessions": []})


def test_never_defaults_to_real_home(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path / "fake-home"))
    with pytest.raises(TypeError):
        read_usage_data()  # type: ignore[call-arg]
    assert not os.path.exists(tmp_path / "fake-home")
