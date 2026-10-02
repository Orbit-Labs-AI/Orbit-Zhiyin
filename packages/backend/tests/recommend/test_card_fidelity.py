"""Card fidelity: A7 / A1 / Lite / menubar / widget read backend card fields directly.

Offline only: ``fixtures/parity_inputs.json`` is RecInputs sanitised from the synthetic
parity probe (36 synthetic Codex sessions + the upstream signals they should emit).
"""

from __future__ import annotations

from test_rec_routes import env  # noqa: F401 - shared FastAPI fixture (fake gateway + inputs)

from tandem_backend.recommend import runs, store

# -- 0. run stability ----------------------------------------------------------------------

def test_empty_catalog_keeps_run_id(env, monkeypatch):  # noqa: F811
    """catalog.db present but empty (fresh install): repeated GETs reuse one run."""
    client, gw, _ = env
    gw.catalog = object()
    monkeypatch.setattr(runs, "_catalog_state", lambda catalog: (0, 0))
    first = client.get("/v1/recommendations").json()
    second = client.get("/v1/recommendations").json()
    assert first["run"]["run_id"] == second["run"]["run_id"]
    with gw.appdb.read() as conn:
        scope = store.get_run(conn, first["run"]["run_id"])["scope"]
    assert runs.run(gw, scope)["reused"] is True
    cid = first["items"][0]["candidate_id"]
    assert client.get(f"/v1/recommendations/{cid}").status_code == 200
