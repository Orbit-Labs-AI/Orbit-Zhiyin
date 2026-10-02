"""Deterministic four-axis persona: Wilson bounds, gates, periods and reveal."""

import json
import re
from datetime import date
from pathlib import Path

import pytest

from tandem_backend.uiview import persona
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
