"""Opt-in native Codex -> canonical database -> analytics -> Skill recommendations."""

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from tandem_data.cli import statistics
from tandem_data.discovery import inputs
from tandem_data.service import ImportRequest, ImportService
from tandem_data.source_reader import SourceUnavailable
from tandem_data.store import Store

from tandem_backend.analytics.inputs import Scope
from tandem_backend.analytics.service import analyze_store
from tandem_backend.data_access.store import CanonicalStore
from tandem_backend.recommend.catalog import load_catalog
from tandem_backend.recommend.contracts import RecommendationContext
from tandem_backend.recommend.service import recommend

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CATALOG = Path(__file__).with_name("fixtures") / "reviewed-skills.json"


def save(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    path.chmod(0o600)


def run(source, output, *, latest=20, catalog=DEFAULT_CATALOG, context=None, scope=None, progress=None):
    """Never generate activity, lower thresholds, or modify source transcripts.

    Fresh output prevents old imported sessions from silently contaminating a
    newly selected sample. Outputs inside the repository must stay in .local.
    """
    source, output = Path(source).expanduser().resolve(), Path(output).expanduser().resolve()
    if not source.is_dir():
        raise ValueError("Codex source directory does not exist")
    if output.is_relative_to(source) or source.is_relative_to(output):
        raise ValueError("Output and Codex source directories must be separate")
    if output.is_relative_to(ROOT) and not output.is_relative_to(ROOT / ".local"):
        raise ValueError("Real-data output inside this repository must be under .local")
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise ValueError("Use a fresh output directory; existing results are not overwritten")
    if isinstance(latest, bool) or not isinstance(latest, int) or latest < 0:
        raise ValueError("latest must be nonnegative; 0 means all allowlisted session files")
    context = RecommendationContext.model_validate(context if context is not None else {"agent": "codex"})
    if context.agent != "codex":
        raise ValueError("This Codex acceptance script requires context.agent=codex")
    payload = json.loads(Path(catalog).expanduser().read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema_version") != "recommendation-catalog-v1" or payload.get("family") != "skills":
        raise ValueError("Catalog must be a recommendation-catalog-v1 skills envelope")
    loaded = load_catalog(items=payload.get("items")) if isinstance(payload.get("items"), list) else None
    if loaded is None or not loaded.items or any(i.family != "skills" for i in loaded.items):
        raise ValueError("Catalog contains no valid Skill entries or includes another family")
    files = sorted((item.path for item in inputs("codex", source)),
                   key=lambda p: (-p.stat().st_mtime_ns, str(p)))
    selected = files[:latest] if latest else files
    if not selected:
        raise ValueError("No allowlisted Codex session transcripts found; check --codex-home")
    output.mkdir(parents=True, mode=0o700)
    output.chmod(0o700)
    save(output / "selection.json", {"source": str(source), "available_files": len(files),
         "selected_files": [str(p.relative_to(source)) for p in selected],
         "selection": "all" if latest == 0 else "latest_modified", "synthetic_activity": False})
    home = output / "data"
    with Store(home) as store:
        # Native inputs are now indexed in place. A live writer can append
        # between indexing, projection and verification; rescan the SAME sample.
        for attempt in range(1, 4):
            try:
                imported = ImportService(store, progress=progress).import_source(ImportRequest("codex", source, files=tuple(selected)))
                save(output / "import.json", {"attempt": attempt, "import": imported, "stored": statistics(store)})
                if imported["capture_errors"] or imported["cancelled"]:
                    raise RuntimeError("Import was incomplete; inspect local import.json")
                verification = store.verify()
                save(output / "verify.json", verification)
                if verification["integrity"] != "ok":
                    unavailable = verification.get("unavailable_sources", [])
                    if unavailable and all(item["status"] == "changed" for item in unavailable):
                        raise SourceUnavailable("changed", "Source changed before verification")
                    raise RuntimeError("Source verification was incomplete; inspect local verify.json")
                break
            except SourceUnavailable as error:
                if error.status != "changed" or attempt == 3:
                    raise
                if progress:
                    progress({"stage": "rescan", "attempt": attempt + 1, "reason": "source_changed"})
    if progress:
        progress({"stage": "analytics"})
    analysis = analyze_store(CanonicalStore(home), scope or Scope(), with_text=False)
    save(output / "analytics.json", analysis)
    if not analysis.get("sessions"):
        raise RuntimeError("No analyzable main sessions in this selection; inspect analytics.json or use --latest 0")
    if progress:
        progress({"stage": "recommend"})
    result = recommend(analysis, context=context, catalog=loaded.items, family="skills", limit=6)
    save(output / "recommendations.json", result)
    save(output / "context.json", context.model_dump(mode="json"))
    save(output / "catalog.json", payload)
    cards = result["recommendations"]
    summary = {"pipeline_status": "completed", "synthetic_activity": False,
               "selected_files": len(selected), "analyzed_main_sessions": len(analysis["sessions"]),
               "counts": analysis["overview"]["counts"], "unparsed_records": imported["current_unparsed"],
               "catalog_items": len(loaded.items), "catalog_diagnostics": loaded.diagnostics,
               "recommendation_status": result["status"], "recommendation_count": len(cards),
               "skills": [{"name": c["name"], "priority_score": c["priority_score"],
                           "status": c["recommendation_status"], "rule_id": c["rule_id"],
                           "pending_requirements": c["pending_requirements"]} for c in cards],
               "analysis_digest": result["analysis_digest"], "output": str(output),
               "notes": ["只读导入实际 Codex 日志；没有生成或补写会话及瓶颈标注。",
                         "默认目录是四个公共 Skill 的内容审阅元数据；不会执行或安装 Skill。",
                         "环境未明确提供时保留 needs_context；不把未知依赖当成可用。",
                         "没有推荐时不回退到构造数据；退出码 2 表示链路完成但没有匹配。",
                         "没有成本和改善假设时收益保持未知。"]}
    save(output / "summary.json", summary)
    lines = ["# 本机 Codex 到 Skill 推荐", "",
             f"导入 {len(selected)} 个真实日志文件，分析 {len(analysis['sessions'])} 个主会话，得到 {len(cards)} 个 Skill 推荐。", "",
             f"推荐状态：{result['status']}。未知依赖必须确认后才能试用；收益未测量。", ""]
    for card in cards:
        lines.extend([f"## {card['name']}", "", f"优先级：{card['priority_score']}；状态：{card['recommendation_status']}。", "",
                      card["reason"], "", "待确认：" + "、".join(card["pending_requirements"] or ["无"]), "",
                      f"证据根会话：`{card['scope']['root_session_uid']}`；证据条数：{len(card['evidence'])}。", ""])
    if not cards:
        lines.extend(["当前数据未产生符合条件的 Skill 推荐。请查看 recommendations.json 中的 assessments、excluded_resources 和 diagnostics；可以扩大真实日志范围，不能通过降低证据标准制造推荐。", ""])
    lines.extend(["完整输入范围、导入核验、分析结果与推荐证据分别见同目录 selection.json、import.json、verify.json、analytics.json、recommendations.json。", ""])
    (output / "report.md").write_text("\n".join(lines), encoding="utf-8")
    (output / "report.md").chmod(0o600)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--codex-home", type=Path, default=Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))))
    parser.add_argument("--latest", type=int, default=20, help="Most recently modified session files; 0 imports all.")
    parser.add_argument("--output", type=Path, help="Fresh private result directory; default .local/codex-recommend/run-<time>-<id>.")
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--context", type=Path, help="RecommendationContext JSON with known environment/preferences; defaults to agent=codex only.")
    parser.add_argument("--from-ts", type=int)
    parser.add_argument("--until-ts", type=int)
    args = parser.parse_args()
    output = args.output or ROOT / ".local/codex-recommend" / (datetime.now(timezone.utc).strftime("run-%Y%m%d-%H%M%S-") + uuid4().hex[:8])

    def progress(event):
        if event.get("stage") != "capture" or event["completed"] == event["total"] or event["completed"] % 5 == 0:
            print(json.dumps(event, ensure_ascii=False), file=sys.stderr, flush=True)

    previous_mask = os.umask(0o077)
    try:
        context = json.loads(args.context.expanduser().read_text(encoding="utf-8")) if args.context else None
        summary = run(args.codex_home, output, latest=args.latest, catalog=args.catalog, context=context,
                      scope=Scope(from_ts=args.from_ts, until_ts=args.until_ts), progress=progress)
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0 if summary["recommendation_count"] else 2
    except (OSError, ValueError, RuntimeError) as error:
        print(f"Local Codex recommendation failed: {error}", file=sys.stderr)
        return 1
    finally:
        os.umask(previous_mask)


if __name__ == "__main__":
    raise SystemExit(main())
