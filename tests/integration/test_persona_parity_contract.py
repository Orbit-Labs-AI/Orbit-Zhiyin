"""Backend persona == App persona on the same rows (``uiview-persona-v1``).

The gateway computes the persona in ``uiview/persona_signals.py`` + ``uiview/persona.py``;
the App recomputes it client-side from the facts wire rows (``15-derive.js``
``personaCompose``: demo mode, live agent subsets, live rows that carry the units). Both
must give the same four values, intervals, signal scores, type code and confidence.

The prototype side runs in Node (``prototypes/advance/tools/persona-eval.mjs`` loads the
same source files the App build concatenates). Inputs are constructed only: fictional users
from ``benchmarks/analytics/synthetic.persona_population``, the live stub fixture
``prototypes/shared/fixtures/core/facts.json`` and hand-written edge rows.

Tolerances: values, interval ends and signal scores are rounded to 0.1 on both sides; float
summation order differs between the two languages, so they may differ by one rounding step
(``TOL`` = 0.1). Letters, type code, confidence, unit counts, ``strong``, ``decided``,
``agree`` and ``consistency`` must be identical (the backend rounds half-up like the App's
``Math.round``, see ``persona.jsround``).
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
from benchmarks.analytics.synthetic import persona_population

from orbit_backend.uiview import persona
from orbit_backend.uiview import persona_signals as sig

ROOT = Path(__file__).resolve().parents[2]
EVAL = ROOT / "prototypes/advance/tools/persona-eval.mjs"
CORE_FACTS = ROOT / "prototypes/shared/fixtures/core/facts.json"
TOL = 0.1 + 1e-9


def decode(body: dict) -> list[dict]:
    """Columnar facts wire body (``facts.compact``) → row dicts, as the App decodes it."""
    fields, dicts, consts = body["fields"], body.get("dicts") or {}, body.get("constants") or {}
    prefix = (body.get("meta") or {}).get("id_prefix") or ""
    rows = []
    for raw in body["rows"]:
        row = dict(consts)
        for name, value in zip(fields, raw, strict=True):
            if name in dicts and value is not None:
                value = dicts[name][value]
            row[name] = value
        row["id"] = prefix + str(row["id"])
        rows.append(row)
    return rows


def edge_rows() -> list[dict]:
    base = {"p": "proj-a", "msgs": 4, "corr": 1, "dk": 3, "dn": 4, "vk": 1, "ik": 0, "kn": 4,
            "op": 1, "oa": 1, "os": 0, "ol": 120, "sc": 0, "rb": 0}
    return [
        {**base, "id": "e1", "d": "2026-09-01", "a": "claude_code", "t0": 0, "t1": 3_600_000},
        # same day, other agent, overlapping → multi-thread day
        {**base, "id": "e2", "d": "2026-09-01", "a": "codex", "t0": 1_800_000, "t1": 5_000_000,
         "msgs": 1, "corr": 0, "dk": 1, "dn": 1, "vk": 0, "kn": 1, "sc": None},
        # old snapshot: only ``op``; unknown msgs / corr; no turns
        {**base, "id": "e3", "d": "2026-09-02", "a": "claude_code", "t0": None, "t1": None,
         "msgs": None, "corr": None, "dk": 0, "dn": 0, "vk": 0, "ik": 0, "kn": 0,
         "oa": None, "os": None, "ol": None, "sc": None, "rb": None},
        # heavy delegation, asked for verification every turn, rolled back
        {**base, "id": "e4", "d": "2026-09-04", "a": "gemini", "t0": 0, "t1": 60_000,
         "msgs": 2, "corr": 0, "dk": 2, "dn": 2, "vk": 2, "ik": 1, "kn": 2, "oa": 0,
         "os": 1, "ol": 2400, "sc": 3, "rb": 1},
        # one long session with many stops and redirects
        {**base, "id": "e5", "d": "2026-09-04", "a": "claude_code", "t0": 30_000, "t1": 90_000,
         "msgs": 30, "corr": 9, "dk": 2, "dn": 30, "vk": 9, "ik": 8, "kn": 25, "ol": 12},
    ]


def cases() -> list[dict]:
    out = []
    for i, user in enumerate(persona_population(users=10, sessions=40, seed=11)):
        agents = sorted({r["a"] for r in user["rows"]})
        out.append({"name": f"population-{i}", "rows": user["rows"],
                    "agents": [agents[:1], agents[1:], agents[::2]]})
    core = decode(json.loads(CORE_FACTS.read_text()))
    core_agents = sorted({r["a"] for r in core if r.get("d")})
    out.append({"name": "core-fixture", "rows": core,
                "agents": [[a] for a in core_agents] + [core_agents[1:]]})
    edges = edge_rows()
    out.append({"name": "edges", "rows": edges,
                "agents": [["claude_code"], ["codex"], ["gemini", "codex"]]})
    out.append({"name": "single", "rows": edges[:1], "agents": []})
    out.append({"name": "old-snapshot", "rows": edges[2:3], "agents": []})
    return out


def backend(rows: list[dict], agents: list[str] | None = None) -> dict:
    rows = [r for r in rows if r.get("d") and not r.get("excluded")]
    if agents is None:
        return persona.persona_from(sig.suff(rows, None))
    return persona.persona_for_agents(sig.by_agent(rows, None), set(agents))


def assert_same(name: str, py: dict, js: dict) -> None:
    assert py["ok"] == js["ok"], name
    if not py["ok"]:
        return
    assert (py["n"], py["days"], py["code"], py["conf"], py["decided_axes"]) == \
        (js["n"], js["days"], js["code"], js["conf"], js["decided_axes"]), name
    assert py["consistency"] == js["consistency"], name
    for a, b in zip(py["axes"], js["axes"], strict=True):
        where = f"{name} axis {a['k']}"
        assert (a["k"], a["letter"], a["state"], a["strong"], a["decided"]) == \
            (b["k"], b["letter"], b["state"], b["strong"], b["decided"]), where
        assert (a["n_units"], a["k_units"]) == (b["n_units"], b["k_units"]), where
        for key in ("value", "lo", "hi"):
            assert a[key] == pytest.approx(b[key], abs=TOL), f"{where} {key}"
        assert a["agree"] == b["agree"], where
        assert [s["key"] for s in a["signals"]] == [s["key"] for s in b["signals"]], where
        for s, t in zip(a["signals"], b["signals"], strict=True):
            assert (s["weight"], s["n"]) == (t["weight"], t["n"]), f"{where} {s['key']}"
            assert s["score"] == pytest.approx(t["score"], abs=TOL), f"{where} {s['key']}"


def test_backend_and_app_compute_the_same_persona():
    node = shutil.which("node")
    assert node, "node is required: the App side of the persona runs in Node"
    data = cases()
    run = subprocess.run([node, str(EVAL)], input=json.dumps({"cases": data}),
                         capture_output=True, text=True, timeout=120, check=False)
    assert run.returncode == 0, run.stderr
    results = {c["name"]: c for c in json.loads(run.stdout)["cases"]}
    codes = set()
    for case in data:
        js = results[case["name"]]
        py = backend(case["rows"])
        assert_same(case["name"], py, js["all"])
        codes.add(py["code"])
        for ids, sub in zip(case["agents"], js["subsets"], strict=True):
            assert_same(f"{case['name']} {ids}", backend(case["rows"], ids), sub)
    # the cases are not all one type (a parity test on a single code would prove little)
    assert len(codes) >= 4


def test_core_fixture_rows_carry_the_persona_units():
    """The live stub fixture has every persona unit the gateway sends, so a live persona
    page under the stub shows the real multi-signal structure (no server round trip)."""
    rows = [r for r in decode(json.loads(CORE_FACTS.read_text())) if r.get("d")]
    units = ("dk", "dn", "vk", "ik", "kn", "op", "ol", "oa", "os", "sc", "rb", "t0", "t1")
    assert all(r.get("dn") is not None for r in rows)
    assert all(k in r for r in rows for k in units)
    p = backend(rows)
    assert all(len(a["signals"]) >= 2 for a in p["axes"])


def test_anchor_health_on_a_fictional_population():
    """Not calibration (the population is invented, see benchmarks/analytics/persona_spread):
    on users with independent latent traits every axis spreads out, follows its trait, does
    not pile up at one end or at 50, and all 16 types occur."""
    from benchmarks.analytics.persona_spread import spread

    out = spread(users=300, sessions=60, seed=7)
    for k, a in out["axes"].items():
        q05, _, _, _, q95 = a["quantiles"]
        assert q95 - q05 >= 30, (k, a)          # not squeezed together
        assert q05 <= 40 and q95 >= 60, (k, a)  # both letters well inside reach
        assert a["band_share"] <= 0.35, (k, a)  # no pile-up at 50
        assert 0.3 <= a["high_share"] <= 0.7, (k, a)  # no pile-up at one end
        assert a["corr"] >= 0.8, (k, a)          # the axis measures its trait
    assert len(out["codes"]) == 16
