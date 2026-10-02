"""Constructed (synthetic) bundles for the signal layer, metrics and insights API tests."""

from tandem_backend.analytics.context import AnalysisContext
from tandem_backend.analytics.inputs import AnalysisInputBundle, Scope
from tandem_backend.analytics.service import analyze_context
from tandem_backend.analytics.signals import build_signal_layer

T0 = 1_790_000_000_000
MIN = 60_000
DAY = 24 * 60 * MIN


class Session:
    """Append events and L3 tool calls in native order for one synthetic session."""

    def __init__(self, sid, *, kind="main", project="p1", source="src-a", root=None, ts=T0, **meta):
        self.row = {"session_uid": sid, "root_uid": root or sid, "kind": kind, "project_id": project,
                    "source_id": source, "started_at": ts, **meta}
        self.sid, self.events, self.calls, self.turns = sid, [], [], []
        self.seq, self.ts, self.turn = 0, ts, None

    def _event(self, kind, text=None, actor=None, **attrs):
        uid = f"{self.sid}-e{self.seq}"
        self.events.append({"event_uid": uid, "session_uid": self.sid, "seq": self.seq, "ts": self.ts,
                            "kind": kind, "actor": actor, "turn_uid": self.turn, "text": text,
                            "attrs": attrs})
        self.seq += 1
        self.ts += MIN
        return uid

    def user(self, text, **attrs):
        self.turn = f"{self.sid}-t{len(self.turns)}"
        self.turns.append({"turn_uid": self.turn, "session_uid": self.sid, "idx": len(self.turns),
                           "trigger": "human", "status": "completed"})
        return self._event("message.user", text, "human", origin="human", **attrs)

    def reply(self, text="好的，已经处理。", final=True):
        return self._event("message.assistant", text, "assistant",
                           **({"phase": "final"} if final else {}))

    def event(self, kind, **attrs):
        return self._event(kind, None, None, **attrs)

    def tool(self, head="pytest", *, kind="shell", status="failed", digest="d1", scope="command",
             complete=True, name=None, files=None, **extra):
        n = len(self.calls)
        call_uid = f"{self.sid}-c{n}"
        call_event = self._event("tool.call", None, "assistant", call_id=call_uid)
        result_event = self._event("tool.result", None, None, call_id=call_uid)
        self.events[-1]["ts"] = self.events[-2]["ts"]
        self.calls.append({"call_uid": call_uid, "session_uid": self.sid, "turn_uid": self.turn,
                           "call_event_uid": call_event, "result_event_uid": result_event,
                           "name_raw": name or ("Bash" if kind == "shell" else kind),
                           "name": name or kind, "kind": kind, "command_head": head,
                           "command_complete": complete, "status": status,
                           "exit_code": 0 if status == "success" else 1,
                           "status_scope": scope, "argument_digest": digest,
                           "argument_digest_kind": "sha256" if digest else None,
                           "files": files or [], "started_at": self.ts - 2 * MIN,
                           "duration_ms": 1200, "duration_quality": "reported",
                           "duration_source": "reported", "approval": None, **extra})
        return call_uid

    def interrupt(self):
        self.turns[-1]["status"] = "interrupted"


def bundle(sessions, *, model_calls=None, inventory=None, turns=True, legacy=False,
           tool_calls=True, events=True):
    rows = [s.row for s in sessions]
    coverage = {k: {"status": "available"} for k in
                ("events", "sessions", "projects", "tool_calls", "model_calls", "turns")}
    return AnalysisInputBundle(
        rows, [e for s in sessions for e in s.events] if events else None,
        [c for s in sessions for c in s.calls] if tool_calls else None,
        model_calls if model_calls is not None else [], coverage,
        turns=[t for s in sessions for t in s.turns] if turns else None,
        versions={"storage": "legacy-json-ledger"} if legacy else {}, inventory=inventory)


def analyze(b, scope=None, **kw):
    context = AnalysisContext.select(b, scope or Scope())
    result = analyze_context(context, False, with_recommendations=False)
    return context, result, build_signal_layer(context, result, **kw)


def detected(sessions, sid=None, **kw):
    _, _, layer = analyze(bundle(sessions, **kw))
    return layer.detected[sid or sessions[0].sid]


def retry_session(sid, *, head="pytest", n=3, **kw):
    s = Session(sid, **kw)
    s.user("请修复失败的测试")
    for _ in range(n):
        s.tool(head)
    s.reply()
    return s
