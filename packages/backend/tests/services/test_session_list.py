"""/v1/sessions: session model, kind field and kind filter (synthetic fixtures only)."""

from __future__ import annotations

from orbit_data.service import ImportRequest, ImportService
from orbit_data.store import Store
from orbit_data.validation.fixtures import create_sources


def imported_home(tmp_path):
    roots = create_sources(tmp_path / "fixtures")
    home = tmp_path / "home"
    with Store(home) as store:
        service = ImportService(store)
        for agent, root in roots.items():
            service.import_source(ImportRequest(agent, root))
    return home


def test_sessions_report_model_kind_and_filter(tmp_path, client_factory):
    home = imported_home(tmp_path)
    import sqlite3

    with sqlite3.connect(home / "orbit.db") as db:
        # The fixtures only hold main sessions; mark one as a review run.
        db.execute(
            "UPDATE session SET kind='review' WHERE session_uid="
            "(SELECT MIN(session_uid) FROM session)"
        )
        kinds = dict(db.execute("SELECT kind, COUNT(*) FROM session GROUP BY kind").fetchall())
        modeled = {r[0] for r in db.execute("SELECT DISTINCT session_uid FROM model_call")}
    assert kinds.get("main") and len(kinds) > 1, kinds
    client, _ = client_factory(home)

    default = client.get("/v1/sessions", params={"limit": 200})
    assert default.status_code == 200
    assert int(default.headers["x-total-count"]) == kinds["main"]
    assert {s["kind"] for s in default.json()} == {"main"}
    assert all(s["agent"] for s in default.json())

    everything = client.get("/v1/sessions", params={"limit": 200, "kind": "all"}).json()
    assert len(everything) == sum(kinds.values())
    with_model = [s for s in everything if s["id"] in modeled]
    assert with_model and all(s["model"] != "unknown" for s in with_model)

    other = next(k for k in kinds if k != "main")
    both = client.get("/v1/sessions", params={"limit": 200, "kind": f"main,{other}"})
    assert int(both.headers["x-total-count"]) == kinds["main"] + kinds[other]
    bad = client.get("/v1/sessions", params={"kind": "nope"})
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "invalid_kind"


def test_projects_hide_empty_and_disambiguate_names(tmp_path, client_factory):
    home = imported_home(tmp_path)
    import sqlite3

    with sqlite3.connect(home / "orbit.db") as db:
        used = db.execute(
            "SELECT p.project_id, p.name FROM project p JOIN session s USING(project_id)"
            " GROUP BY p.project_id ORDER BY p.project_id LIMIT 1"
        ).fetchone()
        db.execute("INSERT INTO project VALUES('p_empty','path','/x/empty','empty',NULL,'[]')")
        db.execute(
            "INSERT INTO project VALUES('p_twin','path',?,?,NULL,'[]')",
            (f"/elsewhere/{used[1]}", used[1]),
        )
        db.execute(
            "UPDATE session SET project_id='p_twin' WHERE session_uid="
            "(SELECT MAX(session_uid) FROM session WHERE project_id=?)",
            (used[0],),
        )
        db.execute(
            "UPDATE session SET kind='review' WHERE session_uid="
            "(SELECT MIN(session_uid) FROM session WHERE project_id=?)",
            (used[0],),
        )
        main = db.execute(
            "SELECT COUNT(*) FROM session WHERE project_id=? AND kind='main'", (used[0],)
        ).fetchone()[0]
    client, _ = client_factory(home)

    listed = {p["project_id"]: p for p in client.get("/v1/projects").json()}
    assert "p_empty" not in listed
    assert "p_empty" in {
        p["project_id"] for p in client.get("/v1/projects", params={"include_empty": "true"}).json()
    }
    assert listed["p_twin"]["name"] == f"{used[1]} (elsewhere)"
    assert listed[used[0]]["name"] != listed["p_twin"]["name"]
    assert "key" not in listed["p_twin"]
    page = client.get("/v1/sessions", params={"project_id": used[0], "limit": 200})
    assert listed[used[0]]["sessions"] == int(page.headers["x-total-count"]) == main
    assert listed[used[0]]["sessions_all"] == main + 1
