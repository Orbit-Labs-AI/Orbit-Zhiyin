"""Persona reveal over real ``uiview.persona.page`` payloads from hand-built fact rows."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from orbit_backend.shell import reveal
from orbit_backend.uiview import persona

TODAY = date(2026, 9, 30)
OVERVIEW = {"overview": {"counts": {"main_sessions": 120},
                         "activity_rhythm": {"active_days": 14, "sessions": {
                             "by_hour": {"9": 5, "14": 9},
                             "by_weekday_hour": {"1:9": 5, "3:14": 9}}}},
            "effective_samples": {"tools": 900}}


def facts_body(today: date = TODAY) -> dict:
    """Three sessions over two days (one agent); old snapshot shape (``open`` only, turns
    without status), so each axis has the signals listed below (uiview-persona-v1).

    D: steps — turns with ≥ 5 steps: s1 6, 7; s2 5; s3 1 → 3 of 4 → 5 + 90·0.75 = 72.5 → D.
    I: struct — openings without structure: s1, s3 of 3 → 5 + 90·⅔ = 65.0 → I.
    M: parallel — day 1 overlaps, day 2 does not → 1 of 2 → 50; sessions per day 2, 1 →
       (40 + 20) / 2 = 30; agents per day 1, 1 → 30. (0.35·50 + 0.25·30 + 0.25·30) / 0.85
       = 38.2 → F.
    V: verify — only s3's turn → 1 of 4 → 5 + 90·0.25 = 27.5 → T.
    """
    d1, d2 = (today - timedelta(days=1)).isoformat(), today.isoformat()
    rows = [{"id": "s1", "d": d1, "a": "codex", "p": None, "h": 9},
            {"id": "s2", "d": d1, "a": "codex", "p": None, "h": 10},
            {"id": "s3", "d": d2, "a": "codex", "p": None, "h": 14}]
    aux = {"s1": {"turns": [[6, 0], [7, 0]], "open": 0, "t0": 0, "t1": 10},
           "s2": {"turns": [[5, 0]], "open": 1, "t0": 5, "t1": 15},
           "s3": {"turns": [[1, 1]], "open": 0, "t0": 0, "t1": 5}}
    return {"meta": {}, "rows": rows, "aux": aux,
            "agents": [{"id": "codex", "short": "Codex"}], "projects": []}


def page(period: str = "30") -> dict:
    return persona.page(facts_body(), {"period": period}, TODAY)


def test_axes_come_from_the_persona_page():
    p = page()
    axes = {a["axis"]: a for a in reveal.ui_axes(p)}
    assert {k: a["value"] for k, a in axes.items()} == {"D": 72.5, "I": 65.0, "M": 38.2,
                                                         "V": 45.0}
    assert reveal.code_of(reveal.ui_axes(p)) == p["code"] == "DIFT"
    assert [axes[k]["name"] for k in "DIMV"] == ["委托", "即兴", "专注", "信任"]
    # The reveal keeps the page's interval verbatim (no recomputation).
    by_k = {a["k"]: a for a in p["axes"]}
    for k in "DIMV":
        assert (axes[k]["lo"], axes[k]["hi"]) == (by_k[k]["lo"], by_k[k]["hi"])
        assert axes[k]["lo"] <= axes[k]["value"] <= axes[k]["hi"]
    assert all(a["settled"] for a in axes.values())


def test_compose_one_session_gives_a_full_code():
    one = persona.page({**facts_body(), "rows": facts_body()["rows"][2:]}, {"period": "30"},
                       TODAY)
    body = reveal.compose(one, OVERVIEW)
    # s3 alone: D 0/1 → 5 → S, I 1/1 → 95 → I, M one session / agent on its day → F,
    # V 1/1 → 95 → V.
    assert body["ok"] and body["code"] == "SIFV" and body["share"]["allowed"]
    assert body["gate"]["passed"] and body["gate"]["sessions"] == 1


def test_matches_follow_persona_candidates():
    rows = reveal.matches(page())
    # match = mean of (v if high letter else 100 − v):
    # V: 1 of 4 turns asked for verification → 45 (anchor 5% → 25, 30% → 50).
    # DIFT (72.5 + 65 + 61.8 + 55) / 4 = 63.6, DIFV (72.5 + 65 + 61.8 + 45) / 4 = 61.1.
    assert [r["code"] for r in rows[:2]] == ["DIFT", "DIFV"]
    assert rows[0]["match"] == pytest.approx(63.575, abs=0.06)
    assert rows[1]["match"] == pytest.approx(61.075, abs=0.06)
    assert rows[0]["similarity"] == round(rows[0]["match"] / 100, 3)
    assert reveal.matches(None) == []


def test_reasons():
    none = reveal.compose(None, None)
    assert none["ok"] is False and none["reason"] == "persona_unavailable"
    assert none["matches"] == [] and none["code"] is None
    empty = persona.page({**facts_body(), "rows": []}, {"period": "30"}, TODAY)
    low = reveal.compose(empty, OVERVIEW)
    assert low["reason"] == "insufficient_data" and not low["gate"]["passed"]
    # Four axes without a value block it (main rule) even when the page says ok.
    blank = page()
    blank["axes"] = [{**a, "value": None, "state": "no_data"} for a in blank["axes"]]
    assert reveal.compose(blank, OVERVIEW)["reason"] == "insufficient_data"
    ok = reveal.compose(page(), OVERVIEW, meta={"scope_hash": "h"})
    assert ok["ok"] and ok["reason"] is None and ok["code"] == "DIFT"
    assert ok["type"]["code"] == "DIFT" and ok["type"]["zh"] == page()["zh"]
    assert ok["gate"]["axes"] == [{"axis": k, "n_units": n, "state": "settled"}
                                  for k, n in zip("DIMV", (4, 3, 2, 4), strict=True)]


def test_fingerprint_facts_and_method():
    ok = reveal.compose(page(), OVERVIEW, span=(1, 2),
                        extra={"agent_hours": {"claude_code": 3.0, "codex": 1.0},
                               "top_error_class": {"class": "test_failure", "n": 7},
                               "verification_share": 0.25})
    fp = ok["fingerprint"]
    assert len(fp["by_hour"]) == 24 and fp["by_hour"][14] == 9 and fp["sessions"] == 120
    assert fp["by_weekday_hour"][0][9] == 5 and fp["by_weekday_hour"][2][14] == 9
    assert (fp["first_ts"], fp["last_ts"]) == (1, 2)
    facts = {f["stage"]: f for f in ok["facts"]}
    assert facts["agents"]["value"] == "claude_code 75% · codex 25%"
    assert facts["friction"]["value"] == "test_failure" and facts["verification"]["value"] == 0.25
    method = ok["method"]
    assert method["rules_version"] == persona.METHOD
    assert method["thresholds"]["midpoint"] == 50 and method["thresholds"]["min_sessions"] == 1
    assert [a["axis"] for a in method["axes"]] == list("DIMV")
    blank = {f["stage"]: f for f in reveal.compose(None, None)["facts"]}
    assert blank["sessions"]["value"] is None and blank["verification"]["value"] is None


def test_endpoint_without_data(gateway_factory):
    client, _ = gateway_factory()
    body = client.get("/v1/shell/reveal").json()
    assert body["ok"] is False and body["reason"] == "insufficient_data"
    assert body["matches"] == [] and body["method"]["thresholds"]["midpoint"] == 50
    assert body["meta"]["scope_hash"]


def test_load_reads_the_facts_snapshot(gateway_factory, tmp_path, monkeypatch):
    """Missing facts → computing + one submit; cached facts → the persona page's code."""
    from types import SimpleNamespace

    from realtime_fixtures import NOW, Orbit

    from orbit_backend.exporting import sharecard
    from orbit_backend.services.sections import rules_digest
    from orbit_backend.services.snapshots import SnapshotKey, scope_hash
    from orbit_backend.shell import default_scope
    from orbit_backend.uiview import overview

    home = tmp_path / "orbit"
    home.mkdir()
    t = Orbit(home)
    t.session("a", status="completed", started=NOW - 3_600_000, ended=NOW - 1_800_000)
    t.db.close()
    _, gw = gateway_factory(home=home, started=False)
    gw.revisions.update(data_rev=7, inventory_rev=0)
    submitted = []

    def submit(name, *args):
        submitted.append(name)
        return SimpleNamespace(id=f"job-{name}", status="queued")

    gw.supervisor.analysis.submit = submit
    scope = default_scope(gw, 30)
    first = reveal.load(gw, scope)
    assert first["reason"] == "computing" and first["ok"] is False
    assert sorted(submitted) == ["overview", "uiview_facts"]
    assert reveal.persona_summary(gw, scope)["reason"] == "computing"
    facts_scope, params, _ = sharecard.persona_request(scope)
    assert params["period"] == "30"
    rules = rules_digest()
    body = facts_body(overview.today_in(scope.get("display_timezone")))
    gw.snapshots.put(SnapshotKey("uiview_facts", scope_hash(facts_scope, {}), 7, 0, rules), body)
    gw.snapshots.put(SnapshotKey("overview", scope_hash(scope, {}), 7, 0, rules), OVERVIEW)
    out = reveal.load(gw, scope)
    assert out["ok"] and out["code"] == "DIFT" and out["meta"]["freshness"] == "fresh"
    assert out["fingerprint"]["first_ts"] == NOW - 3_600_000
    summary = reveal.persona_summary(gw, scope)
    assert summary == {"ok": True, "code": "DIFT", "name_zh": out["type"]["zh"],
                       "reason": None, "gate": out["gate"]}
