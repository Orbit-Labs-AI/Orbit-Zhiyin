"""Deterministic four-axis persona: Wilson bounds, gates, periods and reveal."""

import copy
import json
import re
from datetime import date
from pathlib import Path

import pytest

from tandem_backend.uiview import derive, insight, overview, persona
from tandem_backend.uiview.typecopy import AXES, BUILTIN, TYPES

from .synth import TODAY, analysed

SPEC = {a["k"]: a for a in AXES}


def test_wilson_hand_computed():
    lo, hi = persona.wilson(31, 84)
    # p = 31/84, z = 1.96: centre 0.374775, half-width 0.101075
    assert lo == pytest.approx(0.2737, abs=5e-4) and hi == pytest.approx(0.4758, abs=5e-4)
    assert persona.wilson(0, 0) == (0.0, 1.0)


def test_axis_letters_and_gates():
    settled = persona.axis(SPEC["D"], 80, 100, 20)
    assert settled["letter"] == "D" and settled["state"] == "settled"
    assert settled["strong"] == 80
    assert persona.axis(SPEC["V"], 10, 100, 20)["letter"] == "T"
    assert persona.axis(SPEC["I"], 50, 100, 20)["letter"] == "?"
    assert persona.axis(SPEC["I"], 50, 100, 20)["state"] == "experimental"
    assert persona.axis(SPEC["D"], 25, 29, 20)["state"] == "insufficient"
    assert persona.axis(SPEC["D"], 80, 100, 9)["letter"] == "?"  # < 10 active days


def test_small_sample_is_not_ok():
    rows = [{"id": f"s{i}", "d": "2026-09-01", "a": "codex"} for i in range(29)]
    p = persona.persona(rows, {})
    assert p["ok"] is False and p["n"] == 29 and p["code"] is None


def test_type_copy_matches_the_prototype_table():
    js = (Path(__file__).resolve().parents[4] / "prototypes" / "advance" / "src" / "js"
          / "05-data.js").read_text(encoding="utf-8")
    table = js[js.index("const TYPES = {"):js.index("};", js.index("const TYPES = {"))]
    parsed = {code: (zh, en, line) for code, zh, en, line in
              re.findall(r"(\w{4}): \['([^']*)', '([^']*)', '([^']*)'\]", table)}
    assert len(parsed) == 16 and BUILTIN == parsed
    assert len(TYPES) == 16 and TYPES["SPFV"][0] == "工匠"


def page(**params):
    return persona.page(analysed()[4], {"period": "90", **params}, TODAY)


def test_page_on_synthetic_store_is_deterministic():
    a, b = page(), page()
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)
    assert a["ok"] and a["n"] == 150 and len(a["axes"]) == 4
    for axis in a["axes"]:
        assert axis["lo"] <= axis["value"] <= axis["hi"]
        assert axis["letter"] in ("D", "S", "P", "I", "M", "F", "V", "T", "?")
        assert axis["evidence"]["txt"]
    assert a["code"] == "".join(x["letter"] for x in a["axes"])
    assert a["low"] == {"n": 150, "need": 30}
    assert sum(sum(h) for h in a["fp"]["byH"]) == 150
    assert {f["a"] for f in a["fit"]} == {"codex", "claude_code"}
    assert all(f["basis"] == "descriptive_estimate" for f in a["fit"])


def test_previous_month_matches_months_series():
    current = page(period="2026-09")
    months = {m["k"]: m for m in current["months"]}
    assert current["prev"]["period"] == "2026-08"
    assert current["prev"]["code"] == months["2026-08"]["code"]
    assert current["prev"]["v"] == months["2026-08"]["v"]
    assert current["code"] == months["2026-09"]["code"]
    assert page(period="sep")["code"] == current["code"]


def test_filters_relax_and_low_sample():
    cc = page(agents=["claude_code"], period="7")
    assert cc["n"] < 30 and cc["ok"] is False
    relax = {r["k"]: r["n"] for r in cc["relax"]}
    assert relax["agents"] > cc["n"] and relax["period"] >= cc["n"]
    with pytest.raises(ValueError):
        persona.page(analysed()[4], {"period": "fortnight"}, TODAY)


def test_reveal_subset():
    out = persona.reveal(analysed()[4], {"period": "all"}, TODAY)
    assert out["code"] == page(period="all")["code"]
    assert len(out["particles"]) == out["particles_total"] == 150
    assert set(out["particles"][0]) == {"h", "mi", "dur", "a"}
    matches = [c["match"] for c in out["candidates"]]
    assert matches == sorted(matches, reverse=True) and len(matches) == 6


def test_months_window_resolution():
    window, label, prev, prev_label = persona.resolve_period("2026-01", date(2026, 3, 15), -400)
    assert label == "2026-01" and prev_label == "2025-12"
    assert window == ((date(2026, 1, 1) - date(2026, 3, 15)).days,
                      (date(2026, 1, 31) - date(2026, 3, 15)).days)


# -- sessions without a project ------------------------------------------------------------
# Kimi without session_index.jsonl or a session without cwd has project_id NULL; persona
# evidence used to sort (ratio, pid) tuples and raised str < None on a ratio tie.

def test_evidence_ties_with_a_projectless_bucket():
    rows = [{"id": "a", "d": "2026-09-01", "a": "kimi", "p": None, "msgs": 3},
            {"id": "b", "d": "2026-09-01", "a": "codex", "p": "p1", "msgs": 3}]
    aux = {"a": {"open": 1, "turns": [[5, 1]]}, "b": {"open": 1, "turns": [[5, 1]]}}
    p = {"axes": [{"k": "I", "n_units": 2, "k_units": 0}]}
    st = {"per": 3.0, "auto": 5.0, "verify": 100.0}
    ev = persona.evidence(rows, aux, p, st, {"p1": {"id": "p1", "name": "Alpha"}})
    assert ev["I"]["vals"] == [100, 100] and ev["V"]["vals"] == [100, 100]
    assert ev["I"]["projects"] == ev["V"]["projects"] == ["Alpha", derive.NO_PROJECT]


def _projectless(share: int = 3) -> dict:
    body = copy.deepcopy(analysed()[4])
    for r in body["rows"][::share]:
        r["p"] = None
    return body


def test_page_and_reveal_with_projectless_sessions():
    body = _projectless()
    for period in ("all", "90", "2026-09"):
        out = persona.page(body, {"period": period}, TODAY)
        for k in ("I", "V"):
            ev = (next(a for a in out["axes"] if a["k"] == k)["evidence"] or {})
            assert all(isinstance(name, str) for name in ev.get("projects") or [])
    full = persona.page(body, {"period": "all"}, TODAY)
    assert full["ok"] and derive.NO_PROJECT in next(
        a for a in full["axes"] if a["k"] == "I")["evidence"]["projects"]
    reveal = persona.reveal(body, {"period": "all"}, TODAY)
    assert reveal["code"] == full["code"]
    assert len(reveal["particles"]) == reveal["particles_total"] == 150


def test_overview_insight_names_the_projectless_bucket():
    rows = [{"id": "a", "p": None, "corr": 3, "fric": "方向错误"},
            {"id": "b", "p": "p1", "corr": 1, "fric": "方向错误"}]
    st = {"verify": 0, "ok": 0, "corr": 4}
    p = {"ok": False, "n": 2}
    out = insight.build(rows, st, p, {"p1": {"id": "p1", "name": "Alpha"}})
    assert f"集中在 {derive.NO_PROJECT}、Alpha" in out["stuck"]["text"]
    body = _projectless(share=1)
    assert overview.build(body, {"range": 30}, TODAY)["insight"]["stuck"]["text"]
