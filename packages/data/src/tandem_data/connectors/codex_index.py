"""Read only allowlisted Codex index columns in one SQLite snapshot."""

from tandem_data.contract import canonical

THREAD_COLUMNS = (
    "id rollout_path cwd name title preview created_at updated_at created_at_ms updated_at_ms "
    "archived source thread_source model model_provider reasoning_effort cli_version originator "
    "git_sha git_branch git_origin_url project_id agent_nickname agent_role agent_path"
).split()
TABLES = (
    ("threads", THREAD_COLUMNS, "state_index"),
    ("thread_spawn_edges", ["parent_thread_id", "child_thread_id", "status"], "spawn_edge"),
    ("projects", ["id", "name"], "project_index"),
    ("project_roots", ["project_id", "path", "position"], "project_root"),
)


def index_rows(path):
    from tandem_data.store import readonly_connection

    with readonly_connection(path) as db:
        db.execute("BEGIN")
        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        for table, allowed, kind in TABLES:
            if table not in tables:
                continue
            columns = {r["name"] for r in db.execute(f"PRAGMA table_info({table})")}
            selected = [c for c in allowed if c in columns]
            if selected:
                names = ",".join(selected)
                for row in db.execute(f"SELECT {names} FROM {table} ORDER BY {names}"):
                    yield (canonical({"type": kind, "payload": dict(row)}) + "\n").encode()
