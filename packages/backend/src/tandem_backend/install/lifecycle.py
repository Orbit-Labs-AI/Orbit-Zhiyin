"""IN-06 install lifecycle: installed → observing → kept / idle / reverted / archived.

Candidates and pending approvals belong to recommend; this covers what is on disk. Every
user-visible change writes one ledger row (archive / enable / disable). ``sweep`` is a
function the scheduler may call; nothing runs it automatically in the MVP.
"""

from __future__ import annotations

from . import store
from .errors import InstallError

STATES = {"installed", "observing", "kept", "idle", "reverted", "archived"}
TRANSITIONS = {
    "installed": {"observing", "kept", "idle", "reverted", "archived"},
    "observing": {"kept", "reverted", "idle", "archived"},
    "kept": {"idle", "reverted", "archived"},
    "idle": {"installed", "archived", "reverted"},
    "reverted": {"archived"},
    "archived": {"installed"},
}
LEDGER_ACTION = {"archived": "archive", "idle": "disable"}  # everything else re-enables


def _state(service, install_id: str) -> dict:
    state = store.state_get(service.appdb, install_id)
    if state is None:
        raise InstallError("not_found", f"安装不存在：{install_id}", http=404)
    return state


def transition(service, install_id: str, to: str, actor: str = "user") -> dict:
    """Move one install to ``to``; ``reverted`` really undoes the files via the service."""
    state = _state(service, install_id)
    current = state["state"]
    if to not in STATES or to not in TRANSITIONS.get(current, set()):
        raise InstallError("bad_transition", f"不能从 {current} 变为 {to}", http=409,
                           detail={"from": current, "to": to, "allowed": sorted(TRANSITIONS.get(current, ()))})
    if to == "reverted":
        result = service.revert(install_id, actor=actor)
        if not result["ok"]:
            raise InstallError("revert_refused", "部分文件在安装后被修改，未自动撤销", http=409, detail=result)
        return store.state_get(service.appdb, install_id)
    now = service.now_ms()
    fields = {"state": to}
    if to == "archived":
        fields["archived_at"] = now
    elif current == "archived":
        fields["archived_at"] = None
    if to == "kept":
        fields["observe_until"] = None
    with service.appdb.write() as db:
        store.state_update(db, install_id, **fields)
        store.ledger_append(db, [{"actor": actor, "action": LEDGER_ACTION.get(to, "enable"), "ts": now,
                                  "install_id": install_id, "plan_id": state["plan_id"],
                                  "candidate_id": state.get("candidate_id"), "note": f"{current}->{to}"}])
    return {**state, **fields}


def mark_triggered(service, install_id: str, ts: int) -> dict:
    """Recommend/analytics callback: the installed item was used at ``ts`` (ms)."""
    state = _state(service, install_id)
    with service.appdb.write() as db:
        store.state_update(db, install_id, last_triggered_at=max(ts, state.get("last_triggered_at") or 0))
    if state["state"] == "idle":
        return transition(service, install_id, "installed", actor="agent")
    return store.state_get(service.appdb, install_id)


def sweep(service, now: int, idle_days: int = 30) -> int:
    """installed/kept items not triggered for ``idle_days`` become idle. Returns the count."""
    cutoff = now - idle_days * 86_400_000
    stale = [s for s in store.state_list(service.appdb, None, limit=100_000)
             if s["state"] in ("installed", "kept") and (s.get("last_triggered_at") or s["installed_at"]) < cutoff]
    for s in stale:
        transition(service, s["install_id"], "idle", actor="tandem")
    return len(stale)
