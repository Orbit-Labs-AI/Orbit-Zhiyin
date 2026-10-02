"""Protocol state vocabulary; text never establishes execution success."""




STATES = {"message.assistant": "ASSISTANT_MESSAGE", "tool.call": "TOOL_CALL",
          "tool.result": "TOOL_RESULT", "error": "ERROR", "permission.request": "PERMISSION",
          "branch": "BRANCH", "context.compaction": "COMPACTION", "subagent.spawn": "SUBAGENT_SPAWN",
          "subagent.result": "SUBAGENT_RESULT", "turn.interrupted": "INTERRUPTION"}
STATES.update({"subagent.activity": "SUBAGENT_ACTIVITY", "subagent.message": "SUBAGENT_MESSAGE",
               "subagent.wait": "SUBAGENT_WAIT", "subagent.close": "SUBAGENT_CLOSE"})


RESULT_FIELDS = ("status", "status_scope", "exit_code", "error_class", "failure_reason",
                 "duration_ms", "duration_source", "duration_quality", "ended_at",
                 "known_command_results", "failed_command_results", "unknown_return_values",
                 "validation_result", "validation_report")
RESULT_FIELDS += ("native_execution_ms", "wall_elapsed_ms", "approval_wait_ms")


def result_status(call):
    """Only protocol evidence; a wrapper's success never erases inner uncertainty."""
    if call.get("pairing_status") == "conflict":
        return "unknown"
    status = call.get("status")
    if call.get("failed_command_results"):
        return "failed"
    if call.get("unknown_return_values") and status in ("success", "completed"):
        return "unknown"
    if status == "completed":
        return "success"
    if status in ("declined", "denied"):
        return "rejected"
    return status if status in ("success", "failed", "rejected", "interrupted", "running") else "unknown"
