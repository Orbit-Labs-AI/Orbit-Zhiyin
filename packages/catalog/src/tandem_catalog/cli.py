"""Explicit catalog construction, refresh, local embedding and retrieval commands."""

import argparse
import json
from pathlib import Path

from .contracts import MatchRequest, SourceSpec
from .network import HttpClient
from .service import CatalogService, default_home
from .sources.structured import FILE_KINDS
from .sync import CatalogSync
from .vectors import index_embeddings


def main(argv=None):
    parser = argparse.ArgumentParser(description="Tandem 推荐资源数据模块")
    parser.add_argument("--home", type=Path, default=default_home())
    parser.add_argument("--model-dir", type=Path, help="已下载的 E5 模型目录；不自动联网下载")
    sub = parser.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init")
    init.add_argument("--sources", type=Path, help="可选的 SourceSpec JSON 数组")
    sub.add_parser("status")
    sub.add_parser("verify")
    sub.add_parser("rebuild")
    sync = sub.add_parser("sync")
    sync.add_argument("--source", action="append", default=[])
    sync.add_argument("--force", action="store_true", help="忽略刷新间隔；仍复用固定版本和未完成 checkpoint")
    sync.add_argument("--max-pages", type=int, default=10000)
    sync.add_argument("--concurrency", type=int, default=3, help="并发抓取的来源数")
    sync.add_argument("--offline", action="store_true", help="只读本地 HTTP 缓存，不发网络请求")
    imported = sub.add_parser("import-file", help="从本地 JSON（夹具或公开榜单缓存）导入一个结构化来源，不经网络")
    imported.add_argument("--source", required=True)
    imported.add_argument("--file", type=Path, required=True)
    snap = sub.add_parser("snapshot", help="从已联网同步的 home 构建离线种子快照（发布前运行，产物入仓库）")
    snap.add_argument("--out", type=Path, required=True)
    snap.add_argument("--from-home", type=Path, required=True, help="已同步的 Tandem home（只读）")
    snap.add_argument("--max-bytes", type=int, default=3_000_000)
    snap.add_argument("--no-staged", action="store_true", help="不使用未完成同步的暂存条目（如 MCP 中断的全量扫描）")
    seed = sub.add_parser("seed-import", help="把内置（或指定）种子快照和官方条目导入当前 home，不联网")
    seed.add_argument("--file", type=Path, help="种子快照 .json.gz；缺省用包内 data/library-seed.v1.json.gz")
    official = sub.add_parser("export-official", help="把推荐知识库 remedies.v1.json 导出为官方条目 official.v1.json")
    official.add_argument("--remedies", type=Path, required=True)
    official.add_argument("--out", type=Path, required=True)
    embed = sub.add_parser("embed")
    embed.add_argument("--max-chunks", type=int)
    query = sub.add_parser("search")
    query.add_argument("text", nargs="?", default="")
    query.add_argument("--request", type=Path, help="完整 MatchRequest JSON，含分析特征和证据 ID")
    query.add_argument("--type", action="append", default=[])
    query.add_argument("--limit", type=int, default=10)
    detail = sub.add_parser("detail")
    detail.add_argument("item_id")
    serve = sub.add_parser("serve")
    serve.add_argument("--port", type=int, default=8766)
    args = parser.parse_args(argv)
    if args.command in ("snapshot", "export-official"):
        result = _offline_tool(args)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    http = HttpClient(args.home / "catalog-http-cache", offline=True) if getattr(args, "offline", False) else None
    service = CatalogService(args.home / "catalog.db", model_dir=args.model_dir, http=http)
    try:
        if args.command == "init":
            if args.sources:
                service.store.register([SourceSpec.model_validate(s) for s in json.loads(args.sources.read_text())])
            result = {"database": str(service.store.path), "sources": service.store.sources()}
        elif args.command == "status":
            result = {"catalog": service.store.stats(), "sources": service.store.sources()}
        elif args.command == "sync":
            result = CatalogSync(service.store, service.http).sync(args.source, force=args.force, max_pages=args.max_pages,
                                                                   concurrency=args.concurrency)
            service.retire_seeds(result)
        elif args.command == "seed-import":
            result = service.bootstrap(args.file.read_bytes() if args.file else None)
        elif args.command == "import-file":
            row = next((s for s in service.store.sources() if s["source_id"] == args.source), None)
            if row is None or row["spec"].get("kind") not in FILE_KINDS:
                parser.error("import-file requires a models_dev/litellm/swe_bench/gemini source")
            spec = SourceSpec.model_validate(row["spec"])
            service.store.register([spec.model_copy(update={"config": {**spec.config, "file": str(args.file.resolve())}})])
            result = CatalogSync(service.store, service.http).sync([args.source], force=True)
        elif args.command == "embed":
            if service.encoder() is None:
                parser.error("embed requires --model-dir with a local E5 snapshot")
            result = index_embeddings(service.store, service.encoder(), max_chunks=args.max_chunks)
        elif args.command == "search":
            request = MatchRequest.model_validate_json(args.request.read_text()) if args.request else MatchRequest(text=args.text, types=args.type, limit=args.limit)
            result = service.match(request)
        elif args.command == "detail":
            result = service.store.detail(args.item_id)
        elif args.command == "verify":
            result = service.store.verify()
        elif args.command == "rebuild":
            result = service.store.rebuild()
        else:
            import uvicorn

            from .api import create_catalog_app
            uvicorn.run(create_catalog_app(service), host="127.0.0.1", port=args.port)
            return
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if args.command in ("sync", "import-file") and any(r["status"] == "failed" for r in result):
            raise SystemExit(1)
        if args.command == "verify" and not result["ok"]:
            raise SystemExit(1)
    finally:
        service.close()


def _offline_tool(args) -> dict:
    """Commands that only read a given file/home and write one output file."""
    if args.command == "export-official":
        from .sources.structured import official_entries
        entries = official_entries(json.loads(args.remedies.read_text()))
        args.out.write_text(json.dumps(entries, ensure_ascii=False, indent=1) + "\n")
        return {"out": str(args.out), "entries": len(entries)}
    from .snapshot import build_snapshot, load_seed
    from .store import CatalogStore
    source = args.from_home / "catalog.db"
    if not source.is_file():
        raise SystemExit(f"no catalog.db under {args.from_home}")
    data = build_snapshot(CatalogStore(source), max_bytes=args.max_bytes, include_staged=not args.no_staged)
    args.out.write_bytes(data)
    doc = load_seed(data)
    return {"out": str(args.out), "bytes": len(data), "stats": doc["stats"],
            "sources": {sid: len(src["items"]) for sid, src in doc["sources"].items()}}


if __name__ == "__main__":
    main()
