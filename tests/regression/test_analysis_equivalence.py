"""Result-equivalence regression for the analysis core on deterministic synthetic input.

Performance refactors of ``analyze_bundle`` / ``build_products`` must keep these sections
identical. The golden stores, per section, the key tree that was present when it was
recorded plus a sha256 of the normalized projection onto that tree: new fields or new
sections never break the assertion, removed fields or changed values do.

Regenerate only when a result change is intended, and explain the reason and the diff
in the PR description::

    uv run python tests/regression/test_analysis_equivalence.py --update-golden
"""

from __future__ import annotations

import getpass
import hashlib
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:  # benchmarks/ is a repository package, not an installed one
    sys.path.insert(0, str(ROOT))

from benchmarks.analytics.synthetic import canonical_json, generate_bundle  # noqa: E402

from tandem_backend.analytics.inputs import AnalysisInputBundle, Scope  # noqa: E402
from tandem_backend.analytics.products.service import build_products  # noqa: E402
from tandem_backend.analytics.service import analyze_bundle  # noqa: E402

GOLDEN = ROOT / "packages/backend/tests/fixtures/analysis-golden-v1.json"
SESSIONS, SEED, TIMEZONE = 200, 7, "Asia/Shanghai"
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


def run():
    bundle = AnalysisInputBundle.from_dict(generate_bundle(SESSIONS, SEED))
    scope = Scope(display_timezone=TIMEZONE)
    result = analyze_bundle(bundle, scope, with_text=False)
    bundle = AnalysisInputBundle.from_dict(generate_bundle(SESSIONS, SEED))
    products = build_products(bundle, scope)
    return result, products


def build_golden():
    result, products = run()
    sections = {}
    for name, value in core_sections(result, products).items():
        value = normalize(value)
        tree = key_tree(value)
        sections[name] = {"keys": tree, "sha256": digest(project(value, tree))}
    return {
        "golden_version": 1,
        "input": {
            "generator": "benchmarks.analytics.synthetic",
            "sessions": SESSIONS,
            "seed": SEED,
            "display_timezone": TIMEZONE,
            "with_text": False,
        },
        "values": key_values(result, products),
        "sections": sections,
    }


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


def test_core_analysis_results_match_golden():
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    result, products = run()
    values = key_values(result, products)
    assert {k: values.get(k) for k in golden["values"]} == golden["values"]
    current = core_sections(result, products)
    mismatched, missing = [], set()
    for name, recorded in golden["sections"].items():
        assert name in current, f"core section removed: {name}"
        value = normalize(current[name])
        missing |= {name + p for p in key_paths(recorded["keys"]) - key_paths(key_tree(value))}
        projected = project(value, recorded["keys"])
        if digest(projected) != recorded["sha256"]:
            mismatched.append(name)
    assert not missing, f"fields removed from core sections: {sorted(missing)[:20]}"
    assert not mismatched, (
        f"core analysis results changed: {mismatched}; if intended, rerun with --update-golden "
        "and explain the difference in the PR"
    )


if __name__ == "__main__":
    if sys.argv[1:] != ["--update-golden"]:
        raise SystemExit(
            "usage: python tests/regression/test_analysis_equivalence.py --update-golden"
        )
    GOLDEN.write_text(
        json.dumps(build_golden(), ensure_ascii=False, indent=1, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"updated {GOLDEN.relative_to(ROOT)}")
