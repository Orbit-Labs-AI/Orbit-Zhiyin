"""Thirteen explicit gates (RC-04): every check says true / false / 'n/a' and why.

Gated candidates are kept (with reasons) so the UI can answer「为什么没推荐」and
EV-05 has a denominator. Missing context is 'n/a', never silent agreement.
"""

from ..problems import MIN_DENOMINATOR, MIN_SESSIONS, passes

NA = "n/a"
TRUSTED_ORIGINS = {"kb", "template", "inventory", "generated", "builtin"}
LANGUAGE_KINDS = {"rule", "prompt", "skill", "subagent"}
WIDENING_FLAGS = {"runs_command", "network", "widens_permissions"}
REVISIT_STATUSES = {"not_applicable", "dismissed"}
UNSUPPORTED_ON = {"pi": {"mcp", "subagent"}}
UNKNOWN_LICENSES = {"", "unknown", "noassertion", "none", "other"}


def evidence_changed(current: float, last: float | None) -> bool:
    """≥ 20 % change in supporting sessions re-opens a closed decision."""
    if last is None:
        return False
    return abs(current - last) / max(last, 1) >= .2


def top_agent(inputs: dict) -> str | None:
    agents = inputs.get("agents") or {}
    return max(sorted(agents), key=lambda a: agents[a]) if agents else None


def _sessions(raw: dict) -> int:
    problem = raw.get("problem") or {}
    return problem.get("sessions") or len((raw.get("evidence") or {}).get("session_uids") or [])


def _profile_evidence(raw, inputs, memory):
    problem = raw.get("problem") or {}
    dim = problem.get("dimension")
    if not dim:
        return NA, ""
    ev = ((inputs.get("profile") or {}).get("evidence_sessions"))
    count = ev.get(dim, 0) if isinstance(ev, dict) else 0
    if count >= 1 or (problem.get("sessions", 0) >= 1 and (problem.get("evidence") or {}).get("session_uids")):
        return True, ""
    return False, f"画像里还没有「{dim}」维度的证据"


def _bottleneck_evidence(raw, inputs, memory):
    problem = raw.get("problem")
    evidence = raw.get("evidence") or {}
    if not problem and (evidence.get("counts") or {}).get("sessions"):
        # a card that claims sessions (e.g. the model route) must let A3 open them
        return (True, "") if evidence.get("session_uids") else (False, "没有可回看的会话证据")
    if not problem or raw.get("kind") == "removal":  # removal stands on inventory facts, not sessions
        return NA, ""
    uids = (raw.get("evidence") or {}).get("session_uids") or (problem.get("evidence") or {}).get("session_uids")
    return (True, "") if uids else (False, "没有可回看的会话证据")


def _scene_ok(raw, inputs, memory):
    scenes = (raw.get("gates_hint") or {}).get("scenes")
    scene = (raw.get("problem") or {}).get("scene")
    if not scenes or not scene:
        return NA, ""
    return (True, "") if scene in scenes else (False, f"适用场景不含「{scene}」")


def _language_ok(raw, inputs, memory):
    declared = (raw.get("gates_hint") or {}).get("language")
    if raw.get("kind") not in LANGUAGE_KINDS or not declared:
        return NA, ""
    if "any" in declared:
        return True, ""
    have = set((inputs.get("profile") or {}).get("languages") or [])
    if lang := (raw.get("problem") or {}).get("language"):
        have.add(lang)
    if not have:
        return NA, "不知道你常用的语言"
    return (True, "") if have & set(declared) else (False, "语言不匹配：" + "、".join(declared))


def _source_verified(raw, inputs, memory):
    source = raw.get("source") or {}
    origin = source.get("origin")
    if origin in TRUSTED_ORIGINS:
        return True, ""
    if origin == "catalog":
        # only the catalog's own verification (repository and source read) counts; a licence plus a
        # content hash proves provenance of bytes, not that anyone reviewed what they do
        if source.get("verified"):
            return True, ""
        return False, "来源未核验（资源库未标记为已审阅）"
    return (True, "") if source.get("verified") else (False, "来源未核验")


def target_agents(raw: dict, inputs: dict) -> list[str]:
    """Agents a card must fit: those of the sessions its problem occurred in, else every Agent the
    user runs (most used first). Never only the most-used Agent: a problem seen in opencode
    sessions is judged against opencode even when Claude Code dominates."""
    used = [a for a, n in sorted((inputs.get("agents") or {}).items(), key=lambda kv: (-kv[1], kv[0])) if n]
    of = (inputs.get("facts") or {}).get("session_agents") or {}
    uids = ((raw.get("problem") or {}).get("evidence") or {}).get("session_uids") or ()
    seen = list(dict.fromkeys(of[u] for u in uids if u in of))
    return sorted(seen, key=lambda a: used.index(a) if a in used else len(used)) or used


def agent_support(raw: dict, agent: str) -> str:
    if raw.get("kind") in UNSUPPORTED_ON.get(agent, ()):
        return "unsupported"
    return (raw.get("agents") or {}).get(agent, "unknown")


def _agent_supported(raw, inputs, memory):
    agents = target_agents(raw, inputs)
    if not agents:
        return NA, ""
    support = {a: agent_support(raw, a) for a in agents}
    if all(v == "unsupported" for v in support.values()):
        return False, "、".join(agents) + " 不支持这类改动"
    if any(v in {"native", "manual", "adaptation_required"} for v in support.values()):
        return True, ""
    return True, "needs_context"  # unknown for every target Agent: shown as unverified, never as compatible


def _not_installed(raw, inputs, memory):
    state = (memory.get("state") or {}).get(raw["rec_key"]) or {}
    if state.get("status") == "installed":
        return False, "已安装"
    inventory = inputs.get("inventory")
    if inventory is None:
        return NA, "未扣除已装项"
    item_id = (raw.get("source") or {}).get("item_id")
    if item_id and any(i.get("catalog_item_id") == item_id for i in inventory):
        return False, "已装同一条目"
    return True, ""


def _not_dismissed(raw, inputs, memory):
    kb_id = (raw.get("kb") or {}).get("id")
    if kb_id and kb_id in (memory.get("muted_kb_rules") or []):
        return False, "你已静音这条规则"
    ptype = (raw.get("problem") or {}).get("type")
    if ptype and ptype in (memory.get("muted_problem_types") or []):
        return False, "你已静音这类问题"
    state = (memory.get("state") or {}).get(raw["rec_key"]) or {}
    status = state.get("status")
    if status == "muted":
        return False, "你已静音"
    if status == "snoozed" and (state.get("snooze_until") or 0) > (memory.get("now") or 0):
        return False, "稍后提醒中"
    if status in REVISIT_STATUSES:
        if evidence_changed(_sessions(raw), state.get("last_evidence")):
            return True, "证据变化超过 20%，重新出现"
        return False, "你标记过不适用"
    return True, ""


def _evidence_ok(raw, inputs, memory):
    problem = raw.get("problem")
    if not problem or raw.get("kind") in {"removal", "model"}:
        return NA, ""
    kb = raw.get("kb") or {}
    min_sessions = kb.get("min_sessions") or (kb.get("problem") or {}).get("min_sessions") or MIN_SESSIONS
    # Same calibrated bar as problems.build (per scope / project / task family), never a fixed 5 %.
    ok = problem.get("status") == "active" and problem.get("sessions", 0) >= min_sessions and passes(problem)
    if ok:
        return True, ""
    n = problem.get("denominator") or 0
    if n < MIN_DENOMINATOR:
        return False, f"再积累 {MIN_DENOMINATOR - n} 个会话"
    return False, f"证据不足：{problem.get('sessions', 0)}/{n} 个会话"


def _risk_ok(raw, inputs, memory):
    risk = raw.get("risk") or {}
    if risk.get("level") == "high":
        return False, "风险高，不推荐"
    if risk.get("level") == "medium" or set(risk.get("flags") or []) & WIDENING_FLAGS:
        return True, "降为 L3，需逐行预览"
    return True, ""


def _license_ok(raw, inputs, memory):
    source = raw.get("source") or {}
    if source.get("origin") != "catalog":
        return NA, ""
    lic = (source.get("license") or (raw.get("item") or {}).get("license") or "").lower()
    return (False, "无许可证，只提供链接") if lic in UNKNOWN_LICENSES else (True, "")


def _audience_ok(raw, inputs, memory):
    level = memory.get("level")
    if level is None:
        return NA, ""
    return (False, "面向更熟练的用户") if raw.get("audience_min", 0) > level else (True, "")


def _requirements_ok(raw, inputs, memory):
    req = raw.get("requirements") or {}
    profile = inputs.get("profile") or {}
    checked, unknown, missing = False, False, set()
    for key in ("tools", "software"):
        needed = {t.lower() for t in req.get(key) or ()}
        observed = profile.get(key)
        if not needed:
            continue
        if not observed:
            unknown = True  # Absent/empty observations are unknown, not a full inventory.
            continue
        checked = True
        missing.update(needed - {t.lower() for t in observed})
    if missing:
        return False, "未观察到要求项：" + "、".join(sorted(missing))
    return (True, "") if checked and not unknown else (NA, "")


CHECKS = {
    "profile_evidence": _profile_evidence, "bottleneck_evidence": _bottleneck_evidence,
    "scene_ok": _scene_ok, "language_ok": _language_ok, "source_verified": _source_verified,
    "agent_supported": _agent_supported, "not_installed": _not_installed, "not_dismissed": _not_dismissed,
    "evidence_ok": _evidence_ok, "risk_ok": _risk_ok, "license_ok": _license_ok,
    "audience_ok": _audience_ok, "requirements_ok": _requirements_ok,
}


def check(raw: dict, inputs: dict, memory: dict) -> dict:
    """Return {passed, checks, reasons, notes, level}; notes are reasons of non-failing checks.

    `level` is the possibly raised install level (risk downgrade forces ≥ 3);
    callers strip `notes`/`level` before persisting `Cand.gates`.
    """
    checks, reasons, notes = {}, [], []
    level = raw.get("level") or 1
    for name, fn in CHECKS.items():
        value, reason = fn(raw, inputs, memory)
        checks[name] = value
        if reason:
            reasons.append(reason)
            if value is not False:
                notes.append(reason)
        if name == "risk_ok" and reason.startswith("降为 L3"):
            level = max(level, 3)
    return {"passed": False not in checks.values(), "checks": checks, "reasons": reasons,
            "notes": notes, "level": level}
