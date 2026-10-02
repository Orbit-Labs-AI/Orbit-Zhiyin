"""Readable labels from published facts. Display fallbacks never rewrite source evidence."""

import json
import re

AGENTS = {
    "claude_code": "Claude Code",
    "codex": "Codex",
    "dsh": "DSH",
    "pi": "pi",
    "hermes": "Hermes",
    "opencode": "OpenCode",
    "kimi": "Kimi",
}
KINDS = {
    "message.user": "用户消息",
    "message.assistant": "助手回复",
    "reasoning": "思考记录",
    "context.inject": "上下文更新",
    "context.compaction": "上下文压缩",
    "session.meta": "会话信息",
    "session.title": "会话标题",
    "setting.change": "设置更新",
    "turn.start": "轮次开始",
    "turn.end": "轮次结束",
    "tool.call": "工具调用",
    "tool.result": "工具结果",
    "model.usage": "模型用量",
    "permission.request": "权限请求",
    "permission.decision": "权限决定",
    "hook.run": "Hook 记录",
    "subagent.spawn": "启动子代理",
    "subagent.result": "子代理结果",
    "plan.update": "计划更新",
    "file.change": "文件变更",
    "link": "关联记录",
    "queue": "队列记录",
    "error": "错误",
    "ui.state": "运行状态",
    "branch": "会话分支",
    "unknown": "尚未识别的记录",
}
ATTACHMENTS = {
    "total_tokens_reminder": ("用量提醒", "运行时提供的令牌用量提醒。"),
    "deferred_tools_record": ("工具清单", "可延迟加载的工具信息。"),
    "deferred_tools_delta": ("工具清单更新", "可延迟加载工具的变更信息。"),
    "environment": ("环境信息", "本次运行的工作目录与系统环境。"),
    "silent_turn_reminder": ("轮次控制提醒", "运行时提供的静默轮次控制信息。"),
    "edited_text_file": ("文件更新上下文", "已编辑文件的内容或差异加入了上下文。"),
    "remote_session_change": ("远程会话更新", "运行时记录的远程会话变更信息。"),
    "queued_command": ("排队指令", "等待处理的指令记录。"),
    "prompt_snapshot": ("提示词快照", "运行时保存的提示词版本信息。"),
    "mcp_instructions_delta": ("MCP 指令更新", "MCP 工具提供的使用说明发生更新。"),
    "instructions": ("补充指令", "运行时加入的补充指令。"),
    "file": ("文件上下文", "文件内容或文件引用加入了上下文。"),
    "date": ("日期信息", "运行时提供的当前日期。"),
    "skill_listing": ("Skill 清单", "运行时提供的可用 Skill 信息。"),
    "session_context": ("会话上下文", "运行时补充的会话信息。"),
    "hook_success": ("Hook 完成信息", "Hook 执行结果加入了上下文。"),
    "model": ("模型信息", "运行时提供的模型说明。"),
}


def session_display(row):
    """Prefer native title, then a labelled first-message excerpt, then stable identity."""
    result = dict(row)
    title = (result.get("title") or "").strip()
    prompt = result.pop("first_prompt", None)
    workflow_label = result.pop("workflow_label", None)
    if title:
        origin = "native_title"
    elif isinstance(workflow_label, str) and workflow_label.strip():
        title, origin = workflow_label.strip(), "workflow_label"
    elif isinstance(prompt, str) and prompt.strip():
        title = re.sub(r"\s+", " ", prompt).strip()
        title = title[:72] + ("…" if len(title) > 72 else "")
        origin = "first_message"
    else:
        kind = {
            "subagent": "子代理",
            "workflow_agent": "工作流代理",
            "review": "审查",
            "import": "导入会话",
            "auxiliary": "辅助会话",
        }.get(result.get("kind"), "会话")
        identity = result.get("native_id") or result["session_uid"].removeprefix("session_")
        title = f"{AGENTS.get(result.get('agent'), result.get('agent', 'Agent'))} · {kind} · {identity[:12]}"
        origin = "identity"
    result.update(display_title=title, display_title_source=origin)
    return result


def _text(value, depth=0):
    """Read known text fields only; never stringify arbitrary native metadata as a message."""
    if depth > 4:
        return None
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, list):
        parts, chars = [], 0
        for item in value:
            part = _text(item, depth + 1)
            if part:
                chars += len(part) + bool(parts)
                parts.append(part)
                if chars > 8192:
                    break  # Keep the overflow character so the preview is marked truncated.
        return "\n".join(parts) or None
    if isinstance(value, dict):
        for name in ("text", "content", "stdout", "summary"):
            candidate = _text(value.get(name), depth + 1)
            if candidate:
                return candidate
        if isinstance(value.get("file"), dict):
            return _text(value["file"], depth + 1)
    return None


def event_display(event):
    """Describe structured-only events without inventing a missing message body."""
    kind, attrs, ext = event["kind"], event.get("attrs") or {}, event.get("ext") or {}
    title, body = KINDS.get(kind, kind), event.get("text") or None
    summary, fields = "", {}
    native = ext.get("native") if isinstance(ext.get("native"), dict) else {}
    attachment = ext.get("attachment", native.get("attachment", {}))
    context_type = attrs.get("context_type") or attrs.get("content_type")
    native_type = native.get("type")
    if kind == "unknown" and native_type in (
        "started",
        "result",
        "failed",
        "relocated",
        "continued-in",
    ):
        title = {
            "started": "工作流开始记录",
            "result": "工作流结果记录",
            "failed": "工作流失败记录",
            "relocated": "工作目录迁移",
            "continued-in": "会话续接记录",
        }[native_type]
        summary = "原生过程记录；当前保留原始结构供查看，不作为用户消息或成功结论。"
        fields = {
            key: native[key]
            for key in ("label", "phase", "agentId", "relocatedCwd", "continuedInSessionId")
            if key in native
        }
    elif kind == "context.inject":
        if isinstance(attachment, dict) and attachment:
            typ = attachment.get("type", "")
            title, summary = ATTACHMENTS.get(
                typ, ("上下文附件", f"结构化上下文记录：{typ or '类型未知'}。")
            )
            body = body or _text(attachment)
            if not body and typ == "instructions":
                body = _text(attachment.get("files"))
            if not body and typ in ("deferred_tools_delta", "mcp_instructions_delta"):
                body = _text(attachment.get("addedBlocks")) or _text(attachment.get("addedLines"))
            if (
                not body
                and typ == "session_context"
                and isinstance(attachment.get("context"), dict)
            ):
                body = _text(attachment["context"].get("gitStatus"))
            for name in (
                "entries",
                "addedNames",
                "removedNames",
                "failedMcpServers",
                "needsAuthMcpServers",
                "pendingMcpServers",
                "names",
                "files",
            ):
                if isinstance(attachment.get(name), list):
                    fields[name + "_count"] = len(attachment[name])
            for name in (
                "filename",
                "displayPath",
                "date",
                "hookEvent",
                "hookName",
                "exitCode",
                "durationMs",
                "usedTokens",
                "totalTokens",
            ):
                if isinstance(attachment.get(name), (str, int, float, bool)):
                    fields[name] = attachment[name]
            snapshot = attachment.get("snapshot")
            if typ == "environment" and isinstance(snapshot, dict):
                fields.update(
                    {
                        name: snapshot[name]
                        for name in ("workingDirectory", "platform", "shell", "isGitRepo")
                        if name in snapshot
                    }
                )
        elif context_type == "inherited_history":
            title, summary = (
                "继承的历史上下文",
                "由原生运行时重建的父会话上下文；不会再次计作用户消息、工具执行或模型请求。",
            )
            fields = {
                key: attrs[key]
                for key in ("parent_native_id", "native_kind", "parent_event_match")
                if key in attrs
            }
        elif context_type == "stream_provenance":
            title, summary = "流式记录索引", "关联流式分片与原始证据；没有独立的对话正文。"
        elif context_type in (
            "image",
            "input_image",
            "local_image",
            "localImage",
            "LocalImage",
            "Image",
            "audio",
            "Audio",
            "document",
            "file",
        ):
            title, summary = "媒体或文件附件", "这条记录引用媒体或文件，正文不以文本形式提供。"
            fields = {
                key: attrs[key]
                for key in ("content_type", "mime_type", "raw_content_path")
                if attrs.get(key) is not None
            }
        elif event.get("event_path") == "world_state":
            title, summary = "运行环境快照", "模型、工作目录或运行环境等结构化设置。"
            state = ext.get("state") or (native.get("payload") or {}).get("state") or {}
            if isinstance(state, dict):
                fields = {
                    key: state[key]
                    for key in ("model", "cwd", "effort", "model_provider")
                    if key in state
                }
        elif event.get("event_path") in (
            "session/title-llm-request",
            "web/deepseek-search-llm-request",
        ):
            title = (
                "标题生成请求" if event["event_path"].startswith("session/") else "搜索请求上下文"
            )
            summary = "内部请求的上下文与参数记录。"
        else:
            summary = "运行时加入的上下文信息。"
        if not body:
            body = _text(ext.get("content")) or _text(ext.get("message"))
        if not body and not summary:
            summary = "来源只记录了结构化上下文，没有提供文本正文。"
    elif kind == "tool.call":
        title += " · " + str(attrs.get("name", "未知工具"))
        if not body and attrs.get("input") is not None:
            body = json.dumps(attrs["input"], ensure_ascii=False, indent=2)
        summary = "工具调用参数。"
    elif kind == "tool.result":
        body = body or _text(attrs.get("output"))
        summary = "工具结果状态：" + str(attrs.get("status", "unknown")) + "。"
    else:
        if kind == "context.compaction":
            body = body or _text(ext.get("summary"))
        fields = {
            key: attrs[key]
            for key in ("model_raw", "provider", "effort_raw", "status", "cwd", "name", "reason")
            if attrs.get(key) is not None
        }
        summary = title + "，具体字段可在下方查看。"
    if kind == "context.inject" and not body and "没有" not in summary:
        summary += "该事件没有独立的文本正文。"
    truncated = bool(event.get("text_truncated")) or bool(body and len(body) > 8192)
    return {
        "title": title,
        "summary": summary,
        "body": body[:8192] if body else None,
        "fields": fields,
        "body_truncated": truncated,
        "category": "context" if kind == "context.inject" else "event",
    }
