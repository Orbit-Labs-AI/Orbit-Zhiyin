import io
import json

import pytest

from orbit_backend.cli import main as orbit_main
from orbit_backend.evalrun.cli import main


def _run(argv):
    out = io.StringIO()
    return main(argv, out=out), out.getvalue()


def test_list(fake_suites, tmp_path):
    code, text = _run(["eval", "list", "--home", str(tmp_path)])
    assert code == 0 and "ok" in text and "half" in text


def test_run_pass_writes_history_and_json(fake_suites, tmp_path):
    report = tmp_path / "out" / "report.json"
    code, text = _run(["eval", "run", "--suite", "ok", "--suite", "skip", "--fail-under", "1",
                       "--json", str(report), "--home", str(tmp_path)])
    assert code == 0 and text.strip().splitlines()[-1].startswith("PASS score=1.000")
    assert "skip   no data" in text
    run_id = json.loads(report.read_text())["run_id"]
    code, text = _run(["eval", "history", "--home", str(tmp_path)])
    assert code == 0 and run_id in text and "PASS" in text


def test_run_fail_exit_code_and_failed_checks(fake_suites, tmp_path):
    code, text = _run(["eval", "run", "--suite", "half", "--home", str(tmp_path)])
    assert code == 1 and "failed: half.b" in text
    assert "FAIL score=0.500" in text


def test_no_store_writes_nothing(fake_suites, tmp_path):
    code, _ = _run(["eval", "run", "--suite", "ok", "--no-store", "--home", str(tmp_path)])
    assert code == 0 and not (tmp_path / "app.db").exists()
    assert _run(["eval", "history", "--home", str(tmp_path)]) == (0, "还没有评测记录。\n")


@pytest.mark.parametrize("argv", [["eval", "run", "--suite", "nope"], ["eval", "run", "--fail-under", "2"],
                                  ["eval", "bogus"], ["eval", "run", "--fail-under", "x"]])
def test_usage_errors_exit_2(fake_suites, tmp_path, argv):
    assert _run([*argv, "--home", str(tmp_path)])[0] == 2
    assert not (tmp_path / "app.db").exists()


def test_orbit_entry_delegates(fake_suites, tmp_path, capsys):
    with pytest.raises(SystemExit) as exc:
        orbit_main(["eval", "run", "--suite", "half", "--no-store", "--home", str(tmp_path)])
    assert exc.value.code == 1 and "FAIL" in capsys.readouterr().out
