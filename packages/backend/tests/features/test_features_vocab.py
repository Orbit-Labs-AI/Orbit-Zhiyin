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
