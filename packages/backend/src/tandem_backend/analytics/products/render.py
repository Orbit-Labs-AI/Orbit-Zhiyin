"""Offline terminal, CSV and HTML views of the same analysis snapshot."""

import csv
import html
import io
import json
import os
import tempfile
from datetime import date
from pathlib import Path
from typing import Any

Record = dict[str, Any]


def number(value: int | float | None, digits: int = 2) -> str:
    """Display unknown values distinctly from observed zero."""
    return (
        "未知" if value is None else str(value) if isinstance(value, int) else f"{value:.{digits}f}"
    )


def terminal_report(product: Record) -> str:
    """Render deterministic tables suitable for CI logs and a developer's terminal."""
    tools, feedback = product["tools"], product["feedback"]
    counts = product["overview"]["counts"]
    lines = [
        "Tandem 分析组合报告",
        f"数据摘要 {product['analysis_digest']}",
        f"主会话 {counts['main_sessions']} | 真人消息 {number(counts['human_messages'])} | 工具调用 {number(tools['call_count'])}",
        "",
        "工具调用占比（当前可观测调用为分母）",
        "工具 | 次数 | 占比 | 已知成功率 | 未知/其他状态",
    ]
    for row in tools["by_name"] or []:
        lines.append(
            f"{row['name']} | {row['count']} | {row['share']['value']:.1%} | "
            f"{number(row['success_rate']['value'])} | {row['success_rate']['unknown_n']}"
        )
    lines += [
        "",
        "下一调用类型转移概率（同会话、有可确认下一调用）",
        "当前 → 下一类 | 次数/分母 | 概率",
    ]
    for row in (tools["transitions"] or {}).get("kind", {}).get("rows", []):
        lines.append(
            f"{row['from']} → {row['to']} | {row['count']}/{row['denominator']} | {row['probability']:.1%}"
        )
    lines += [
        "",
        "明确情绪表达趋势（实验性；未识别不等于中性）",
        "日期 | 积极 | 消极 | 混合 | 未知 | 表达平衡",
    ]
    for row in feedback["by_day"] or []:
        states = row["counts"]
        lines.append(
            f"{row['day']} | {states.get('positive', 0)} | {states.get('negative', 0)} | "
            f"{states.get('mixed', 0)} | {states.get('unknown', 0)} | {number(row['balance']['value'])}"
        )
    lines += ["", "验收与反馈（两种证据分开展示）"]
    for row in product["sessions"]:
        journey = row["journey"]
        lines.append(
            f"{row['session_uid']} | 验收 {journey['outcome'].get('acceptance_counts', {})} | "
            f"反馈 {(journey['feedback'].get('counts') or {}).get('linked_feedback_count', '未知')}"
        )
    lines += ["", *product["limitations"]]
    lines += ["", "分布统计（均值 / 中位数 / P90 / 标准差）"]
    for name, row in product["statistics"]["metrics"].items():
        lines.append(
            f"{name} | n={row['n']} 未知={row['unknown_n']} | "
            f"{number(row['mean'])} / {number(row['median'])} / {number(row['quantiles']['p90'])} / {number(row['stddev'])}"
        )
    lexical = product["lexical"]
    lines += [
        "",
        f"词频前 20 项（完整词表 {lexical.get('vocabulary_size', 0)} 项均保存在分析记录）",
        "词 | 次数 | 消息数 | 会话数 | 每千词频次",
    ]
    for row in (lexical["terms"] or [])[:20]:
        lines.append(
            f"{row['term']} | {row['count']} | {row['message_count']} | {row['session_count']} | {row['per_1000_tokens']:.2f}"
        )
    if product.get("comparison"):
        lines += ["", "与上期比较（均值差 / 中位数差 / 均值差 95% 区间）"]
        for row in comparison_rows(product):
            lines.append(" | ".join(str(value) for value in row))
    return "\n".join(lines) + "\n"


def comparison_rows(product: Record) -> list[list[Any]]:
    """Render stored comparison values without recomputing a different set of statistics."""
    rows = []
    for row in product["comparison"]["distributions"]["rows"]:
        interval = row["uncertainty"]["confidence_interval_95"]
        bounds = (
            " — ".join(number(value) for value in interval)
            if interval
            else "有效会话不足或无法估计"
        )
        rows.append(
            [
                row["metric"],
                number(row["mean_difference"]),
                number(row["median_difference"]),
                bounds,
            ]
        )
    return rows


def _table(headers: list[str], rows: list[list[Any]]) -> str:
    """Escape every cell, including names originating in untrusted session logs."""

    def escape(value: Any) -> str:
        return html.escape(str(value))

    return (
        "<table><thead><tr>"
        + "".join(f"<th>{escape(h)}</th>" for h in headers)
        + "</tr></thead><tbody>"
        + "".join(
            "<tr>" + "".join(f"<td>{escape(value)}</td>" for value in row) + "</tr>" for row in rows
        )
        + "</tbody></table>"
    )


def _shares_svg(rows: list[Record]) -> str:
    """Draw shares against a common zero-to-one scale."""
    bars = []
    for index, row in enumerate(rows[:12]):
        y = 24 + index * 28
        bars.append(
            f'<text x="0" y="{y + 4}">{html.escape(row["name"][:27])}</text>'
            f'<rect x="240" y="{y - 10}" width="{row["share"]["value"] * 330:.1f}" height="18" fill="#356b65"/>'
            f'<text x="585" y="{y + 4}">{row["share"]["value"]:.1%}</text>'
        )
    return (
        f'<svg viewBox="0 0 660 {max(60, 36 + min(12, len(rows)) * 28)}" role="img" aria-label="工具调用占比">'
        + "".join(bars)
        + "</svg>"
    )


def _emotion_svg(rows: list[Record]) -> str:
    """Plot actual calendar distances and break the curve at unknown or missing days."""
    points, path, segments = [], [], []
    start = date.fromisoformat(rows[0]["day"]).toordinal() if rows else 0
    end = date.fromisoformat(rows[-1]["day"]).toordinal() if rows else 0
    previous = None
    for row in rows:
        ordinal = date.fromisoformat(row["day"]).toordinal()
        value = row["balance"]["value"]
        if value is None or previous is not None and ordinal - previous > 1:
            if path:
                segments.append(" ".join(path))
            path = []
        previous = ordinal
        if value is None:
            continue
        x = 30 + (ordinal - start) / max(1, end - start) * 600
        y = 100 - value * 70
        path.append(f"{'M' if not path else 'L'}{x:.1f},{y:.1f}")
        points.append(
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4" fill="#356b65"><title>{row["day"]}：{value:.2f}；有效消息 {row["balance"]["effective_n"]}</title></circle>'
        )
    if path:
        segments.append(" ".join(path))
    axes = '<line x1="30" y1="100" x2="630" y2="100" stroke="#aaa"/><text x="0" y="32">+1</text><text x="0" y="104">0</text><text x="0" y="174">−1</text>'
    curves = "".join(
        f'<path d="{segment}" fill="none" stroke="#356b65" stroke-width="2"/>'
        for segment in segments
    )
    labels = (
        ""
        if not rows
        else f'<text x="30" y="198">{rows[0]["day"]}</text><text x="630" y="198" text-anchor="end">{rows[-1]["day"]}</text>'
    )
    return (
        '<svg viewBox="0 0 660 215" role="img" aria-label="明确情绪表达平衡趋势">'
        + axes
        + curves
        + "".join(points)
        + labels
        + "</svg>"
    )


def html_report(product: Record) -> str:
    """Produce a self-contained, script-free report with accessible numeric tables."""
    tools, feedback = product["tools"], product["feedback"]
    matrices = (tools["transitions"] or {}).get("kind", {}).get("rows", [])
    emotions = feedback["by_day"] or []
    sections = [
        "<h1>会话分析组合验收</h1><p>工具占比、调用转移、情绪表达及任务验收均来自同一数据快照。</p>",
        f'<p class="meta">{html.escape(product["analysis_digest"])} · {html.escape(product["scope"]["display_timezone"])}</p>',
        "<h2>数值分布</h2><p>每项保留样本、未知数量、分位数和异常值位置；日志跨度不等于实际工作时间。</p>",
        _table(
            ["指标", "样本", "未知", "均值", "中位数", "P90", "标准差"],
            [
                [
                    name,
                    row["n"],
                    row["unknown_n"],
                    number(row["mean"]),
                    number(row["median"]),
                    number(row["quantiles"]["p90"]),
                    number(row["stddev"]),
                ]
                for name, row in product["statistics"]["metrics"].items()
            ],
        ),
        "<h2>词频与覆盖</h2><p>使用实际中文分词与英文词统计；本表展示前 30 项，完整词表、短语、共现与证据均保存在 JSON 和分析历史。</p>",
        _table(
            ["词", "次数", "消息数", "会话数", "每千词频次", "TF-IDF 均值"],
            [
                [
                    row["term"],
                    row["count"],
                    row["message_count"],
                    row["session_count"],
                    number(row["per_1000_tokens"]),
                    number(row["tfidf_mean"], 4),
                ]
                for row in (product["lexical"]["terms"] or [])[:30]
            ],
        ),
        "<h2>工具调用占比</h2><p>按可观测调用计数，缺失状态单列；图展示前 12 项。</p>",
        _shares_svg(tools["by_name"] or []),
        _table(
            ["工具", "次数", "占比", "成功率分母"],
            [
                [
                    r["name"],
                    r["count"],
                    f"{r['share']['value']:.1%}",
                    r["success_rate"]["effective_n"],
                ]
                for r in tools["by_name"] or []
            ],
        ),
        "<h2>下一调用类型转移概率</h2><p>每行只在确有下一调用时计数，不跨会话；末次调用另记终点。</p>",
        _table(
            ["当前类型", "下一类型", "次数", "条件分母", "概率"],
            [
                [r["from"], r["to"], r["count"], r["denominator"], f"{r['probability']:.1%}"]
                for r in matrices
            ],
        ),
        "<h2>明确情绪表达趋势</h2><p>实验性规则候选；积极减消极再除以已识别消息数，范围 −1 到 +1；未知不是中性，也不补零。</p>",
        _emotion_svg(emotions),
        _table(
            ["日期", "积极", "消极", "混合", "未知", "表达平衡"],
            [
                [
                    r["day"],
                    r["counts"].get("positive", 0),
                    r["counts"].get("negative", 0),
                    r["counts"].get("mixed", 0),
                    r["counts"].get("unknown", 0),
                    number(r["balance"]["value"]),
                ]
                for r in emotions
            ],
        ),
        "<h2>项目用量与验收</h2>",
        _table(
            ["项目", "会话", "Token", "客观验收"],
            [
                [
                    p.get("name") or p.get("project_id") or "未知项目",
                    p["session_count"],
                    number(p["usage"]["total_tokens"]),
                    p["outcomes"]["acceptance_counts"] or "无明确验收项",
                ]
                for p in product["projects"]
            ],
        ),
        "<h2>覆盖与边界</h2>",
        _table(
            ["数据", "状态"], [[key, value["status"]] for key, value in product["coverage"].items()]
        ),
        "<ul>"
        + "".join(f"<li>{html.escape(text)}</li>" for text in product["limitations"])
        + "</ul>",
    ]
    if product.get("comparison"):
        sections += [
            "<h2>与上期比较</h2><p>使用相邻等长窗口，区间按会话树重抽样估计。</p>",
            _table(["指标", "均值差", "中位数差", "均值差 95% 区间"], comparison_rows(product)),
        ]
    return (
        '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Tandem 分析验收</title><style>body{font:15px/1.6 system-ui,sans-serif;color:#263733;background:#f7f8f6;margin:0}main{max-width:1000px;margin:auto;padding:36px 24px}h1{font-size:28px}h2{margin-top:40px}table{border-collapse:collapse;width:100%;background:white;margin:16px 0;font-variant-numeric:tabular-nums}th,td{text-align:left;padding:8px;border-bottom:1px solid #ddd;overflow-wrap:anywhere}svg{max-width:750px;width:100%;font:12px system-ui}p,.meta{color:#52615d}.meta{overflow-wrap:anywhere}@media(max-width:600px){main{padding:18px 10px}table{font-size:12px}}</style><main>'
        + "".join(sections)
        + "</main></html>"
    )


def atomic_write(path: Path, text: str) -> None:
    """Replace only the named artifact atomically, keeping private files owner-readable."""
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=".tandem-")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def export_report(product: Record, output: Path) -> dict[str, str]:
    """Export one snapshot to JSON, terminal text, CSV and an offline HTML view."""
    output = output.expanduser().resolve()
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer)
    writer.writerow(["tool", "calls", "share", "known_status_n", "unknown_status_n"])
    for row in product["tools"]["by_name"] or []:
        name = row["name"]
        if name.lstrip().startswith(("=", "+", "-", "@")):
            name = "'" + name
        writer.writerow(
            [
                name,
                row["count"],
                row["share"]["value"],
                row["success_rate"]["effective_n"],
                row["success_rate"]["unknown_n"],
            ]
        )
    files = {
        "analysis.json": json.dumps(product, ensure_ascii=False, indent=2, allow_nan=False),
        "report.txt": terminal_report(product),
        "report.html": html_report(product),
        "tools.csv": buffer.getvalue(),
    }
    words = io.StringIO(newline="")
    writer = csv.writer(words)
    writer.writerow(
        ["term", "count", "message_count", "session_count", "per_1000_tokens", "tfidf_mean"]
    )
    for row in product["lexical"]["terms"] or []:
        term = row["term"]
        if term.lstrip().startswith(("=", "+", "-", "@")):
            term = "'" + term
        writer.writerow(
            [
                term,
                row["count"],
                row["message_count"],
                row["session_count"],
                row["per_1000_tokens"],
                row["tfidf_mean"],
            ]
        )
    files["words.csv"] = words.getvalue()
    for name, content in files.items():
        atomic_write(output / name, content)
    return {name: str(output / name) for name in files}
