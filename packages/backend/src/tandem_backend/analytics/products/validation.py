"""Cross-product invariants used by synthetic and opt-in local-history acceptance runs."""

import math
from collections import defaultdict
from typing import Any

Record = dict[str, Any]


def validate_products(product: Record) -> Record:
    """Check accounting, evidence membership, ordering and finite exportable numbers."""
    errors, checks = [], []

    def check(name: str, passed: bool) -> None:
        checks.append({"name": name, "passed": passed})
        if not passed:
            errors.append(name)

    tools = product["tools"]
    lexical = product["lexical"]
    if lexical["terms"] is not None:
        check(
            "word counts match retained tokens",
            sum(row["count"] for row in lexical["terms"]) == lexical["token_count"],
        )
        check("full vocabulary is retained", len(lexical["terms"]) == lexical["vocabulary_size"])
        check(
            "word evidence accounting",
            all(
                sum(ref["count"] for ref in row["evidence"]) == row["count"]
                for row in lexical["terms"]
            ),
        )
    for name, summary in product["statistics"]["metrics"].items():
        check(
            f"{name}: known + unknown = samples",
            summary["n"] + summary["unknown_n"]
            == summary.get("samples_total", len(summary["samples"])),
        )
    if tools["call_count"] is not None:
        for name in ("by_name", "by_kind"):
            rows = tools[name]
            check(f"{name}: call accounting", sum(r["count"] for r in rows) == tools["call_count"])
            check(
                f"{name}: shares sum to one",
                not rows or math.isclose(sum(r["share"]["value"] for r in rows), 1.0),
            )
            check(
                f"{name}: status denominators",
                all(
                    r["success_rate"]["effective_n"] + r["success_rate"]["unknown_n"] == r["count"]
                    for r in rows
                ),
            )
        for name, matrix in tools["transitions"].items():
            sums = defaultdict(float)
            for edge in matrix["rows"]:
                sums[edge["from"]] += edge["probability"]
            check(
                f"{name}: conditional rows sum to one",
                all(math.isclose(v, 1.0) for v in sums.values()),
            )
            check(
                f"{name}: transition accounting",
                sum(e["count"] for e in matrix["rows"]) == matrix["pair_count"],
            )
    event_ids = set()
    for session in product["sessions"]:
        for lane in session["journey"]["lanes"] or []:
            events = lane["events"]
            seq = [e["seq"] for e in events]
            check(f"lane {lane['session_uid']}: native order", seq == sorted(seq))
            check(
                f"lane {lane['session_uid']}: unique events",
                len({e["event_uid"] for e in events}) == len(events),
            )
            event_ids.update(e["event_uid"] for e in events)
    feedback = product["feedback"]
    if feedback["messages"] is not None:
        check(
            "emotion evidence belongs to selected events",
            all(r["event_uid"] in event_ids for r in feedback["messages"]),
        )
        summary = feedback["summary"]
        check(
            "emotion known + unknown = human messages",
            summary["balance"]["effective_n"] + summary["balance"]["unknown_n"]
            == summary["human_message_n"],
        )
        check(
            "emotion calendar accounting",
            sum(r["human_message_n"] for r in feedback["by_day"]) + feedback["time_unknown_n"]
            == summary["human_message_n"],
        )
        check(
            "emotion scores bounded",
            all(
                r["balance"]["value"] is None or -1 <= r["balance"]["value"] <= 1
                for r in feedback["by_day"]
            ),
        )
    return {
        "status": "passed" if not errors else "failed",
        "checks": checks,
        "errors": errors,
        "meaning": "consistency checks on this snapshot, not proof of semantic accuracy or absence of all defects",
    }
