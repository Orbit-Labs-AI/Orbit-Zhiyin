from tandem_backend.features.vocab import (
    command_info,
    from_catalog_feature,
    from_session_feature,
    path_markers,
    to_catalog_pairs,
    vocab_table,
)


def test_session_feature_golden():
    assert from_session_feature("tool_category", "shell") == ["tool:shell"]
    assert from_session_feature("mcp_server", "Playwright") == ["mcp:playwright", "tool:browser"]
    assert from_session_feature("skill", "PDF Tools") == ["skill:pdf-tools"]
    assert from_session_feature("command_head", "git status") == [
        "cmd:git status", "cmdfam:vcs", "cmdcls:readonly"]
    assert from_session_feature("file_extension", ".PY") == ["ftype:.py", "lang:python"]
    assert from_session_feature("file_extension", ".lock") == ["ftype:.lock"]
    assert from_session_feature("unknown", "x") == []


def test_command_classes():
    assert command_info("rm")["cls"] == "destructive"
    assert command_info("git push")["cls"] == "destructive"
    assert command_info("git commit")["cls"] == "write"
    assert command_info("curl")["cls"] == "network"
    assert command_info("/usr/bin/ls")["head"] == "ls"
    assert command_info("docker rm")["family"] == "infra"
    assert command_info("frobnicate") == {"head": "frobnicate", "family": "other", "cls": "unknown"}
    assert command_info("")["cls"] == "unknown"


def test_catalog_roundtrip():
    pairs = [("domain", "testing"), ("software", "docker"), ("tool_kind", "browser"),
             ("command", "git"), ("file_type", ".py"), ("agent", "claude_code"),
             ("language", "python"), ("framework", "nextjs"), ("mcp_server", "github"),
             ("error_class", "timeout"), ("friction", "tool_error")]
    for feature, value in pairs:
        fids = from_catalog_feature(feature, value)
        assert fids, (feature, value)
        assert (feature, value) in to_catalog_pairs(fids[0])
    assert from_catalog_feature("nonsense", "x") == []
    assert ("file_type", ".tsx") in to_catalog_pairs("lang:typescript")
    assert to_catalog_pairs("cmd:git status") == [("command", "git")]
    assert to_catalog_pairs("cmdcls:readonly") == []


def test_path_markers_and_table():
    assert path_markers("/x/App.xcodeproj/project.pbxproj") == ["fw:xcode"]
    assert path_markers("web/next.config.mjs") == ["fw:nextjs"]
    assert path_markers("Package.swift") == ["fw:swiftpm"]
    table = vocab_table()
    assert table["version"] == "vocab-1"
    assert "readonly" in table["namespaces"]["cmdcls"]["values"]
    assert len(table["friction"]) == 6


def _cls(cmd, head=None):
    return command_info(head or cmd.split()[0], cmd)["cls"]


def test_dangerous_arguments_downgrade_readonly_heads():
    """UT-07: risk is judged by arguments when the full command is known."""
    assert _cls("git branch -D feature", "git branch") == "destructive"
    assert _cls("git branch --delete old", "git branch") == "destructive"
    assert _cls("git branch new-feature", "git branch") == "write"  # creates a branch
    assert _cls("git branch -m old new", "git branch") == "write"
    assert _cls("git branch -a -v", "git branch") == "readonly"
    assert _cls("git branch --list 'feat/*'", "git branch") == "readonly"
    assert _cls("find . -name '*.pyc' -delete") == "destructive"
    assert _cls("find . -name x -exec rm {} ;") == "destructive"  # rm segment after ';'
    assert _cls("find . -type f -name '*.py'") == "readonly"
    assert _cls("sed -i 's/a/b/' f.txt") == "write"
    assert _cls("sed -i.bak 's/a/b/' f.txt") == "write"
    assert _cls("sed --in-place 's/a/b/' f.txt") == "write"
    assert _cls("sed -n '1,20p' f.txt") == "readonly"
    assert _cls("echo hi > notes.txt") == "write"
    assert _cls("echo hi >> notes.txt") == "write"
    assert _cls("ls > /dev/null 2>&1") == "readonly"
    assert _cls("echo hi") == "readonly"
    assert _cls("cat a.txt | tee b.txt") == "write"
    assert _cls("ls && rm -rf build") == "destructive"
    assert _cls("uv run python manage.py migrate", "uv run") == "write"
    assert _cls("uv run ./scripts/anything.sh", "uv run") == "unknown"
    assert _cls("uv run pytest -q", "uv run") == "write"
    assert command_info("uv run", "uv run pytest -q")["family"] == "test"
    # argv lists and their JSON text (event.attrs.input.command) are accepted too.
    assert command_info("sed", ["/bin/zsh", "-lc", "sed -i s/a/b/ f"])["cls"] == "write"
    assert command_info("ls", '["ls", "-la"]')["cls"] == "readonly"


def test_conditional_heads_without_arguments_are_unknown():
    for head in ("find", "git branch", "sed", "uv run"):
        assert command_info(head)["cls"] == "unknown", head
    assert command_info("ls")["cls"] == "readonly"  # argument-independent heads keep class
