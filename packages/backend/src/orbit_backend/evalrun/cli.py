"""``orbit eval {list,run,history}`` (EV-12) and ``orbit label`` (EV-02.1).

Exit codes: 0 pass, 1 fail, 2 usage error. ``--home`` is the Orbit home: it holds the
``app.db`` history and is handed to suites that need data; ``--no-store`` writes nothing.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from pathlib import Path

from orbit_data.paths import default_home

from . import registry, runner
from . import store as eval_store


def _parser() -> argparse.ArgumentParser:
    home = argparse.ArgumentParser(add_help=False)
    home.add_argument("--home", type=Path, default=None, help="Orbit 数据目录（默认 ORBIT_HOME）")
    parser = argparse.ArgumentParser(prog="orbit", description="Orbit 评测运行与标注")
    sub = parser.add_subparsers(dest="command", required=True)
    ev = sub.add_parser("eval", help="运行评测 suite").add_subparsers(dest="action", required=True)
    ev.add_parser("list", parents=[home], help="列出 suite")
    run = ev.add_parser("run", parents=[home], help="运行 suite 并按 --fail-under 给出退出码")
    run.add_argument("--suite", action="append", dest="suites", metavar="ID",
                     help="suite id，可重复；省略或 all 表示全部")
    run.add_argument("--fail-under", type=float, default=None)
    run.add_argument("--json", type=Path, default=None, help="写出完整 RunReport")
    run.add_argument("--real", action="store_true", help="允许 suite 读取真实数据目录")
    run.add_argument("--no-store", action="store_true", help="不写入 app.db 历史")
    history = ev.add_parser("history", parents=[home], help="最近的评测运行")
    history.add_argument("--limit", type=int, default=20)
    label = sub.add_parser("label", parents=[home], help="逐条标注最新推荐的准确性（EV-02.1）")
    label.add_argument("--kind", choices=("candidate", "problem"), default="candidate")
    label.add_argument("--limit", type=int, default=20)
    label.add_argument("--labeler", default="user")
    return parser


def main(argv: list[str] | None = None, *, input_fn: Callable[[str], str] = input,
         out=None) -> int:
    out = out or sys.stdout
    try:
        args = _parser().parse_args(argv)
    except SystemExit as exc:
        return int(exc.code or 0) and 2
    home = (args.home or default_home()).expanduser()
    try:
        if args.command == "label":
            return _label(args, home, input_fn, out)
        return {"list": _list, "run": _run, "history": _history}[args.action](args, home, out)
    except ValueError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2


def _list(args, home: Path, out) -> int:
    for suite in registry.list_suites():
        print(f"{suite['id']:<20} {suite['title']}  [{', '.join(suite['ev'])}]", file=out)
    return 0


def _run(args, home: Path, out) -> int:
    suites = args.suites or ["all"]
    selected: list[str] | str = "all" if "all" in suites else suites
    if args.fail_under is not None and not 0 <= args.fail_under <= 1:
        raise ValueError("--fail-under 必须在 0 到 1 之间")
    runner.resolve(selected)  # Unknown ids are a usage error before anything is written.
    db = None
    if not args.no_store:
        from ..appdb import AppDB

        db = AppDB(home / "app.db")

    def progress(suite_id: str, row: dict | None) -> None:
        if row is not None:
            print(_line(row), file=out, flush=True)

    try:
        report = runner.run(selected, fail_under=args.fail_under, home=home, real=args.real,
                            store=db, progress=progress)
    finally:
        if db is not None:
            db.close()
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    score = "n/a" if report["score"] is None else f"{report['score']:.3f}"
    bar = "" if args.fail_under is None else f" fail_under={args.fail_under}"
    print(f"{'PASS' if report['passed'] else 'FAIL'} score={score}{bar} run_id={report['run_id']}",
          file=out)
    return 0 if report["passed"] else 1


def _line(row: dict) -> str:
    if row["skipped"]:
        return f"  {row['suite']:<20} skip   {row['skipped']}"
    failed = [c["id"] for c in row["checks"] if not c["passed"]]
    score = "  n/a" if row["score"] is None else f"{row['score']:.3f}"
    return f"  {row['suite']:<20} {score}  " + (f"failed: {', '.join(failed)}" if failed else "ok")


def _history(args, home: Path, out) -> int:
    if not (home / "app.db").is_file():
        print("还没有评测记录。", file=out)
        return 0
    from ..appdb import AppDB

    db = AppDB(home / "app.db")
    try:
        runs = eval_store.list_runs(db, args.limit)
    finally:
        db.close()
    for r in runs:
        verdict = {True: "PASS", False: "FAIL", None: "-"}[r["passed"]]
        score = "n/a" if r["score"] is None else f"{r['score']:.3f}"
        print(f"{r['run_id']}  {r['started_at']}  {r['status']:<9} {verdict:<4} {score}  "
              f"{','.join(r['suites'])}", file=out)
    if not runs:
        print("还没有评测记录。", file=out)
    return 0



def _label(args, home: Path, input_fn, out) -> int:
    if not (home / "app.db").is_file():
        print("还没有 app.db；先在 App 里生成一次推荐。", file=out)
        return 0
    from ..appdb import AppDB
    from .labels import label_loop

    db = AppDB(home / "app.db")
    try:
        label_loop(db, home / "orbit.db", kind=args.kind, limit=args.limit,
                   labeler=args.labeler, input_fn=input_fn, out=out)
    finally:
        db.close()
    return 0
