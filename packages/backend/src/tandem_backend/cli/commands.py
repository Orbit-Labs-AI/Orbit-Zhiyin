"""Explicit local commands: importing data never sends it to a model or network."""

import argparse
import json
import re
from pathlib import Path

from tandem_data.paths import default_home

from ..application.reports import build_report
from ..evaluation.readability import benchmark
from ..reporting.analysis_reports import (
    bottlenecks_markdown,
    cli_summary,
    process_markdown,
    profile_markdown,
)
from ..reporting.narrative import markdown
from ..store import Store, import_codex


def demo_home(path: Path) -> Path:
    """Deterministic fictional logs; these are never mixed with the real history database."""
    folder = path / "sessions"
    folder.mkdir(parents=True, exist_ok=True)
    for index, request in enumerate(("请给初学者写一份程序教程，把思路讲清楚。", "请用两段话介绍项目报告的结构。", "先做最小可运行版本，再测试。")):
        sid = f"demo-{index}"
        rows = [
            {"type": "session_meta", "timestamp": "2026-01-01T00:00:00Z", "payload": {"id": sid, "cwd": "/fictional/sample-project", "source": "cli", "thread_source": "user", "cli_version": "synthetic"}},
            {"type": "event_msg", "timestamp": "2026-01-01T00:00:01Z", "payload": {"type": "task_started", "turn_id": f"turn-{index}"}},
            {"type": "turn_context", "timestamp": "2026-01-01T00:00:01Z", "payload": {"turn_id": f"turn-{index}", "model": "demo-model"}},
            {"type": "response_item", "timestamp": "2026-01-01T00:00:02Z", "payload": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": request}]}},
            {"type": "response_item", "timestamp": "2026-01-01T00:00:04Z", "payload": {"type": "message", "role": "assistant", "channel": "final", "content": [{"type": "output_text", "text": "示例结果，仅用于检查数据流。"}]}},
        ]
        if index == 0:
            rows[-1]["payload"]["content"][0]["text"] = "程序以一组变换来构建输出，并在条件满足时终止。"
            rows.extend([
                {"type": "event_msg", "timestamp": "2026-01-01T00:00:05Z", "payload": {"type": "task_started", "turn_id": "revision"}},
                {"type": "turn_context", "timestamp": "2026-01-01T00:00:05Z", "payload": {"turn_id": "revision", "model": "demo-model"}},
                {"type": "response_item", "timestamp": "2026-01-01T00:00:06Z", "payload": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "没看懂，换个直观的例子。"}]}},
                {"type": "response_item", "timestamp": "2026-01-01T00:00:08Z", "payload": {"type": "message", "role": "assistant", "channel": "final", "content": [{"type": "output_text", "text": "程序先读输入的数量。例如收到3个苹果，再逐个装盒；每装一个，剩余数量减一，到零就停止。"}]}},
                {"type": "event_msg", "timestamp": "2026-01-01T00:00:09Z", "payload": {"type": "task_started", "turn_id": "comparison"}},
                {"type": "turn_context", "timestamp": "2026-01-01T00:00:09Z", "payload": {"turn_id": "comparison", "model": "demo-model"}},
                {"type": "response_item", "timestamp": "2026-01-01T00:00:10Z", "payload": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "这一版比上一版更清楚。"}]}},
            ])
        if index == 2:
            tools = []
            for attempt in range(3):
                tools.extend([
                    {"type": "response_item", "timestamp": "2026-01-01T00:00:03Z", "payload": {"type": "function_call", "name": "exec_command", "call_id": f"c-{attempt}", "arguments": '{"cmd":"run-demo-check"}'}},
                    {"type": "response_item", "timestamp": "2026-01-01T00:00:04Z", "payload": {"type": "function_call_output", "call_id": f"c-{attempt}", "output": '{"exit_code":1}'}},
                ])
            rows[-1:-1] = tools
        for ordinal, row in enumerate(rows):
            if row["type"] == "response_item" and row["payload"].get("role") == "user":
                row["metadata"] = {"user_input_order": ordinal}
        (folder / f"{sid}.jsonl").write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Tandem 本地轨迹后端")
    parser.add_argument("--home", type=Path, default=default_home(), help="L0–L3 数据目录，默认 macOS Application Support/Tandem")
    parser.add_argument("--db", help="显式使用旧版 MVP 数据库（兼容模式）")
    parser.add_argument("--catalog-cache", type=Path, default=Path(".local/catalog.json"))
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("init", "rebuild", "verify", "stats", "discover"):
        sub.add_parser(name)
    ingest_parser = sub.add_parser("ingest", help="经统一 L0–L3 链路导入显式启用的来源")
    ingest_parser.add_argument("--agent", required=True)
    ingest_parser.add_argument("--root", type=Path, required=True)
    ingest_parser.add_argument("--limit", type=int, help="仅用于样本验证")
    staging = sub.add_parser("import-connector", help="从 TypeScript connector 的不可变归档桥接")
    staging.add_argument("--connector-home", type=Path, required=True)
    imp = sub.add_parser("import", help="只读导入已授权的 Codex 数据目录")
    imp.add_argument("--codex-home", type=Path, required=True)
    imp.add_argument("--before", help="固定样本快照，ISO UTC 时间")
    imp.add_argument("--exclude-session", action="append", default=[])
    imp.add_argument("--reset-sample-policy", action="store_true", help="显式重新设置快照和排除范围；默认保留已有隔离")
    report = sub.add_parser("report")
    report.add_argument("--output", type=Path, default=Path(".local/report"))
    report.add_argument("--audience", choices=("user", "developer"), default="user")
    report.add_argument("--project-id")
    report.add_argument("--model")
    report.add_argument("--scene", help="只分析指定任务场景")
    analytics = sub.add_parser("analytics", help="计算有覆盖说明的特征、聚类和二维坐标")
    analytics.add_argument("--output", type=Path, help="完整 JSON，仅建议保存在 .local 下")
    analytics.add_argument("--display-timezone", default="UTC")
    analytics.add_argument("--from-ts", type=int)
    analytics.add_argument("--until-ts", type=int)
    for flag in ("project-id", "legacy-project-id", "model-id", "effort-raw", "root-session-uid", "exclude-session"):
        analytics.add_argument("--" + flag, action="append")
    analytics.add_argument("--include-children", action=argparse.BooleanOptionalAction, default=True)
    analytics.add_argument("--scene")
    analytics.add_argument("--no-text", action="store_true", help="只计算确定性测量，跳过文本表示")
    demo = sub.add_parser("demo")
    demo.add_argument("--output", type=Path, default=Path(".local/demo"))
    for command in (report, demo):
        command.add_argument("--view", choices=("summary", "profile", "bottlenecks", "process", "recommendations"),
                             default="summary", help="直接在终端查看画像、卡点、过程或推荐；默认展示整条链路摘要")
    eval_parser = sub.add_parser("evaluate")
    eval_parser.add_argument("--output", type=Path, default=Path(".local/evaluation.json"))
    eval_parser.add_argument("--suite", choices=("all", "readability", "pipeline", "probe"), default="all")
    reader_pack = sub.add_parser("reader-pack", help="生成事实固定、展示顺序互换的读者评审材料")
    reader_pack.add_argument("--cases", type=Path, help="独立的 evaluation_only 案例 JSON；默认使用虚构案例")
    reader_pack.add_argument("--output", type=Path, default=Path(".local/reader-review"))
    reader_pack.add_argument("--seed", type=int, default=0)
    reader_results = sub.add_parser("reader-results", help="汇总已填写的评审表，不改写历史画像")
    reader_results.add_argument("--pack", type=Path, required=True)
    reader_results.add_argument("--ratings", type=Path, required=True)
    reader_results.add_argument("--output", type=Path)
    serve = sub.add_parser("serve")
    serve.add_argument("--port", type=int, default=8765)
    refresh = sub.add_parser("catalog-refresh", help="显式核对公开 GitHub 资源来源，不执行安装")
    refresh.add_argument("--output", type=Path, default=Path(".local/catalog.json"))
    refresh.add_argument("--latest", action="store_true")
    refresh.add_argument("--resource-id", action="append", default=[])
    evidence = sub.add_parser("evidence", help="在终端回看一条判断引用的统一事件")
    evidence.add_argument("event_id")
    evidence.add_argument("--json", action="store_true", help="输出完整的已保存事件元数据")
    args = parser.parse_args(argv)
    if args.command in ("ingest", "import-connector", "init", "rebuild", "verify", "stats", "discover"):
        from ..data_access.ingest import ingest, ingest_staging, maintain
        if args.db:
            parser.error("数据层命令使用 --home；--db 只用于旧版分析兼容")
        try:
            if args.command == "discover":
                from tandem_data.discovery import candidates
                result = candidates()
            elif args.command == "ingest":
                result = ingest(args.home, args.agent, args.root, limit=args.limit)
            elif args.command == "import-connector":
                result = ingest_staging(args.home, args.connector_home)
            else:
                result = maintain(args.home, args.command)
        except (ValueError, OSError, RuntimeError) as exc:
            parser.error(str(exc))
        print(json.dumps(result, ensure_ascii=False))
        imported = result.get("import", {}) if isinstance(result, dict) else {}
        if imported.get("capture_errors") or imported.get("current_unparsed"):
            raise SystemExit(2)
        return
    if args.command == "import" and args.db is None:
        from ..data_access.ingest import ingest
        if args.before or args.exclude_session or args.reset_sample_policy:
            parser.error("统一归档保留完整历史；analytics 用 --until-ts/--exclude-session 选择样本。旧版持久采样请显式传 --db。")
        try:
            result = ingest(args.home, "codex", args.codex_home)
        except (ValueError, OSError, RuntimeError) as exc:
            parser.error(str(exc))
        print(json.dumps(result, ensure_ascii=False))
        if result["import"].get("capture_errors") or result["import"].get("current_unparsed"):
            raise SystemExit(2)
        return
    if args.command in ("reader-pack", "reader-results"):
        from ..evaluation.reader import make_pack, reader_results

        result = make_pack(args.output, args.cases, args.seed) if args.command == "reader-pack" else reader_results(args.pack, args.ratings)
        if args.command == "reader-results" and args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    if args.command == "serve":
        import uvicorn

        from ..api.routes import create_app
        uvicorn.run(create_app(args.db, args.catalog_cache, home=args.home), host="127.0.0.1", port=args.port)
        return
    if args.command == "catalog-refresh":
        from ..recommendation.resource_fetch import refresh_catalog
        result = refresh_catalog(args.output, latest=args.latest, resource_ids=set(args.resource_id))
        print(json.dumps({"verified": result["success"], "failed": result["failed"], "output": str(args.output.resolve())}, ensure_ascii=False))
        return
    if args.command == "evaluate":
        from ..evaluation.pipeline import pipeline_benchmark
        result = {"human_acceptance": "pending", "history_updated": False}
        if args.suite in ("all", "readability"):
            result["readability"] = benchmark()
        if args.suite in ("all", "pipeline"):
            result["pipeline"] = pipeline_benchmark()
        if args.suite in ("all", "probe"):
            result["probe"] = pipeline_benchmark(dataset="probe")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2))
        print(json.dumps({"human_acceptance": "pending", "history_updated": False,
                          "suites": {k: {field: suite[field] for field in ("cases", "correct", "limitation")}
                                     for k, suite in result.items() if isinstance(suite, dict)}}, ensure_ascii=False))
        return
    if args.command == "demo":
        from ..data_access.ingest import ingest
        args.db = None
        args.home = args.output / "data"
        ingest(args.home, "codex", demo_home(args.output / "codex"))
    if args.db:
        store = Store(args.db)
    else:
        from ..data_access.store import CanonicalStore
        try:
            store = CanonicalStore(args.home)
        except ValueError as exc:
            parser.error(str(exc))
    if args.command == "analytics":
        from ..analytics.inputs import Scope
        from ..analytics.service import analyze_store
        try:
            scope = Scope(display_timezone=args.display_timezone, project_ids=args.project_id,
                          legacy_project_ids=args.legacy_project_id, model_ids=args.model_id,
                          effort_raw=args.effort_raw, from_ts=args.from_ts, until_ts=args.until_ts,
                          root_session_uids=args.root_session_uid, excluded_session_uids=args.exclude_session or [],
                          include_children=args.include_children, scene=args.scene)
            result = analyze_store(store, scope, not args.no_text)
        except ValueError as exc:
            parser.error(str(exc))
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
        counts = result["overview"]["counts"]
        print(f"主会话 {counts['main_sessions']}；确认真人消息 {counts['human_messages']}；来源未知 {counts['human_origin_unknown']}。")
        print(f"工具调用 {result['effective_samples']['tools']}；文本样本 {result['effective_samples']['text_sessions']}；累计 token 不能冒充模型调用。")
        print(json.dumps({"clustering": result['text'].get('clustering'),
                          "coverage": {k: v['status'] for k, v in result['coverage'].items()},
                          "output": str(args.output.resolve()) if args.output else None}, ensure_ascii=False))
        return
    if args.command == "evidence":
        if hasattr(store, "evidence"):
            item = store.evidence(args.event_id)
        else:
            with store.connect() as conn:
                row = conn.execute("SELECT data FROM events WHERE id=?", (args.event_id,)).fetchone()
            item = json.loads(row[0]) if row else None
        if not item:
            parser.error("证据不存在；请确认使用生成报告时的数据库。")
        if args.json:
            print(json.dumps(item, ensure_ascii=False, indent=2))
        else:
            position = (f"事件序号 {item['ordinal']} · 原始记录 {item['details']['record_uid']}"
                        if item["details"].get("record_uid") else f"原记录第 {item['ordinal']} 行")
            print(f"证据 {item['id']} · {item['kind']} · {position}")
            print(item['text'] or json.dumps(item['details'], ensure_ascii=False, indent=2))
        return
    if args.command == "import":
        result = import_codex(store, args.codex_home, args.before, set(args.exclude_session), args.reset_sample_policy)
        print(json.dumps({"import": result.to_dict(), "stored": store.counts()}, ensure_ascii=False))
        return
    if args.command == "demo":
        args.audience, args.project_id, args.model, args.scene = "user", None, None, None
    if hasattr(store, "report_snapshot"):
        store = store.report_snapshot(args.project_id, args.model)
    data, result = build_report(store, project_id=args.project_id, model=args.model,
                                scene=args.scene, audience=args.audience, catalog_cache=args.catalog_cache)
    args.output.mkdir(parents=True, exist_ok=True)
    # Local evidence snapshots let every report work without a running server or
    # a particular port. Only already-normalized, redacted events are copied.
    evidence_folder = args.output / 'evidence'
    evidence_folder.mkdir(exist_ok=True)
    wanted = {eid for p in data['profile']['observations'] for eid in p['evidence_ids']}
    wanted.update(eid for d in data['bottleneck_details'] for eid in d['evidence_ids'])
    wanted.update(e['event_id'] for e in data['normalization']['examples'])
    wanted.update(result['main_evidence_ids'])
    wanted.update(eid for rec in result['recommendations'] for eid in rec['evidence_ids'])
    wanted.update(eid for pair in data['profile']['preference_audit']['pairs'] for eid in pair['evidence_ids'])
    # Remove only snapshots owned by this exporter when a rerun narrows the
    # sample. Leave unrelated user files alone.
    for old in evidence_folder.iterdir():
        if old.is_file() and re.fullmatch(r'(?:[0-9a-f]{24}|event_[0-9a-f]{64})', old.name) and old.name not in wanted:
            old.unlink()
    for event in store.events():
        if event.id in wanted:
            (evidence_folder / event.id).write_text(json.dumps(event.to_dict(), ensure_ascii=False, indent=2))
    evidence_base = str(evidence_folder.resolve())
    (args.output / "analysis.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
    (args.output / "report.md").write_text(markdown(result, evidence_base))
    for name, value, render in (
        ('profile', data['profile'], profile_markdown),
        ('bottlenecks', data['bottleneck_details'], bottlenecks_markdown),
        ('process', data['normalization'], process_markdown),
    ):
        (args.output / f'{name}.json').write_text(json.dumps(value, ensure_ascii=False, indent=2))
        (args.output / f'{name}.md').write_text(render(data, evidence_base))
    views = {'profile': profile_markdown, 'bottlenecks': bottlenecks_markdown, 'process': process_markdown}
    if args.view in views:
        text = views[args.view](data, evidence_base)
        # Folding is useful in saved Markdown; terminals display the actual text.
        text = '\n'.join(line for line in text.splitlines()
                         if line not in ('<details>', '</details>', '<summary>查看原始要求</summary>'))
        text = re.sub(r'\[证据\]\(<[^>]+/([^/>]+)>\)', r'证据 ID：\1', text)
        print(text)
    elif args.view == 'recommendations':
        print(markdown(result, evidence_base))
    else:
        print(cli_summary(data, result['recommendations']))
    print(f"完整结果：{args.output.resolve()}（profile / bottlenecks / process / report 的 Markdown 与 JSON）")
