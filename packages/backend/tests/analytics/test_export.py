import json
from pathlib import Path

from orbit_backend.analytics.export import export_families, family_values, observations
from orbit_backend.analytics.inputs import AnalysisInputBundle
from orbit_backend.analytics.service import analyze_bundle


def result():
    data = json.loads((Path(__file__).parents[1] / "fixtures/analysis-input-v1.json").read_text())
    return analyze_bundle(AnalysisInputBundle.from_dict(data), with_text=False)


def resolve(document, pointer):
    for token in pointer.split("/")[1:]:
        token = token.replace("~1", "/").replace("~0", "~")
        document = document[int(token)] if isinstance(document, list) else document[token]
    return document


def test_export_has_every_declared_feature_once_with_exact_values_and_paths():
    analysis = result()
    families = family_values(analysis)
    names = [name for document in families.values() for name in document["features"]]
    assert len(names) == len(set(names)) == len(analysis["feature_dictionary"])
    assert set(names) == set(analysis["feature_dictionary"])
    for document in families.values():
        for field in document["features"].values():
            for row in field["observations"]:
                assert row["value"] == resolve(analysis, row["source_path"])
        for row in document["payload"]:
            assert row["value"] == resolve(analysis, row["source_path"])
    # Counts at different levels are all retained, never averaged for a preview.
    paths = [row["source_path"] for row in families["tools"]["features"]["call_count"]["observations"]]
    assert "/tools/totals/call_count" in paths
    assert any(path.startswith("/tools/by_tool/") for path in paths)
    assert any(path.startswith("/sessions/") for path in paths)


def test_missing_null_zero_false_and_empty_values_remain_distinct():
    document = {"records": [{"event_uid": "e", "zero": 0, "false": False, "unknown": None, "empty": []}]}
    assert observations(document, "records.*.absent") == []
    for key, value in (("zero", 0), ("false", False), ("unknown", None), ("empty", [])):
        row = observations(document, f"records.*.{key}")[0]
        assert row["value"] is value or row["value"] == value
        assert row["entity"] == {"event_uid": "e"}
    analysis = result()
    analysis["preferences"]["records"] = []
    fields = family_values(analysis)["preference"]["features"]
    assert all(field["observations"] == [] and field["missing_reason"] for field in fields.values())


def test_complete_local_files_include_unknown_families_and_private_permissions(tmp_path):
    analysis = result()
    exported = export_families(analysis, tmp_path / "features")
    manifest = json.loads((tmp_path / "features/index.json").read_text())
    assert exported["feature_count"] == len(analysis["feature_dictionary"])
    for family in manifest["families"]:
        doc = json.loads((tmp_path / f"features/{family}.json").read_text())
        assert set(doc["features"]) == set(manifest["families"][family]["features"])
        assert (tmp_path / f"features/{family}.md").exists()
    assert "cost_usd" in (tmp_path / "features/README.md").read_text()
    assert (tmp_path / "features/usage.json").stat().st_mode & 0o777 == 0o600
