"""Session takeaway (A3-18 / L-sess-3): deterministic L0 template, no model call.

Each action names a prototype recommendation id and the recommend problem type it maps to
(``recommend/problems.py``), so the front end can resolve the live recommendation. Marking a
takeaway as wrong goes through ``POST /v1/labels`` (target_kind=key_moment|facet,
label=inaccurate); nothing here stores state.
"""

from __future__ import annotations

REC_PROBLEM = {"retry-breaker": "tool_env_failure", "acceptance": "wrong_approach",
               "deploy-target": "wrong_approach", "verify-step": "missing_verification"}
ACTIONS = {"retry-breaker": "加 Hook：重复失败熔断", "acceptance": "生成规则：开场写明完成条件",
           "deploy-target": "生成规则：写明部署目标", "verify-step": "生成规则：结束前跑验证"}


def _action(rec_id: str) -> dict:
    return {"label": ACTIONS[rec_id], "rec_id": rec_id, "problem_type": REC_PROBLEM[rec_id]}


def takeaway(facts: dict, fric: str | None = None) -> dict:
    """``facts``: live, streak, corr, errors, verify, out (from the detail builder)."""
    corr, errors = facts.get("corr") or 0, facts.get("errors")
    actions: list[dict] = []
    if facts.get("live"):
        text = f"会话进行中：已调用工具 {facts.get('tools') or 0} 次，暂时没有卡住的迹象。"
    elif facts.get("streak"):
        text = "同一命令连续失败 3 次以上才停下——失败两次就先检查认证与环境，再继续。"
        if corr:
            text += f"这次你还纠偏了 {corr} 次。"
        actions.append(_action("retry-breaker"))
    elif corr >= 2:
        text = (f"你纠偏了 {corr} 次，方向在中途才说清——把完成条件写进第一条消息，"
                "能省掉大部分来回。")
        actions.append(_action("deploy-target" if fric == "方向错误" else "acceptance"))
    elif facts.get("verify"):
        text = "目标清楚、过程中" + ("只纠偏 1 次" if corr else "没有返工") + "，最后跑了验证命令。可以把这次的开场方式存成模板。"
    elif errors:
        text = f"出现 {errors} 次工具错误，没有看到验证命令——加一步测试或线上检查，结果会更稳。"
        actions.append(_action("verify-step"))
    elif errors is None:
        text = "这个 Agent 的日志没有记录工具成败，无法判断是否出错；结束前跑一次验证会更稳。"
        actions.append(_action("verify-step"))
    else:
        text = "这次协作很顺：没有纠偏，也没有工具失败。没有看到验证命令，可以考虑加一步检查。"
        actions.append(_action("verify-step"))
    return {"text": text, "actions": actions, "basis": "l0_template",
            "feedback": {"endpoint": "/v1/labels", "target_kind": ["key_moment", "facet"],
                         "label": "inaccurate"}}
