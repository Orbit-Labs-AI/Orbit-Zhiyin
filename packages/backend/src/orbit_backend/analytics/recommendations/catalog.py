"""Small reviewed catalogue, loaded offline; recommendations never install code."""

import hashlib
import json
import re
from importlib.resources import files
from pathlib import PurePosixPath

from orbit_data.capabilities import MATRIX

KINDS = {"skill", "agent", "hook", "prompt"}
# Every agent the data layer has a capability row for (claude_code, codex, opencode, pi,
# hermes, dsh, kimi), plus "generic". One source, so a newly supported agent is accepted
# by the GET routes and the compatibility analyzer without editing a second list.
TARGETS = frozenset({"generic", *MATRIX})
CAPABILITIES = {"scope_alignment", "requirements_memory", "debugging", "retry_control",
                "tool_preflight", "verification", "validation_visibility", "context_budget"}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def builtin_resources():
    specs = [
        ("scope-brief", "目标与验收对齐", ["scope_alignment"],
         "开始任务时，列出目标、输入、允许修改的范围、必须保留的行为和验收项。只询问会改变实现的缺失信息；按验收项执行并记录结果。"),
        ("requirement-ledger", "任务要求记录", ["requirements_memory"],
         "为当前任务维护简短的要求表：对象、要求 ID、最新确认内容、验收方式、证据。收到修改时更新对应项；阶段结束时逐项核对，避免要求失落。"),
        ("diagnose-retry", "重试前诊断", ["debugging", "retry_control", "tool_preflight"],
         "调用失败后先保存状态与错误证据，区分输入、环境、权限、限流和程序故障。提出一个可验证的原因；重试前说明改变了什么。相同输入再失败时暂停重复调用并补充证据；临时错误采用有上限的退避。"),
        ("validation-ledger", "验收证据核对", ["verification", "validation_visibility"],
         "对每个明确的验收项记录任务 ID、产物版本、验证范围、实际命令、退出状态和证据 ID。未执行或版本不匹配保持未知；只有匹配的证据才能支持通过结论。"),
        ("context-checkpoint", "阶段上下文摘要", ["context_budget"],
         "在任务阶段结束时保存目标、最新约束、已确认结论、未解决问题、产物版本和证据引用。后续阶段按需读取原始证据，避免重复粘贴完整工具输出。摘要不能替代验收标准，也不能丢弃失败与不确定性。"),
    ]
    return [{"id": "orbit-" + uid, "name": name, "kind": "prompt", "origin": "project_template",
             "verification": "project_template", "content_sha256": hashlib.sha256(preview.encode()).hexdigest(),
             "capabilities": caps, "compatibility": dict.fromkeys(sorted(TARGETS), "manual"), "effort": "low",
             "summary": name, "preview": preview, "effect_status": "unmeasured",
             "setup_steps": ["在一个合成或获授权的任务中手动采用此模板。", "替换任务与验收信息，记录启用前后的同口径指标。"],
             "limitations": ["这是本项目编写的试用模板，效果尚未测量；增加的提示与验证成本也应计入。"],
             "trial": "固定任务输入、模型配置和验收项，对比目标指标、验收结果及新增 Token／耗时。"}
            for uid, name, caps, preview in specs]


def load_catalog():
    external = json.loads(files("orbit_backend").joinpath("data/bottleneck-resources.json").read_text(encoding="utf-8"))
    return builtin_resources() + external


def rejection_reason(resource):
    if not isinstance(resource, dict):
        return "invalid_resource"
    if (not isinstance(resource.get("id"), str) or not resource["id"] or resource.get("kind") not in KINDS
            or resource.get("effort") not in {"low", "medium", "high"}
            or not isinstance(resource.get("compatibility"), dict)
            or not isinstance(resource.get("capabilities"), list)
            or not resource["capabilities"] or any(c not in CAPABILITIES for c in resource["capabilities"])):
        return "invalid_resource_contract"
    if any(not resource.get(k) for k in ("name", "summary", "preview", "setup_steps", "limitations", "trial")):
        return "missing_actionable_content"
    if resource.get("source_status") in {"unavailable", "revoked"}:
        return "source_unavailable"
    if resource.get("origin") == "project_template":
        trusted = next((r for r in builtin_resources() if r["id"] == resource["id"]), None)
        return None if resource == trusted else "unrecognized_project_template"
    if resource.get("origin") != "github" or resource.get("verification") not in {
            "repository_and_skill_read", "repository_and_source_read"}:
        return "unverified_source"
    if not re.fullmatch(r"https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", resource.get("url", "")):
        return "invalid_source_url"
    path = resource.get("source_path", "")
    if not path or PurePosixPath(path).is_absolute() or ".." in PurePosixPath(path).parts or "\\" in path:
        return "invalid_source_path"
    for key, length in (("verified_sha", 40), ("blob_sha", 40), ("content_sha256", 64)):
        if not re.fullmatch(rf"[a-f0-9]{{{length}}}", resource.get(key, "")):
            return "missing_source_pin"
    if not resource.get("verified_at") or resource.get("license") in (None, "", "unknown", "NOASSERTION"):
        return "missing_source_provenance"
    return None


def vetted_catalog(catalog):
    accepted, excluded, seen = [], [], set()
    for resource in catalog:
        reason = rejection_reason(resource)
        uid = resource.get("id") if isinstance(resource, dict) else None
        if uid in seen:
            reason = "duplicate_resource_id"
        if reason:
            excluded.append({"resource_id": uid, "reason": reason})
        else:
            seen.add(uid)
            accepted.append(resource)
    return accepted, excluded
