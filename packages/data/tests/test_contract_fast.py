"""The hand-written event check must never accept what event-v1.schema.json rejects.

Envelopes come from importing the synthetic small tree (no real agent data); each is
then mutated field by field. For every candidate, ``event_certainly_valid`` may only be
True when the full jsonschema validator also accepts it, and ``validate_event`` must
raise exactly when the schema validator does.
"""

import copy
import json
import random
import sys
from importlib.resources import files
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from orbit_data import contract
from orbit_data.service import ImportRequest, ImportService
from orbit_data.store import Store

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from benchmarks.data.synthetic import generate  # noqa: E402

SCHEMA = Draft202012Validator(
    json.loads(files("orbit_data").joinpath("schemas/event-v1.schema.json").read_text())
)
ODD_VALUES = [
    None, True, False, 0, 1, -1, 2, 1.0, 0.5, -0.5, float("nan"), "", "x", "missing",
    "reported", "call", "delta", "cumulative", "session_snapshot", "prompt", [], [1], {}, {"a": 1},
]  # fmt: skip


@pytest.fixture(scope="module")
def envelopes(tmp_path_factory):
    seen = []
    original = contract.validate_event

    def record(event):
        seen.append(copy.deepcopy(event))
        original(event)

    with pytest.MonkeyPatch.context() as patch:
        base = tmp_path_factory.mktemp("fastcheck")
        patch.setenv("HOME", str(base / "home"))
        patch.setattr("orbit_data.pipeline.validate_event", record)
        out = base / "synthetic"
        manifest = generate(out, "small")
        with Store(base / "data") as store:
            service = ImportService(store, workers=1)
            for agent, relative in sorted(manifest["sources"].items()):
                service.import_source(ImportRequest(agent, out / relative))
    assert len(seen) > 500
    return seen


def _same(event):
    accepted = SCHEMA.is_valid(event)
    if contract.event_certainly_valid(event):
        assert accepted, event
    try:
        contract.validate_event(event)
        raised = False
    except Exception:  # noqa: BLE001 - compared with the schema verdict
        raised = True
    assert raised == (not accepted)


def _paths(value, prefix=()):
    if isinstance(value, dict):
        for key, child in value.items():
            yield (*prefix, key)
            yield from _paths(child, (*prefix, key))


def _set(event, path, value):
    target = event
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value


def _drop(event, path):
    target = event
    for key in path[:-1]:
        target = target[key]
    del target[path[-1]]


def test_real_envelopes_take_the_fast_path(envelopes):
    accepted = sum(contract.event_certainly_valid(event) for event in envelopes)
    for event in envelopes:
        assert SCHEMA.is_valid(event)
    assert accepted == len(envelopes)


def test_mutations_agree_with_schema(envelopes):
    rng = random.Random(7)
    by_kind = {}
    for event in envelopes:
        by_kind.setdefault(event["kind"], []).append(event)
    samples = [event for group in by_kind.values() for event in group[:6]]
    for event in samples:
        paths = [path for path in _paths(event) if path[0] != "ext" and path[-1] != "reported"]
        for path in paths:
            for value in rng.sample(ODD_VALUES, 6):
                mutated = copy.deepcopy(event)
                _set(mutated, path, value)
                _same(mutated)
            mutated = copy.deepcopy(event)
            _drop(mutated, path)
            _same(mutated)
        for name in ("origin", "name", "request_key", "snapshot_key", "request_id"):
            for value in ODD_VALUES[:8]:
                mutated = copy.deepcopy(event)
                mutated["attrs"][name] = value
                _same(mutated)
        for kind in contract.KINDS:
            mutated = copy.deepcopy(event)
            mutated["kind"] = kind
            _same(mutated)
        extra = copy.deepcopy(event)
        extra["unexpected"] = 1
        _same(extra)
