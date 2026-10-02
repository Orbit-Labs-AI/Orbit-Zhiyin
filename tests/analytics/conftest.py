import pytest

from tandem_backend.analytics.inputs import AnalysisInputBundle


def session(sid="s", **kw):
    return {"session_uid": sid, "root_uid": sid, "kind": "main", "project_id": "p", "started_at": 0, **kw}


def event(text="请编写报告", uid="e", seq=0, sid="s", ts=100, **attrs):
    return {"event_uid": uid, "session_uid": sid, "seq": seq, "ts": ts, "kind": "message.user",
            "actor": "human", "turn_uid": f"t-{uid}", "text": text, "attrs": {"origin": "human", **attrs}}


def bundle(events, sessions=None):
    return AnalysisInputBundle(sessions or [session()], events, [], [],
        {k: {"status": "available"} for k in ("events", "sessions", "projects", "tool_calls", "model_calls")})


@pytest.fixture
def fixtures():
    return session, event, bundle
