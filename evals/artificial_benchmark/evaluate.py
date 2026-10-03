"""Interleaved held-out execution and paired, missing-aware measurements."""

from __future__ import annotations

import argparse
import concurrent.futures
import csv
import itertools
import random
import shutil
import statistics
from pathlib import Path

from .runner import one_run
from .study import ARMS, FAMILIES, MODULE, digest, load_frozen, read, save, tree, verify_source


def compare(a: dict, b: dict) -> str:
    if a["passed"] is None or b["passed"] is None:
        return "unknown"
    if a["passed"] != b["passed"]:
        return "win" if a["passed"] else "loss"
    if not a["passed"]:
        return "tie"
    left, right = a["usage"]["total_tokens"], b["usage"]["total_tokens"]
    if left is None or right is None:
        return "unknown"
    return "win" if left < right else "loss" if left > right else "tie"


def aggregate(rows: list[dict]) -> dict:
    passed = sum(r["passed"] is True for r in rows)
    known_pass = sum(r["passed"] is not None for r in rows)
    tokens = [r["usage"]["total_tokens"] for r in rows if r["usage"]["total_tokens"] is not None]
    total = sum(tokens) if len(tokens) == len(rows) and rows else None
    return {"runs": len(rows), "scored": known_pass, "passed": passed,
            "pass_rate": passed / known_pass if known_pass else None,
            "usage_complete_runs": len(tokens), "total_tokens": total,
            "known_total_tokens": sum(r["usage"]["known_total_tokens"] for r in rows),
            "mean_tokens": total / len(rows) if total is not None else None,
            "median_tokens_known_runs": statistics.median(tokens) if tokens else None,
            "tokens_per_success": total / passed if total is not None and passed else None,
            "agent_turns": sum(r["agent_turns"] for r in rows),
            "tool_calls": sum(r["tool_calls"] for r in rows),
            "failed_tool_calls": sum(r["failed_tool_calls"] for r in rows),
            "wall_time_seconds": sum(r["wall_time_seconds"] for r in rows)}


def check_adaptation(output: Path) -> dict:
    path = output / "adaptation/frozen.json"
    if digest(path) != path.with_suffix(".sha256").read_text().strip():
        raise ValueError("Adaptation manifest changed")
    frozen = read(path)
    if digest(output / "history_bundle.json") != frozen["history_bundle_sha256"]:
        raise ValueError("Adaptation history changed")
    for name, value in frozen["adapter_files"].items():
        if digest(MODULE / name) != value:
            raise ValueError("Test/adaptation code changed after adaptation freeze")
    for arm, expected in frozen["arms"].items():
        if tree(output / "adaptation" / arm / "assets") != expected:
            raise ValueError(f"Personalization changed: {arm}")
    return frozen


def report(output: Path) -> dict:
    study = load_frozen(output)
    rows = [read(p) for p in sorted((output / "test").glob("*/result.json"))]
    by_id = {(r["task_id"], r["arm"]): r for r in rows}
    pairs = []
    for task in study["tasks"]:
        if task["split"] != "test":
            continue
        for left, right in itertools.combinations(ARMS, 2):
            if (task["task_id"], left) in by_id and (task["task_id"], right) in by_id:
                a, b = by_id[task["task_id"], left], by_id[task["task_id"], right]
                pairs.append({"task_id": task["task_id"], "left": left, "right": right,
                              "verdict": compare(a, b)})
    overlaps = {r["test"] for r in read(output / "tasks/split-overlap.json") if r["same_environment"]}
    adaptation = {}
    for arm in ("ours", "llm"):
        calls = [read(p) for p in sorted((output / "adaptation" / arm).rglob("trajectory.json"))]
        values = [c["usage"]["total_tokens"] for c in calls]
        adaptation[arm] = {"model_calls": len(calls), "total_tokens": sum(values) if all(v is not None for v in values) else None,
                           "known_total_tokens": sum(c["usage"]["known_total_tokens"] for c in calls),
                           "model_wall_time_seconds": sum(c["wall_time_seconds"] for c in calls)}
    summary = {"complete": len(rows) == 36, "completed_test_runs": len(rows),
               "arms": {arm: aggregate([r for r in rows if r["arm"] == arm]) for arm in ARMS},
               "families": {f: {a: aggregate([r for r in rows if r["family"] == f and r["arm"] == a])
                                for a in ARMS} for f in FAMILIES},
               "nonidentical_environment_tests": {a: aggregate([r for r in rows if r["arm"] == a and r["task_id"] not in overlaps])
                                                   for a in ARMS},
               "identical_environment_test_ids": sorted(overlaps), "paired": pairs, "adaptation": adaptation,
               "amortized_horizons": {}}
    for arm in ARMS:
        online = summary["arms"][arm]["mean_tokens"]
        adapt = 0 if arm == "vanilla" else adaptation[arm]["total_tokens"]
        summary["amortized_horizons"][arm] = {str(n): adapt + n * online if adapt is not None and online is not None else None
                                             for n in (12, 24, 48)}
    folder = output / "report"
    folder.mkdir(exist_ok=True)
    save(folder / "summary.json", summary)
    with (folder / "results.csv").open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["task_id", "family", "arm", "passed", "total_tokens", "usage_complete", "agent_turns",
                         "tool_calls", "failed_tool_calls", "wall_time_seconds"])
        for row in rows:
            writer.writerow([row[k] for k in ("task_id", "family", "arm", "passed")] +
                            [row["usage"]["total_tokens"], row["usage"]["complete"]] +
                            [row[k] for k in ("agent_turns", "tool_calls", "failed_tool_calls", "wall_time_seconds")])

    def number(value):
        return "未知" if value is None else f"{value:,.0f}"

    lines = ["# Orbit artificial benchmark", "", "## 1. 实验设置", "",
             "SkillLearnBench-derived，Pi memory-off，kimi-coding/k3，thinking=max。"
             "每族 1–3 为 history、4–6 为 test；共 12 条 history、36 个 test runs。",
             f"当前完成：{len(rows)}/36。" + ("尚未完成，不能作最终结论。" if len(rows) != 36 else ""), "",
             f"上游 `{study['benchmark_commit']}`；Orbit `{study['orbit_commit']}`；Pi `{study['pi_version']}`。",
             "每次 fresh process/session/container；无网络和宿主挂载，个性化资产只读，hidden verifier 在 agent 退出后注入。",
             "", "## 2. 主结果", "", "| 组 | 完成 | 通过/已评分 | Online tokens | Tokens/success |",
             "|---|---:|---:|---:|---:|"]
    for arm, value in summary["arms"].items():
        lines.append(f"| {arm} | {value['runs']} | {value['passed']}/{value['scored']} | "
                     f"{number(value['total_tokens'])} | {number(value['tokens_per_success'])} |")
    lines += ["", "未知用量不记为零；总量含失败任务和缓存输入；reasoning 不重复计数。",
              "", "## 3. 配对与逐题结果", "", "| Task | Vanilla pass/tokens | Ours pass/tokens | LLM pass/tokens |",
              "|---|---|---|---|"]
    for task in study["tasks"]:
        if task["split"] != "test":
            continue
        cells = []
        for arm in ARMS:
            row = by_id.get((task["task_id"], arm))
            cells.append(f"{row['passed']} / {number(row['usage']['total_tokens'])}" if row else "未运行")
        lines.append("| " + task["task_id"] + " | " + " | ".join(cells) + " |")
    for left, right in itertools.combinations(ARMS, 2):
        matched = [p for p in pairs if p["left"] == left and p["right"] == right]
        counts = {v: sum(p["verdict"] == v for p in matched) for v in ("win", "tie", "loss", "unknown")}
        lines.append(f"\n{left} vs {right}：{counts}")
    lines += ["", "## 4. 个性化产物与覆盖", "",
              "B 经过真实 Pi connector、canonical 数据库、画像/事实分析、rec-engine-v2 和产品产物生成；"
              "采用产品选中的可执行资源，未人工编写领域技能或为结果降低门槛。",
              "完整 slate、gate 和物化去向见 `../adaptation/ours/coverage.json`；"
              "Pi 不支持的 MCP/subagent 与固定模型冲突等均保留原因。",
              "C 将同一份完整 history bundle 交给 Kimi，自行提炼一个简洁可复用 Skill；没有固定 token 上限。",
              "", "## 5. Adaptation 成本与摊销", ""]
    for arm, value in adaptation.items():
        lines.append(f"- {arm}：{value['model_calls']} 次模型调用，{number(value['total_tokens'])} tokens。")
    lines += ["", "摊销公式 adaptation + N × 本轮 online mean，N=12/24/48；"
              "这是按本轮均值推算，不是额外重复实验。详见 `summary.json`。history 采集成本单独留存。",
              "", "## 6. 轨迹案例", ""]
    for left, right in (("ours", "vanilla"), ("llm", "vanilla"), ("ours", "llm")):
        candidates = [(tid, by_id[tid, left], by_id[tid, right]) for tid, arm in by_id
                      if arm == left and (tid, right) in by_id]
        for wanted in ("win", "tie", "loss"):
            chosen = next(((tid, a, b) for tid, a, b in candidates if compare(a, b) == wanted), None)
            if chosen:
                tid, a, b = chosen
                lines.append(f"- {left} vs {right} 的 {wanted} 案例：{tid}。通过={a['passed']}/{b['passed']}，"
                             f"tokens={number(a['usage']['total_tokens'])}/{number(b['usage']['total_tokens'])}，"
                             f"tool calls={a['tool_calls']}/{b['tool_calls']}。原始证据："
                             f"[左轨迹](../test/{tid}--{left}/trajectory.json)、"
                             f"[右轨迹](../test/{tid}--{right}/trajectory.json)。")
    lines += ["", "## 7. 有效性边界", "",
              f"{len(overlaps)} 道 test 与 history 环境文件完全相同：" + ", ".join(sorted(overlaps)) + "。"
              "单独给出排除这些任务后的统计，不能把全量结果解释为新数据泛化。",
              "history 中 weighted-gdp-calculation-2 缺少上游 verifier，标为未评分并保留轨迹；所有 held-out verifier 齐全。",
              "只有四个任务族、每组每题一次；公开数据可能已进入模型训练集。缓存、API 延迟和并发影响耗时，耗时仅作次要指标。",
              "本实验不等同于官方 SkillLearnBench 协议；镜像去掉预装技能，工具通过 Pi Docker adapter，"
              "软件依赖来源与最终镜像 ID 已记录。",
              "所有原始事件、失败、工具输出、产物和 verifier 记录留在对应运行目录。", ""]
    (folder / "BENCHMARK_REPORT.md").write_text("\n".join(lines))
    return summary


def run(output: Path, docker: str, credentials: Path) -> None:
    study = load_frozen(output)
    verify_source(study)
    check_adaptation(output)
    jobs = [(task, arm) for task in study["tasks"] if task["split"] == "test" for arm in ARMS]
    random.Random(study["seed"]).shuffle(jobs)
    planned = [{"task_id": task["task_id"], "arm": arm} for task, arm in jobs]
    order_file = output / "planned-test-order.json"
    if order_file.exists() and read(order_file) != planned:
        raise ValueError("Execution order changed")
    save(order_file, planned)
    report(output)
    with concurrent.futures.ThreadPoolExecutor(max_workers=study["workers"]) as pool:
        futures = []
        for task, arm in jobs:
            destination = output / "test" / f"{task['task_id']}--{arm}"
            if (destination / "result.json").exists():
                continue
            assets = output / "adaptation" / arm / "assets" if arm != "vanilla" else None
            futures.append(pool.submit(one_run, study, task, destination, docker, credentials, arm=arm, assets=assets))
        for future in concurrent.futures.as_completed(futures):
            future.result()
            check_adaptation(output)
            report(output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("run", "report"))
    parser.add_argument("--study", type=Path, required=True)
    parser.add_argument("--docker", default=shutil.which("docker") or "docker")
    parser.add_argument("--pi-config", type=Path, default=Path.home() / ".pi/agent")
    args = parser.parse_args()
    if args.stage == "report":
        report(args.study.resolve())
    else:
        run(args.study.resolve(), args.docker, args.pi_config.resolve())


if __name__ == "__main__":
    main()
