"""Raw-log locate for a session (AN-16.1): file paths only, never contents.

Files come from ``raw_record`` (session_uid → file_id) joined to ``source_file`` and the
registered ``source`` root. A path is revealable only when its resolved target stays under
the resolved source root, so a symlink pointing outside is never followed or stat'ed.
"""

from __future__ import annotations

from pathlib import Path

FILES_SQL = """
SELECT DISTINCT sf.file_id, sf.relative_path, sf.source_id, src.agent, src.root_path
FROM raw_record rr
JOIN source_file sf ON sf.file_id = rr.file_id
JOIN source src ON src.source_id = sf.source_id
WHERE rr.session_uid = ?
ORDER BY sf.relative_path
"""


def file_entry(root_path: str, relative_path: str) -> dict:
    root = Path(root_path).expanduser()
    path = root / relative_path
    try:
        revealable = path.resolve().is_relative_to(root.resolve())
    except (OSError, RuntimeError):
        revealable = False
    exists, size = False, None
    if revealable and path.is_file():
        exists, size = True, path.stat().st_size
    return {"path": str(path), "exists": exists, "size": size, "revealable": revealable and exists}


def locate(conn, session_uid: str) -> dict:
    files = []
    for row in conn.execute(FILES_SQL, (session_uid,)):
        entry = file_entry(row["root_path"], row["relative_path"])
        files.append({**entry, "source_id": row["source_id"], "agent": row["agent"]})
    first = conn.execute("SELECT record_uid FROM event WHERE session_uid = ? ORDER BY seq LIMIT 1",
                         (session_uid,)).fetchone()
    if first is None:
        first = conn.execute("SELECT record_uid FROM raw_record WHERE session_uid = ? "
                             "ORDER BY file_id, ordinal LIMIT 1", (session_uid,)).fetchone()
    return {"session_uid": session_uid, "files": files,
            "first_record_uid": first[0] if first else None}
