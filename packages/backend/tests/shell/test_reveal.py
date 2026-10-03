"""Persona reveal over hand-written profiles (no logs): axis mapping, matches, reasons."""

from __future__ import annotations

from tandem_backend.shell import reveal

TYPES = {"DPMV": ("总设计师", "The Architect", "先写清规格。"),
         "DIMV": ("指挥家", "The Conductor", "多线并进。")}
OVERVIEW = {"overview": {"counts": {"main_sessions": 120},
                         "activity_rhythm": {"active_days": 14, "sessions": {
                             "by_hour": {"9": 5, "14": 9},
                             "by_weekday_hour": {"1:9": 5, "3:14": 9}}}},
            "effective_samples": {"tools": 900}}


def axis(score, n, direction=None):
    return {"observed_score": score, "effective_task_n": n, "direction": direction}


def profile(d=(0.9, 40, "D"), p=(0.8, 40, "P"), o=(0.85, 40, "O"), v=(0.9, 40, "V")):
    return {"method_version": "collaboration-profile-v1",
            "axes": {"delegation": axis(*d), "planning": axis(*p),
                     "orchestration": axis(*o), "verification": axis(*v)}}


def test_axis_mapping_and_bands():
    axes = {a["axis"]: a for a in reveal.ui_axes(profile())}
    assert axes["D"]["value"] == 90.0 and axes["D"]["letter"] == "D" and axes["D"]["settled"]
    # planning is inverted: 规划 0.8 → I axis 20 → letter P.
    assert axes["I"]["value"] == 20.0 and axes["I"]["letter"] == "P" and axes["I"]["settled"]
    assert axes["I"]["lo"] <= 20.0 <= axes["I"]["hi"]
    assert axes["M"]["letter"] == "M" and axes["V"]["letter"] == "V"
    # No undetermined band: exactly 50 takes the high letter.
    mid = {a["axis"]: a for a in reveal.ui_axes(profile(d=(0.5, 40, None)))}
    assert mid["D"]["letter"] == "D" and mid["D"]["settled"] and mid["D"]["strong"] == 50
    lean = {a["axis"]: a for a in reveal.ui_axes(profile(d=(0.49, 40, None)))}
    assert lean["D"]["letter"] == "S"
    empty = {a["axis"]: a for a in reveal.ui_axes(profile(o=(None, 0, None)))}
    assert empty["M"]["value"] is None and empty["M"]["lo"] is None
    assert empty["M"]["letter"] == "M" and not empty["M"]["settled"]
    # Below the profile's own minimum: single-pole axes fall back to signal_rate.
    small = profile(v=(None, 1, None))
    small["axes"]["verification"].update(signal_rate=0.25, observable_task_n=4)
    assert {a["axis"]: a for a in reveal.ui_axes(small)}["V"]["letter"] == "T"


def test_matches_sorted_with_winner_first():
    axes = reveal.ui_axes(profile())
    rows = reveal.matches(axes, "DPMV", TYPES)
    assert len(rows) == 6 and rows[0]["code"] == "DPMV" and rows[0]["zh"] == "总设计师"
    sims = [r["similarity"] for r in rows]
    assert sims == sorted(sims, reverse=True)
    # D=90, I=20, M=85, V=90 → distance to DPMV = (10+20+15+10)/4.
    assert rows[0]["similarity"] == round(1 - 13.75 / 100, 3)
    assert rows[1]["code"] in {"SPMV", "DIMV", "DPFV", "DPMT"}
    # An unsettled code does not reorder: pure similarity ranking.
    loose = reveal.matches(reveal.ui_axes(profile(p=(0.5, 40, None))), "D?MV", TYPES)
    assert loose[0]["similarity"] >= loose[1]["similarity"]
    assert reveal.matches(reveal.ui_axes({"axes": {}}), None, TYPES) == []


def test_reasons():
    none = reveal.compose(None, None, types=TYPES)
    assert none["ok"] is False and none["reason"] == "persona_unavailable"
    assert none["matches"] == [] and none["code"] is None
    blank = {k: (None, 0, None) for k in ("d", "p", "o", "v")}
    low = reveal.compose(profile(**blank), OVERVIEW, types=TYPES)
    assert low["reason"] == "insufficient_data" and not low["gate"]["passed"]
    small = reveal.compose(profile(v=(0.9, 1, "V")),
                           {"overview": {"activity_rhythm": {"active_days": 1}}}, types=TYPES)
    assert small["ok"] and small["code"] == "DPMV" and small["share"]["allowed"]
    no_direction = reveal.compose(profile(p=(0.8, 40, None)), OVERVIEW, types=TYPES)
    assert no_direction["ok"] and no_direction["code"] == "DPMV"
    ok = reveal.compose(profile(), OVERVIEW, types=TYPES, meta={"scope_hash": "h"})
    assert ok["ok"] and ok["reason"] is None and ok["code"] == "DPMV"
    assert ok["type"] == {"code": "DPMV", "zh": "总设计师", "en": "The Architect",
                          "line": "先写清规格。"}
    assert ok["matches"][0]["code"] == "DPMV" and ok["share"]["allowed"]
    assert ok["gate"] == {"min_units": 0, "min_active_days": 0, "active_days": 14,
                          "passed": True, "axes": [{"axis": k, "n_units": 40} for k in "DIMV"]}


def test_fingerprint_facts_and_method():
    ok = reveal.compose(profile(), OVERVIEW, types=TYPES, span=(1, 2),
                        extra={"agent_hours": {"claude_code": 3.0, "codex": 1.0},
                               "top_error_class": {"class": "test_failure", "n": 7},
                               "verification_share": 0.25})
    fp = ok["fingerprint"]
    assert len(fp["by_hour"]) == 24 and fp["by_hour"][14] == 9 and fp["sessions"] == 120
    assert len(fp["by_weekday_hour"]) == 7 and all(len(r) == 24 for r in fp["by_weekday_hour"])
    assert fp["by_weekday_hour"][0][9] == 5 and fp["by_weekday_hour"][2][14] == 9
    assert (fp["first_ts"], fp["last_ts"]) == (1, 2)
    facts = {f["stage"]: f for f in ok["facts"]}
    assert facts["sessions"]["value"] == 120 and facts["tools"]["value"] == 900
    assert facts["rhythm"]["value"] == 14
    assert facts["agents"]["value"] == "claude_code 75% · codex 25%"
    assert facts["friction"]["value"] == "test_failure" and facts["verification"]["value"] == 0.25
    method = ok["method"]
    assert method["rules_version"] == "collaboration-profile-v1"
    assert method["thresholds"] == {"min_units": 0, "min_active_days": 0, "midpoint": 50}
    assert [a["axis"] for a in method["axes"]] == list("DIMV")
    # Unknown facts stay None, never 0.
    blank = {f["stage"]: f for f in reveal.compose(None, None, types=TYPES)["facts"]}
    assert blank["sessions"]["value"] is None and blank["verification"]["value"] is None


def test_endpoint_without_data(gateway_factory):
    client, _ = gateway_factory()
    body = client.get("/v1/shell/reveal").json()
    assert body["ok"] is False
    expected = "persona_unavailable" if reveal._export() is None else "insufficient_data"
    assert body["reason"] == expected
    assert body["gate"]["min_units"] == 0 and body["matches"] == []
    assert body["method"]["thresholds"]["midpoint"] == 50
    assert body["meta"]["scope_hash"]


def test_load_with_export_stand_in(gateway_factory, tmp_path, monkeypatch):
    """Gateway path with a stand-in for the export package (merged in round 3): missing
    sections → computing + one submit each; cached sections → the full payload."""
    from types import SimpleNamespace

    from realtime_fixtures import NOW, Tandem

    from tandem_backend.services.sections import rules_digest
    from tandem_backend.services.snapshots import SnapshotKey, scope_hash
    from tandem_backend.shell import default_scope

    home = tmp_path / "tandem"
    home.mkdir()
    t = Tandem(home)
    t.session("a", status="completed", started=NOW - 3_600_000, ended=NOW - 1_800_000)
    t.db.close()
    _, gw = gateway_factory(home=home, started=False)
    gw.revisions.update(data_rev=7, inventory_rev=0)
    fake = (SimpleNamespace(persona_profile=lambda bodies: profile()),
            SimpleNamespace(TYPES=TYPES))
    monkeypatch.setattr(reveal, "_export", lambda: fake)
    submitted = []

    def submit(name, *args):
        submitted.append(name)
        return SimpleNamespace(id=f"job-{name}")

    gw.supervisor.analysis.submit = submit
    scope = default_scope(gw, 30)
    first = reveal.load(gw, scope)
    assert first["reason"] == "computing" and first["ok"] is False
    assert sorted(submitted) == sorted(reveal.PERSONA_SECTIONS)
    assert len(first["meta"]["job_ids"]) == 4
    assert reveal.persona_summary(gw, scope)["reason"] == "computing"
    h = scope_hash(scope, {})
    for name in reveal.PERSONA_SECTIONS:
        gw.snapshots.put(SnapshotKey(name, h, 7, 0, rules_digest()),
                         OVERVIEW if name == "overview" else {name: {}})
    body = reveal.load(gw, scope)
    assert body["ok"] and body["code"] == "DPMV" and body["meta"]["freshness"] == "fresh"
    assert body["fingerprint"]["first_ts"] == NOW - 3_600_000
    assert {f["stage"]: f for f in body["facts"]}["agents"]["value"] == "claude_code 100%"
    summary = reveal.persona_summary(gw, scope)
    assert summary == {"ok": True, "code": "DPMV", "name_zh": "总设计师", "reason": None,
                       "gate": body["gate"]}
