"""Read Codex rollouts without modifying any Codex file or database.

    Canonical response_item messages are preferred to event_msg UI mirrors.
    Guardian and delegated prompts are excluded from the user's profile.
    Source timestamps delimit logged spans, not CPU time or human effort.
"""

import json
import math
import re
import sqlite3
from contextlib import closing
from pathlib import Path

from ..content import embedded_artifact_body, measure_length
from ..models import Event, ParsedSession, Session, stable_id, utc_time
from ..privacy import direct_user_text, redact

MAX_TEXT = 12_000
MAX_LINE = 32 * 1024 * 1024


def metadata_index(codex_home: Path) -> dict[str, dict]:
    """Optional desktop metadata, in a consistent read-only SQLite transaction."""
    paths = sorted(codex_home.glob("state_*.sqlite"), key=lambda p: (
        int(m[1]) if (m := re.fullmatch(r"state_(\d+)\.sqlite", p.name)) else -1, p.name), reverse=True)
    if not paths:
        return {}
    try:
        with closing(sqlite3.connect(paths[0].resolve().as_uri() + "?mode=ro", uri=True)) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("BEGIN")
            columns = {row[1] for row in conn.execute("PRAGMA table_info(threads)")}
            wanted = [x for x in ("id", "title", "model", "thread_source", "git_origin_url") if x in columns]
            if "id" not in wanted:
                return {}
            return {row["id"]: dict(row) for row in conn.execute(f"SELECT {','.join(wanted)} FROM threads")}
    except sqlite3.Error:
        return {}  # JSONL is sufficient; newer metadata schemas may be unsupported.


def _text(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            part.get("text", "") for part in content
            if isinstance(part, dict) and isinstance(part.get("text"), str)
        )
    return ""


def _command_metadata(data: object) -> str | None:
    if not isinstance(data, dict) or not isinstance(data.get("output"), str):
        return None
    elapsed = data.get("wall_time_seconds")
    if not isinstance(elapsed, (int, float)) or isinstance(elapsed, bool) or elapsed < 0:
        return None
    try:
        if not math.isfinite(elapsed):
            return None
    except OverflowError:
        return None
    code = data.get("exit_code")
    if isinstance(code, int) and not isinstance(code, bool):
        return "success" if code == 0 else "failed"
    return None


def _command_output_hint(arguments: str) -> bool:
    """A syntax hint only; never execute or persist imported JavaScript."""
    try:
        envelope = json.loads(arguments)
        if isinstance(envelope, dict) and isinstance(envelope.get("code"), str):
            arguments = envelope["code"]
    except (ValueError, TypeError, RecursionError):
        pass
    stripped = re.sub(r"(?s)//[^\n]*|/\*.*?\*/|\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'|`(?:\\.|[^`\\])*`", " ", arguments)
    return bool(re.search(r"\btools\.(?:exec_command|write_stdin)\s*\(", stripped))


def _status_details(output: str, tool: str | None = None, command_outputs: bool = False) -> dict:
    """Keep transport status separate from arbitrary stdout and from script completion."""
    name = tool.rsplit(".", 1)[-1] if isinstance(tool, str) else ""
    command = name in ("exec_command", "write_stdin")
    try:
        data = json.loads(output)
    except (ValueError, TypeError, RecursionError):
        data = None
    if isinstance(data, dict):
        if data.get("isError") is True:
            return {"status": "failed", "status_scope": "explicit_tool_error"}
        code = data.get("exit_code")
        if command and isinstance(code, int) and not isinstance(code, bool):
            return {"status": "success" if code == 0 else "failed", "status_scope": "command_return"}
        if name == "exec" and command_outputs and (state := _command_metadata(data)):
            return {"status": state, "status_scope": "nested_command_return", "known_command_results": 1}
    # Never inspect stdout: a fixture printed by cat can contain a fake exit code.
    if command and output.startswith("Chunk ID:"):
        parts = re.split(r"\n(?:Final output|Output):", output, maxsplit=1)
        if len(parts) == 2 and re.search(r"^Wall time:", parts[0], re.M):
            match = re.search(r"^Process exited with code\s+(-?\d+)\s*$", parts[0], re.M)
            if match:
                return {"status": "success" if int(match[1]) == 0 else "failed", "status_scope": "command_transport"}
    if name != "exec":
        return {"status": None, "status_scope": "unknown"}
    wrapper = re.match(r"\AScript (completed|failed)\nWall time:?\s+\d+(?:\.\d+)? seconds\n", output)
    if not wrapper:
        return {"status": None, "status_scope": "unknown"}
    if wrapper[1] == "failed":
        return {"status": "failed", "status_scope": "orchestration_error"}
    if not command_outputs:
        return {"status": None, "status_scope": "orchestration_only"}
    body = output[wrapper.end():]
    if not body.startswith("Output:\n"):
        return {"status": None, "status_scope": "orchestration_only"}
    remaining = body[len("Output:\n"):].strip()
    states = []
    unknown = 0
    decoder = json.JSONDecoder()

    def collect(value, depth=0):
        nonlocal unknown
        if depth > 3:
            unknown += 1
        elif isinstance(value, list):
            for item in value:
                collect(item, depth + 1)
        elif isinstance(value, dict) and value.get("status") == "fulfilled" and "value" in value:
            collect(value["value"], depth + 1)
        elif state := _command_metadata(value):
            states.append(state)
        else:
            unknown += 1

    while remaining:
        try:
            value, end = decoder.raw_decode(remaining)
        except (ValueError, RecursionError):
            unknown += 1
            break
        collect(value)
        remaining = remaining[end:].lstrip()
    # A known failure is evidence even in a mixed batch. Success requires all
    # emitted values to be completed command returns, with no unparsed remainder.
    status = "failed" if "failed" in states else ("success" if states and not unknown else None)
    return {"status": status, "status_scope": "nested_command_returns", "known_command_results": len(states),
            "failed_command_results": states.count("failed"), "unknown_return_values": unknown}


def _status(output: str, tool: str | None = None, command_outputs: bool = False) -> str | None:
    """Compatibility helper for callers that need only the tri-state status."""
    return _status_details(output, tool, command_outputs)["status"]


def parse_rollout(
    path: Path, metadata: dict | None = None, before: str | None = None,
    exclude_sessions: set[str] | None = None,
) -> ParsedSession:
    metadata = metadata or {}
    cutoff = utc_time(before) if before else None
    if before and not cutoff:
        raise ValueError("before 必须是带时区的 ISO 时间")
    result = ParsedSession(None)
    turn_id, model = None, "unknown"
    calls: dict[str, Event] = {}
    turn_models: dict[str, str] = {}
    mirrors: list[Event] = []

    with path.open("rb") as stream:
        for ordinal, raw in enumerate(stream, 1):
            if len(raw) > MAX_LINE:
                result.warnings.append({"line": ordinal, "code": "oversized_line"})
                continue
            if not raw.endswith(b"\n"):
                result.warnings.append({"line": ordinal, "code": "incomplete_tail"})
                continue
            try:
                envelope = json.loads(raw)
            except (ValueError, UnicodeDecodeError, RecursionError):
                result.warnings.append({"line": ordinal, "code": "invalid_json"})
                continue
            if not isinstance(envelope, dict):
                result.warnings.append({"line": ordinal, "code": "invalid_envelope"})
                continue
            payload = envelope.get("payload", {})
            if not isinstance(payload, dict):
                continue
            kind = envelope.get("type")
            timestamp = utc_time(envelope.get("timestamp"))
            if cutoff and not timestamp:
                result.warnings.append({"line": ordinal, "code": "unclocked_at_snapshot"})
                if kind == "session_meta":
                    result.skipped_reason = "unclocked_metadata"
                    return result
                continue
            if kind != "session_meta" and cutoff and timestamp and timestamp > cutoff:
                continue
            if kind == "session_meta":
                if result.session:
                    continue  # Copied parent metadata must not change this file's identity.
                sid = str(payload.get("id") or payload.get("session_id") or stable_id(path))
                md = metadata.get(sid, {})
                source = payload.get("source", "unknown")
                if isinstance(source, dict) and "subagent" in source:
                    result.skipped_reason = "non_user_session"
                    return result
                if any(marker in ("guardian_review", "subagent") for marker in
                       (payload.get("thread_source"), md.get("thread_source"))):
                    result.skipped_reason = "non_user_session"
                    return result
                if sid in (exclude_sessions or set()):
                    result.skipped_reason = "evaluation_isolation"
                    return result
                if cutoff and timestamp and timestamp > cutoff:
                    result.skipped_reason = "after_snapshot"
                    return result
                cwd = str(payload.get("cwd") or "unknown")
                project = Path(cwd).name or "未知项目"
                # Full normalized path avoids collisions between identically named folders.
                project_key = str(Path(cwd).expanduser().resolve()) if cwd != "unknown" else cwd
                model = (md.get("model") or "unknown") if not cutoff else "unknown"
                result.session = Session(
                    sid, stable_id(project_key), project, cwd, str(path.resolve()), model,
                    "未命名会话" if cutoff else redact(str(md.get("title") or "未命名会话")), timestamp,
                    payload.get("forked_from_id"), "user", str(payload.get("cli_version", "unknown")),
                )
                continue
            if not result.session:
                continue
            if kind == "turn_context":
                turn_id = payload.get("turn_id") or turn_id
                model = payload.get("model") or model
                if turn_id:
                    turn_models[turn_id] = model
                result.session.model = model
                continue
            event_kind, text, call_id, tool, status, details = None, "", None, None, None, {}
            if kind == "response_item":
                ptype = payload.get("type")
                if ptype == "message" and payload.get("role") in ("user", "assistant"):
                    role = payload["role"]
                    phase = payload.get("channel") or payload.get("phase")
                    if phase == "analysis":
                        continue
                    original = _text(payload.get("content"))
                    text = direct_user_text(original) if role == "user" else redact(original)
                    if not text:
                        continue
                    event_kind = "user_message" if role == "user" else "assistant_message"
                    details = {"phase": phase, "original_chars": len(text), "message_digest": stable_id(text)}
                    if role == "user":
                        details["input_format"] = "question_reply" if original.strip().startswith(
                            "<send_user_message_question_reply>") else "prompt"
                    else:
                        details["writing_measurements"] = {surface: measure_length(text, {"surface": surface})
                                                           for surface in ("reply", "summary", "body")}
                        details["artifact_body_present"] = embedded_artifact_body(text)
                elif ptype in ("function_call", "custom_tool_call"):
                    event_kind, tool = "tool_call", payload.get("name")
                    call_id = payload.get("call_id")
                    # Do not retain arguments: they often contain full private documents or code.
                    arguments = str(payload.get("arguments", payload.get("input", "")))
                    details = {"arguments_chars": len(arguments), "argument_digest": stable_id(arguments)}
                    if isinstance(tool, str) and tool.rsplit(".", 1)[-1] == "exec":
                        details["command_output_hint"] = _command_output_hint(arguments)
                elif ptype in ("function_call_output", "custom_tool_call_output"):
                    event_kind, call_id = "tool_result", payload.get("call_id")
                    output = _text(payload.get("output"))
                    paired = calls.get(call_id)
                    status_info = _status_details(output, paired.tool if paired else None,
                                                  paired.details.get("command_output_hint", False) if paired else False)
                    status = status_info.pop("status")
                    details = {"output_chars": len(output), **status_info}
            elif kind == "event_msg":
                ptype = payload.get("type")
                if ptype == "task_started":
                    turn_id = payload.get("turn_id") or turn_id
                    event_kind = "turn_started"
                elif ptype in ("task_complete", "task_interrupted", "turn_aborted"):
                    event_kind = "turn_completed" if ptype == "task_complete" else "turn_interrupted"
                elif ptype == "token_count":
                    info = payload.get("info") or {}
                    if isinstance(info, dict) and isinstance(info.get("total_token_usage"), dict):
                        event_kind = "usage"
                        details = {"cumulative_tokens": info["total_token_usage"]}
                elif ptype in ("user_message", "agent_message"):
                    original = str(payload.get("message", ""))
                    text = direct_user_text(original) if ptype == "user_message" else redact(original)
                    if text:
                        mirror_details = {
                            "mirror": True, "original_chars": len(text), "message_digest": stable_id(text),
                            "input_format": "question_reply" if original.strip().startswith(
                                "<send_user_message_question_reply>") else "prompt"}
                        if ptype == "agent_message":
                            mirror_details["writing_measurements"] = {surface: measure_length(text, {"surface": surface})
                                                                      for surface in ("reply", "summary", "body")}
                            mirror_details["artifact_body_present"] = embedded_artifact_body(text)
                        mirrors.append(Event(stable_id(result.session.id, ordinal), result.session.id,
                                             ordinal, "user_message" if ptype == "user_message" else "assistant_message",
                                             timestamp, model, turn_id, text[:MAX_TEXT], details=mirror_details))
                    continue
            if not event_kind:
                continue
            event = Event(stable_id(result.session.id, ordinal), result.session.id, ordinal,
                          event_kind, timestamp, model, turn_id, text[:MAX_TEXT], call_id, tool, status,
                          details=details)
            if event_kind == "tool_call" and call_id:
                calls[call_id] = event
            if event_kind == "tool_result" and call_id in calls:
                start = calls[call_id]
                event.tool = start.tool
                if start.timestamp and event.timestamp:
                    from datetime import datetime
                    duration = (datetime.fromisoformat(event.timestamp) - datetime.fromisoformat(start.timestamp)).total_seconds() * 1000
                    if duration >= 0:
                        event.duration_ms = duration
                        event.details.update({"timing_quality": "logged_pair", "start": start.timestamp})
                    else:
                        result.warnings.append({"line": ordinal, "code": "negative_duration"})
            result.events.append(event)
    if not result.session:
        result.skipped_reason = "missing_metadata"
        return result
    # A second, different user message can arrive during the same turn. Its UI
    # mirror is still evidence when no canonical copy of that content exists.
    canonical = {(e.turn_id, e.kind, e.details["message_digest"]) for e in result.events if e.kind.endswith("message")}
    result.events.extend(e for e in mirrors if (e.turn_id, e.kind, e.details["message_digest"]) not in canonical)
    result.events.sort(key=lambda e: e.ordinal)
    for event in result.events:
        if event.turn_id in turn_models:
            event.model = turn_models[event.turn_id]
    return result
