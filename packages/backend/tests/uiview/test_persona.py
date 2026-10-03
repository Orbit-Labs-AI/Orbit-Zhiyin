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
    # No undetermined band: exactly 50 takes the high letter, just below takes the low one.
    assert persona.axis(SPEC["I"], 50, 100, 20)["letter"] == "I"
    assert persona.axis(SPEC["I"], 49, 100, 20)["letter"] == "P"
    assert persona.axis(SPEC["I"], 50, 100, 20)["state"] == "settled"
    assert persona.axis(SPEC["D"], 3, 4, 1)["letter"] == "D"  # tiny samples still lean
    empty = persona.axis(SPEC["M"], 0, 0, 1)
    assert empty["letter"] == "M" and empty["state"] == "no_data" and empty["value"] is None


def test_one_session_gives_a_full_code():
    rows = [{"id": "s0", "d": "2026-09-01", "a": "codex"}]
    aux = {"s0": {"open": 1, "turns": [[7, 0], [2, 1]], "t0": 0, "t1": 10}}
    p = persona.persona(rows, aux)
    assert p["ok"] is True and p["n"] == 1 and p["classified"]
    assert len(p["code"]) == 4 and "?" not in p["code"] and p["code"] in TYPES
    assert p["hint"] == "基于 1 个会话，数据越多越准" and p["conf"] == "低"
    assert persona.candidates(p)[0]["code"] == p["code"]
    none = persona.persona([], {})
    assert none["ok"] is False and none["code"] is None and none["hint"] is None


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
        assert axis["letter"] in ("D", "S", "P", "I", "M", "F", "V", "T")
        assert axis["evidence"]["txt"]
    assert a["code"] == "".join(x["letter"] for x in a["axes"])
    assert a["low"] == {"n": 150, "need": 1, "soft": 30}
    assert a["classified"] and a["hint"] is None and a["conf"] == "高"
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
    assert 0 < cc["n"] < 30 and cc["ok"] is True and "?" not in cc["code"]
    assert cc["hint"] == f"基于 {cc['n']} 个会话，数据越多越准"
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


# -- hand-computed core functions -------------------------------------------------------
def _hand_rows():
    rows = [{"id": "s1", "d": "2026-09-01", "a": "codex"},
            {"id": "s2", "d": "2026-09-01", "a": "codex"},
            {"id": "s3", "d": "2026-09-02", "a": "codex"},
            {"id": "s4", "d": "2026-09-02", "a": "codex"},
            {"id": "s5", "d": "2026-09-03", "a": "codex"},
            {"id": "s6", "d": "2026-09-03", "a": "claude_code"}]
    aux = {
        # day 1: one agent, s1 [0,10] and s2 [5,15] overlap → multi-thread day
        "s1": {"turns": [[4, 0], [5, 1]], "open": 1, "t0": 0, "t1": 10},
        "s2": {"turns": [[6, 0]], "open": 0, "t0": 5, "t1": 15},
        # day 2: one agent, [0,10] then [10,20] only touch → not multi-thread
        "s3": {"turns": [[5, 1], [3, 1]], "open": None, "t0": 0, "t1": 10},
        "s4": {"turns": [], "open": 0, "t0": 10, "t1": 20},
        # day 3: disjoint in time but two agents → multi-thread day
        "s5": {"open": 1, "t0": 0, "t1": 5},
        "s6": {"turns": [[4, 0]], "open": 0, "t0": 100, "t1": 200},
    }
    return rows, aux


def test_units_hand_computed():
    rows, aux = _hand_rows()
    # D: turns with ≥ 5 steps: 5, 6, 5 (the 4s and 3 are below) → 3 of 6 turns.
    # V: verify flags 1 (s1), 1, 1 (s3) → 3 of 6 turns.
    # I: openings 1,0,0,1,0 (s3 None is skipped) → 3 unstructured of 5.
    # M: day 1 overlap + day 3 two agents → 2 of 3 days.
    assert persona.units(rows, aux) == {"D": (3, 6), "I": (3, 5), "M": (2, 3), "V": (3, 6)}
    assert persona.session_counts(rows, aux) == {
        "D": [(1, 2), (1, 1), (1, 2), (0, 1)], "V": [(1, 2), (0, 1), (2, 2), (0, 1)]}


def test_cluster_interval_hand_computed_and_duplicates_do_not_narrow():
    # Two sessions, 5/5 and 0/5: p = 0.5, var = 2/1 · (2.5² + 2.5²) / 10² = 0.25,
    # n_eff = 0.25 / 0.25 = 1 → Wilson at n = 1: centre 0.5, half 0.4454.
    lo, hi, n_eff = persona.cluster_interval([(5, 5), (0, 5)])
    assert n_eff == pytest.approx(1.0)
    assert lo == pytest.approx(0.0546, abs=5e-4) and hi == pytest.approx(0.9454, abs=5e-4)
    # Same sessions, every turn duplicated: identical interval (not the n=20 Wilson).
    assert persona.cluster_interval([(10, 10), (0, 10)]) == (lo, hi, n_eff)
    ind_lo, ind_hi = persona.wilson(5, 10)
    assert ind_hi - ind_lo < hi - lo
    # Zero between-session variance falls back to one unit per session (20 < 40 turns).
    assert persona.cluster_interval([(1, 2)] * 20)[2] == 20


def test_axis_interval_is_session_clustered():
    clusters = [(6, 6)] * 15 + [(0, 6)] * 15
    doubled = [(12, 12)] * 15 + [(0, 12)] * 15
    a = persona.axis(SPEC["D"], 90, 180, 20, clusters)
    b = persona.axis(SPEC["D"], 180, 360, 20, doubled)
    assert (a["lo"], a["hi"]) == (b["lo"], b["hi"])
    # var = 30/29 · 30·3² / 180² → n_eff = 0.25 / var = 29.0
    assert a["n_eff"] == b["n_eff"] == 29.0
    assert a["ci_basis"] == "wilson_at_cluster_effective_n"
    plain = persona.axis(SPEC["D"], 90, 180, 20)
    assert plain["hi"] - plain["lo"] < a["hi"] - a["lo"]


def test_decided_marks_intervals_clear_of_the_band():
    # Wilson(80, 100) = [71.1, 86.7] and Wilson(10, 100) = [5.5, 17.4] clear the 45–55 band;
    # Wilson(52, 100) = [42.3, 61.5] straddles it. Every axis still gets a letter.
    a = persona.axis(SPEC["D"], 80, 100, 20)
    b = persona.axis(SPEC["D"], 52, 100, 20)
    c = persona.axis(SPEC["V"], 10, 100, 20)
    assert a["decided"] and a["letter"] == "D"
    assert not b["decided"] and b["letter"] == "D"
    assert c["decided"] and c["letter"] == "T"
    assert not persona.axis(SPEC["M"], 0, 0, 1)["decided"]
    rows = [{"id": f"s{i}", "d": "2026-09-01", "a": "codex"} for i in range(120)]
    p = persona.persona(rows, {})
    assert p["ok"] and "?" not in p["code"] and p["conf"] == "高"  # n ≥ 100
    assert p["decided_axes"] == sum(1 for x in p["axes"] if x["decided"])
    m = persona.mini(p)
    assert set(m) >= {"ok", "code", "zh", "en", "conf", "n", "hint", "method", "axes",
                      "decided_axes"}
    assert m["decided_axes"] == p["decided_axes"] and len(m["axes"]) == 4


def test_candidates_hand_computed():
    p = {"ok": True, "code": "DPMV", "v": {"D": 80, "I": 30, "M": 60, "V": 90}}
    # match = mean over axes of (v if the code takes the high letter else 100 − v):
    # DPMV (80+70+60+90)/4 = 75, DPFV 70, DIMV 65, DIFV 60 = SPMV 60 (code order), DPMT 55.
    got = persona.candidates(p)
    assert [(c["code"], c["match"]) for c in got] == [
        ("DPMV", 75.0), ("DPFV", 70.0), ("DIMV", 65.0), ("DIFV", 60.0), ("SPMV", 60.0),
        ("DPMT", 55.0)]
    # An axis without data counts as 50: DPMV and DPFV tie at 72.5, the own code first.
    tied = persona.candidates({**p, "v": {**p["v"], "M": None}})
    assert [(c["code"], c["match"]) for c in tied[:4]] == [
        ("DPMV", 72.5), ("DPFV", 72.5), ("DIFV", 62.5), ("DIMV", 62.5)]
    assert persona.candidates({**p, "ok": False}) == []


def test_strengths_and_traits_skip_axes_without_data():
    p = {"axes": [{"k": "D", "letter": "D", "strong": 70, "n_units": 40, "state": "settled"},
                  {"k": "I", "letter": "I", "strong": None, "n_units": 0, "state": "no_data"},
                  {"k": "M", "letter": "F", "strong": 90, "n_units": 12, "state": "settled"},
                  {"k": "V", "letter": "T", "strong": 60, "n_units": 40, "state": "settled"}]}
    assert [(s["letter"], s["strong"]) for s in persona.strengths(p)] == [
        ("F", 90), ("D", 70), ("T", 60)]
    assert persona.traits(p) == ["高吞吐", "单线专注", "信任结果"]


def test_fit_uses_wilson_over_known_outcomes():
    rows = ([{"id": f"a{i}", "a": "a", "out": "ok"} for i in range(5)]
            + [{"id": f"b{i}", "a": "b", "out": "fail"} for i in range(5)]
            + [{"id": f"bu{i}", "a": "b", "out": None} for i in range(2)]
            + [{"id": f"c{i}", "a": "c", "out": "ok"} for i in range(3)])
    fit = {f["a"]: f for f in persona.fit(rows, ["a", "b", "c"])}
    # Wilson(5, 5): centre 0.7828, half 0.2173 → [56.6, 100]; Wilson(0, 5) mirrors it.
    assert fit["a"]["ok_est"] == 100.0 and fit["a"]["ok_ci"] == [56.6, 100.0]
    assert fit["b"]["ok_n"] == 5 and fit["b"]["ok_est"] == 0.0  # unknown outcomes excluded
    assert fit["b"]["ok_ci"][0] == 0.0 and fit["b"]["ok_ci"][1] == pytest.approx(43.4, abs=0.11)
    assert fit["c"]["ok_ci"] is None and fit["c"]["off"] is True  # n < 5


def test_evidence_hand_computed_with_projectless_bucket_and_missing_msgs():
    rows = [{"id": "r1", "d": "2026-09-01", "p": "p1", "msgs": 4, "steps": 8},
            {"id": "r2", "d": "2026-09-01", "p": None, "msgs": None, "steps": 3},
            {"id": "r3", "d": "2026-09-02", "p": None, "msgs": 6, "steps": 2}]
    aux = {"r1": {"open": 1, "turns": [[1, 1], [1, 0]]},
           "r2": {"open": 0, "turns": [[1, 0]]},
           "r3": {"open": 1, "turns": []}}
    p = {"axes": [{"k": "I", "n_units": 3, "k_units": 1}]}
    ev = persona.evidence(rows, aux, p, {"verify": 50.0}, {"p1": {"id": "p1", "name": "Alpha"}})
    # Messages known for r1, r3 only: (4+6)/2 = 5.0 per session, (8+2)/10 = 1.0 step.
    assert ev["D"]["txt"] == "每会话 5.0 条消息 · 单轮平均 1.0 步"
    assert ev["D"]["missing_n"] == 1
    assert ev["D"]["vals"] == [0, 0, 1, 1, 0, 0, 0, 0, 0, 0]  # 4 → bin 2, 6 → bin 3
    assert ev["I"]["txt"] == "结构化开场占 67%"  # (3 − 1) / 3
    # Structured openings: no-project bucket 1/2 = 50%, p1 1/1 = 100%.
    assert ev["I"]["vals"] == [50, 100] and ev["I"]["projects"][1] == "Alpha"
    # Verification turns: no-project 0/1, p1 1/2.
    assert ev["V"]["vals"] == [0, 50] and ev["V"]["txt"] == "50% 会话要求或运行了验证"
    assert ev["M"]["txt"] == "日均 1.5 个会话 · 同日 1.0 个 Agent"  # 3 rows over 2 days
    none = persona.evidence([{"id": "x", "d": "2026-09-01", "p": None, "msgs": None}], {},
                            {"axes": [{"k": "I", "n_units": 0, "k_units": 0}]}, {"verify": 0}, {})
    assert none["D"]["txt"] == "消息数未知" and none["D"]["vals"] is None


def test_blind_spots_hand_computed():
    rows = [{"fric": "方向错误"}] * 3 + [{"fric": "改动过度"}] * 3 + [{"fric": "误解需求"}] \
        + [{"fric": "工具 / 环境失败"}] * 2 + [{"fric": None}]
    spots = persona.blind_spots(rows)
    assert [(s["type"], s["n"], s["problem"]) for s in spots] == [
        ("改动过度", 3, "overreach"), ("方向错误", 3, "wrong_approach"),
        ("工具 / 环境失败", 2, "tool_env_failure")]
    assert all("rec_id" not in s and s["recs_ref"].startswith("/v1/recommendations") for s in spots)


def test_axis_sig_lists_only_computed_signals():
    for key, sig in persona.SIG_USED.items():
        a = persona.axis(SPEC[key], 10, 40, 20)
        assert a["sig"] == sig
    assert "中途改向" not in persona.SIG_USED["I"] and "子代理" not in persona.SIG_USED["M"]
