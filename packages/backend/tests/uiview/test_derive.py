"""``derive`` = ``15-derive.js`` formulas, checked against hand-computed values."""

from datetime import date

import pytest

from tandem_backend.uiview import derive

TODAY = date(2026, 10, 1)  # a Thursday


def row(i, d, a="codex", p="p1", h=10, dur=30.0, msgs=4, tools=10, steps=12, corr=0,
        errors=None, tok=None, out="ok", verify=True, fric=None, topic="git"):
    return {"id": f"s{i}", "d": d, "h": h, "mi": 0, "a": a, "p": p, "dur": dur, "msgs": msgs,
            "tools": tools, "steps": steps, "corr": corr, "errors": errors, "tok": tok,
            "out": out, "verify": verify, "fric": fric, "topic": topic, "live": False,
            "excluded": False}


ROWS = [
    row(1, "2026-10-01", dur=60, msgs=10, tools=20, steps=30, corr=2, errors=4, tok=1000,
        out="part", fric="方向错误"),
    row(2, "2026-09-30", a="claude_code", dur=30, msgs=5, tools=10, steps=10, corr=0, errors=0,
        tok=None, verify=False),
    row(3, "2026-09-28", dur=90, msgs=5, tools=0, steps=0, corr=1, out="fail", h=23),
    row(4, "2026-07-01", dur=15, msgs=2, tools=2, steps=4),
]


def test_stats_match_hand_computation():
    st = derive.stats(derive.prepare(ROWS[:3], TODAY))
    assert st["n"] == 3
    assert st["hours"] == pytest.approx(180 / 60)
    assert st["msgs"] == 20 and st["tools"] == 30 and st["corr"] == 3
    assert st["per"] == pytest.approx(20 / 3)
    assert st["auto"] == pytest.approx(40 / 20)  # steps / msgs (prototype: tools·1.54 / msgs)
    assert st["fric"] == pytest.approx(3 / 20 * 100)
    assert st["verify"] == pytest.approx(2 / 3 * 100)
    assert st["ok"] == pytest.approx(1 / 3 * 100)
    assert st["tok"] == 1000
    assert st["errors"] == 4 and st["err"] == pytest.approx(4 / 30 * 100)


def test_unknown_errors_and_tokens_stay_null():
    st = derive.stats(derive.prepare([ROWS[2]], TODAY))
    assert st["errors"] is None and st["err"] is None and st["tok"] is None
    empty = derive.stats([])
    assert empty["n"] == 0 and empty["auto"] == 0 and empty["fric"] == 0


def test_windows_follow_the_prototype():
    assert derive.win(7) == (-6, 0) and derive.win(30) == (-29, 0)
    assert derive.win(0, -120) == (-120, 0)
    assert derive.prev_win(30, -120) == (-59, -30)
    assert derive.prev_win(90, -120) is None  # would start before the first data day
    assert derive.prev_win(0, -120) is None


def test_selection_filters():
    rows = derive.prepare(ROWS, TODAY)
    w = derive.win(30)
    assert [r["id"] for r in derive.sel(rows, w)] == ["s1", "s2", "s3"]
    assert [r["id"] for r in derive.sel(rows, w, {"agents": ["claude_code"]})] == ["s2"]
    assert [r["id"] for r in derive.sel(rows, w, {"outcome": "fail"})] == ["s3"]
    assert len(derive.sel(rows, w, {"outcome": "fail"}, no_extra=True)) == 3
    assert [r["id"] for r in derive.sel(rows, w, {"hour": 23})] == ["s3"]


def test_heat_buckets_and_series():
    rows = derive.sel(derive.prepare(ROWS, TODAY), derive.win(30))
    hm = derive.heat(rows)
    assert sum(map(sum, hm["H"])) == 20 and sum(map(sum, hm["C"])) == 3
    assert hm["H"][3][10] == 10 and hm["peak"] == [3, 10]  # Thursday 10:00
    bks = derive.buckets(derive.win(90), TODAY)
    assert bks[0]["a"] == -89 and bks[-1]["b"] == 0
    assert all((TODAY.toordinal() + b["b"]) % 7 == 0 or b["b"] == 0 for b in bks)  # ends Sun
    ser = derive.series(rows, derive.win(7), "n", ["codex", "claude_code"], TODAY)
    assert len(ser) == 7 and ser[-1]["v"] == [1, 0] and ser[-2]["v"] == [0, 1]
    tok = derive.series(rows, derive.win(7), "tok", ["codex", "claude_code"], TODAY)
    assert tok[-1]["v"][0] == pytest.approx(0.001) and tok[-2]["v"][1] is None


def test_outcome_mix_and_tool_rows():
    rows = derive.prepare(ROWS[:3], TODAY)
    mix = {m["id"]: m["value"] for m in derive.outcome_mix(rows)}
    assert mix == {"ok": 1, "part": 1, "fail": 1}
    aux = {"s1": {"tools": {"shell": ["shell", 10, 2, 10], "edit": ["file.edit", 4, 0, 0]}},
           "s2": {"tools": {"shell": ["shell", 5, 1, 5]}}}
    tools = derive.tool_rows(rows, aux)
    assert tools[0] == {"name": "shell", "kind": "shell", "n": 15, "fails": 3,
                        "err": pytest.approx(0.2), "known": 15}
    assert tools[1]["err"] is None and tools[1]["fails"] is None


def test_ratios_only_use_rows_with_known_inputs():
    """UT-04: steps / verify / out = None are unknown, not zero, in their denominators."""
    rows = [row(1, "2026-10-01", msgs=10, steps=50, verify=True, out="ok"),
            row(2, "2026-10-01", msgs=10, steps=None, verify=None, out=None)]
    st = derive.stats(rows)
    assert st["auto"] == 5.0 and st["auto_n"] == 1  # 50 steps / 10 msgs of the stepped row
    assert st["verify"] == 100.0 and st["verify_n"] == 1
    assert st["ok"] == 100.0 and st["ok_n"] == 1
    assert st["msgs"] == 20 and st["per"] == 10.0  # totals still count every row


def test_mixed_known_rows_share():
    rows = [row(1, "2026-10-01", verify=True, out="ok"),
            row(2, "2026-10-01", verify=False, out="part"),
            row(3, "2026-10-01", verify=None, out="fail"),
            row(4, "2026-10-01", verify=None, out=None)]
    st = derive.stats(rows)
    assert st["verify"] == pytest.approx(50.0) and st["verify_n"] == 2  # 1 of 2 known
    assert st["ok"] == pytest.approx(100 / 3) and st["ok_n"] == 3  # 1 of 3 known


def test_all_unknown_ratios():
    rows = [row(1, "2026-10-01", steps=None, verify=None, out=None)]
    assert derive.stats(rows)["auto"] == 0  # numeric contract for legacy callers
    st = derive.stats(rows, unknown=None)
    assert (st["auto"], st["verify"], st["ok"]) == (None, None, None)
    assert (st["auto_n"], st["verify_n"], st["ok_n"]) == (0, 0, 0)
