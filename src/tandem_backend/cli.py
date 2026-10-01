"""Explicit local commands: importing data never sends it to a model or network."""

import argparse
import json
from pathlib import Path

from .analysis import analyze
from .catalog import resources
from .evaluation import benchmark
from .narrative import explain, markdown
from .recommend import recommend
from .store import Store, import_codex


def demo_home(path: Path) -> Path:
    """Deterministic fictional logs; these are never mixed with the real history database."""
    folder = path / "sessions"
    folder.mkdir(parents=True, exist_ok=True)
    for index, request in enumerate(("请简洁直接、说人话地解释这段代码。", "没看懂，换个直观的例子。", "先做最小可运行版本，再测试。")):
        sid = f"demo-{index}"
        rows = [
            {"type": "session_meta", "timestamp": "2026-01-01T00:00:00Z", "payload": {"id": sid, "cwd": "/fictional/sample-project", "source": "cli", "cli_version": "synthetic"}},
            {"type": "event_msg", "timestamp": "2026-01-01T00:00:01Z", "payload": {"type": "task_started", "turn_id": f"turn-{index}"}},
            {"type": "turn_context", "timestamp": "2026-01-01T00:00:01Z", "payload": {"turn_id": f"turn-{index}", "model": "demo-model"}},
            {"type": "response_item", "timestamp": "2026-01-01T00:00:02Z", "payload": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": request}]}},
            {"type": "response_item", "timestamp": "2026-01-01T00:00:04Z", "payload": {"type": "message", "role": "assistant", "channel": "final", "content": [{"type": "output_text", "text": "示例结果，仅用于检查数据流。"}]}},
        ]
        if index == 0:
            rows[-1]["payload"]["content"][0]["text"] = "KL、JS、POMDP、embedding 与 latent z_u 经过 factorize 获得表示。"
        if index == 2:
            tools = []
            for attempt in range(3):
                tools.extend([
                    {"type": "response_item", "timestamp": "2026-01-01T00:00:03Z", "payload": {"type": "function_call", "name": "exec_command", "call_id": f"c-{attempt}", "arguments": '{"cmd":"run-demo-check"}'}},
                    {"type": "response_item", "timestamp": "2026-01-01T00:00:04Z", "payload": {"type": "function_call_output", "call_id": f"c-{attempt}", "output": '{"exit_code":1}'}},
                ])
            rows[-1:-1] = tools
        (folder / f"{sid}.jsonl").write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows))
    return path


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Tandem 本地轨迹后端")
    parser.add_argument("--db", default=".local/tandem.sqlite")
    parser.add_argument("--catalog-cache", type=Path, default=Path(".local/catalog.json"))
    sub = parser.add_subparsers(dest="command", required=True)
    imp = sub.add_parser("import", help="只读导入已授权的 Codex 数据目录")
    imp.add_argument("--codex-home", type=Path, required=True)
    imp.add_argument("--before", help="固定样本快照，ISO UTC 时间")
    imp.add_argument("--exclude-session", action="append", default=[])
    report = sub.add_parser("report")
    report.add_argument("--output", type=Path, default=Path(".local/report"))
    report.add_argument("--audience", choices=("user", "developer"), default="user")
    report.add_argument("--project-id")
    report.add_argument("--model")
    report.add_argument("--scene", help="只分析指定任务场景")
    demo = sub.add_parser("demo")
    demo.add_argument("--output", type=Path, default=Path(".local/demo"))
    eval_parser = sub.add_parser("evaluate")
    eval_parser.add_argument("--output", type=Path, default=Path(".local/evaluation.json"))
    eval_parser.add_argument("--suite", choices=("all", "readability", "pipeline", "probe"), default="all")
    serve = sub.add_parser("serve")
    serve.add_argument("--port", type=int, default=8765)
    refresh = sub.add_parser("catalog-refresh", help="显式核对公开 GitHub 资源来源，不执行安装")
    refresh.add_argument("--output", type=Path, default=Path(".local/catalog.json"))
    refresh.add_argument("--latest", action="store_true")
    refresh.add_argument("--resource-id", action="append", default=[])
    args = parser.parse_args(argv)
    if args.command == "serve":
        import uvicorn

        from .api import create_app
        uvicorn.run(create_app(args.db, args.catalog_cache), host="127.0.0.1", port=args.port)
        return
    if args.command == "catalog-refresh":
        from .resource_fetch import refresh_catalog
        result = refresh_catalog(args.output, latest=args.latest, resource_ids=set(args.resource_id))
        print(json.dumps({"verified": result["success"], "failed": result["failed"], "output": str(args.output.resolve())}, ensure_ascii=False))
        return
    if args.command == "evaluate":
        from .pipeline_eval import pipeline_benchmark
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
        args.db = str(args.output / "demo.sqlite")
    store = Store(args.db)
    if args.command == "import":
        result = import_codex(store, args.codex_home, args.before, set(args.exclude_session))
        print(json.dumps({"import": result.to_dict(), "stored": store.counts()}, ensure_ascii=False))
        return
    if args.command == "demo":
        import_codex(store, demo_home(args.output / "codex"))
        args.audience, args.project_id, args.model, args.scene = "user", None, None, None
    data = analyze(store, args.project_id, args.model, scene=args.scene)
    result = explain(data, recommend(data, catalog=resources(args.catalog_cache)), args.audience)
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "analysis.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
    (args.output / "report.md").write_text(markdown(result))
    print(result["summary"])
    print(f"结果：{(args.output / 'report.md').resolve()}")
