from orbit_backend.recommend.ranking.gates import check

NA = "n/a"


def problem(**kw):
    base = {"problem_id": "p1", "type": "permission_friction", "key": "readonly_shell", "dimension": None,
            "sessions": 8, "denominator": 20, "wilson_lo": .2, "weekly_count": 5, "status": "active",
            "evidence": {"session_uids": ["s1"]}, "scene": None, "language": None, "vars": {}}
    return base | kw


def raw(**kw):
    base = {"rec_key": "kb:ro-allow", "problem": problem(), "kind": "permission_rule", "dim": "hook", "level": 1,
            "audience_min": 0, "title": "只读命令自动放行", "evidence": {"session_uids": ["s1", "s2"]},
            "source": {"origin": "kb", "item_id": None}, "agents": {"claude_code": "native"},
            "risk": {"level": "low", "flags": []}, "kb": {"id": "ro-allow"}, "gates_hint": {}, "requirements": {}}
    return base | kw


INPUTS = {"agents": {"claude_code": 40, "codex": 3}, "sessions": {"main": 43}, "inventory": [], "profile": None}
MEMORY = {"now": 1000, "state": {}, "labels": {}, "muted_kb_rules": [], "muted_problem_types": [], "level": None}


def run(r=None, inputs=None, memory=None):
    return check(r or raw(), INPUTS | (inputs or {}), MEMORY | (memory or {}))


def test_all_pass_and_na_for_missing_context():
    g = run()
    assert g["passed"] is True
    c = g["checks"]
    assert c["profile_evidence"] == NA and c["scene_ok"] == NA and c["language_ok"] == NA
    assert c["license_ok"] == NA and c["audience_ok"] == NA and c["requirements_ok"] == NA
    assert c["bottleneck_evidence"] is True and c["evidence_ok"] is True and c["not_installed"] is True
    assert len(c) == 13


def test_profile_and_bottleneck_evidence():
    with_dim = raw(problem=problem(dimension="verbosity", sessions=0, evidence={"session_uids": []}),
                   evidence={"session_uids": []})
    g = run(with_dim, inputs={"profile": {"evidence_sessions": {"verbosity": 0}}})
    assert g["checks"]["profile_evidence"] is False and g["checks"]["bottleneck_evidence"] is False
    g = run(with_dim, inputs={"profile": {"evidence_sessions": {"verbosity": 2}}})
    assert g["checks"]["profile_evidence"] is True
    assert run(raw(problem=None))["checks"]["bottleneck_evidence"] == NA
    assert run(raw(kind="removal", evidence={}, problem=problem(evidence={})))["checks"]["bottleneck_evidence"] == NA


def test_scene_and_language():
    r = raw(kind="skill", problem=problem(scene="document", language="zh"),
            gates_hint={"scenes": ["math_explanation"], "language": ["en"]})
    g = run(r)
    assert g["checks"]["scene_ok"] is False and g["checks"]["language_ok"] is False and not g["passed"]
    r["gates_hint"] = {"scenes": ["document"], "language": ["any"]}
    assert run(r)["checks"]["scene_ok"] is True and run(r)["checks"]["language_ok"] is True
    # hooks are language-neutral
    assert run(raw(gates_hint={"language": ["en"]}))["checks"]["language_ok"] == NA


def test_source_and_license():
    cat = raw(source={"origin": "catalog", "item_id": "c1", "license": "", "verified": False})
    g = run(cat)
    assert g["checks"]["source_verified"] is False and g["checks"]["license_ok"] is False
    assert "无许可证，只提供链接" in g["reasons"]
    hashed = raw(source={"origin": "catalog", "item_id": "c1", "license": "MIT"},
                 item={"license": "MIT", "content_hash": "ab" * 32})
    g = run(hashed)  # licence + hash without the catalog's review is not verification
    assert g["checks"]["source_verified"] is False and g["checks"]["license_ok"] is True
    ok = raw(source={"origin": "catalog", "item_id": "c1", "license": "MIT", "verified": True})
    assert run(ok)["checks"]["source_verified"] is True
    assert run(raw(source={"origin": "legacy", "verified": False}))["checks"]["source_verified"] is False


def test_agent_supported():
    assert run(raw(agents={"claude_code": "unsupported"}))["checks"]["agent_supported"] is False
    g = run(raw(agents={}))
    assert g["checks"]["agent_supported"] is True and "needs_context" in g["notes"]
    pi = run(raw(kind="mcp", agents={"pi": "native"}), inputs={"agents": {"pi": 9}})
    assert pi["checks"]["agent_supported"] is False


def test_not_installed():
    g = run(inputs={"inventory": None})
    assert g["checks"]["not_installed"] == NA and "未扣除已装项" in g["reasons"] and g["passed"]
    r = raw(source={"origin": "catalog", "item_id": "c9", "license": "MIT", "verified": True})
    assert run(r, inputs={"inventory": [{"catalog_item_id": "c9"}]})["checks"]["not_installed"] is False
    state = {"kb:ro-allow": {"status": "installed"}}
    assert run(memory={"state": state})["checks"]["not_installed"] is False


def test_not_dismissed_snooze_expiry_and_resurfacing():
    snoozed = {"kb:ro-allow": {"status": "snoozed", "snooze_until": 2000}}
    assert run(memory={"state": snoozed})["checks"]["not_dismissed"] is False
    assert run(memory={"state": snoozed, "now": 3000})["checks"]["not_dismissed"] is True
    na = {"kb:ro-allow": {"status": "not_applicable", "last_evidence": 7}}
    assert run(memory={"state": na})["checks"]["not_dismissed"] is False  # 8 vs 7: +14 %
    na["kb:ro-allow"]["last_evidence"] = 6  # 8 vs 6: +33 % → resurfaces
    assert run(memory={"state": na})["checks"]["not_dismissed"] is True
    assert run(memory={"muted_kb_rules": ["ro-allow"]})["checks"]["not_dismissed"] is False
    assert run(memory={"muted_problem_types": ["permission_friction"]})["checks"]["not_dismissed"] is False


def test_evidence_ok_asks_for_more_sessions():
    g = run(raw(problem=problem(status="insufficient", sessions=2, denominator=3, wilson_lo=.1)))
    assert g["checks"]["evidence_ok"] is False and "再积累 2 个会话" in g["reasons"]
    g = run(raw(problem=problem(sessions=3, wilson_lo=.03)))
    assert g["checks"]["evidence_ok"] is False
    assert run(raw(kind="removal"))["checks"]["evidence_ok"] == NA
    assert run(raw(problem=None))["checks"]["evidence_ok"] == NA
    assert run(raw(kb={"id": "x", "problem": {"min_sessions": 10}}))["checks"]["evidence_ok"] is False


def test_risk_downgrade_and_high_block():
    g = run(raw(risk={"level": "low", "flags": ["runs_command"]}))
    assert g["passed"] and g["level"] == 3 and "降为 L3，需逐行预览" in g["notes"]
    assert run(raw(risk={"level": "high"}))["checks"]["risk_ok"] is False


def test_audience_and_requirements():
    assert run(raw(audience_min=2), memory={"level": 1})["checks"]["audience_ok"] is False
    assert run(raw(audience_min=1), memory={"level": 1})["checks"]["audience_ok"] is True
    r = raw(requirements={"tools": ["latexmk"]})
    assert run(r, inputs={"profile": {"tools": ["git"]}})["checks"]["requirements_ok"] is False
    assert run(r, inputs={"profile": {"tools": ["LaTeXmk"]}})["checks"]["requirements_ok"] is True
    assert run(r)["checks"]["requirements_ok"] == NA


def test_unverified_catalog_row_is_rejected():
    from orbit_backend.recommend.recall.catalog_route import _normalise_catalog, from_item

    row = {"item_id": "x", "type": "skill", "name": "X", "license": "MIT", "content_hash": "ab" * 32,
           "agents": ["claude_code"]}
    assert _normalise_catalog(row)["verified"] is None  # not in the search row: looked up in catalog_item
    assert _normalise_catalog(row | {"verification": "metadata_only"})["verified"] is False
    assert _normalise_catalog(row | {"verification": "repository_and_skill_read"})["verified"] is True
    cand = from_item(_normalise_catalog(row), None, INPUTS, match_basis="profile")
    g = run(raw(source=cand["source"], item=cand["item"]))
    assert g["checks"]["source_verified"] is False and "来源未核验（资源库未标记为已审阅）" in g["reasons"]


def test_catalog_agents_without_declaration_are_unknown():
    from orbit_backend.recommend.recall.catalog_route import from_item

    item = {"item_id": "x", "kind": "skill", "name": "X", "agents": ["claude_code", "codex"], "verified": True}
    cand = from_item(item, None, INPUTS, match_basis="profile")
    assert cand["agents"] == {} and cand["target"]["agents_listed"] == ["claude_code", "codex"]
    g = run(raw(agents=cand["agents"]))
    assert g["checks"]["agent_supported"] is True and "needs_context" in g["notes"]
    declared = from_item(item | {"support": {"claude_code": "native"}}, None, INPUTS, match_basis="profile")
    assert run(raw(agents=declared["agents"]))["notes"] == []
