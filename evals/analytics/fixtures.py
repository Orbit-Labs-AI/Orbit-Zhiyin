"""Synthetic fixtures shared by semantic quality and performance checks."""

def synthetic_events(size):
    """A worst-case long task with many delivery versions, each followed by feedback."""
    return [{"event_uid": f"e{i}", "session_uid": "s", "seq": i, "ts": i,
             "turn_uid": f"t{i // 2}", "kind": "message.assistant" if i % 2 == 0 else "message.user",
             "actor": "assistant" if i % 2 == 0 else "human", "text": "交付" if i % 2 == 0 else "可以了",
             "attrs": {"task_id": "task", "phase": "final" if i % 2 == 0 else None,
                       "origin": "assistant" if i % 2 == 0 else "human"}} for i in range(size)]
