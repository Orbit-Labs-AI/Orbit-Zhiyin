"""Validate family metadata and carry actual dependencies into common filters."""

from .hooks.dictionary import ItemFeatures as HookFeatures
from .mcp.dictionary import ItemFeatures as MCPFeatures
from .model_configs.dictionary import ItemFeatures as ModelFeatures
from .plugins.dictionary import ItemFeatures as PluginFeatures
from .rules_prompts.dictionary import ItemFeatures as PromptFeatures
from .skills.dictionary import ItemFeatures as SkillFeatures
from .workflows.dictionary import ItemFeatures as WorkflowFeatures

SCHEMAS = {"skills": SkillFeatures, "hooks": HookFeatures, "mcp": MCPFeatures,
           "model_configs": ModelFeatures, "plugins": PluginFeatures,
           "rules_prompts": PromptFeatures, "workflows": WorkflowFeatures}


def prepare_item(item):
    item = item.model_copy(deep=True)
    raw = dict(item.family_features)
    # These are explicit backwards-compatible metadata flags, not permissions.
    legacy = raw.pop("legacy_template", False)
    template_type = raw.pop("template_type", None)
    upstream_type = raw.pop("upstream_resource_type", None)
    values = SCHEMAS[item.family].model_validate(raw).model_dump(exclude_unset=True)
    item.family_features = values
    if legacy:
        item.family_features["legacy_template"] = True
    if template_type is not None:
        item.family_features["template_type"] = template_type
    if upstream_type is not None:
        item.family_features["upstream_resource_type"] = upstream_type
    if item.family == "skills":
        item.requirements.tools = sorted(set(item.requirements.tools) | set(values.get("required_tools", [])))
    if item.family in ("plugins", "mcp"):
        item.risk_permission.required_permissions = sorted(set(item.risk_permission.required_permissions) | set(values.get("permissions", [])))
    if item.family == "plugins":
        item.requirements.resources = sorted(set(item.requirements.resources) | set(values.get("dependencies", [])))
    if item.family == "workflows":
        item.requirements.tools = sorted(set(item.requirements.tools) | set(values.get("tools", [])))
    pending = []
    required = {"hooks": ("event", "condition", "action"), "model_configs": ("model", "reasoning_effort", "agent_harness")}
    for name in required.get(item.family, ()):
        if not values.get(name):
            pending.append("family_features." + name)
    return item, pending
