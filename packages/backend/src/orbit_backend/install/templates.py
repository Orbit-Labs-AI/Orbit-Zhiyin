"""Built-in reference templates (RC-12) so install can render a candidate without recommend.

Template rendering with AI slots belongs to recommend; these are the deterministic templates
the install module must be able to produce on its own (and test end-to-end).
"""

from __future__ import annotations

from .errors import PlanError

READONLY_ALLOWLIST = "permissions/readonly-allowlist@1"
DEFAULT_READONLY = ["git status", "git diff", "git log", "git show", "ls", "cat", "pwd", "which",
                    "gh pr view", "gh pr checks"]
# Command prefixes that only read state. Anything else is refused for this template.
READONLY_VOCAB = frozenset(DEFAULT_READONLY + [
    "git branch", "git blame", "git remote -v", "git rev-parse", "git ls-files", "head", "tail", "wc",
    "rg", "grep", "find", "tree", "du", "df", "file", "stat", "date", "whoami", "uname", "env",
    "gh pr list", "gh pr diff", "gh issue view", "gh issue list", "gh run view", "gh run list",
    "uv tree", "npm ls", "pnpm ls"])
TEMPLATES = {READONLY_ALLOWLIST: "只读命令白名单：减少只读 shell 命令的确认弹窗"}


def render_template(template_id: str, params: dict | None, targets_agents: list[str] | None) -> dict:
    """Return an InstallSpec for a built-in template."""
    params = params or {}
    if template_id != READONLY_ALLOWLIST:
        raise PlanError("unknown_template", f"未知模板：{template_id}", http=422)
    allow = params.get("allow") or DEFAULT_READONLY
    if not isinstance(allow, list) or not all(isinstance(a, str) for a in allow):
        raise PlanError("invalid_spec", "allow 必须是字符串列表", http=422)
    allow = [" ".join(a.split()) for a in allow]
    bad = [a for a in allow if a not in READONLY_VOCAB]
    if bad:
        raise PlanError("not_readonly", f"不在只读词表内：{', '.join(bad)}", detail={"rejected": bad})
    return {
        "kind": "permission_rule", "id": params.get("id") or "readonly-allowlist",
        "title": params.get("title") or "只读命令免确认", "agents": list(targets_agents or ["claude_code"]),
        "scope": params.get("scope") or "user", "project_path": params.get("project_path"),
        "payload": {"allow": list(dict.fromkeys(allow))},
        "source": {"type": "spec", "id": None, "template": template_id, "license": None, "sha256": None},
        "ai_ranges": None, "evidence_refs": list(params.get("evidence_refs") or []),
    }
