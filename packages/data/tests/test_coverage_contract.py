"""Source-agnostic state rules; no user's paths, IDs or real histories."""

import json
from importlib.resources import files

import pytest
from jsonschema import Draft202012Validator

from orbit_data.coverage import dataset_coverage


@pytest.mark.parametrize(
    "rows,excluded,reasons,counts,status",
    [
        (0, False, (), {}, "available"),
        (8, False, (), {}, "available"),
        (None, False, (), {}, "unavailable"),
        (None, True, (), {}, "excluded"),
        (8, True, ("filter",), {}, "excluded"),
        (8, False, ("vendor_missing_data",), {}, "partial"),
        (0, False, (), {"source_incomplete": 1}, "partial"),
        (8, False, ("missing",), {"missing": 0}, "available"),
        (None, False, ("no_scan",), {}, "unavailable"),
    ],
)
def test_coverage_states_do_not_conflate_missing_empty_and_excluded(
    rows, excluded, reasons, counts, status
):
    result = dataset_coverage(rows, excluded=excluded, reasons=reasons, reason_counts=counts)
    schema = json.loads(
        files("orbit_data").joinpath("schemas/coverage-v1.schema.json").read_text()
    )
    Draft202012Validator(schema).validate(result)
    assert result["status"] == status and result["rows"] == rows
    assert bool(result["reasons"]) == (status != "available")
    assert all(n > 0 for n in result["reason_counts"].values())


@pytest.mark.parametrize("rows", [-1, True, "0", 1.5])
def test_invalid_counts_do_not_turn_into_zero_or_success(rows):
    with pytest.raises(ValueError):
        dataset_coverage(rows)


@pytest.mark.parametrize("counts", [{"gap": -1}, {"gap": True}, {"gap": None}, {"": 1}])
def test_invalid_gap_counts_are_rejected(counts):
    with pytest.raises(ValueError):
        dataset_coverage(1, reason_counts=counts)
