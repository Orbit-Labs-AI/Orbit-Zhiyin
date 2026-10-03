"""A1 / Lite overview payload over the synthetic store (windows, compare, filters, heat)."""

from datetime import UTC, datetime, timedelta

import pytest

from orbit_backend.uiview import derive, overview

from .synth import TODAY, analysed


def build(**params):
    base = {"range": 30, "agents": None, "project": None, "compare": False, "metric": "n",
            "edition": "advance"}
    return overview.build(analysed()[4], {**base, **params}, TODAY)


def expected(range_, f=None):
    rows = derive.prepare(analysed()[4]["rows"], TODAY)
    return derive.sel(rows, derive.win(range_, derive.first_index(rows)), f or {})


@pytest.mark.parametrize("range_", [7, 30, 90, 0])
def test_window_counts(range_):
    payload = build(range=range_)
    L = expected(range_)
    assert payload["header"]["n"] == len(L)
    tiles = {t["k"]: t for t in payload["tiles"]}
    assert tiles["n"]["value"] == len(L)
    assert tiles["m"]["value"] == sum(r["msgs"] for r in L)
    assert len(tiles["n"]["trend"]) == (7 if range_ == 7 else 12)
    assert sum(o["value"] for o in payload["outcome"]) == sum(1 for r in L if r["out"])
    assert all(o["basis"] == "estimate" for o in payload["outcome"])
    heat = payload["heat"]
    assert sum(map(sum, heat["H"])) == sum(r["msgs"] for r in L)
    assert sum(map(sum, heat["C"])) == sum(r["corr"] for r in L)
    assert sum(sum(v for v in s["values"] if v) for s in payload["trend"]["series"]) == len(L)
    if range_ == 90 or range_ == 0:
        assert payload["trend"]["bucket"] == "week"


def test_compare_previous_window():
    payload = build(range=30, compare=True)
    rows = derive.prepare(analysed()[4]["rows"], TODAY)
    prev = derive.sel(rows, derive.prev_win(30, derive.first_index(rows)))
    assert len(prev) >= 5
    tiles = {t["k"]: t for t in payload["tiles"]}
    assert tiles["n"]["delta"] == {"cur": len(expected(30)), "prev": len(prev), "unit": "pct"}
    assert tiles["f"]["delta"]["goodDown"] is True and tiles["a"]["delta"]["unit"] == "pt"
    assert {t["k"]: t["delta"] for t in build(range=30)["tiles"]}["n"] is None


def test_small_previous_window_has_no_delta():
    rows = derive.prepare(analysed()[4]["rows"], TODAY)
    first = derive.first_index(rows)
    prev = derive.prev_win(30, first)
    small = [r for r in analysed()[4]["rows"]]
    keep = {r["id"] for r in derive.sel(rows, prev)[:3]}
    cut = [r for r in small if r["id"] in keep or
           next(x for x in rows if x["id"] == r["id"])["di"] > prev[1]]
    payload = overview.build({**analysed()[4], "rows": cut},
                             {"range": 30, "compare": True, "agents": None}, TODAY)
    assert all(t["delta"] is None for t in payload["tiles"])
    assert payload["tiles"][0]["sub"] == "无可比上期"
    assert build(range=90, compare=True)["tiles"][0]["delta"] is None  # no earlier 90 days


def test_agent_filter_counts_rows_by_agent():
    payload = build(range=0, agents=["codex"])
    assert payload["header"]["n"] == 90 == sum(1 for r in analysed()[4]["rows"]
                                               if r["a"] == "codex")
    assert [s["agent"] for s in payload["trend"]["series"]] == ["codex"]
    assert build(range=0, agents=[])["header"]["n"] == 0


def test_extra_filters_and_brush():
    full = build(range=0)
    by_hour = build(range=0, hour=10)
    assert 0 < by_hour["header"]["n"] < full["header"]["n"]
    assert by_hour["meta"]["persona_scope_note"]
    assert by_hour["persona_mini"]["n"] == full["persona_mini"]["n"]  # persona ignores hour
    start = datetime.combine(TODAY - timedelta(days=6), datetime.min.time(), UTC)
    brushed = build(range=30, from_ts=int(start.timestamp() * 1000),
                    until_ts=int((start + timedelta(days=7)).timestamp() * 1000))
    assert brushed["meta"]["brushed"] and brushed["header"]["n"] == len(expected(7))
    assert all(t["delta"] is None and t["sub"] == "刷选范围" for t in brushed["tiles"])


def test_metrics_tools_insight_and_lite():
    tok = build(range=30, metric="tok")["trend"]
    L = expected(30)
    assert tok["unit"] == "million_tokens"
    total = sum(v or 0 for s in tok["series"] for v in s["values"])
    assert total == pytest.approx(sum(r["tok"] for r in L) / 1e6, rel=1e-3)
    payload = build(range=30, edition="lite")
    assert len(payload["strip"]) == 30 and payload["strip"][-1]["d"] == TODAY.isoformat()
    assert sum(d["n"] for d in payload["strip"]) == len(L)
    assert payload["completion"]["basis"] == "estimate"
    tools = payload["tools"]
    assert tools["top"] and len(tools["top"]) <= 6
    assert any(t["err"] is None for t in tools["top"])  # Codex shell status is unknown
    insight = payload["insight"]
    assert insight["basis"] == "l0_template" and insight["lede"]
    assert insight["good"]["basis"] == "estimate"
    assert payload["persona_mini"]["method"] == "uiview-persona-v1"


def test_unknown_steps_tile_shows_unknown_not_zero():
    """UT-04: a window where no row has steps shows auto as unknown (None), not 0.0."""
    body = analysed()[4]
    rows = [{**r, "steps": None, "verify": None, "out": None} for r in body["rows"]]
    payload = overview.build({**body, "rows": rows},
                             {"range": 30, "agents": None, "project": None, "compare": True,
                              "metric": "n", "edition": "lite"}, TODAY)
    tile = {t["k"]: t for t in payload["tiles"]}["a"]
    assert tile["value"] is None and tile["delta"] is None
    assert payload["completion"]["value"] is None and payload["completion"]["n"] == 0
    assert "未知" in payload["insight"]["good"]["text"]


def _with_rev(rev):
    body = analysed()[4]
    return {**body, "meta": {**(body.get("meta") or {}), "data_rev": rev}}


def test_insight_uses_matching_ai_narrative_and_names_it():
    from orbit_backend.uiview import insight as card

    calls = []
    narrative = {"job_id": "aj_1", "engine": "fake", "finished_at": 5,
                 "result": {"summary": "最近验证做得扎实", "source": "fake", "caveats": ["样本少"],
                            "findings": [{"scene": "good", "text": "多数会话跑了测试。"},
                                         {"scene": "stuck", "text": "卡在依赖安装。"}]}}

    def provider(scope, data_rev):
        calls.append((scope, data_rev))
        return narrative

    base = {"range": 30, "agents": None, "project": None, "compare": False, "metric": "n",
            "edition": "advance"}
    l0 = overview.build(_with_rev(7), base, TODAY)["insight"]
    card.set_ai_provider(provider)
    ai = overview.build(_with_rev(7), base, TODAY)["insight"]
    assert calls == [({"days": 30, "project_id": None}, 7)]
    assert ai["basis"] == "ai_narrative" and ai["lede"] == "最近验证做得扎实"
    assert ai["source"] == {"task_id": "narrate.overview", "job_id": "aj_1", "engine": "fake",
                            "finished_at": 5}
    assert ai["good"]["text"] == "多数会话跑了测试。" and ai["stuck"]["text"] == "卡在依赖安装。"
    # Counts / refs stay the L0 ones; a scene the model did not write keeps the L0 text.
    assert ai["good"]["evidence_n"] == l0["good"]["evidence_n"] and ai["next"] == l0["next"]
    # Filters a narrative cannot describe, or no published data: the provider is not asked.
    calls.clear()
    assert overview.build(_with_rev(7), {**base, "topic": "bugfix"}, TODAY)["insight"]["basis"] \
        == "l0_template"
    assert overview.build(_with_rev(None), base, TODAY)["insight"]["basis"] == "l0_template"
    assert calls == []
    card.set_ai_provider(lambda scope, data_rev: None)
    assert overview.build(_with_rev(7), base, TODAY)["insight"] == l0


def test_insight_names_the_scope_regenerate_posts():
    """``ai_scope`` is the narrate.overview scope this card reads back (the page's 「重新生成」
    posts it verbatim). Agent subsets, the project and 「全部」 each get their own scope; only
    filters the narrative cannot take (topic / outcome / friction / hour / brush) have none."""
    from orbit_backend.uiview import insight as card

    seen = []
    card.set_ai_provider(lambda scope, data_rev: seen.append(scope))
    base = {"range": 7, "agents": None, "project": None, "compare": False, "metric": "n",
            "edition": "advance"}
    assert overview.build(_with_rev(3), base, TODAY)["insight"]["ai_scope"] == \
        {"days": 7, "project_id": None}
    everything = overview.build(_with_rev(3), {**base, "range": 0}, TODAY)
    rows = derive.prepare(analysed()[4]["rows"], TODAY)
    first = TODAY + timedelta(days=min(derive.first_index(rows), 0))
    start = int(datetime(first.year, first.month, first.day, tzinfo=UTC).timestamp() * 1000)
    assert everything["insight"]["ai_scope"] == {"start_ms": start, "project_id": None}
    # Stable across rebuilds (the read-back must find the job it posted).
    assert overview.build(_with_rev(3), {**base, "range": 0}, TODAY)["insight"]["ai_scope"] == \
        everything["insight"]["ai_scope"]
    assert overview.build(_with_rev(3), {**base, "agents": ["codex", "claude_code"]},
                          TODAY)["insight"]["ai_scope"] == \
        {"days": 7, "project_id": None, "agent_ids": ["claude_code", "codex"]}
    assert overview.build(_with_rev(3), {**base, "project": "p1"}, TODAY)["insight"]["ai_scope"] == \
        {"days": 7, "project_id": "p1"}
    assert overview.build(_with_rev(3), {**base, "agents": []}, TODAY)["insight"]["ai_scope"] is None
    assert overview.build(_with_rev(3), {**base, "topic": "bugfix"}, TODAY)["insight"]["ai_scope"] \
        is None
    assert {"days": 7, "project_id": None, "agent_ids": ["claude_code", "codex"]} in seen
    card.set_ai_provider(None)