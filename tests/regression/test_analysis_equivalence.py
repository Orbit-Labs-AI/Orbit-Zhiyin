"""Result-equivalence regression for the analysis core on deterministic synthetic input.

Two kinds of checks:

- Truth: the generator returns what it injected (sessions, subagents, projects, turns, human
  messages, tool calls and failures, token total). The analysis must reproduce those numbers
  exactly; this is an oracle independent of the implementation.
- Golden: performance refactors of ``analyze_bundle`` / ``build_products`` must keep the core
  sections identical. The golden stores, per section, the key tree that was present when it
  was recorded, a sha256 of the normalized projection onto that tree and a readable summary
  (scalars and list/dict sizes): new fields or new sections never break the assertion,
  removed fields or changed values do. A small ``with_text=True`` run covers the
  text-dependent sections (text, preferences) the same way.

Regenerate only when a result change is intended; the command prints the old → new diff of
values and summaries. Explain the reason and the diff in the PR description::

    uv run python tests/regression/test_analysis_equivalence.py --update-golden
"""

from __future__ import annotations

import getpass
import hashlib
import json
import math
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:  # benchmarks/ is a repository package, not an installed one
    sys.path.insert(0, str(ROOT))

from benchmarks.analytics.synthetic import (  # noqa: E402
    canonical_json,
    generate_bundle,
    generate_bundle_with_truth,
)

from tandem_backend.analytics.inputs import AnalysisInputBundle, Scope  # noqa: E402
from tandem_backend.analytics.products.service import build_products  # noqa: E402
from tandem_backend.analytics.service import analyze_bundle  # noqa: E402

GOLDEN = ROOT / "tests/regression/fixtures/analysis-golden-v2.json"
SESSIONS, SEED, TIMEZONE = 200, 7, "Asia/Shanghai"
TEXT_SESSIONS, TEXT_SEED = 30, 11  # with_text=True is ~10x slower; keep it small
FLOAT_DIGITS = 9


def normalize(value):
    """Round floats so last-bit platform differences do not count as result changes."""
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return repr(value)
        return float(f"{value:.{FLOAT_DIGITS}g}")
    if isinstance(value, dict):
        return {str(k): normalize(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [normalize(v) for v in value]
    if isinstance(value, (set, frozenset)):
        return sorted(normalize(v) for v in value)
    return value


def key_tree(value):
    """Union of dict keys at every depth; list items share one tree."""
    if isinstance(value, dict):
        return {k: key_tree(v) for k, v in sorted(value.items())}
    if isinstance(value, list):
        merged = {}
        for item in value:
            tree = key_tree(item)
            if isinstance(tree, dict):
                for k, sub in tree.items():
                    merged[k] = _merge(merged.get(k), sub)
        return [merged] if merged else []
    return None


def _merge(left, right):
    if isinstance(left, dict) and isinstance(right, dict):
        return {k: _merge(left.get(k), right.get(k)) for k in sorted(left.keys() | right.keys())}
    if isinstance(left, list) and isinstance(right, list):
        return (
            [_merge(left[0] if left else None, right[0] if right else None)]
            if (left or right)
            else []
        )
    return left if right is None else right


def project(value, tree):
    """Keep only recorded keys, so fields added after recording do not change the digest."""
    if isinstance(tree, dict) and isinstance(value, dict):
        return {k: project(value[k], sub) for k, sub in tree.items() if k in value}
    if isinstance(tree, list) and tree and isinstance(value, list):
        return [project(item, tree[0]) for item in value]
    return value


def key_paths(tree, prefix=""):
    """Flatten a key tree; list items are written as ``[]``."""
    if isinstance(tree, dict):
        paths = set()
        for k, sub in tree.items():
            paths |= {f"{prefix}.{k}"} | key_paths(sub, f"{prefix}.{k}")
        return paths
    if isinstance(tree, list) and tree:
        return key_paths(tree[0], f"{prefix}[]")
    return set()


def sample_counts(statistics):
    """Statistics are compared by sample sizes, not by every derived figure."""
    return {
        name: {
            key: metric.get(key)
            for key in ("status", "n", "unknown_n", "unit", "grain")
            if key in metric
        }
        | {"samples": len(metric.get("samples") or [])}
        for name, metric in sorted((statistics.get("metrics") or {}).items())
    }


def core_sections(result, products):
    return {
        "overview.counts": result["overview"]["counts"],
        "sessions.features": [
            {"session_uid": s["session_uid"], "features": s["features"]} for s in result["sessions"]
        ],
        "sessions.usage": [
            {"session_uid": s["session_uid"], "usage": s["usage"]} for s in result["sessions"]
        ],
        "sessions.bottleneck_features": [
            {"session_uid": s["session_uid"], "bottleneck_features": s["bottleneck_features"]}
            for s in result["sessions"]
        ],
        "projects": result["projects"],
        "tools": result["tools"],
        "workflow": result["workflow"],
        "work_graph": result["work_graph"],
        "statistics.sample_counts": sample_counts(result["statistics"]),
        "products.statistics.sample_counts": sample_counts(products["statistics"]),
        "products.tools": products["tools"],
        "products.sessions": [
            {k: s[k] for k in ("session_uid", "features", "usage", "duration") if k in s}
            for s in products["sessions"]
        ],
    }


def key_values(result, products):
    counts = result["overview"]["counts"]
    totals = result["tools"]["totals"]
    return normalize(
        {
            "sessions": counts["sessions"],
            "main_sessions": counts["main_sessions"],
            "events": counts["events"],
            "turns": counts["turns"],
            "human_messages": counts["human_messages"],
            "correction_signals": counts["correction_signals"],
            "tool_calls": totals["call_count"],
            "tool_failures": totals["known_failure_count"],
            "total_tokens": result["overview"]["usage"]["total_tokens"],
            "product_sessions": len(products["sessions"]),
            "product_projects": len(products["projects"]),
        }
    )


def digest(value):
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def run(sessions=SESSIONS, seed=SEED, with_text=False):
    bundle = AnalysisInputBundle.from_dict(generate_bundle(sessions, seed))
    scope = Scope(display_timezone=TIMEZONE)
    result = analyze_bundle(bundle, scope, with_text=with_text)
    bundle = AnalysisInputBundle.from_dict(generate_bundle(sessions, seed))
    products = build_products(bundle, scope)
    return result, products


def text_sections(result):
    return {"text": result["text"], "preferences": result["preferences"]}


def summary(value):
    """Readable shape of a section: scalars verbatim, containers by size (one level deep)."""
    def size(item):
        if isinstance(item, list):
            return f"list[{len(item)}]"
        if isinstance(item, dict):
            return f"dict[{len(item)}]"
        return item

    if isinstance(value, dict):
        return {k: size(v) for k, v in sorted(value.items())}
    return size(value)


def recorded(sections):
    out = {}
    for name, value in sections.items():
        value = normalize(value)
        tree = key_tree(value)
        out[name] = {"keys": tree, "sha256": digest(project(value, tree)), "summary": summary(value)}
    return out


def build_golden():
    result, products = run()
    text_result, _ = run(TEXT_SESSIONS, TEXT_SEED, with_text=True)
    return {
        "golden_version": 2,
        "input": {
            "generator": "benchmarks.analytics.synthetic",
            "sessions": SESSIONS,
            "seed": SEED,
            "display_timezone": TIMEZONE,
            "with_text": False,
        },
        "truth": generate_bundle_with_truth(SESSIONS, SEED)[1],
        "values": key_values(result, products),
        "sections": recorded(core_sections(result, products)),
        "text_small": {
            "input": {"sessions": TEXT_SESSIONS, "seed": TEXT_SEED, "with_text": True},
            "sections": recorded(text_sections(text_result)),
        },
    }


def golden_diff(old, new) -> list[str]:
    """Readable old → new lines for --update-golden."""
    lines = []
    for group in ("truth", "values"):
        for key in sorted(set(old.get(group, {})) | set(new[group])):
            before, after = old.get(group, {}).get(key), new[group].get(key)
            if before != after:
                lines.append(f"{group}.{key}: {before!r} -> {after!r}")
    for prefix, old_sections, new_sections in (
        ("", old.get("sections", {}), new["sections"]),
        ("text_small.", old.get("text_small", {}).get("sections", {}),
         new["text_small"]["sections"]),
    ):
        for name in sorted(set(old_sections) | set(new_sections)):
            before, after = old_sections.get(name, {}), new_sections.get(name, {})
            if before.get("sha256") == after.get("sha256"):
                continue
            lines.append(f"{prefix}{name}: changed")
            b_sum, a_sum = before.get("summary") or {}, after.get("summary") or {}
            if isinstance(b_sum, dict) and isinstance(a_sum, dict):
                for key in sorted(set(b_sum) | set(a_sum)):
                    if b_sum.get(key) != a_sum.get(key):
                        lines.append(f"  {key}: {b_sum.get(key)!r} -> {a_sum.get(key)!r}")
            elif b_sum != a_sum:
                lines.append(f"  {b_sum!r} -> {a_sum!r}")
    return lines


def private_markers():
    markers = {"/Users/", "/home/", "C:\\Users", str(Path.home())}
    for name in (getpass.getuser(), Path.home().name):
        if name and len(name) >= 3:
            markers.add(name)
    return markers


def test_generator_is_deterministic_and_fictional():
    first, second = generate_bundle(40, SEED), generate_bundle(40, SEED)
    assert canonical_json(first) == canonical_json(second)
    assert canonical_json(generate_bundle(40, SEED + 1)) != canonical_json(first)
    text = canonical_json(first)
    assert not [m for m in private_markers() if m in text]


def test_golden_contains_no_private_paths_or_user_names():
    text = GOLDEN.read_text(encoding="utf-8")
    assert not [m for m in private_markers() if m in text]


def compare_sections(recorded_sections, current) -> tuple[list[str], set[str]]:
    mismatched, missing = [], set()
    for name, entry in recorded_sections.items():
        assert name in current, f"core section removed: {name}"
        value = normalize(current[name])
        missing |= {name + p for p in key_paths(entry["keys"]) - key_paths(key_tree(value))}
        if digest(project(value, entry["keys"])) != entry["sha256"]:
            mismatched.append(name)
    return mismatched, missing


def test_core_analysis_results_match_golden():
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    result, products = run()
    values = key_values(result, products)
    assert {k: values.get(k) for k in golden["values"]} == golden["values"]
    mismatched, missing = compare_sections(golden["sections"], core_sections(result, products))
    assert not missing, f"fields removed from core sections: {sorted(missing)[:20]}"
    assert not mismatched, (
        f"core analysis results changed: {mismatched}; if intended, rerun with --update-golden "
        "and explain the difference in the PR"
    )


def test_text_sections_match_small_golden():
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))["text_small"]
    assert golden["input"] == {"sessions": TEXT_SESSIONS, "seed": TEXT_SEED, "with_text": True}
    result, _ = run(TEXT_SESSIONS, TEXT_SEED, with_text=True)
    mismatched, missing = compare_sections(golden["sections"], text_sections(result))
    assert not missing, f"fields removed from text sections: {sorted(missing)[:20]}"
    assert not mismatched, f"text analysis results changed: {mismatched}; see --update-golden"


def test_analysis_reproduces_injected_truth():
    """Oracle independent of the implementation: what the generator wrote."""
    bundle, truth = generate_bundle_with_truth(SESSIONS, SEED)
    result = analyze_bundle(AnalysisInputBundle.from_dict(bundle), Scope(display_timezone=TIMEZONE),
                            with_text=False)
    counts, totals = result["overview"]["counts"], result["tools"]["totals"]
    assert counts["sessions"] == truth["sessions"] == truth["main_sessions"] + truth["subagent_sessions"]
    assert counts["main_sessions"] == truth["main_sessions"]
    assert counts["turns"] == truth["turns"]
    # Prompts a parent agent sends to its subagent are not human messages.
    assert counts["human_messages"] == truth["human_messages"]
    assert totals["call_count"] == truth["tool_calls"]
    assert totals["known_failure_count"] == truth["failed_tool_calls"]
    assert result["overview"]["usage"]["request_count"] == truth["model_calls"]
    assert result["overview"]["usage"]["total_tokens"] == truth["total_tokens"]
    products = build_products(AnalysisInputBundle.from_dict(bundle), Scope(display_timezone=TIMEZONE))
    assert len(products["projects"]) == truth["projects"]
    assert len(products["sessions"]) == truth["main_sessions"]


def test_golden_records_the_generator_truth():
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    assert golden["truth"] == generate_bundle_with_truth(SESSIONS, SEED)[1]


@pytest.mark.xfail(strict=True, reason=(
    "follow-up (analytics lexicon): of the generator's 4 correction phrases the detector hits "
    "'不对' and 'revert that' but misses '这个方向错了，先回滚再说' and '没看懂，换个直观的例子', "
    "and it counts the feedback '还是不行' as a correction"))
def test_correction_signals_match_injected_corrections():
    bundle, truth = generate_bundle_with_truth(SESSIONS, SEED)
    result = analyze_bundle(AnalysisInputBundle.from_dict(bundle), Scope(display_timezone=TIMEZONE),
                            with_text=False)
    assert result["overview"]["counts"]["correction_signals"] == truth["correction_messages"]


if __name__ == "__main__":
    if sys.argv[1:] != ["--update-golden"]:
        raise SystemExit(
            "usage: python tests/regression/test_analysis_equivalence.py --update-golden"
        )
    previous = json.loads(GOLDEN.read_text(encoding="utf-8")) if GOLDEN.is_file() else {}
    golden = build_golden()
    for line in golden_diff(previous, golden) or ["no changes"]:
        print(line)
    GOLDEN.parent.mkdir(parents=True, exist_ok=True)
    GOLDEN.write_text(
        json.dumps(golden, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"updated {GOLDEN.relative_to(ROOT)}")
