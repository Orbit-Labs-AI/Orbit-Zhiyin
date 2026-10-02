"""Explicit catalog construction, refresh, local embedding and retrieval commands."""

import argparse
import json
from pathlib import Path

from .contracts import MatchRequest, SourceSpec
from .service import CatalogService, default_home
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
    service = CatalogService(args.home / "catalog.db", model_dir=args.model_dir)
    try:
        if args.command == "init":
            if args.sources:
                service.store.register([SourceSpec.model_validate(s) for s in json.loads(args.sources.read_text())])
            result = {"database": str(service.store.path), "sources": service.store.sources()}
        elif args.command == "status":
            result = {"catalog": service.store.stats(), "sources": service.store.sources()}
        elif args.command == "sync":
            result = CatalogSync(service.store, service.http).sync(args.source, force=args.force, max_pages=args.max_pages)
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
        if args.command == "sync" and any(r["status"] == "failed" for r in result):
            raise SystemExit(1)
        if args.command == "verify" and not result["ok"]:
            raise SystemExit(1)
    finally:
        service.close()


if __name__ == "__main__":
    main()
