"""Orchestration completion is not the same fact as a command's exit status."""

import json

from orbit_backend.analysis import analyze
from orbit_backend.importers.codex import _command_output_hint, _status, _status_details
from orbit_backend.pipeline_eval import _write_case
from orbit_backend.recommend import recommend
from orbit_backend.store import Store, import_codex


def command_result(code=0, output="command stdout"):
    return {"chunk_id": "fixture", "wall_time_seconds": 0.1, "exit_code": code, "output": output}


def wrapper(*values):
    return "Script completed\nWall time 0.2 seconds\nOutput:\n" + "\n".join(json.dumps(v) for v in values)


def test_completed_script_preserves_failed_nested_command_without_scanning_stdout():
    assert _status(wrapper(command_result(1)), "exec", True) == "failed"
    stdout = json.dumps(command_result(1)) + "\nProcess exited with code 1"
    assert _status(wrapper(command_result(0, stdout)), "exec", True) == "success"
    assert _status(wrapper(command_result(1)), "mcp__business__fixture", True) is None
    assert _status(wrapper(command_result(1)), "exec", False) is None


def test_mixed_command_batch_keeps_known_failure_and_pending_returns():
    info = _status_details(wrapper(command_result(0), command_result(2)), "exec", True)
    assert info["status"] == "failed" and info["failed_command_results"] == 1
    assert info["known_command_results"] == 2
    pending = {"wall_time_seconds": 0.1, "output": "running", "session_id": 123}
    info = _status_details(wrapper(command_result(0), pending), "exec", True)
    assert info["status"] is None and info["unknown_return_values"] == 1
    settled = [{"status": "fulfilled", "value": command_result(0)}]
    assert _status(wrapper(settled), "exec", True) == "success"


def test_bool_codes_and_unstructured_body_are_unknown():
    assert _status(wrapper(command_result(True)), "exec", True) is None
    assert _status("Script completed\nWall time 0.1 seconds\nOutput:\nexit_code:1", "exec", True) is None
    assert _status("Script failed\nWall time 0.1 seconds\nScript error: invalid syntax", "exec") == "failed"
    assert _status("Chunk ID: fixture\nProcess exited with code 1\nOutput:\n", "exec_command") is None


def test_source_hint_ignores_comments_and_literals():
    assert _command_output_hint("text(await tools.exec_command({cmd:'run-check'}));")
    assert _command_output_hint(json.dumps({"code": "text(await tools.write_stdin({session_id:1}));"}))
    assert not _command_output_hint("// tools.exec_command({})\ntext('fixture');")
    assert not _command_output_hint("text('tools.exec_command({})');")


def test_wrapped_failures_reach_the_actual_pipeline_but_stdout_fixtures_do_not(tmp_path):
    for name, result, expected in (("failed", command_result(1), {"systematic-debugging"}),
                                   ("fixture", command_result(0, json.dumps(command_result(1))), set())):
        home = tmp_path / name / "codex"
        _write_case(home, "wrapper_test", [{"kind": "user", "text": "请完成可运行版本，最后运行测试。"}] + [
            {"kind": "tool", "tool": "exec", "arguments": "text(await tools.exec_command({cmd:'check'}));", "output": wrapper(result)}
            for _ in range(3)])
        store = Store(home.parent / "evaluation.sqlite")
        import_codex(store, home)
        data = analyze(store)
        assert {r["resource_id"] for r in recommend(data)} == expected
        assert data["counts"]["explicit_tool_failures"] == (3 if name == "failed" else 0)
