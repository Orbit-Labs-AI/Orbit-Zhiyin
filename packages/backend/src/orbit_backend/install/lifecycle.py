"""IN-06 install lifecycle: installed → observing → kept / idle / reverted / archived.

Candidates and pending approvals belong to recommend; this covers what is on disk. Every
user-visible change writes one ledger row (archive / enable / disable).

The daily maintenance task (``platform.maintenance._install_sweep``) first calls
``record_usage`` and then ``sweep``:

- ``record_usage`` reads the imported ``tool_call`` facts in orbit.db and calls
  ``mark_triggered`` for every install that was really used. Only kinds whose use is
  observable in agent logs take part (``USAGE_KINDS``): a skill shows up as
  ``tool_call.skill``, an MCP server as ``tool_call.mcp_server``, a plugin as the
  ``<plugin>:`` prefix of its skills or its MCP server name. Permission rules, settings,
  rules, hooks, commands and subagents leave no per-use record we can attribute, so the
  sweep never idles them on "no trigger" — absence of evidence is not disuse.
- ``sweep`` moves observable installed/kept items untouched for ``idle_days`` to idle,
  and ends the observation window: an ``observing`` item past ``observe_until`` becomes
  ``kept`` if it was triggered since install, else ``idle`` (non-observable kinds become
  ``kept`` — we cannot prove disuse). Each move writes its ledger row via ``transition``.
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


USAGE_KINDS = {"skill", "mcp", "plugin"}
# One SQL per kind; ``?`` is one install name. Skills from plugins appear as "<plugin>:<skill>".
_USAGE_SQL = {
    "skill": "SELECT MAX(COALESCE(started_at, ended_at)) FROM tool_call "
             "WHERE skill = ?1 OR skill LIKE '%:' || ?1",
    "mcp": "SELECT MAX(COALESCE(started_at, ended_at)) FROM tool_call WHERE mcp_server = ?1",
    "plugin": "SELECT MAX(COALESCE(started_at, ended_at)) FROM tool_call "
              "WHERE skill LIKE ?1 || ':%' OR mcp_server = ?1 OR mcp_server LIKE 'plugin_' || ?1 || '_%'",
}


def _names(service, state: dict) -> set[str]:
    spec = (store.get_plan(service.appdb, state["plan_id"]) or {}).get("spec") or {}
    payload = spec.get("payload") or {}
    keys = ("plugin",) if state["kind"] == "plugin" else ("name",)
    return {str(payload[k]) for k in keys if payload.get(k)} or ({str(spec["id"])} if spec.get("id") else set())


def record_usage(service, reads=None) -> int:
    """Mark every observable, live install whose name appears in ``tool_call`` since it was
    installed. ``reads`` is the orbit.db read pool (defaults to ``service.reads``). Returns
    how many installs got a newer ``last_triggered_at``; 0 when orbit.db is not there yet."""
    reads = reads if reads is not None else service.reads
    if reads is None:
        return 0
    marked = 0
    live = [s for s in store.state_list(service.appdb, None, limit=100_000)
            if s["kind"] in USAGE_KINDS and s["state"] in ("installed", "observing", "kept", "idle")]
    for state in live:
        latest = None
        for name in _names(service, state):
            with reads.read() as db:
                ts = db.execute(_USAGE_SQL[state["kind"]], (name,)).fetchone()[0]
            if ts is not None and (latest is None or ts > latest):
                latest = ts
        if latest is not None and latest >= state["installed_at"] and latest > (state.get("last_triggered_at") or 0):
            mark_triggered(service, state["install_id"], latest)
            marked += 1
    return marked


def sweep(service, now: int, idle_days: int = 30) -> dict:
    """Idle-mark stale observable installs and close expired observation windows.

    Returns ``{"idle": n, "kept": n}`` — the number of items moved to each state."""
    cutoff = now - idle_days * 86_400_000
    moved = {"idle": 0, "kept": 0}
    for s in store.state_list(service.appdb, None, limit=100_000):
        triggered = s.get("last_triggered_at")
        if s["state"] in ("installed", "kept"):
            if s["kind"] in USAGE_KINDS and (triggered or s["installed_at"]) < cutoff:
                transition(service, s["install_id"], "idle", actor="orbit")
                moved["idle"] += 1
        elif s["state"] == "observing" and s.get("observe_until") is not None and s["observe_until"] <= now:
            used = triggered is not None and triggered >= s["installed_at"]
            to = "kept" if used or s["kind"] not in USAGE_KINDS else "idle"
            transition(service, s["install_id"], to, actor="orbit")
            moved[to] += 1
    return moved
