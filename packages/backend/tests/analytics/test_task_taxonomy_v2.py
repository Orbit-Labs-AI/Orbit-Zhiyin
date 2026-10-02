"""Fixed synthetic semantic regression cases, never extracted personal history."""

import copy
import json
from importlib.resources import files

import pytest

from tandem_backend.analytics.common import semantic_messages
from tandem_backend.analytics.task import extract_task_features, summarize_task_distribution
from tandem_backend.analytics.task.taxonomy import DOMAIN_DETAILS, DOMAINS, TAXONOMY_VERSION

CORPUS = json.loads(files("tandem_backend").joinpath("data/task-domain-corpus-v2.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", CORPUS["development"], ids=lambda case: case["id"])
def test_development_corpus_exact_detail_sets(case, fixtures):
    session, event, _ = fixtures
    result = extract_task_features(semantic_messages([event(case["text"])], [session()]))
    assert sorted(d["id"] for d in result["domain_details"] or []) == sorted(case["expected_details"])


@pytest.mark.parametrize("case", CORPUS["heldout"], ids=lambda case: case["id"])
def test_heldout_style_compositional_cases(case, fixtures):
    session, event, _ = fixtures
    result = extract_task_features(semantic_messages([event(case["text"])], [session()]))
    assert sorted(d["id"] for d in result["domain_details"] or []) == sorted(case["expected_details"])


def test_corpus_covers_each_domain_and_is_packaged():
    assert len(DOMAIN_DETAILS) == 27
    assert set(DOMAINS) == {"software", "mathematics", "data_analysis", "writing", "design", "education"}
    assert CORPUS["taxonomy_version"] == TAXONOMY_VERSION
    for split in ("development", "heldout"):
        assert set(DOMAIN_DETAILS) <= {label for case in CORPUS[split] for label in case["expected_details"]}
    assert not ({case["text"] for case in CORPUS["development"]} & {case["text"] for case in CORPUS["heldout"]})


@pytest.mark.parametrize("text", [
    "Please react to this paragraph", "Create a travel agent brochure", "Please clean the rag",
    "请不要实现前端组件，也请不要创建后端接口", "任务名称：请重构数据库", "我刚刚修复代码",
])
def test_ambiguous_short_words_and_reported_actions_abstain(text, fixtures):
    session, event, _ = fixtures
    result = extract_task_features(semantic_messages([event(text)], [session()]))
    assert result["domain_details"] is None


def test_forbidden_action_does_not_hide_current_request_after_contrast(fixtures):
    session, event, _ = fixtures
    result = extract_task_features(semantic_messages([event("不要实现后端接口但请创建海报")], [session()]))
    assert result["domain"] == ["design"]
    assert [d["id"] for d in result["domain_details"]] == ["design.visual"]


@pytest.mark.parametrize("text, expected", [
    ("请整理微分谱的实验记录", False),
    ("请展示微分截面的测量结果", False),
    ("请推导一阶微分方程", True),
    ("请计算微分谱曲线的积分", True),
])
def test_physics_compound_terms_do_not_borrow_math_prefix(text, expected, fixtures):
    session, event, _ = fixtures
    result = extract_task_features(semantic_messages([event(text)], [session()]))
    assert ("mathematics" in (result["domain"] or [])) is expected
    assert ("math.calculus" in {d["id"] for d in result["domain_details"] or []}) is expected


def test_specificity_does_not_turn_transition_matrix_into_math(fixtures):
    session, event, _ = fixtures
    result = extract_task_features(semantic_messages([event("请生成工具调用转移矩阵")], [session()]))
    assert result["domain"] == ["data_analysis"]
    assert result["domain_details"][0]["id"] == "data.visualization"
    proof = extract_task_features(semantic_messages([event("请上传付款证明")], [session()]))
    assert proof["domain"] is None
    report = extract_task_features(semantic_messages([event("请总结测试报告")], [session()]))
    assert report["domain"] == ["writing"]
    assert report["task_type"] == ["summarize"]


def test_contextual_match_has_auditable_evidence_and_session_identity(fixtures):
    session, event, _ = fixtures
    es = [event("请测试这个后端函数", "a", 0, "one"), event("请实现前端组件", "b", 0, "two")]
    result = extract_task_features(semantic_messages(es, [session("one"), session("two")]))
    details = {d["id"]: d for d in result["domain_details"]}
    debug = details["software.testing_debugging"]
    assert debug["parent_id"] == "software" and debug["parent_label"] == "软件工程"
    assert debug["status"] == "candidate" and debug["taxonomy_version"] == TAXONOMY_VERSION
    assert debug["evidence"][0]["match_basis"] == "term_with_context"
    assert debug["evidence"][0]["context_term"] == "后端"
    assert debug["evidence"][0]["session_uid"] == "one"
    assert result["label_evidence"]["domain_details"]["software.frontend"][0]["session_uid"] == "two"


def test_counts_are_per_distinct_task_and_old_records_remain_unknown(fixtures):
    session, event, _ = fixtures
    current = {"task_id": "new", **extract_task_features(semantic_messages([
        event("请实现前端前端前端组件", "a"), event("继续实现前端组件", "b", 1)
    ], [session()]))}
    legacy = {"task_id": "old", "domain": ["software"], "task_type": ["create"]}
    incomplete = {"task_id": "missing"}
    inputs = [current, current, legacy, incomplete]
    before = copy.deepcopy(inputs)
    summary = summarize_task_distribution(inputs)
    assert summary["task_count"] == 3
    assert summary["domain_details"]["counts"] == {"software.frontend": 1}
    assert summary["domain_details"]["effective_n"] == 1
    assert summary["domain_details"]["unknown_n"] == 2
    assert summary["domain_details"]["rates"] == {"software.frontend": 1}
    assert summary["domain"]["counts"] == {"software": 2}
    assert inputs == before
    assert summarize_task_distribution(None)["domain_details"] is None
    assert summarize_task_distribution([])["domain_details"]["rates"] is None
