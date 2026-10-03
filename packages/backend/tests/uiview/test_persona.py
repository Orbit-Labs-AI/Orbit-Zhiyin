"""Deterministic four-axis persona: Wilson bounds, gates, periods and reveal."""

import copy
import json
import re
from datetime import date
from pathlib import Path

import pytest

from orbit_backend.uiview import derive, insight, overview, persona
from orbit_backend.uiview import persona_signals as sig
from orbit_backend.uiview.typecopy import AXES, BUILTIN, TYPES

from .synth import TODAY, analysed

SPEC = {a["k"]: a for a in AXES}


def test_wilson_hand_computed():
    lo, hi = persona.wilson(31, 84)
    # p = 31/84, z = 1.96: centre 0.374775, half-width 0.101075
    assert lo == pytest.approx(0.2737, abs=5e-4) and hi == pytest.approx(0.4758, abs=5e-4)
    assert persona.wilson(0, 0) == (0.0, 1.0)


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
    assert len(TYPES) == 16 and TYPES["SPFV"][0] == "分析学家"


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
            {"id": "r3", "d": "2026-09-02", "p": None, "msgs": 6, "steps": 2},
            {"id": "r4", "d": "2026-09-02", "p": None, "msgs": 10, "steps": None}]
    aux = {"r1": {"open": 1, "turns": [[1, 1], [1, 0]]},
           "r2": {"open": 0, "turns": [[1, 0]]},
           "r3": {"open": 1, "turns": []}}
    p = {"axes": [{"k": "I", "n_units": 3, "k_units": 1}]}
    ev = persona.evidence(rows, aux, p, {"verify": 50.0, "verify_n": 2},
                          {"p1": {"id": "p1", "name": "Alpha"}})
    # Messages known for r1, r3, r4: (4+6+10)/3 = 6.7 per session. Steps per message only
    # over rows with both known (r1, r3): (8+2)/(4+6) = 1.0 — r4's 10 messages without
    # steps must not dilute it to 10/20 = 0.5.
    assert ev["D"]["txt"] == "每会话 6.7 条消息 · 单轮平均 1.0 步"
    assert ev["D"]["missing_n"] == 1 and ev["D"]["auto_n"] == 2
    assert ev["V"]["verify_n"] == 2
    assert ev["D"]["vals"] == [0, 0, 1, 1, 0, 1, 0, 0, 0, 0]  # 4 → bin 2, 6 → 3, 10 → 5
    assert ev["I"]["txt"] == "结构化开场占 67%"  # (3 − 1) / 3
    # Structured openings: no-project bucket 1/2 = 50%, p1 1/1 = 100%.
    assert ev["I"]["vals"] == [50, 100] and ev["I"]["projects"][1] == "Alpha"
    # Verification turns: no-project 0/1, p1 1/2.
    assert ev["V"]["vals"] == [0, 50] and ev["V"]["txt"] == "50% 会话要求或运行了验证"
    assert ev["M"]["txt"] == "日均 2.0 个会话 · 同日 1.0 个 Agent"  # 4 rows over 2 days
    none = persona.evidence([{"id": "x", "d": "2026-09-01", "p": None, "msgs": None}], {},
                            {"axes": [{"k": "I", "n_units": 0, "k_units": 0}]},
                            derive.stats([{"id": "x"}], unknown=None), {})
    assert none["D"]["txt"] == "消息数未知" and none["D"]["vals"] is None
    # No row with a known verify flag: unknown, not "0%".
    assert none["V"]["txt"] == "验证情况未知" and none["V"]["verify_n"] == 0


def test_fit_without_known_outcomes_is_unknown():
    fit = persona.fit([{"id": "u1", "a": "a", "out": None}], ["a"])[0]
    assert fit["ok_est"] is None and fit["ok_n"] == 0 and fit["ok_ci"] is None


def test_blind_spots_hand_computed():
    rows = [{"fric": "方向错误"}] * 3 + [{"fric": "改动过度"}] * 3 + [{"fric": "误解需求"}] \
        + [{"fric": "工具 / 环境失败"}] * 2 + [{"fric": None}]
    spots = persona.blind_spots(rows)
    assert [(s["type"], s["n"], s["problem"]) for s in spots] == [
        ("改动过度", 3, "overreach"), ("方向错误", 3, "wrong_approach"),
        ("工具 / 环境失败", 2, "tool_env_failure")]
    assert all("rec_id" not in s and s["recs_ref"].startswith("/v1/recommendations") for s in spots)


# -- composite axes (uiview-persona-v1) -----------------------------------------------------
def _stats(**ratio) -> dict:
    """Sufficient statistics with the given ratio signals as per-session (k, n) clusters."""
    s = sig.empty()
    s["n"] = 1
    for key, clusters in ratio.items():
        for k, n in clusters:
            sig._add_ratio(s["ratio"][key], k, n)
    return s


def _turn_share(k: int, n: int) -> list[tuple[int, int]]:
    return [(1, 1)] * k + [(0, 1)] * (n - k)


def test_axis_letters_and_gates():
    settled = persona.axis(SPEC["D"], _stats(steps=_turn_share(80, 100)))
    # only the steps signal: score = 5 + 90·0.8 = 77
    assert settled["value"] == 77.0 and settled["letter"] == "D" and settled["state"] == "settled"
    assert settled["strong"] == 77 and [x["key"] for x in settled["signals"]] == ["steps"]
    assert persona.axis(SPEC["V"], _stats(verify=_turn_share(10, 100)))["letter"] == "T"
    # No undetermined band: exactly 50 takes the high letter, just below takes the low one.
    assert persona.axis(SPEC["I"], _stats(struct=_turn_share(50, 100)))["letter"] == "I"
    assert persona.axis(SPEC["I"], _stats(struct=_turn_share(49, 100)))["letter"] == "P"
    assert persona.axis(SPEC["D"], _stats(steps=_turn_share(3, 4)))["letter"] == "D"
    empty = persona.axis(SPEC["M"], sig.empty())
    assert empty["letter"] == "M" and empty["state"] == "no_data" and empty["value"] is None
    assert empty["sig"] == "暂无可用信号"


def test_suff_hand_computed():
    rows, aux = _hand_rows()
    s = sig.suff(rows, aux)
    # D steps: s1 (1,2), s2 (1,1), s3 (1,2), s6 (0,1) → 3 of 6 turns over 4 sessions.
    assert s["ratio"]["steps"][:3] == [3, 6, 4]
    # V: s1 (1,2), s2 (0,1), s3 (2,2), s6 (0,1) → 3 of 6.
    assert s["ratio"]["verify"][:3] == [3, 6, 4]
    # I struct (old snapshots: ``open`` stands in): openings 1,0,0,1,0 → 3 unstructured of 5.
    assert s["ratio"]["struct"][:3] == [3, 5, 5]
    # per day [sessions, agents, overlap]: day 1 overlaps, day 3 has two agents.
    assert s["days"] == {"2026-09-01": [2, 1, 1], "2026-09-02": [2, 1, 0],
                         "2026-09-03": [2, 2, 0]}
    assert sig._with_days(s)["parallel"][:2] == [2, 3]


def test_cluster_interval_is_used_by_ratio_signals_and_duplicates_do_not_narrow():
    a = sig.signal("steps", _stats(steps=[(6, 6)] * 15 + [(0, 6)] * 15)["ratio"]["steps"])
    b = sig.signal("steps", _stats(steps=[(12, 12)] * 15 + [(0, 12)] * 15)["ratio"]["steps"])
    assert (a["lo"], a["hi"], a["n_eff"]) == (b["lo"], b["hi"], b["n_eff"]) and a["n_eff"] == 29.0
    lo, hi, _ = persona.cluster_interval([(6, 6)] * 15 + [(0, 6)] * 15)
    assert a["lo"] == pytest.approx(5 + 90 * lo) and a["hi"] == pytest.approx(5 + 90 * hi)


def test_decided_marks_intervals_clear_of_the_band():
    a = persona.axis(SPEC["D"], _stats(steps=_turn_share(80, 100)))
    b = persona.axis(SPEC["D"], _stats(steps=_turn_share(52, 100)))
    c = persona.axis(SPEC["V"], _stats(verify=_turn_share(10, 100)))
    assert a["decided"] and a["letter"] == "D"
    assert not b["decided"] and b["letter"] == "D"
    assert c["decided"] and c["letter"] == "T"
    assert not persona.axis(SPEC["M"], sig.empty())["decided"]
    rows = [{"id": f"s{i}", "d": "2026-09-01", "a": "codex"} for i in range(120)]
    p = persona.persona(rows, {})
    assert p["ok"] and "?" not in p["code"] and p["conf"] == "高"  # n ≥ 100, signals agree
    assert p["decided_axes"] == sum(1 for x in p["axes"] if x["decided"])
    m = persona.mini(p)
    assert set(m) >= {"ok", "code", "zh", "en", "conf", "n", "hint", "method", "axes",
                      "decided_axes"}
    assert m["decided_axes"] == p["decided_axes"] and len(m["axes"]) == 4


def test_axis_signals_cover_the_method_copy():
    # Every signal the 「如何计算」 copy names is computed (no aspirational signals left).
    assert "中途改向" in persona.SIG_USED["I"] and "子代理" in persona.SIG_USED["M"]
    assert "打断" in persona.SIG_USED["D"] and "回滚" in persona.SIG_USED["V"]
    for k in "DIMV":
        weights = [s[2] for s in sig.BY_AXIS[k]]
        assert len(weights) >= 2 and sum(weights) == pytest.approx(1.0)


def test_anchors_are_bounded_and_monotone():
    for key, _, _, _, _, anchors, _ in sig.SIGNALS:
        xs = [a[0] for a in anchors]
        ys = [a[1] for a in anchors]
        assert xs == sorted(xs) and all(5 <= y <= 95 for y in ys), key
        assert ys == sorted(ys) or ys == sorted(ys, reverse=True), key
    assert sig.pl(-5, ((0, 10), (1, 90))) == 10 and sig.pl(9, ((0, 10), (1, 90))) == 90
    assert sig.pl(0.25, ((0, 10), (1, 90))) == 30


def _one(**unit) -> dict:
    row = {"id": "x", "d": "2026-09-01", "a": "codex", "msgs": unit.pop("msgs", None),
           "corr": unit.pop("corr", None)}
    return persona.persona([row], {"x": unit})


def test_each_signal_moves_its_axis():
    v = lambda p, k: next(a for a in p["axes"] if a["k"] == k)["value"]  # noqa: E731
    # D: fewer messages per session and fewer interruptions read more delegated.
    few, many = _one(msgs=2), _one(msgs=40)
    assert v(few, "D") > 50 > v(many, "D")
    calm = _one(turns=[[1, 0, 0, 0, 0, 1]] * 4)
    stopped = _one(turns=[[1, 0, 0, 0, 1, 1]] * 4)
    assert v(calm, "D") > v(stopped, "D")
    # I: a spec reference, a long opening and no redirection read planned; redirection improvised.
    plan = _one(oacc=1, ospec=1, olen=900, msgs=10, corr=0)
    impro = _one(oacc=0, ospec=0, olen=15, msgs=10, corr=4)
    assert v(plan, "I") < 50 < v(impro, "I")
    # M: parallel sub-agents push towards multi-thread.
    assert v(_one(sub=3), "M") > v(_one(sub=0), "M")
    # V: rollback / redo evidence pushes towards verification.
    assert v(_one(rb=1), "V") > 50 > v(_one(rb=0), "V")


def test_missing_signals_renormalise():
    # Only the length signal on I: the value is that score alone, not diluted by absent ones.
    p = _one(olen=80)
    ax = next(a for a in p["axes"] if a["k"] == "I")
    assert [x["key"] for x in ax["signals"]] == ["length"] and ax["value"] == 62.0


def test_conf_drops_when_signals_disagree():
    rows = [{"id": f"s{i}", "d": f"2026-09-{1 + i % 28:02d}", "a": "codex", "msgs": 40,
             "corr": 0} for i in range(120)]
    # Long delegated turns but long, interrupted sessions; unstructured but spec-led openings;
    # no checks but rollbacks: every axis's signals pull both ways.
    aux = {r["id"]: {"turns": [[9, 0, 0, 0, 1, 1]], "oacc": 0, "ospec": 1, "olen": 1200,
                     "rb": 1}
           for r in rows}
    p = persona.persona(rows, aux)
    assert p["consistency"] is not None and p["consistency"] < persona.CONFIG["consistency"]
    assert p["conf"] == "中"  # n ≥ 100 would be 高
    assert persona.confidence(120, 0.9) == "高" and persona.confidence(5, 0.1) == "低"


# -- agent subsets from per-agent statistics (F14) --------------------------------------------
def test_any_agent_subset_equals_direct_computation():
    body = analysed()[4]
    rows = derive.prepare(body["rows"], TODAY)
    aux = body["aux"]
    window = derive.win(0, derive.first_index(rows))
    scope = derive.sel(rows, window, {}, no_extra=True)
    blocks = sig.by_agent(scope, aux)
    agents = sorted(a for a in blocks if a)
    assert len(agents) >= 2
    for subset in ([agents[0]], [agents[1]], agents):
        direct = persona.persona([r for r in scope if r.get("a") in subset], aux)
        merged = persona.persona_for_agents(blocks, set(subset))
        assert merged["code"] == direct["code"] and merged["n"] == direct["n"]
        for x, y in zip(merged["axes"], direct["axes"], strict=True):
            assert x["value"] == pytest.approx(y["value"], abs=1e-9)
            assert (x["lo"], x["hi"]) == (y["lo"], y["hi"])
    # The page answers a subset the same way.
    pg = persona.page(body, {"period": "all", "agents": [agents[0]]}, TODAY)
    direct = persona.persona([r for r in scope if r.get("a") == agents[0]], aux)
    assert pg["code"] == direct["code"] and pg["v"] == direct["v"]


def test_combine_is_exact_for_shared_days_across_agents():
    rows, aux = _hand_rows()
    whole = sig.suff(rows, aux)
    merged = sig.combine(sig.by_agent(rows, aux).values())
    assert merged == whole



def test_v_counts_only_turns_where_the_user_asked_for_verification():
    """V = how *you* make sure it is right: a test the agent ran on its own does not count."""
    from orbit_backend.uiview import facts
    # [steps, verify, requested, ran, stopped, known]
    turns = [[6, 1, 1, 0, 0, 1], [6, 1, 0, 1, 0, 1], [6, 1, 1, 1, 0, 1], [2, 0, 0, 0, 0, 1]]
    assert sig.requested_turns(turns) == 2
    assert facts.aux_units({"turns": turns})["vk"] == 2
    # Snapshots from before the split ([steps, verify]) fall back to ``verify``.
    assert sig.requested_turns([[6, 1], [2, 0], [3, 1]]) == 2
    asked = persona.persona([{"id": "s", "d": "2026-09-01", "a": "codex"}],
                            {"s": {"turns": [[3, 1, 1, 0, 0, 1]] * 4}})
    agent_only = persona.persona([{"id": "s", "d": "2026-09-01", "a": "codex"}],
                                 {"s": {"turns": [[3, 1, 0, 1, 0, 1]] * 4}})
    assert asked["code"][3] == "V" and agent_only["code"][3] == "T"
