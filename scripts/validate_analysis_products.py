#!/usr/bin/env python3
"""Opt-in native import -> canonical data -> UI products -> API/export acceptance."""

from __future__ import annotations

import argparse
import json
import sqlite3
import subprocess
import time
import uuid
from pathlib import Path

from fastapi.testclient import TestClient
from tandem_data.discovery import inputs
from tandem_data.service import ImportRequest, ImportService
from tandem_data.store import Store
from tandem_data.validation.fixtures import create_sources

from tandem_backend.analytics.inputs import Scope
from tandem_backend.analytics.products import analyze_product_store
from tandem_backend.analytics.products.render import atomic_write, export_report, terminal_report
from tandem_backend.analytics.products.validation import validate_products
from tandem_backend.api import create_app
from tandem_backend.cli import demo_home
from tandem_backend.data_access.store import CanonicalStore


def private_destination(output: Path) -> Path:
    """Reject unignored output paths inside any Git checkout before importing private data."""
    output = output.expanduser().resolve()
    ancestor = output
    while not ancestor.exists():
        ancestor = ancestor.parent
    probe = subprocess.run(
        ["git", "-C", str(ancestor), "rev-parse", "--show-toplevel"], capture_output=True, text=True
    )
    if probe.returncode == 0:
        root = Path(probe.stdout.strip())
        ignored = subprocess.run(
            ["git", "-C", str(root), "check-ignore", "-q", str(output / "analysis.json")]
        )
        if ignored.returncode:
            raise ValueError("真实日志与报告必须写入 Git 忽略目录，例如 .local/analysis-validation")
    output.mkdir(parents=True, exist_ok=True, mode=0o700)
    return output


def synthetic_sources(output: Path) -> dict[str, Path]:
    """Add two known emotion messages to the existing seven-agent fictional corpus."""
    roots = create_sources(output / "sources")
    roots["codex"] = demo_home(output / "sources/codex")
    path = roots["codex"] / "sessions/expressions.jsonl"
    rows = [
        {
            "type": "session_meta",
            "timestamp": "2026-10-01T00:00:00Z",
            "payload": {
                "id": "ui-expressions",
                "cwd": "/fictional/ui-products",
                "source": "cli",
                "thread_source": "user",
            },
        }
    ]
    for index, text in enumerate(
        ("请检查代码。", "我很满意。", "我很失望。", "请翻译：我很满意。")
    ):
        stamp = f"2026-10-0{index + 1}T00:00:01Z"
        rows.extend(
            [
                {
                    "type": "event_msg",
                    "timestamp": stamp,
                    "payload": {"type": "task_started", "turn_id": f"t{index}"},
                },
                {
                    "type": "event_msg",
                    "timestamp": stamp,
                    "payload": {"type": "user_message", "message": text},
                },
                {
                    "type": "response_item",
                    "timestamp": stamp,
                    "payload": {
                        "type": "message",
                        "role": "user",
                        "content": [{"type": "input_text", "text": text}],
                    },
                },
            ]
        )
        if index == 0:
            for step, name in enumerate(
                ("read_file", "exec_command", "web_search", "exec_command", "read_file")
            ):
                stamp = f"2026-10-01T00:00:{step + 2:02d}Z"
                rows.extend(
                    [
                        {
                            "type": "response_item",
                            "timestamp": stamp,
                            "payload": {
                                "type": "function_call",
                                "name": name,
                                "call_id": f"flow-{step}",
                                "arguments": json.dumps(
                                    {"cmd": "printf synthetic", "path": "/fictional/app.py"}
                                ),
                            },
                        },
                        {
                            "type": "response_item",
                            "timestamp": stamp,
                            "payload": {
                                "type": "function_call_output",
                                "call_id": f"flow-{step}",
                                "output": '{"exit_code":0}',
                            },
                        },
                    ]
                )
    atomic_write(path, "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows))
    return roots


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--synthetic", action="store_true", help="使用七种 Agent 的虚构原生记录，不读取个人目录"
    )
    parser.add_argument(
        "--source",
        action="append",
        default=[],
        metavar="AGENT=ROOT",
        help="显式允许导入的来源，可重复",
    )
    parser.add_argument(
        "--limit-files", type=int, default=3, help="每来源按修改时间选最近 N 个文件；0 表示全部"
    )
    parser.add_argument(
        "--file",
        action="append",
        type=Path,
        help="单一来源中明确选取的文件，可重复，覆盖 limit-files",
    )
    parser.add_argument("--output", type=Path, default=Path(".local/analysis-validation"))
    parser.add_argument("--display-timezone", default="Asia/Shanghai")
    parser.add_argument("--from-ts", type=int)
    parser.add_argument("--until-ts", type=int)
    parser.add_argument(
        "--with-text", action="store_true", help="额外运行本地文本聚类，较大样本可能较慢"
    )
    args = parser.parse_args(argv)
    if args.synthetic == bool(args.source) or args.limit_files < 0:
        parser.error("必须选择 --synthetic 或一个以上 --source，limit-files 不得为负")
    if args.file and (args.synthetic or len(args.source) != 1):
        parser.error("--file 需要且仅允许一个 --source")
    started = time.perf_counter()
    output = None
    try:
        scope = Scope(
            display_timezone=args.display_timezone, from_ts=args.from_ts, until_ts=args.until_ts
        )
        output = private_destination(args.output)
        # A fresh run cannot inherit previously captured files outside today's selection.
        home = output / "runs" / uuid.uuid4().hex / "data"
        mode_path = output / "run-mode.json"
        mode = "synthetic" if args.synthetic else "local"
        if mode_path.exists() and json.loads(mode_path.read_text())["mode"] != mode:
            raise ValueError("构造案例与真实记录必须使用不同的 output 目录")
        sources = list(synthetic_sources(home.parent).items()) if args.synthetic else []
        for value in args.source:
            agent, separator, root = value.partition("=")
            if not separator or not root:
                raise ValueError("source 格式是 AGENT=ROOT")
            sources.append((agent, Path(root).expanduser().resolve(strict=True)))
        for _, root in sources:
            if (
                home.is_relative_to(root)
                or root.is_relative_to(home)
                or output.is_relative_to(root)
            ):
                raise ValueError("来源目录必须与数据和报告目录分开")
        atomic_write(mode_path, json.dumps({"mode": mode}))
        atomic_write(
            output / "validation.json",
            json.dumps({"status": "running", "mode": mode, "data_home": str(home)}),
        )
        imports, selected = [], []
        with Store(home) as store:
            for agent, root in sources:
                available = sorted(
                    inputs(agent, root),
                    key=lambda item: (-item.path.stat().st_mtime_ns, str(item.path)),
                )
                files = (
                    available
                    if args.synthetic or args.limit_files == 0
                    else available[: args.limit_files]
                )
                if args.file:
                    selected_paths = {
                        (path if path.is_absolute() else root / path).resolve()
                        for path in args.file
                    }
                    files = [item for item in available if item.path.resolve() in selected_paths]
                    if len(files) != len(selected_paths):
                        raise ValueError("指定文件不属于该来源允许读取的会话记录")
                if not files:
                    raise ValueError(f"{agent} 没有可导入的会话文件")
                selected.append(
                    {
                        "agent": agent,
                        "root": str(root),
                        "files": [str(item.path.relative_to(root)) for item in files],
                        "available_files": len(available),
                        "selected_files": len(files),
                    }
                )
                result = ImportService(store).import_source(
                    ImportRequest(agent, root, files=tuple(item.path for item in files))
                )
                imports.append(result)
                print(
                    f"{agent}: 导入 {result['files']} 个文件，读取失败 {result['capture_errors']}，未解析 {result['current_unparsed']}",
                    flush=True,
                )
            verification = store.verify()
        product = analyze_product_store(CanonicalStore(home), scope, with_text=args.with_text)
        checks = validate_products(product)
        if args.synthetic:
            oracles = {
                "synthetic: tool transitions are populated": product["tools"]["transitions"][
                    "kind"
                ]["pair_count"]
                >= 2,
                "synthetic: positive expression": product["feedback"]["summary"]["counts"].get(
                    "positive"
                )
                == 1,
                "synthetic: negative expression": product["feedback"]["summary"]["counts"].get(
                    "negative"
                )
                == 1,
            }
            for name, passed in oracles.items():
                checks["checks"].append({"name": name, "passed": passed})
                if not passed:
                    checks["errors"].append(name)
            checks["status"] = "failed" if checks["errors"] else "passed"
        params = {
            "display_timezone": args.display_timezone,
            "with_text": str(args.with_text).lower(),
        }
        params.update(
            {
                key: value
                for key, value in (("from_ts", args.from_ts), ("until_ts", args.until_ts))
                if value is not None
            }
        )
        with TestClient(create_app(home=home)) as client:
            response = client.get("/v1/analytics/products", params=params)
            parity = response.status_code == 200 and response.json() == product
        exports = export_report(product, output / "report")
        json_parity = json.loads((output / "report/analysis.json").read_text()) == product
        status = (
            "passed"
            if checks["status"] == "passed"
            and parity
            and json_parity
            and not verification["unparsed"]
            and not any(r["capture_errors"] for r in imports)
            else "failed"
        )
        result = {
            "status": status,
            "mode": mode,
            "source_selection": selected,
            "imports": imports,
            "data_home": str(home),
            "data_verification": verification,
            "product_validation": checks,
            "api_equal": parity,
            "export_equal": json_parity,
            "exports": exports,
            "coverage": product["coverage"],
            "elapsed_seconds": round(time.perf_counter() - started, 3),
            "limitations": product["limitations"],
        }
        atomic_write(
            output / "validation.json",
            json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False),
        )
        print(terminal_report(product))
        print(f"验收 {status}；报告 {exports['report.html']}；诊断 {output / 'validation.json'}")
        return 0 if status == "passed" else 1
    except (ValueError, OSError, RuntimeError, sqlite3.Error) as error:
        if output is not None:
            atomic_write(
                output / "validation.json",
                json.dumps({"status": "failed", "error": str(error)}, ensure_ascii=False),
            )
        parser.exit(2, f"验收未完成：{error}\n")


if __name__ == "__main__":
    raise SystemExit(main())
