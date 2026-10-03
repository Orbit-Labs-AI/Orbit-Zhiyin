"""A8 library view: parts/m/why over a synthetic profile and 20 cross-kind items (offline)."""

import re

import pytest

from orbit_catalog import query
from orbit_catalog.contracts import Feature, Record, Resource, SourceSpec
from orbit_catalog.features import extract
from orbit_catalog.risk import scan
from orbit_catalog.service import CatalogService

from .test_storage import publish

KINDS = ["skill", "hook", "plugin", "subagent", "mcp_server", "rule", "workflow", "command"]
LOCAL = {"kind": "skill", "name": "PDF 小工具", "summary": "local pdf helper", "body": "# Steps\nSplit a .pdf file.",
         "agents": ["codex"], "self_check": {"passed": True, "checks": []}}


def record(n: int) -> Record:
    features = [Feature(feature="file_type", value=".pdf" if n % 2 else ".py", origin="declared")]
    if n % 5 == 0:
        features.append(Feature(feature="friction", value="retry_same_call", origin="curated", evidence="reviewed"))
    summary = f"tool number {n}" + (" stops a retry loop after the same failure" if n % 3 == 0 else "")
    resource = Resource(item_id=f"lib{n:02}", type=KINDS[n % len(KINDS)], name=f"Lib item {n:02}", summary=summary,
                        url=f"https://github.com/o/r{n}", license="MIT" if n % 2 else "GPL-3.0", official=n % 4 == 0,
                        agents=["claude_code", "codex"] if n % 2 else ["codex"], features=features,
                        metadata={"verification": "repository_and_source_read" if n % 3 == 0 else None,
                                  "source_updated_at": 1_700_000_000_000 + n},
                        popularity={"stars": 1000 - n})
    return Record(native_id=f"n{n}", resource=resource)


@pytest.fixture
def service(tmp_path):
    service = CatalogService(tmp_path / "catalog.db")
    service.store.register([SourceSpec(source_id="primary", kind="bundle", url="bundled:test", priority=90)])
    publish(service.store, [record(n) for n in range(20)])
    service.add_local(LOCAL)
    yield service
    service.close()


PROFILE = {"ok": True, "n_sessions": 40, "window_days": 30, "scope_hash": "h",
           "features": [{"fid": "ftype:.pdf", "feature": "file_type", "value": ".pdf", "weight": 1.0, "sessions": 19,
                         "label": ".pdf"},
                        {"fid": "friction:retry_same_call", "feature": "friction", "value": "retry_same_call",
                         "weight": 0.8, "sessions": 23, "label": "失败后重试"}]}


def test_parts_bounded_weights_sum_and_m_monotonic(service):
    view = service.library(profile=PROFILE, limit=50)
    assert abs(sum(view["weights"].values()) - 1) < 1e-9
    assert view["profile_basis"]["ok"] and view["total"] == len(view["items"]) > 10
    for item in view["items"]:
        assert all(0 <= v <= 1 for v in item["parts"].values())
        expected = round(100 * sum(view["weights"][k] * v for k, v in item["parts"].items()))
        assert item["m"] == expected and item["users"] is None and item["rec"] is None
        assert set(item) >= {"id", "kind", "kind_label", "src", "desc", "compat", "local", "why", "matched_features"}
    ms = [item["m"] for item in view["items"]]
    assert ms == sorted(ms, reverse=True)
    top = view["items"][0]
    assert top["parts"]["feature_overlap"] == 1 and any("19 个会话" in w for w in top["why"])
    curated = next(i for i in view["items"] if i["id"] == "lib05")  # odd → .pdf, n%5==0 → curated friction
    assert curated["parts"]["friction"] == 1.0 and any("失败后重试" in w for w in curated["why"])
    assert curated["src"] == "社区 · MIT" and curated["compat"] == "Claude Code · Codex"


def test_pain_sort_extracted_friction_and_pagination(service):
    pain = service.library(profile=PROFILE, sort="pain", limit=50)["items"]
    frictions = [i["parts"]["friction"] for i in pain]
    assert frictions == sorted(frictions, reverse=True)
    extracted = next(i for i in pain if i["id"] == "lib03")  # text "retry" only → extracted 0.6
    assert extracted["parts"]["friction"] == 0.6
    first = service.library(profile=PROFILE, limit=5)
    second = service.library(profile=PROFILE, limit=5, cursor=first["next_cursor"])
    assert not {i["id"] for i in first["items"]} & {i["id"] for i in second["items"]}
    with pytest.raises(ValueError, match="invalid_query"):
        service.library(profile=PROFILE, sort="hot")


def test_exclude_kind_and_local_tab(service):
    view = service.library(profile=PROFILE, exclude=["lib01", "lib05", "missing"], limit=50)
    ids = {i["id"] for i in view["items"]}
    assert not ids & {"lib01", "lib05"} and view["hidden_excluded"] == 2
    hooks = service.library(profile=PROFILE, kinds=["hook"], limit=50)["items"]
    assert hooks and all(i["kind"] == "hook" and i["kind_label"] == "Hook" for i in hooks)
    local = service.library(profile=PROFILE, tab="local")
    assert local["total"] == 1 and all(i["local"] and i["source_kind"] == "local" for i in local["items"])
    # .pdf matches (weight 1.0) but not the 0.8 friction: absolute share 1.0 / 1.8.
    assert local["items"][0]["parts"]["feature_overlap"] == round(1.0 / 1.8, 4)


def test_without_profile_no_personal_reasons(service):
    view = service.library(profile={"ok": False, "n_sessions": 0, "features": []}, limit=50)
    assert view["profile_basis"]["ok"] is False and view["items"]
    for item in view["items"]:
        assert item["parts"]["friction"] == 0 and item["parts"]["feature_overlap"] == 0
        assert not any(re.search(r"\d", w) for w in item["why"])
    searched = service.library(profile=None, q="retry loop", limit=50)["items"]
    assert searched and all(not re.search(r"\d", w) for i in searched for w in i["why"])


def test_extract_tags_bilingual_friction_as_extracted():
    for text in ("失败后重复同一命令就停下", "Stops a retry storm", "自动重试会被拦截"):
        resource = Resource(item_id="x", type="skill", name="guard", summary=text, url="")
        hits = [f for f in extract(resource) if (f.feature, f.value) == ("friction", "retry_same_call")]
        # One name/summary mention: mass 3 → 3/(3+1) = 0.75, times the 0.6 extracted-friction cap.
        assert hits and hits[0].origin == "extracted" and hits[0].weight == 0.45
    plain = Resource(item_id="y", type="skill", name="prompt helper", summary="improve prompts", url="")
    assert not any(f.feature == "domain" and f.value == "git.pr" for f in extract(plain))


def test_scan_marks_rm_rf_hook_dangerous():
    hook = Resource(item_id="h", type="hook", name="cleanup", url="",
                    manifest={"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "rm -rf ./tmp"}]}]}})
    result = scan(hook)
    assert result["verdict"] == "dangerous" and "destructive" in result["reasons"] and result["estimate"] is True
    assert any(f.feature == "hook_event" and f.value == "Stop" for f in extract(hook))
    mcp = Resource(item_id="m", type="mcp_server", name="gh", url="",
                   manifest={"packages": [{"identifier": "gh-mcp", "registryType": "npm", "transport": {"type": "stdio"},
                                           "environmentVariables": [{"name": "GITHUB_TOKEN", "isSecret": True}]}]})
    result = scan(mcp)
    assert result["verdict"] == "caution" and "needs_secret:GITHUB_TOKEN" in result["reasons"]
    found = {(f.feature, f.value) for f in extract(mcp)}
    assert ("transport", "stdio") in found and ("env_required", "GITHUB_TOKEN") in found


def test_detail_labels_scan_and_hook_install_reason(service):
    detail = query.get_item(service.store, "lib01")  # odd → hook? 1 % 8 == 1 → hook
    assert detail["kind"] == "hook" and detail["install"]["installable"] is False
    assert detail["install"]["reason"] == "hook_without_install_declaration"
    assert detail["license_spdx"] == "MIT" and detail["stars_scope"] == "repo" and detail["scan"]["verdict"] == "caution"
    batch = query.cards_by_id(service.store, ["lib02", "nope", "lib01"])
    assert [c["item_id"] for c in batch["items"]] == ["lib02", "lib01"] and batch["missing"] == ["nope"]


def test_search_match_is_absolute_not_relative_to_best_candidate(service):
    # "retry loop" occurs once in the summary of the n%3==0 items, never in a name: a body-only
    # hit saturates at 1/(1.2+1) = 0.45 per term, so the strength stays well below 1 and
    # m <= 100 · (0.5 · 0.45 + 0.2 · 1) = 42.5 even for the best candidate.
    view = service.library(profile=None, q="retry loop", limit=50)
    assert view["items"]
    assert all(i["parts"]["feature_overlap"] <= 0.45 and i["m"] <= 43 for i in view["items"])
    skills = service.library(profile=None, q="retry loop", kinds=["skill"], limit=50)
    m = {i["id"]: (i["m"], i["parts"]["feature_overlap"]) for i in view["items"]}
    assert skills["items"] and all(m[i["id"]] == (i["m"], i["parts"]["feature_overlap"]) for i in skills["items"])


def test_100000_profile_candidates_are_filtered_before_a_bounded_window(service, monkeypatch):
    # Populate only the card/feature projections under test. These synthetic rows do not
    # pretend to be full source imports or measure real user recommendation accuracy.
    with service.store.connect() as conn:
        columns = [row[1] for row in conn.execute("PRAGMA table_info(catalog_item)")]
        overrides = {"item_id": "printf('scale-%06d',n)", "name": "printf('Scale %06d',n)",
                     "name_key": "printf('scale %06d',n)", "type": "CASE WHEN n=99999 THEN 'hook' ELSE 'skill' END",
                     "stars": "n", "body_policy": "'index_only'", "verification": "'dataset_snapshot_read'"}
        values = ",".join(overrides.get(column, "i." + column) for column in columns)
        conn.execute("WITH RECURSIVE numbers(n) AS (VALUES(0) UNION ALL SELECT n+1 FROM numbers WHERE n<99999) "
                     f"INSERT INTO catalog_item ({','.join(columns)}) SELECT {values} FROM numbers "
                     "CROSS JOIN catalog_item i WHERE i.item_id='lib01'")
        conn.execute("INSERT INTO item_feature SELECT item_id,'domain','scale',1.0,'extracted','constructed' "
                     "FROM catalog_item WHERE item_id LIKE 'scale-%'")
        service.store._bump(conn)
    profile = {"ok": True, "features": [{"feature": "domain", "value": "scale", "weight": 1}]}
    built = []
    original = query.card
    def track(row):
        built.append(row["item_id"])
        return original(row)
    monkeypatch.setattr(query, "card", track)
    first = query.library(service.store, profile=profile, sort="stars", limit=20)
    assert len(built) == query.LIBRARY_PROFILE_CANDIDATES
    assert first["candidate_window"] == {"profile_limit": 1000, "profile_matches": 100000,
                                          "profile_truncated": True, "hybrid_candidates": 0}
    assert first["total_scope"] == "eligible_candidate_window" and first["total"] == 1000
    assert first["items"][0]["id"] == "scale-099999"
    second = query.library(service.store, profile=profile, sort="stars", limit=20, cursor=first["next_cursor"])
    assert second["items"][0]["id"] == "scale-099979"
    assert not {i["id"] for i in first["items"]} & {i["id"] for i in second["items"]}
    # Filter before top-K: only one matching hook lives at the opposite end of item-id order.
    hooks = query.library(service.store, profile=profile, kinds=["hook"])
    assert hooks["total"] == 1 and hooks["items"][0]["id"] == "scale-099999"
    assert hooks["candidate_window"]["profile_matches"] == 1
    excluded = query.library(service.store, profile=profile, kinds=["hook"], exclude=["scale-099999"], q="scale")
    assert excluded["items"] == []


def test_index_only_resource_is_profile_exploration_not_verified_remedy(service):
    resource = Resource(item_id="public-python", type="skill", name="Python practices", summary="Python workflows",
                        body="Python debugging verification", body_policy="index_only", agents=["codex"], language="en",
                        url="https://github.com/example/skills", metadata={"verification": "dataset_snapshot_read",
                                                                        "installable": False}, risk=["unverified_license"])
    publish(service.store, [Record(native_id="public-python", resource=resource)], mode="incremental")
    profile = {"ok": True, "window_days": 7, "features": [{"feature": "software", "value": "python", "weight": 1,
                                                            "sessions": 4, "label": "Python"}]}
    view = service.library(profile=profile)
    item = next(i for i in view["items"] if i["id"] == "public-python")
    assert item["parts"]["feature_overlap"] > 0 and item["why"] == ["你近 7 天在 4 个会话用到 Python"]
    assert not query.get_item(service.store, "public-python")["install"]["installable"]
    from orbit_catalog.contracts import MatchRequest
    request = MatchRequest(text="Python", purpose="recommendation", problem_id="p", problem_type="tool_retry",
                           scene="coding", agents=["codex"], language="en", evidence_ids=["e"], profile_evidence_ids=["p"],
                           features=[Feature(feature="dimension", value="verify")])
    assert not service.match(request)["items"]
