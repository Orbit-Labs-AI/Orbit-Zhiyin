"""InstallService: plan → preview (digest) → apply (ledger, backups) → revert, plus reconcile.

Assembles the landing table / environment / fetch (P1) and the format ops / diff / risk /
atomic applier (P2). Cross-module hooks (recommend tracking and labels, platform telemetry,
inventory refresh) are imported lazily and may fail without affecting the install.
"""

from __future__ import annotations

import contextlib
import json
import secrets
import shutil
import time
from collections import OrderedDict
from pathlib import Path

from . import applier, ops, store
from . import cost as cost_mod
from . import risk as risk_mod
from .diff import line_diff
from .env import build_env
from .env import environment as env_environment
from .errors import InstallError, OpConflict, PlanError, RiskBlocked, StaleError
from .fetch import fetch_source
from .fetch import gc as fetch_gc
from .plan import default_catalog_lookup, digest, make_plan

OBSERVE_DAYS = 7
UNDO_WINDOW_MS = 10_000
OK_REVERT = ("reverted", "already_reverted")
TRUST_NOTE = "Codex 会在下次启动时要求信任新增的 hook；在 Codex 中确认后才会生效。"


def _text(data: bytes | None) -> str:
    return "" if data is None else data.decode("utf-8", "replace")


def _diff(before: str, after: str, ai_lines: set[int], context: int = 3) -> dict:
    return line_diff(before, after, context=context if before else None, ai_lines=ai_lines)


def _telemetry(name: str, value: float = 1.0, **tags) -> None:
    try:
        from ..platform import telemetry  # noqa: PLC0415 - optional, platform owns it

        telemetry.record(name, value, **tags)
    except Exception:  # noqa: BLE001
        pass


class InstallService:
    def __init__(self, appdb, home, *, reads=None, env=None, fetcher=None, jobs=None, clock=time.time,
                 catalog_lookup=None):
        self.appdb, self.home = appdb, Path(home)
        self.reads, self.fetcher, self.jobs, self.clock = reads, fetcher, jobs, clock
        self.env = env or build_env()
        self.catalog_lookup = catalog_lookup or default_catalog_lookup
        self.backups = self.home / "backups"
        self.lock_dir = self.home / "locks" / "install"
        self.cache_dir = self.home / "cache" / "install"
        self._previews: OrderedDict[str, dict] = OrderedDict()  # digest -> guards, for stale detail

    def now_ms(self) -> int:
        return int(self.clock() * 1000)

    # ---- environment / plan --------------------------------------------------------------------

    def environment(self, refresh: bool = False) -> dict:
        return env_environment(self.env, reads=self.reads, cache_dir=self.cache_dir, refresh=refresh)

    def plan(self, source: dict, agents=None, scope: str = "user", project_path: str | None = None,
             fetch: bool = False) -> dict:
        return make_plan(source, agents=agents, scope=scope, project_path=project_path, fetch=fetch, service=self)

    def _plan(self, plan_id: str) -> dict:
        plan = store.get_plan(self.appdb, plan_id)
        if plan is None:
            raise InstallError("plan_not_found", f"计划不存在：{plan_id}", http=404)
        if plan["status"] not in ("ready", "unmappable"):
            raise InstallError("plan_not_ready", f"计划状态为 {plan['status']}，尚不能预览",
                               http=409, detail={"status": plan["status"]})
        return plan

    # ---- preview -------------------------------------------------------------------------------

    def _evaluate(self, plan: dict, selected_units=None, disabled_targets=()) -> tuple[dict, dict]:
        spec = plan["spec"]
        sel = {int(k): (list(v) if v is not None else None) for k, v in (selected_units or {}).items()}
        disabled = sorted({int(i) for i in disabled_targets or ()})
        originals: dict[str, bytes | None] = {}
        chained: dict[str, bytes | None] = {}
        rows, conflicts, active, raw, chosen, guards, predicted = [], [], [], [], {}, {}, []
        backup_dir = self.backups / "<install_id>"
        for t in plan["targets"]:
            idx = t["idx"]
            row = {"idx": idx, "agent": t.get("agent"), "scope": t.get("scope"), "display": t.get("display"),
                   "path": t.get("path"), "action": t.get("action"), "mappable": bool(t.get("mappable")),
                   "reason": t.get("reason"), "requires_trust": bool(t.get("requires_trust")),
                   "shared_layer": bool(t.get("shared_layer")), "note": t.get("note"), "group": t.get("group"),
                   "exists": False, "guard_hash": None, "units": [], "diff": {"lines": [], "adds": 0, "dels": 0},
                   "command": None, "conflict": None}
            rows.append(row)
            if not t.get("mappable"):
                row["status"] = "unmappable"
                continue
            if idx in disabled:
                row["status"] = "disabled"
                continue
            all_units = ops.units(t)
            picked = sel.get(idx)
            ids = [u["id"] for u in all_units]
            chosen[idx] = sorted(ids if picked is None else [i for i in ids if i in set(picked)])
            row["units"] = [{**u, "selected": u["id"] in chosen[idx]} for u in all_units]
            if t.get("action") not in ops.WRITE_ACTIONS:
                row["status"] = "manual"
                content = t.get("content")
                row["command"] = content.get("argv") if isinstance(content, dict) else None
                active.append(t)
                continue
            path = t["path"]
            try:
                if path not in originals:
                    originals[path] = applier._read(Path(path))
                    chained[path] = originals[path]
                current = chained[path]
                target = ops.select(t, picked)
                render = ops.render(target, current)
                guard = ops.guard_hash(target, originals[path])
            except OpConflict as error:
                row["status"] = "conflict"
                row["conflict"] = {"code": error.code, "message": str(error), "detail": error.detail}
                conflicts.append({"idx": idx, **row["conflict"]})
                continue
            active.append(target)
            raw.append(t)
            status = render["status"]
            new = render["new"] if status != "noop" else current
            row.update(status=status, exists=originals[path] is not None, guard_hash=guard,
                       diff=_diff(_text(current), _text(new), set(render.get("ai_lines") or ())))
            guards[idx] = guard
            backup = str(backup_dir / f"{idx}-{Path(path).name}") if current is not None and status != "noop" else None
            row["backup_path"] = backup
            predicted.append({"idx": idx, "agent": t.get("agent"), "path": path, "display": t.get("display"),
                              "action": t["action"], "pointer": t.get("pointer"), "status": status,
                              "before_hash": ops.sha256(current), "after_hash": ops.sha256(new),
                              "backup_path": backup, "created_file": status == "create",
                              "applied": {**render["applied"], "created_dirs": []},
                              "file_mode": t.get("file_mode"), "block_id": t.get("block_id")})
            chained[path] = new
        risk = risk_mod.scan(spec, active)
        cost = cost_mod.estimate(spec, active)
        digest_value = digest({"plan_id": plan["plan_id"], "spec_hash": plan["spec_hash"],
                               "selected": {str(k): v for k, v in sorted(chosen.items())}, "disabled": disabled,
                               "guards": {str(k): v for k, v in sorted(guards.items())}, "risk": risk["level"]})
        self._previews[digest_value] = guards
        while len(self._previews) > 64:
            self._previews.popitem(last=False)
        writes = [p for p in predicted if p["status"] != "noop"]
        live = [r for r in rows if r["status"] not in ("unmappable", "disabled")]
        preview = {
            "plan_id": plan["plan_id"], "preview_digest": digest_value, "title": spec.get("title"),
            "kind": spec.get("kind"), "agents": plan["agents"], "scope": plan["scope"],
            "risk": risk, "cost": cost,
            "totals": {"files": len({p["path"] for p in writes}), "adds": sum(r["diff"]["adds"] for r in live),
                       "dels": sum(r["diff"]["dels"] for r in live)},
            "backup_dir": str(backup_dir), "targets": rows, "conflicts": conflicts,
            "warnings": plan.get("warnings") or [],
            "requires_trust": any(r["requires_trust"] for r in live),
            "requires_override": risk["level"] == "dangerous",
            "can_apply": not conflicts and bool(writes) and risk["level"] != "dangerous",
        }
        inner = {"raw": raw, "sel": {i: sel.get(i) for i in chosen}, "guards": guards,
                 "predicted": predicted, "writes": writes}
        return preview, inner

    def preview(self, plan_id: str, selected_units=None, disabled_targets=()) -> dict:
        return self._evaluate(self._plan(plan_id), selected_units, disabled_targets)[0]

    # ---- apply ---------------------------------------------------------------------------------

    def _written(self, install_id: str) -> list[dict]:
        keys = ("idx", "agent", "display", "path", "action", "status", "backup_path", "before_hash", "after_hash")
        rows = [r for r in store.ledger_for(self.appdb, install_id) if r["action"] == "install"]
        return [{k: (r["applied"] or {}).get(k) for k in keys} for r in sorted(rows, key=lambda r: r["target_idx"])]

    def _result(self, state: dict, risk: dict, warnings: list[str], requires_trust: bool) -> dict:
        return {"install_id": state["install_id"], "state": state["state"],
                "written": self._written(state["install_id"]),
                "undo_until_ms": state["installed_at"] + UNDO_WINDOW_MS, "tracking_id": state.get("tracking_id"),
                "risk": risk, "warnings": warnings, "requires_trust_note": TRUST_NOTE if requires_trust else None}

    def apply(self, plan_id: str, preview_digest: str, selected_units=None, disabled_targets=(),
              override_risk: bool = False) -> dict:
        plan = self._plan(plan_id)
        done = store.find_by_digest(self.appdb, plan_id, preview_digest)
        if done:  # same reviewed preview applied before: never install twice
            return self._result(done, {"level": done.get("risk_level")}, ["already_applied"], False)
        old_guards = self._previews.get(preview_digest)
        preview, inner = self._evaluate(plan, selected_units, disabled_targets)
        if preview["preview_digest"] != preview_digest:
            changed = sorted(i for i, g in inner["guards"].items() if old_guards is None or old_guards.get(i) != g)
            raise StaleError("preview_stale", "目标文件或选择在预览后发生变化，请重新预览",
                             detail={"preview_digest": preview["preview_digest"], "targets": changed})
        if preview["conflicts"]:
            first = preview["conflicts"][0]
            raise OpConflict(first["code"], first["message"], detail={"conflicts": preview["conflicts"]})
        risk = preview["risk"]
        if risk["level"] == "dangerous" and not override_risk:
            raise RiskBlocked("risk_blocked", "风险等级为 dangerous，需要显式 override_risk", detail=risk)
        if not inner["writes"]:
            raise PlanError("nothing_to_apply", "所选内容已存在，无需写入")
        spec = plan["spec"]
        candidate_id = plan["source_id"] if plan["source_type"] == "candidate" else None
        install_id = f"in_{time.time_ns():x}{secrets.token_hex(4)}"
        backup_dir = self.backups / install_id
        prepared = applier.preflight(inner["raw"], selected=inner["sel"], expect=inner["guards"],
                                     home=self.env.home)
        note = store.dumps({"preview_digest": preview_digest, "risk": risk["level"]})
        begin = []
        for p in inner["predicted"]:
            rec = {**p, "backup_path": p["backup_path"] and p["backup_path"].replace("<install_id>", install_id)}
            begin.append(self._ledger_row("install_begin", install_id, plan_id, candidate_id, rec, spec, note=note))
        with self.appdb.write() as db:
            store.ledger_append(db, begin)
        started = time.perf_counter()
        try:
            records = applier.apply_targets(prepared, backup_dir=backup_dir, lock_dir=self.lock_dir,
                                            install_id=install_id, home=self.env.home)
        except InstallError as error:
            with self.appdb.write() as db:
                store.ledger_append(db, [{"actor": "tandem", "action": "install_failed", "install_id": install_id,
                                          "plan_id": plan_id, "candidate_id": candidate_id,
                                          "note": store.dumps({"code": error.code, "detail": error.detail})}])
            _telemetry("install.failed", 1, kind=spec["kind"], code=error.code)
            raise
        warnings: list[str] = []
        now = self.now_ms()
        tracking_id = self._track(candidate_id, install_id, now, warnings)
        state = {"install_id": install_id, "plan_id": plan_id, "candidate_id": candidate_id,
                 "source_type": plan["source_type"], "source_id": plan["source_id"],
                 "title": spec.get("title") or spec["id"], "kind": spec["kind"], "agents": plan["agents"],
                 "scope": plan["scope"], "preview_digest": preview_digest,
                 "state": "observing" if tracking_id else "installed", "installed_at": now,
                 "observe_until": now + OBSERVE_DAYS * 86_400_000 if tracking_id else None,
                 "tracking_id": tracking_id, "risk_level": risk["level"]}
        by_idx = {t["idx"]: t for t in plan["targets"]}
        with self.appdb.write() as db:
            store.ledger_append(db, [self._ledger_row("install", install_id, plan_id, candidate_id,
                                                      {**rec, "requires_trust": bool(by_idx.get(rec["idx"], {})
                                                                                     .get("requires_trust"))},
                                                      spec, tracking_id=tracking_id) for rec in records])
            store.state_put(db, state)
        _telemetry("install.apply", 1, kind=spec["kind"], agents=",".join(plan["agents"]))
        _telemetry("install.apply_ms", (time.perf_counter() - started) * 1000, kind=spec["kind"])
        if self.jobs is not None:
            try:
                self.jobs.submit("inventory", origin="install")
            except Exception:  # noqa: BLE001 - a refresh is best effort
                warnings.append("inventory_refresh_failed")
        trust = any(by_idx.get(r["idx"], {}).get("requires_trust") for r in records)
        return self._result(state, risk, warnings, trust)

    def _ledger_row(self, action: str, install_id: str, plan_id: str, candidate_id, rec: dict, spec: dict,
                    **extra) -> dict:
        return {"actor": "tandem", "action": action, "install_id": install_id, "candidate_id": candidate_id,
                "plan_id": plan_id, "target_idx": rec["idx"], "target_agent": rec.get("agent"),
                "path": rec.get("path"), "op": rec.get("action"), "before_hash": rec.get("before_hash"),
                "after_hash": rec.get("after_hash"), "backup_path": rec.get("backup_path"),
                "created_file": bool(rec.get("created_file")), "applied": rec,
                "blob_ref": (spec.get("source") or {}).get("sha256"),
                "evidence_refs": spec.get("evidence_refs") or None, **extra}

    def _track(self, candidate_id, install_id: str, now: int, warnings: list[str]) -> str | None:
        if not candidate_id:
            return None
        try:
            from ..recommend.tracking import register  # noqa: PLC0415 - wired later, optional

            return register(candidate_id=candidate_id, install_id=install_id, installed_at=now)
        except Exception:  # noqa: BLE001
            warnings.append("tracking_unavailable")
            return None

    # ---- revert --------------------------------------------------------------------------------

    def revert(self, install_id: str, targets=None, *, actor: str = "user") -> dict:
        state = store.state_get(self.appdb, install_id)
        if state is None:
            raise InstallError("not_found", f"安装不存在：{install_id}", http=404)
        rows = store.ledger_for(self.appdb, install_id)
        installed = [r for r in rows if r["action"] == "install"]
        done = {r["target_idx"] for r in rows if r["action"] == "revert"}
        wanted = None if targets is None else {int(i) for i in targets}
        pending = [r for r in installed if r["target_idx"] not in done
                   and (wanted is None or r["target_idx"] in wanted)]
        results = applier.revert_records([r["applied"] for r in pending], backup_dir=self.backups / install_id,
                                         lock_dir=self.lock_dir) if pending else []
        results += [{"idx": r["target_idx"], "path": r["path"], "status": "already_reverted"}
                    for r in installed if r["target_idx"] in done and (wanted is None or r["target_idx"] in wanted)]
        results.sort(key=lambda r: r.get("idx") or 0)
        by_idx = {r["target_idx"]: r for r in installed}
        now = self.now_ms()
        entries = []
        for res in results:
            if res["idx"] in done:
                continue
            src = by_idx.get(res["idx"]) or {}
            ok = res["status"] in OK_REVERT
            entries.append({"actor": actor, "action": "revert" if ok else "revert_refused", "ts": now,
                            "install_id": install_id, "plan_id": state["plan_id"],
                            "candidate_id": state.get("candidate_id"), "target_idx": res["idx"],
                            "target_agent": src.get("target_agent"), "path": res.get("path"), "op": src.get("op"),
                            "before_hash": src.get("after_hash"), "after_hash": src.get("before_hash") if ok else None,
                            "backup_path": src.get("backup_path"), "note": res["status"]})
        reverted_idx = done | {r["idx"] for r in results if r["status"] in OK_REVERT}
        all_reverted = bool(installed) and all(r["target_idx"] in reverted_idx for r in installed)
        with self.appdb.write() as db:
            store.ledger_append(db, entries)
            if all_reverted and state["state"] != "reverted":
                store.state_update(db, install_id, state="reverted", reverted_at=now)
        if all_reverted and state["state"] != "reverted":
            state["state"] = "reverted"
            self._after_revert(state)
            _telemetry("install.revert", 1, kind=state["kind"])
        return {"install_id": install_id, "state": state["state"],
                "ok": all(r["status"] in OK_REVERT for r in results), "results": results}

    def _after_revert(self, state: dict) -> None:
        if not state.get("candidate_id"):
            return
        with contextlib.suppress(Exception):
            from ..recommend.tracking import stop  # noqa: PLC0415

            stop(state["install_id"])
        with contextlib.suppress(Exception):
            from ..recommend.labels import label  # noqa: PLC0415

            label(state["candidate_id"], "not_useful", source="install_revert")

    def revert_many(self, install_ids: list[str], *, actor: str = "user") -> dict:
        items = []
        for iid in install_ids:
            try:
                items.append(self.revert(iid, actor=actor))
            except InstallError as error:
                items.append({"install_id": iid, "ok": False, "error": error.code, "results": []})
        return {"ok": all(i["ok"] for i in items), "items": items}

    # ---- reads ---------------------------------------------------------------------------------

    def get(self, install_id: str) -> dict:
        state = store.state_get(self.appdb, install_id)
        if state is None:
            raise InstallError("not_found", f"安装不存在：{install_id}", http=404)
        return {"state": state, "ledger": store.ledger_for(self.appdb, install_id),
                "targets": self._written(install_id)}

    def list_state(self, state: str | None = None) -> list[dict]:
        return store.state_list(self.appdb, state)

    def ledger(self, install_id: str | None = None, limit: int = 50, before_ts: int | None = None) -> dict:
        entries = store.ledger_page(self.appdb, install_id, limit, before_ts)
        return {"entries": entries, "next": entries[-1]["ts"] if len(entries) == limit else None}

    def fetch(self, source: dict, refresh: bool = False) -> dict:
        """User-triggered download into the content-addressed cache; installs nothing."""
        result = fetch_source(source, cache_dir=self.cache_dir, fetcher=self.fetcher, refresh=refresh)
        if not result.get("cached"):
            with contextlib.suppress(Exception):
                fetch_gc(self.cache_dir)
        return result

    # ---- maintenance ---------------------------------------------------------------------------

    def reconcile(self) -> int:
        """Settle installs interrupted between ``install_begin`` and ``install``/``install_failed``."""
        fixed = 0
        for install_id in store.open_begins(self.appdb):
            begins = [r for r in store.ledger_for(self.appdb, install_id) if r["action"] == "install_begin"]
            by_path: dict[str, list[dict]] = {}
            for r in begins:
                by_path.setdefault(r["path"], []).append(r)
            current = {p: ops.sha256(applier._read(Path(p))) for p in by_path}
            complete = all(current[p] == rs[-1]["after_hash"] for p, rs in by_path.items())
            first = begins[0]
            if complete:
                plan = store.get_plan(self.appdb, first["plan_id"]) or {}
                spec = plan.get("spec") or {}
                meta = json.loads(first.get("note") or "{}")
                rows = [{**{k: r[k] for k in store.LEDGER_COLUMNS if k not in ("entry_id", "ts")},
                         "action": "install", "note": "reconciled"} for r in begins]
                with self.appdb.write() as db:
                    store.ledger_append(db, [*rows, {"actor": "tandem", "action": "reconcile",
                                                     "install_id": install_id, "plan_id": first["plan_id"],
                                                     "note": "promoted"}])
                    store.state_put(db, {
                        "install_id": install_id, "plan_id": first["plan_id"], "candidate_id": first["candidate_id"],
                        "source_type": plan.get("source_type") or "spec", "source_id": plan.get("source_id"),
                        "title": spec.get("title") or spec.get("id") or install_id, "kind": spec.get("kind") or "?",
                        "agents": plan.get("agents") or [], "scope": plan.get("scope") or "user",
                        "preview_digest": meta.get("preview_digest") or "", "state": "installed",
                        "installed_at": first["ts"], "risk_level": meta.get("risk")})
            else:
                partial = [r["applied"] for p, rs in by_path.items() if current[p] != rs[0]["before_hash"]
                           for r in rs]
                if partial:
                    applier.revert_records(partial, backup_dir=self.backups / install_id, lock_dir=self.lock_dir)
                with self.appdb.write() as db:
                    store.ledger_append(db, [{"actor": "tandem", "action": "install_failed", "install_id": install_id,
                                              "plan_id": first["plan_id"], "note": "reconciled: interrupted"}])
            fixed += 1
        return fixed

    def sweep_backups(self, keep: int = 50, days: int = 90) -> int:
        """Delete old backup dirs of reverted/archived/failed installs only."""
        if not self.backups.is_dir():
            return 0
        dirs = sorted((d for d in self.backups.iterdir() if d.is_dir()), key=lambda d: d.stat().st_mtime,
                      reverse=True)
        cutoff = self.clock() - days * 86400
        removed = 0
        for i, d in enumerate(dirs):
            state = store.state_get(self.appdb, d.name)
            if state is not None and state["state"] not in ("reverted", "archived"):
                continue
            if i >= keep or d.stat().st_mtime < cutoff:
                shutil.rmtree(d, ignore_errors=True)
                removed += 1
        return removed

    def sweep_plans(self, older_than_days: int = 30) -> int:
        return store.sweep_plans(self.appdb, older_than_days)
