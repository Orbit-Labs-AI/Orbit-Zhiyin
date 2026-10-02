"""Project identity: deleted worktrees and nested plain directories (constructed dsh data)."""

import json
import subprocess

from test_analysis_input_pushdown import session_rows

from tandem_data.contract import canonical
from tandem_data.store import Store


def build(tmp_path, cwds):
    with Store(tmp_path / "data") as store:
        source = store.add_source("dsh", tmp_path / "source")
        for n, cwd in enumerate(cwds):
            rows = session_rows(n, 1000 + n * 10)
            rows[0]["cwd"] = str(cwd)
            store.capture_stream(
                source, f"s{n}.jsonl", [(canonical(r) + "\n").encode() for r in rows]
            )
        store.rebuild()
        sessions = {
            row["native_id"]: row["project_id"]
            for row in store.db.execute("SELECT native_id,project_id FROM session")
        }
        projects = {
            row["project_id"]: dict(row) for row in store.db.execute("SELECT * FROM project")
        }
    return [sessions[f"s{n}"] for n in range(len(cwds))], projects


def git_repo(path):
    path.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    subprocess.run(
        ["git", "-C", str(path), "remote", "add", "origin", "git@github.com:synthetic/repo.git"],
        check=True,
    )


def test_deleted_worktree_folds_into_its_repository(tmp_path):
    repo = tmp_path / "repo"
    git_repo(repo)
    ids, projects = build(
        tmp_path,
        [repo / ".claude/worktrees/feature", repo / ".work/wt-fix/sub", repo],
    )
    assert len(set(ids)) == 1
    assert projects[ids[0]]["key"] == "github.com/synthetic/repo"


def test_deleted_worktree_of_deleted_repository_uses_the_repository_path(tmp_path):
    gone = tmp_path / "gone"
    ids, projects = build(tmp_path, [gone / ".work/wt-a", gone / ".claude/worktrees/b", gone])
    assert len(set(ids)) == 1
    assert projects[ids[0]]["key_type"] == "path"
    assert projects[ids[0]]["key"] == str(gone) and projects[ids[0]]["name"] == "gone"


def test_nested_plain_directories_join_the_outer_project(tmp_path):
    outer = tmp_path / "plain"
    (outer / "src/demo").mkdir(parents=True)
    other = tmp_path / "other"
    other.mkdir()
    # Deepest first: the result must not depend on session order.
    ids, projects = build(tmp_path, [outer / "src/demo", outer / "src", outer, other])
    assert ids[0] == ids[1] == ids[2] != ids[3]
    assert projects[ids[0]]["key"] == str(outer)
    assert set(json.loads(projects[ids[0]]["paths"])) >= {
        str(outer / "src"),
        str(outer / "src/demo"),
    }
