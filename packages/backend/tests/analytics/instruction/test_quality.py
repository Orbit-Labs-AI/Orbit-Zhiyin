"""Constructed expected labels: executable regression corpus, not human accuracy claims."""

import json
from pathlib import Path

import pytest

from tandem_backend.analytics.instruction import extract_instruction_constraints

CASES = json.loads((Path(__file__).parents[2] / "fixtures" / "instruction-quality.json").read_text())


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["id"])
def test_expected_fields_values_and_no_false_positive(case):
    event = {"event_uid": case["id"], "session_uid": "s", "seq": 0, "ts": 0,
             "kind": "message.user", "actor": "human", "text": case["text"], "attrs": {"origin": "human"}}
    row = extract_instruction_constraints([event], main_ids={"s"})[0]
    actual = {name: sorted({c["value"] for c in items}) for name, items in row["features"].items() if items}
    assert actual == case["expected"]
