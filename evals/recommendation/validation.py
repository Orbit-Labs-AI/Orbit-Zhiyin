"""Reproducible recommendation cases; public metadata and fictional activity only."""

import argparse
import hashlib
import json
import platform
import subprocess
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from benchmarks.recommendation import benchmark

from tandem_backend.analytics.service import analyze_bundle
from tandem_backend.recommend.catalog import load_catalog
from tandem_backend.recommend.service import recommend

from .demo import synthetic_bundle

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = Path(__file__).with_name("fixtures") / "reviewed-skills.json"
CONTEXT = {"agent": "codex", "languages": ["python", "typescript"],
           "tools": ["shell", "pytest", "playwright"], "software": ["python", "pytest-cov", "chromium"],
           "permissions": ["repository_read", "repository_write"]}


def span(low, high=None):
    return {"low": low, "high": low if high is None else high}


def fixture_bundle():
    bundle = synthetic_bundle()
    for event in bundle.events:
        label = event.get("attrs", {}).get("interaction", {})
        if "friction_types" in label:
            label["friction_types"] = ["verification"]
    return bundle


def _write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def generate_cases():
    bundle = fixture_bundle()
    analysis = analyze_bundle(bundle, with_text=False)
    items = json.loads(FIXTURE.read_text(encoding="utf-8"))["items"]
    task = analysis["tasks"]["records"][0]["task_id"]
    cases = []

    def run(uid, dimension, description, context=None, *, catalog=None, data=None, expected_top=None,
            expected_status="ready", check=None):
        context = {**deepcopy(CONTEXT), **(context or {})}
        result = recommend(data if data is not None else analysis,
                           catalog=items if catalog is None else catalog, context=context)
        top = next((c["name"] for c in result["recommendations"]), None)
        checks = [{"name": "status", "expected": expected_status, "actual": result["status"],
                   "passed": result["status"] == expected_status}]
        if expected_top is not None:
            checks.append({"name": "top_skill", "expected": expected_top, "actual": top,
                           "passed": top == expected_top})
        if check:
            name, expected, actual = check(result)
            checks.append({"name": name, "expected": expected, "actual": actual, "passed": expected == actual})
        case = {"id": uid, "dimension": dimension, "description": description, "input_context": context,
                "checks": checks, "passed": all(c["passed"] for c in checks), "result": result}
        cases.append(case)
        return case

    for scope, dimension, pairs in (
        ("global", "capability", [("retry_control", "systematic-debugging"), ("verification", "webapp-testing")]),
        ("project", "tool", [("pytest", "pytest-coverage"), ("playwright", "webapp-testing")]),
        ("task", "task_type", [("debug", "systematic-debugging"), ("create", "test-driven-development")]),
    ):
        for value, expected in pairs:
            target = {"global": None, "project": "synthetic-project", "task": task}[scope]
            run(f"{scope}-{value}", scope, f"仅改变 {scope} 的 {dimension}={value}",
                {"preferences": [{"scope": scope, "target_id": target, "dimension": dimension, "value": value}]},
                expected_top=expected)

    debug_pref = {"preferences": [{"dimension": "capability", "value": "retry_control"}]}
    run("no-preferences", "ablation", "去掉偏好，记录未个性化排序")
    run("task-wins", "scope", "同一维度按 task > project > global 选择", {"preferences": [
        {"scope": "global", "dimension": "task_type", "value": "test"},
        {"scope": "project", "target_id": "synthetic-project", "dimension": "task_type", "value": "debug"},
        {"scope": "task", "target_id": task, "dimension": "task_type", "value": "create"}]},
        expected_top="test-driven-development")
    run("wrong-project", "scope", "其他项目的偏好不参与排序", {"preferences": [
        {"scope": "project", "target_id": "unrelated-project", "dimension": "tool", "value": "pytest"}]},
        check=lambda r: ("effective_preferences", [], r["states"][0]["preference_state"]["effective"]))
    run("conflicting-preferences", "scope", "同范围冲突保留，不能任选一个", {"preferences": [
        {"dimension": "tool", "value": "pytest"}, {"dimension": "tool", "value": "playwright"}]},
        check=lambda r: ("conflicts", 1, len(r["states"][0]["preference_state"]["conflicts"])))
    run("unknown-style", "metadata", "资源没有声明表达详略时返回 unknown", {"preferences": [
        {"dimension": "detail", "value": "brief"}]},
        check=lambda r: ("outcomes", ["unknown"], sorted({m["outcome"] for c in r["recommendations"]
                              for m in c["preference_explanation"]["matches"]})))
    run("known-empty-tools", "compatibility", "已确认没有所需工具时排除候选", {**debug_pref, "tools": []},
        expected_status="no_matching_resources")
    run("unknown-tools", "compatibility", "工具未知时保留待确认状态", {**debug_pref, "tools": None},
        expected_top="systematic-debugging", check=lambda r: ("card_status", "needs_context", r["recommendations"][0]["recommendation_status"]))
    run("denied-write", "permissions", "强偏好不能覆盖明确禁止的权限", {**debug_pref, "denied_permissions": ["repository_write"]},
        expected_status="no_matching_resources")
    installed = next(i for i in items if i["identity"]["name"] == "systematic-debugging")
    run("already-installed", "compatibility", "已安装资源不重复推荐", {**debug_pref, "installed_resources": [installed["identity"]["id"]]},
        check=lambda r: ("contains_installed", False, any(c["name"] == "systematic-debugging" for c in r["recommendations"])))
    run("explicit-empty-catalog", "ingestion", "显式空目录不能回退到种子", catalog=[], expected_status="no_matching_resources")
    drafts = deepcopy(items)
    for item in drafts:
        item["evidence_quality"]["status"] = "draft"
    run("unreviewed-drafts", "ingestion", "下载完成不等于完成能力审核", catalog=drafts, expected_status="no_matching_resources")
    malformed = deepcopy(items)
    malformed[0]["extra_field"] = "invalid"
    run("partial-invalid-catalog", "ingestion", "单个非法条目不拖垮其余资源", catalog=malformed,
        check=lambda r: ("invalid_item", True, any(d["reason"] == "invalid_item" for d in r["diagnostics"])))
    quiet = fixture_bundle()
    quiet.tool_calls = []
    quiet.model_calls = []
    for event in quiet.events:
        label = event.get("attrs", {}).get("interaction", {})
        if label:
            label.update(intents=["request"], friction_types=[])
    run("preference-without-evidence", "grounding", "只有偏好没有瓶颈时不声称需要干预", debug_pref,
        data=analyze_bundle(quiet, with_text=False), expected_status="no_threshold_met")

    # Same observed failures throughout; benefit inputs cannot change ranking.
    signal = next(s for s in analysis["bottleneck_recommendations"]["signals"] if s["rule_id"] == "identical_retries")
    scenario = {"resource_id": installed["identity"]["id"], "signal_id": signal["signal_id"], "repeated_windows": 10,
                "analysis_digest": analysis["analysis_digest"],
                "reduction": span(.25, .5), "minutes_per_occurrence": span(10), "setup_minutes": span(5, 10),
                "extra_minutes_per_window": span(1, 2), "tokens_per_occurrence": span(1000),
                "setup_tokens": span(300, 500), "extra_tokens_per_window": span(100, 200),
                "basis": "构造测试假设：未来 10 个窗口重复当前 2 次无效重试；每次 10 分钟 / 1000 Token；改善 25%–50%，尚无实测。"}

    def benefit_case(uid, description, changes, expected):
        return run(uid, "benefit", description, {**debug_pref, "benefit_scenarios": [{**scenario, **changes}]},
                   expected_top="systematic-debugging", check=lambda r: (
                       "net_minutes", expected, r["recommendations"][0]["benefit_estimate"]["estimates"][0]["time_minutes"]["net_savings"]))

    benefit_case("benefit-positive", "10 个窗口的净时间与 Token 估计", {}, span(20, 85))
    benefit_case("benefit-short-horizon", "仅用一次时可能尚未收回配置开销", {"repeated_windows": 1}, span(-7, 4))
    benefit_case("benefit-negative", "开销过高时保留负收益", {"setup_minutes": span(100), "extra_minutes_per_window": span(20)}, span(-250, -200))
    benefit_case("benefit-unknown-cost", "缺少运行成本时不计算净收益", {"extra_minutes_per_window": None}, None)
    benefit_case("benefit-zero-effect", "改善假设为零时不会输出正收益", {"reduction": span(0)}, span(-30, -15))
    run("benefit-stale-signal", "benefit", "过期或其他会话的信号不能借用当前计数", {**debug_pref, "benefit_scenarios": [
        {**scenario, "signal_id": "not-in-this-analysis"}]}, expected_top="systematic-debugging",
        check=lambda r: ("benefit_status", "insufficient_inputs", r["recommendations"][0]["benefit_estimate"]["status"]))
    run("benefit-stale-snapshot", "benefit", "信号 ID 未变但快照变更时拒绝旧估计", {**debug_pref, "benefit_scenarios": [
        {**scenario, "analysis_digest": "stale-analysis"}]}, expected_top="systematic-debugging",
        check=lambda r: ("excluded_reason", "analysis_snapshot_mismatch", r["recommendations"][0]["benefit_estimate"]["excluded"][0]["reason"]))
    run("permutation-stability", "determinism", "资源顺序反转不改变推荐", debug_pref, catalog=list(reversed(items)),
        check=lambda r: ("cards", cases[0]["result"]["recommendations"], r["recommendations"]))
    return bundle, analysis, items, cases


def snapshot_check(home):
    path = home / "skills.raw.json"
    if not path.is_file():
        return {"status": "not_run", "reason": "运行 scripts/test-skill-catalog.sh --fetch 后可核对本地抓取快照。"}
    raw = json.loads(path.read_text(encoding="utf-8"))
    index = {r["resource"]["item_id"]: r["resource"] for r in raw["items"]}
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))["items"]
    checks = []
    for item in fixture:
        actual = index.get(item["identity"]["id"], {})
        checks.append({"name": item["identity"]["name"], "passed": (
            actual.get("commit_sha") == item["source"]["verified_sha"]
            and actual.get("metadata", {}).get("source_blob_sha") == item["source"]["blob_sha"]
            and hashlib.sha256(actual.get("body", "").encode()).hexdigest() == item["source"]["content_sha256"])})
    exported = home / "recommend" / "skills.json"
    draft_result = None
    if exported.is_file():
        items = json.loads(exported.read_text(encoding="utf-8"))["items"]
        result = recommend(analyze_bundle(fixture_bundle(), with_text=False), catalog=items, context=CONTEXT)
        draft_result = {"count": len(items), "accepted": len(load_catalog(items=items).items),
                        "recommended": len(result["recommendations"]), "status": result["status"]}
    return {"status": "passed" if all(c["passed"] for c in checks) else "failed", "raw_count": len(index),
            "checks": checks, "unreviewed_export": draft_result}


def run_tests(output):
    junit = output / "pytest.xml"
    command = [sys.executable, "-m", "pytest", "-q", "packages/backend/tests/recommend",
               "tests/integration/test_recommend_validation.py", f"--junitxml={junit.resolve()}"]
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
    (output / "pytest.log").write_text(result.stdout + result.stderr, encoding="utf-8")
    print(result.stdout, end="")
    print(result.stderr, end="", file=sys.stderr)
    suites = ET.parse(junit).getroot() if junit.is_file() else []
    counts = {key: sum(int(s.get(key, "0")) for s in suites) for key in ("tests", "failures", "errors", "skipped")}
    return {"status": "passed" if result.returncode == 0 else "failed", "exit_code": result.returncode, **counts,
            "command": "python -m pytest -q packages/backend/tests/recommend tests/integration/test_recommend_validation.py"}


def _json(value):
    return "```json\n" + json.dumps(value, ensure_ascii=False, indent=2) + "\n```"


def render_report(result):
    cases = result["cases"]
    rows = ["# Recommend 偏好与收益测试报告", "",
            f"生成时间：{result['generated_at']}。本报告由 `evals.recommendation.validation` 实际调用推荐入口生成。", "",
            f"**案例 {sum(c['passed'] for c in cases)}/{len(cases)} 通过；自动测试状态：{result['tests']['status']}。**", "",
            "## 结论与证据范围", "",
            "已实现用户全局、项目、任务三层显式偏好影响 Skill 召回和排序，并接入 analytics 已解析的偏好历史。收益使用瓶颈实际计数与明确填写的成本／改善假设，分别给出分钟和 Token 的净收益区间。", "",
            "这里的四个 Skill 来自已下载的公共仓库快照，内容与来源经过 Codex 阅读核对；会话、成本和改善幅度均为构造案例。测试只运行 recommend，不执行上游 Skill，因此不能把通过率或收益数字当作真实效果评测。", "",
            "## 调试发现和修改", "",
            "| 调试前 | 修改后 | 验证依据 |", "| --- | --- | --- |",
            "| preference_state 只有 ID，used_for_ranking 恒为 false | 复用历史解析器，加入显式三层偏好及独立召回路线 | 单变量对照、撤销／冲突／跨根会话测试 |",
            "| 任意目录排序靠瓶颈、关键词和环境，无法表达当前偏好 | preference_support 声明支持；缺失标签保留 unknown | 排序解释包含维度、作用域、来源、命中与分数贡献 |",
            "| 只有启发式 priority_score，effect_status=unmeasured | 新增 benefit_estimate；优先级和收益互不替代 | 手算区间、负收益、未知成本、零改善、过期信号 |",
            "| 信号 ID 可能跨快照稳定，不能单独确认收益基线 | 情景同时绑定 analysis_digest，回本计算使用未舍入数值 | 同 ID 的旧快照拒绝；微小正收益仍能计算回本窗口 |",
            "| 全量抓取 JSON 尚未审核，直接运行没有推荐 | 保持草稿过滤，另建四项内容审阅评测目录 | 核对 commit、blob 和解析正文 SHA-256 |", "",
            "## 输入和资源", "",
            "所有单变量对照使用同一构造会话：8 条确认意图消息中 3 条验收纠偏；10 次工具调用中 3 次失败，形成 2 对同参数重试；5 次模型请求合计 20,000 输入、500 输出 Token。所有环境依赖均明确给出。", "",
            _json(CONTEXT), "", "| Skill | 固定来源 | 元数据依据与限制 |", "| --- | --- | --- |"]
    for item in result["items"]:
        source = item["source"]
        url = f"{source['url']}/blob/{source['verified_sha']}/{source['source_path']}"
        rows.append(f"| {item['identity']['name']} | [源文件]({url}) | {item['capability']['text']} 仅手工试用兼容，执行效果未测。 |")
    rows.extend(["", "真实快照核对：", "", _json(result["snapshot"]), "",
                 "## 三类偏好的对照案例", "",
                 "每一对只更改偏好值；候选 Skill、瓶颈、模型与工具环境保持相同。首选断言在运行前固定，并不按输出倒填。", "",
                 "| 案例 | 作用域及偏好 | 首选 Skill | 优先级 | 结果 |", "| --- | --- | --- | ---: | --- |"])
    for case in cases[:6]:
        pref = case["input_context"]["preferences"][0]
        card = case["result"]["recommendations"][0]
        rows.append(f"| {case['id']} | {pref['scope']} / {pref['dimension']}={pref['value']} | {card['name']} | {card['priority_score']} | {'通过' if case['passed'] else '失败'} |")
    rows.extend(["", "优先级是启发式试用顺序，不是效果百分比。MMR 会照顾能力多样性，因此第二、第三张卡片不保证按原始优先级递减。偏好匹配权重默认为 0.30；无有效偏好时不加入该权重及路线。", "",
                 "## 具体输入和生成结果", ""])
    for uid in ("project-pytest", "task-create", "benefit-positive"):
        case = next(c for c in cases if c["id"] == uid)
        card = case["result"]["recommendations"][0]
        rows.extend([f"### {uid}", "", case["description"], "",
                     "在上面的共同环境 context 中加入：", "", _json({k: v for k, v in case["input_context"].items() if k not in CONTEXT}), "",
                     "实际输出节选：", "", _json({"name": card["name"], "recommendation_status": card["recommendation_status"],
                        "priority_score": card["priority_score"], "matched_preferences": card["preference_explanation"]["matches"],
                        "observed_rules": [s["rule_id"] for s in card["explanation"]["observed"]],
                        "net_minutes": next((e["time_minutes"]["net_savings"] for e in card["benefit_estimate"]["estimates"]), None),
                        "net_tokens": next((e["tokens"]["net_savings"] for e in card["benefit_estimate"]["estimates"]), None),
                        "effect_status": card["effect_status"]}), ""])
    rows.extend(["## 收益计算和敏感性", "",
                 "净收益 = 观察到的事件数 × 预测窗口数 × 单次成本 × 改善比例 − 一次配置成本 − 窗口数 × 每窗口新增成本。下界使用最小节省减最大开销，上界相反。分钟和 Token 分开计算，不能相互抵消。", "",
                 "正例的 2 次重复重试来自构造会话中的真实计算；假设未来重复 10 个窗口、每次 10 分钟、改善 25%–50%，则毛节省为 50–100 分钟，扣除 15–30 分钟开销，净节省 **20–85 分钟**。Token 的同口径净节省为 **2,500–8,700**。这些上下限是情景边界，不是置信区间。", "",
                 "| 案例 | 改变条件 | 净时间收益 | 结果 |", "| --- | --- | --- | --- |"])
    for case in cases:
        if case["dimension"] != "benefit":
            continue
        benefit = case["result"]["recommendations"][0]["benefit_estimate"]
        net = next((e["time_minutes"]["net_savings"] for e in benefit["estimates"]), None)
        rows.append(f"| {case['id']} | {case['description']} | {net if net is not None else '未知／不计算'} | {'通过' if case['passed'] else '失败'} |")
    rows.extend(["", "同一失败可能同时触发工具失败和重复重试；不同 Skill 也可能处理同一事件，所以结果是可选情景，不提供可累加总收益。当前自动取数支持 correction_density、identical_retries、tool_failures；其他瓶颈缺少明确的事件成本口径时不估算。", "",
                 "## 多角度结果", "", "| 案例 | 检查内容 | 实际状态 | 结果 |", "| --- | --- | --- | --- |"])
    for case in cases[6:]:
        rows.append(f"| {case['id']} | {case['description']} | {case['result']['status']} | {'通过' if case['passed'] else '失败'} |")
    rows.extend(["", "自动测试还覆盖历史修改／撤销、未来时间、引用文本、项目和任务隔离、API 422 校验、偏好候选不被召回上限挤出、输入不变、未知数据与布尔／NaN／无限值拒绝。", "",
                 _json(result["tests"]), "", "## 性能观察", "",
                 f"运行环境：Python {result['environment']['python']}，{result['environment']['platform']}。", "",
                 "只计已生成 analytics 后的 recommend 调用；不含抓取、模型运行或 Skill 执行。1,000 项是四种元数据的构造复制，不能代表真实大目录质量或并发吞吐。", "",
                 "| 条目数 | 次数 | 中位耗时 ms | 最大耗时 ms |", "| ---: | ---: | ---: | ---: |"])
    for row in result["performance"]:
        rows.append(f"| {row['items']} | {row['runs']} | {row['median_ms']} | {row['max_ms']} |")
    rows.extend(["", "## 本地复现", "", "在仓库根目录执行：", "",
                 "```bash\nbash scripts/test-recommend.sh\n```", "",
                 "脚本运行推荐模块和报告集成测试，随后生成 `.local/recommendation-validation/report.md`、`results.json`、`input-bundle.json`、`analysis.json`、`pytest.xml` 和 `pytest.log`。失败返回非零退出码。输出只含构造会话与公共资源元数据。", "",
                 "完整结果保留每个案例的 context、推荐卡片、原始分数贡献、召回路线、信号证据与收益参数；报告中的 JSON 是节选。初次使用先按仓库指南同步 Python 3.13 workspace。", "",
                 "API 使用 `POST /v1/analytics/recommendations`，请求中的 `context.preferences` 和 `context.benefit_scenarios` 与上述案例一致。收益情景的 signal_id 和 analysis_digest 必须取自同一分析快照；project/task target_id 必须对应解析后的规范 ID。", "",
                 "## 仍需验证", "",
                 "偏好能改变排序已经得到规则测试支持，但还没有独立人工标注的推荐相关性评估。收益具备可复算的估计接口，但改善比例和单位成本尚未从 A/B 实验校准。应固定任务、模型、输入和验收标准，成对执行基线／Skill，记录成功率、用时、Token、配置与验证开销，才能检验预测是否准确。", "",
                 "原始抓取结果仍以草稿为主；本报告只审阅四项作接入评测，不代表已完成全部目录审核。单根会话包含多个未选定任务时，任务偏好保持未解析。只凭偏好、没有瓶颈证据时不会输出干预推荐。UI 原型尚未接入本轮新增字段。", ""])
    return "\n".join(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / ".local/recommendation-validation")
    parser.add_argument("--catalog-home", type=Path, default=ROOT / ".local/skill-catalog")
    parser.add_argument("--skip-tests", action="store_true", help="Generate cases only; report marks automated tests not_run.")
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    tests = {"status": "not_run"} if args.skip_tests else run_tests(output)
    bundle, analysis, items, cases = generate_cases()
    result = {"generated_at": datetime.now(timezone.utc).isoformat(), "synthetic_activity": True,
              "environment": {"python": platform.python_version(), "platform": platform.platform()},
              "tests": tests, "items": items, "cases": cases, "snapshot": snapshot_check(args.catalog_home),
              "performance": benchmark(analysis, items, CONTEXT), "dimensions": dict(Counter(c["dimension"] for c in cases))}
    _write(output / "input-bundle.json", asdict(bundle))
    _write(output / "analysis.json", analysis)
    _write(output / "results.json", result)
    (output / "report.md").write_text(render_report(result), encoding="utf-8")
    passed = all(c["passed"] for c in cases) and tests["status"] != "failed" and result["snapshot"]["status"] != "failed"
    print(json.dumps({"status": "passed" if passed else "failed", "cases": len(cases),
                      "passed": sum(c["passed"] for c in cases), "tests": tests,
                      "report": str(output / "report.md")}, ensure_ascii=False))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
