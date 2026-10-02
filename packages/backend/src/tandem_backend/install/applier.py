"""Write and undo install targets on disk: all-or-nothing, backed up, crash-safe.

``preflight`` renders every writable target and checks guards/paths without touching
disk. ``apply_targets`` takes a per-file ``flock``, re-reads the file (a ``merge_json``
target is re-rendered inside the lock so concurrent unrelated edits survive), backs the
original up, writes via same-directory temp file + fsync + ``os.replace`` + directory
fsync, and on any failure restores already-written targets in reverse order.
``revert_records`` undoes byte-for-byte when the file is still exactly what we wrote, and
otherwise reverses only our units (``ops.unrender``); it never raises.
"""

from __future__ import annotations

import contextlib
import fcntl
import hashlib
import json
import os
import pwd
import secrets
import shutil
import stat
import time
from dataclasses import dataclass
from pathlib import Path

from . import ops
from .diff import three_way
from .errors import ApplyFailed, InstallError, OpConflict, StaleError

LOCK_TIMEOUT = 5.0
MANAGED_DIR = "/Library/Application Support/ClaudeCode/"
SENSITIVE_NAMES = (".claude.json", "config.toml")


@dataclass
class Prepared:
    target: dict
    path: Path
    current: bytes | None
    render: dict
    guard_before: str
    expected_guard: str


# ----------------------------------------------------------------------- helpers


def _real_home() -> Path:
    try:
        return Path(pwd.getpwuid(os.getuid()).pw_dir)
    except KeyError:
        return Path.home()


def _within(child: str, parent: str) -> bool:
    return child == parent or child.startswith(parent.rstrip(os.sep) + os.sep)


def _check_path(path: Path, home: Path) -> None:
    text = str(path)
    if not path.is_absolute():
        raise OpConflict("forbidden_path", detail={"path": text, "reason": "not absolute"})
    if _within(text, MANAGED_DIR.rstrip("/")) or ".git" in path.parts:
        raise OpConflict("forbidden_path", detail={"path": text})
    if os.environ.get("PYTEST_CURRENT_TEST"):
        real = _real_home()
        if _within(os.path.realpath(text), os.path.realpath(real)) and \
                Path(home).resolve() != real.resolve():
            raise ApplyFailed("refusing_real_home_in_tests", detail={"path": text})
    parent = os.path.realpath(path.parent)
    if not _within(os.path.realpath(text), parent):
        raise OpConflict("symlink_escape", detail={"path": text})
    if path.exists() and not stat.S_ISREG(path.stat().st_mode):
        raise OpConflict("not_regular_file", detail={"path": text})


def _read(path: Path) -> bytes | None:
    try:
        size = path.stat().st_size
    except FileNotFoundError:
        return None
    if size > ops.MAX_FILE_BYTES:
        raise OpConflict("file_too_large", detail={"path": str(path), "bytes": size})
    return path.read_bytes()


def _check_writable(path: Path) -> None:
    if path.exists():
        ok = os.access(path, os.W_OK) and os.access(path.parent, os.W_OK)
    else:
        probe = path.parent
        while not probe.exists() and probe != probe.parent:
            probe = probe.parent
        ok = probe.is_dir() and os.access(probe, os.W_OK)
    if not ok:
        raise OpConflict("read_only", detail={"path": str(path)})


@contextlib.contextmanager
def _lock(lock_dir: Path, path: Path):
    lock_dir.mkdir(parents=True, exist_ok=True)
    name = hashlib.sha1(str(path).encode()).hexdigest() + ".lock"
    fd = os.open(lock_dir / name, os.O_RDWR | os.O_CREAT, 0o600)
    deadline = time.monotonic() + LOCK_TIMEOUT
    try:
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise ApplyFailed("locked", detail={"path": str(path)}, http=423) from None
                time.sleep(0.05)
        yield
    finally:
        os.close(fd)


def _fsync_dir(directory: Path) -> None:
    fd = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _atomic_write(path: Path, data: bytes, mode: int) -> None:
    tmp = path.parent / f".tandem-{os.getpid()}-{secrets.token_hex(4)}"
    try:
        with open(tmp, "xb") as f:
            f.write(data)
            os.fchmod(f.fileno(), mode)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            tmp.unlink()
        raise
    _fsync_dir(path.parent)


def _mode_for(path: Path, file_mode: int | None) -> int:
    try:
        existing = path.stat().st_mode & 0o777
    except FileNotFoundError:
        return file_mode if file_mode is not None else 0o644
    if file_mode is None:
        return existing
    return file_mode & existing if path.name in SENSITIVE_NAMES else file_mode


def _make_parents(directory: Path) -> list[str]:
    missing = []
    probe = directory
    while not probe.exists():
        missing.append(probe)
        probe = probe.parent
    for d in reversed(missing):
        d.mkdir()
    return [str(d) for d in reversed(missing)]


def _remove_dirs(dirs: list[str]) -> None:
    for d in reversed(dirs or []):
        with contextlib.suppress(OSError):
            os.rmdir(d)


# --------------------------------------------------------------------- preflight


def preflight(targets: list[dict], *, selected: dict[int, list[str] | None],
              expect: dict[int, str] | None, home: Path) -> list[Prepared]:
    """Render and validate every writable target. Raises before anything is written."""
    prepared: list[Prepared] = []
    stale: list[int] = []
    for t in sorted(targets, key=lambda x: x.get("idx", 0)):
        if t.get("mappable") is False or t.get("action") not in ops.WRITE_ACTIONS:
            continue
        idx = t["idx"]
        path = Path(t["path"])
        _check_path(path, home)
        target = ops.select(t, (selected or {}).get(idx))
        current = _read(path)
        guard = ops.guard_hash(target, current)
        if expect and idx in expect and expect[idx] != guard:
            stale.append(idx)
            continue
        _check_writable(path)
        prepared.append(Prepared(target, path, current, ops.render(target, current), guard,
                                 expect[idx] if expect and idx in expect else guard))
    if stale:
        raise StaleError(detail={"targets": stale})
    return prepared


# ------------------------------------------------------------------------- apply


def _record(p: Prepared, render: dict, current: bytes | None, backup: Path | None,
            created_dirs: list[str]) -> dict:
    t = p.target
    applied = dict(render["applied"], created_dirs=created_dirs)
    new = render["new"] if render["status"] != "noop" else current
    return {
        "idx": t["idx"], "agent": t.get("agent"), "path": str(p.path),
        "display": t.get("display"), "action": t["action"], "pointer": t.get("pointer"),
        "status": render["status"], "before_hash": ops.sha256(current),
        "after_hash": ops.sha256(new), "guard_before": ops.guard_hash(t, current),
        "guard_after": ops.guard_hash(t, new),
        "backup_path": str(backup) if backup else None,
        "created_file": render["status"] == "create", "applied": applied,
        "file_mode": t.get("file_mode"), "block_id": t.get("block_id"),
    }


def _backup(p: Prepared, current: bytes, backup_dir: Path, install_id: str) -> Path:
    backup_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(backup_dir, 0o700)
    dest = backup_dir / f"{p.target['idx']}-{p.path.name}"
    shutil.copy2(p.path, dest)
    meta = {"path": str(p.path), "sha256": ops.sha256(current), "install_id": install_id,
            "ts": int(time.time() * 1000), "mode": p.path.stat().st_mode & 0o777}
    dest.with_name(dest.name + ".meta.json").write_text(json.dumps(meta))
    return dest


def _rerender(p: Prepared, current: bytes | None, written: dict[str, bytes | None]) -> dict:
    """Inside the lock: reuse, re-render (own earlier write / unrelated JSON edit) or stale."""
    if current == p.current:
        return p.render
    key = str(p.path)
    if key in written and written[key] == current:
        return ops.render(p.target, current)
    if p.target["action"] == "merge_json" and \
            ops.guard_hash(p.target, current) == p.expected_guard:
        return ops.render(p.target, current)
    raise StaleError(detail={"targets": [p.target["idx"]]})


def _undo_record(rec: dict) -> None:
    path = Path(rec["path"])
    if rec["status"] == "noop":
        return
    if rec.get("backup_path"):
        data = Path(rec["backup_path"]).read_bytes()
        _atomic_write(path, data, Path(rec["backup_path"]).stat().st_mode & 0o777)
    elif rec.get("created_file"):
        with contextlib.suppress(FileNotFoundError):
            path.unlink()
        _remove_dirs(rec["applied"].get("created_dirs"))


def apply_targets(prepared: list[Prepared], *, backup_dir: Path, lock_dir: Path,
                  install_id: str, home: Path) -> list[dict]:
    """Write all prepared targets or none. Returns one ledger record per target."""
    records: list[dict] = []
    written: dict[str, bytes | None] = {}
    held: set[str] = set()
    current_idx = None
    pending_dirs: list[str] = []
    with contextlib.ExitStack() as locks:
        try:
            for p in prepared:
                current_idx = p.target["idx"]
                _check_path(p.path, home)
                if str(p.path) not in held:
                    locks.enter_context(_lock(lock_dir, p.path))
                    held.add(str(p.path))
                current = _read(p.path)
                render = _rerender(p, current, written)
                if render["status"] == "noop":
                    records.append(_record(p, render, current, None, []))
                    continue
                backup = _backup(p, current, backup_dir, install_id) if current is not None \
                    else None
                mode = _mode_for(p.path, p.target.get("file_mode"))
                pending_dirs = _make_parents(p.path.parent)
                _atomic_write(p.path, render["new"], mode)
                records.append(_record(p, render, current, backup, pending_dirs))
                pending_dirs = []
                written[str(p.path)] = render["new"]
        except BaseException as exc:
            _remove_dirs(pending_dirs)
            rolled = []
            for rec in reversed(records):
                try:
                    _undo_record(rec)
                    rolled.append(rec["idx"])
                except OSError:
                    pass
            detail = {"failed_idx": current_idx, "rolled_back": rolled}
            if isinstance(exc, InstallError):
                exc.detail = {**(exc.detail or {}), **detail}
                raise
            if not isinstance(exc, Exception):
                raise
            raise ApplyFailed("apply_failed", str(exc),
                              detail={**detail, "error": type(exc).__name__}) from exc
    return records


# ------------------------------------------------------------------------ revert


def _manual_steps(rec: dict) -> list[str]:
    where = rec.get("display") or rec["path"]
    if rec.get("action") == "merge_json":
        what = f"JSON 位置 {rec.get('pointer') or '/'}"
    elif rec.get("block_id"):
        what = f"标记块 {rec['block_id']}"
    else:
        what = "整个文件"
    return [f"{where} 中 Tandem 写入的{what}在安装后被修改，未自动撤销。",
            "对照下方差异手动删除或保留这些内容；修改后可再次尝试撤销。"]


def _revert_one(rec: dict, backup_dir: Path | None, lock_dir: Path) -> dict:
    path = Path(rec["path"])
    out = {"idx": rec["idx"], "path": rec["path"]}
    if rec.get("status") == "noop" or rec.get("action") not in ops.WRITE_ACTIONS:
        return {**out, "status": "reverted"}
    applied = rec.get("applied") or {}
    backup = Path(rec["backup_path"]) if rec.get("backup_path") else None
    if backup is None and backup_dir is not None and not rec.get("created_file"):
        guess = backup_dir / f"{rec['idx']}-{path.name}"
        backup = guess if guess.exists() else None
    if backup is not None and not backup.exists():
        backup = None
    with _lock(lock_dir, path):
        current = _read(path)
        h = ops.sha256(current)
        if current is None:
            return {**out, "status": "already_reverted" if rec.get("created_file") else "missing"}
        if h == rec.get("after_hash") and (backup is not None or rec.get("created_file")):
            if backup is not None:
                _atomic_write(path, backup.read_bytes(), backup.stat().st_mode & 0o777)
            else:
                path.unlink()
                _remove_dirs(applied.get("created_dirs"))
            return {**out, "status": "reverted"}
        if h == rec.get("before_hash"):
            return {**out, "status": "already_reverted"}
        target = {"action": rec.get("action"), "pointer": rec.get("pointer"),
                  "block_id": rec.get("block_id")}
        undo = ops.unrender(applied, target, current)
        if undo["status"] == "reverted":
            if undo["delete"]:
                path.unlink()
                _remove_dirs(applied.get("created_dirs"))
            else:
                _atomic_write(path, undo["new"], path.stat().st_mode & 0o777)
            return {**out, "status": "reverted"}
        if undo["status"] == "modified":
            base = backup.read_bytes() if backup is not None else None
            ours = ops.reconstruct(applied, base) or b""
            diff = three_way((base or b"").decode("utf-8", "replace"), ours.decode("utf-8", "replace"),
                             current.decode("utf-8", "replace"))
            return {**out, "status": "modified", "diff": diff, "manual_steps": _manual_steps(rec)}
        return {**out, "status": undo["status"]}


def revert_records(records: list[dict], *, backup_dir: Path | None,
                   lock_dir: Path) -> list[dict]:
    """Undo records newest-first; per-item results, never raises."""
    results = []
    for rec in reversed(records):
        try:
            results.append(_revert_one(rec, backup_dir, lock_dir))
        except (InstallError, OSError, ValueError) as exc:
            results.append({"idx": rec.get("idx"), "path": rec.get("path"), "status": "error",
                            "error": getattr(exc, "code", type(exc).__name__)})
    return results
