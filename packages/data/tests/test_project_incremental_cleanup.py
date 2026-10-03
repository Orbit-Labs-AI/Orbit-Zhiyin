"""Partial child-path projects must not change the final canonical project set."""

from orbit_data.contract import canonical
from orbit_data.reduce import project_for
from orbit_data.service import ImportRequest, ImportService
from orbit_data.store import Store
from orbit_data.validation.integrity import section_digests


def test_incremental_parent_project_matches_full_and_preserves_override(tmp_path):
    root = tmp_path / "source"
    (root / "sessions").mkdir(parents=True)
    files = []
    for name, cwd in (
        ("a-root", "/nonexistent-frozen-project/root"),
        ("z-child", "/nonexistent-frozen-project/root/part"),
    ):
        path = root / "sessions" / ("rollout-" + name + ".jsonl")
        path.write_text(
            canonical(
                {
                    "type": "session_meta",
                    "timestamp": "2026-10-02T00:00:00Z",
                    "payload": {"id": name, "cwd": cwd},
                }
            )
            + "\n"
        )
        files.append(path)
    homes = [tmp_path / "full", tmp_path / "incremental"]
    for home in homes:
        with Store(home) as store:
            manual = project_for(store, "/nonexistent-manual-project")
            store.db.execute(
                "INSERT INTO project_override(pattern,project_id) VALUES(?,?)",
                ("/nonexistent-manual-project/*", manual),
            )
            service = ImportService(store, maintenance="wait")
            if home == homes[0]:
                service.import_source(ImportRequest("codex", root, files=tuple(files)))
            else:
                service.import_source(ImportRequest("codex", root, files=(files[1],)))
                assert (
                    store.db.execute(
                        "SELECT COUNT(*) FROM project WHERE key=?",
                        ("/nonexistent-frozen-project/root/part",),
                    ).fetchone()[0]
                    == 1
                )
                service.import_source(ImportRequest("codex", root, files=(files[0],)))
            assert (
                store.db.execute(
                    "SELECT COUNT(*) FROM project WHERE project_id=?", (manual,)
                ).fetchone()[0]
                == 1
            )
            assert (
                store.db.execute(
                    "SELECT COUNT(*) FROM project WHERE key=?",
                    ("/nonexistent-frozen-project/root/part",),
                ).fetchone()[0]
                == 0
            )
            assert store.verify()["integrity"] == "ok"
    assert section_digests(homes[0]) == section_digests(homes[1])
