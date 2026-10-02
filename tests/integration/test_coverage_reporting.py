"""Coverage is evidence completeness, not command success or tool outcome."""

import json

from tandem_data.analysis_input import AnalysisScope, read_analysis
from tandem_data.store import Store

from tandem_backend.analytics.coverage import coverage_details
from tandem_backend.analytics.service import analyze_store
from tandem_backend.cli import demo_home, main
from tandem_backend.data_access.ingest import ingest
from tandem_backend.data_access.store import CanonicalStore


def prepare(tmp_path):
    root, home = demo_home(tmp_path / "source"), tmp_path / "data"
    ingest(home, "codex", root)
    return root, home


def test_cli_explains_optional_inputs_without_running_inventory(tmp_path, capsys, monkeypatch):
    _, home = prepare(tmp_path)

    def forbidden(*args, **kwargs):
        raise AssertionError("analytics must not enable configuration collection")

    monkeypatch.setattr("tandem_data.inventory.scan_inventory", forbidden)
    main(["--home", str(home), "analytics", "--no-text"])
    text = capsys.readouterr().out
    assert "不是命令执行状态" in text and "未运行文本聚类" in text
    output = json.loads(text.splitlines()[-1])
    assert output["text_status"] == "excluded"
    assert output["coverage"]["sample_exclusions"] == "available"
    details = output["coverage_report"]["datasets"]
    assert "尚未显式扫描" in details["inventory"]["reasons"][0]
    assert details["native_event_payload"]["status"] == "excluded"
    assert "tool_call" not in details and "model_call" not in details


def test_known_missing_tool_endpoints_have_counts_and_remain_partial(tmp_path):
    root, home = prepare(tmp_path)
    path = next((root / "sessions").glob("*.jsonl"))
    with path.open("a") as f:
        for payload in [
            {"type": "function_call", "call_id": "without-result", "name": "shell", "arguments": "{}"},
            {"type": "function_call_output", "call_id": "without-call", "output": "result"},
        ]:
            f.write(json.dumps({"type": "response_item", "payload": payload}) + "\n")
    ingest(home, "codex", root)
    result = analyze_store(CanonicalStore(home), with_text=False)
    tools = result["coverage"]["tool_calls"]
    assert tools["status"] == "partial"
    assert tools["reason_counts"]["tool_calls_without_results"] == 1
    assert tools["reason_counts"]["tool_results_without_calls"] == 1
    assert result["coverage"]["events"]["reason_counts"]["missing_timestamps"] >= 2
    detail = coverage_details(result["coverage"])["tool_calls"]
    assert "1 条调用缺少对应结果" in detail["reasons"]
    assert "1 条结果缺少对应调用" in detail["reasons"]


def test_missing_scan_history_is_not_claimed_available(tmp_path):
    _, home = prepare(tmp_path)
    before = read_analysis(home, AnalysisScope("UTC"))["coverage"]["events"]
    with Store(home) as store:
        store.db.execute("DELETE FROM source_scan")
    bundle = read_analysis(home, AnalysisScope("UTC"))
    assert bundle["coverage"]["source_scans"]["status"] == "unavailable"
    assert bundle["coverage"]["source_scans"]["reason_counts"] == {"source_scan_boundary_unknown": 1}
    assert bundle["sessions"]  # Recorded facts still remain usable.
    assert bundle["coverage"]["events"] == before
    assert "source_scan_boundary_unknown" not in bundle["coverage"]["events"]["reasons"]


def test_incomplete_full_scan_and_intentional_sample_are_distinguished(tmp_path):
    _, home = prepare(tmp_path)
    with Store(home) as store:
        store.db.execute("UPDATE source_scan SET indexed_files=1")
    full = read_analysis(home, AnalysisScope("UTC"))["coverage"]["source_scans"]
    assert full["status"] == "partial" and full["reason_counts"] == {"source_scan_incomplete": 1}
    with Store(home) as store:
        store.db.execute("UPDATE source_scan SET selection='sample'")
    sample = read_analysis(home, AnalysisScope("UTC"))["coverage"]["source_scans"]
    assert sample["status"] == "partial" and sample["reason_counts"] == {"sampled_source_files": 1}


def test_unpaired_and_excluded_are_explained_without_alias_duplicates():
    entry = {"status": "partial", "rows": 5,
             "reasons": ["tool_results_outside_time_scope"],
             "reason_counts": {"tool_results_outside_time_scope": 1}}
    details = coverage_details({"tool_call": entry, "tool_calls": entry,
                                "sample_exclusions": {"status": "excluded", "rows": 2, "reasons": {"explicit": 2}}})
    assert list(details) == ["tool_calls", "sample_exclusions"]
    assert "1 条结果位于所选时间范围之外" in details["tool_calls"]["reasons"]
    assert "本次筛选额外排除 2 个会话" in details["sample_exclusions"]["reasons"]


def test_api_cli_and_report_share_coverage_contract(tmp_path, capsys):
    from fastapi.testclient import TestClient

    from tandem_backend.api import create_app
    from tandem_backend.reporting.narrative import markdown

    _, home = prepare(tmp_path)
    main(["--home", str(home), "analytics", "--no-text"])
    cli = json.loads(capsys.readouterr().out.splitlines()[-1])["coverage_report"]
    with TestClient(create_app(home=home)) as client:
        analytics_response = client.get("/v1/analytics/overview")
        narrative_response = client.get("/v1/analysis")
    assert analytics_response.status_code == narrative_response.status_code == 200
    api = analytics_response.json()["coverage_report"]
    narrative = narrative_response.json()
    report = narrative["coverage_report"]
    assert cli["contract"] == api["contract"] == report["contract"] == "input-coverage-v1"
    for key in ("events", "tool_calls", "inventory", "catalog", "native_event_payload"):
        assert cli["datasets"][key] == api["datasets"][key] == report["datasets"][key]
    assert "数据覆盖说明" in markdown(narrative)
    assert "尚未显式扫描本机安装配置" in markdown(narrative)


def test_all_agents_use_the_same_missing_input_contract(tmp_path):
    from tandem_data.validation.fixtures import create_sources

    roots = create_sources(tmp_path / "agents")
    roots["codex"] = demo_home(tmp_path / "codex")
    for agent, root in roots.items():
        home = tmp_path / ("data-" + agent)
        ingest(home, agent, root)
        coverage = read_analysis(home, AnalysisScope("UTC"))["coverage"]
        assert coverage["source_scans"]["status"] == "available"
        assert coverage["inventory"]["status"] == "unavailable"
        assert coverage["inventory"]["rows"] is None
        assert coverage["inventory"]["reasons"] == ["no_inventory_scan"]
        for key in ("events", "tool_call", "model_call"):
            entry = coverage[key]
            assert entry["status"] in ("available", "partial", "unavailable")
            assert bool(entry["reasons"]) == (entry["status"] != "available")


def test_new_source_reason_does_not_need_local_cli_patch():
    from tandem_data.coverage import dataset_coverage

    from tandem_backend.analytics.coverage import build_coverage_report, coverage_lines

    report = build_coverage_report({"new_source": dataset_coverage(3, reason_counts={"new_adapter_gap": 1})})
    assert report["datasets"]["new_source"]["reason_codes"] == ["new_adapter_gap"]
    assert report["datasets"]["new_source"]["counts"] == {"new_adapter_gap": 1}
    assert "new_adapter_gap" in "\n".join(coverage_lines(report))
    assert "不能推断为完整" in coverage_lines(build_coverage_report(None))[0]
