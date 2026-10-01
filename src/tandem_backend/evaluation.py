"""Readable-output checks. Passing these checks is NOT a human acceptance verdict.

    Cases live separately from history and never update profile/recommendation evidence.
    Scene budgets prevent rewarding short-but-empty answers or punishing necessary math.
"""

import re

SCENE_BUDGETS = {"profile": 900, "bottleneck": 1200, "recommendation": 1100,
                 "developer_report": 2200, "math_explanation": 3200, "status_update": 450}
_EMPTY = re.compile(r"^(?:很好|一切正常|继续努力|持续优化|效果很好)[。！!\s]*$")
_INFLATED = re.compile(r"赋能|全方位|革命性|毋庸置疑|完美实现|全面提升|极致体验")
_CERTAINTY = re.compile(r"(?:保证|必然|一定)(?:能|会|让|提升)|(?:已经|已)(?:证明|证实).{0,12}(?:有效|提升)")
_JARGON = re.compile(r"\b(?:KL|JS|POMDP|embedding|latent|factorize|z_u)\b", re.I)


def evaluate_text(text: str, scene: str, required_facts: list[str] | None = None,
                  forbidden_claims: list[str] | None = None) -> dict:
    if scene not in SCENE_BUDGETS:
        raise ValueError("未知的评价场景")
    issues = []
    if not text.strip() or _EMPTY.fullmatch(text.strip()):
        issues.append({"code": "empty_information", "severity": "error", "message": "读者得不到具体信息。"})
    for fact in required_facts or []:
        if fact not in text:
            issues.append({"code": "missing_fact", "severity": "error", "message": f"遗漏必要信息：{fact}"})
    for claim in forbidden_claims or []:
        if claim in text:
            issues.append({"code": "unsupported_claim", "severity": "error", "message": "出现没有依据的结论。"})
    if len(text) > SCENE_BUDGETS[scene]:
        issues.append({"code": "detail_overload", "severity": "warning", "message": "首层内容过长，考虑把细节移入可展开部分。"})
    opening = re.sub(r"^#.*\n", "", text).strip()[:230]
    if scene != "math_explanation" and len(_JARGON.findall(opening)) >= 3:
        issues.append({"code": "unexplained_jargon", "severity": "warning", "message": "开头堆叠术语，读者还不知道结论。"})
    if _INFLATED.search(text):
        issues.append({"code": "inflated_language", "severity": "warning", "message": "夸大词没有说明具体变化。"})
    if _CERTAINTY.search(text):
        issues.append({"code": "unverified_certainty", "severity": "error", "message": "检查效果声明是否有对照证据。"})
    errors = sum(i["severity"] == "error" for i in issues)
    warnings = len(issues) - errors
    score = max(0, 100 - 35 * errors - 12 * warnings)
    return {"scene": scene, "rule_version": "readability-v1", "score": score,
            "checks_passed": errors == 0 and warnings == 0, "issues": issues,
            "human_acceptance": "pending", "meaning": "这是自动检查结果；背景适配、主次和中文语感仍由读者评价。"}


def benchmark() -> dict:
    """Independent hand-authored contrasts, not historical or synthetic preference evidence."""
    cases = [
        ("empty", "profile", "继续努力。", [], False),
        ("plain_profile", "profile", "已整理 8 个会话。3 个会话里你要求解释更直观；暂时只能用于这些任务，不能据此确定长期偏好。", ["8", "3"], True),
        ("jargon_profile", "profile", "通过 KL、JS、POMDP 和 embedding 对 latent z_u 做 factorize，得到最优画像。", [], False),
        ("false_gain", "recommendation", "安装这个 skill 一定会提升可读性。", [], False),
        ("trial", "recommendation", "你在两次写作任务中要求少用套话。可以试 Humanizer-zh，先对比同一段输入的两个版本；效果还没有测过。", ["效果还没有测过"], True),
        ("lost_fact", "developer_report", "后端已跑通，下一步完善测试。", ["导入", "样本不足"], False),
        ("developer", "developer_report", "后端已跑通导入、分析和建议。采用 SQLite 是因为当前只需要本地查询；样本不足，尚不能验证 skill 的真实收益。下一步做同场景对照。", ["导入", "样本不足"], True),
        ("math", "math_explanation", "并发的两次调用分别覆盖 0–5 秒和 3–8 秒。直接相加得到 10 秒，会把重叠的 2 秒算两遍；取区间并集得到 8 秒。区间并集是只计算每个时刻一次。", ["8 秒", "2 秒"], True),
    ]
    results = []
    for name, scene, text, facts, expected in cases:
        result = evaluate_text(text, scene, facts)
        results.append({"case": name, "expected_checks_passed": expected, "matches": result["checks_passed"] == expected,
                        "output": text, "evaluation": result})
    return {"version": "contrasts-v1", "cases": len(results), "correct": sum(r["matches"] for r in results),
            "results": results, "human_acceptance": "pending",
            "limitation": "这些合成案例用于发现明显错误，不构成用户认可或独立语义评分。"}
