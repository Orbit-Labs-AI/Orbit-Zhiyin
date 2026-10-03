"""Constructed contracts test provenance/failures; they do not measure model accuracy."""

import copy
import json
from dataclasses import replace
from types import SimpleNamespace

import pytest

from tandem_backend.analytics.context import AnalysisContext
from tandem_backend.analytics.inputs import Scope
from tandem_backend.analytics.instruction import (
    extract_instruction_constraints,
    resolve_instruction_scope,
)
from tandem_backend.analytics.interaction import analyze_interaction
from tandem_backend.analytics.outcome_subjective import analyze_subjective_outcomes
from tandem_backend.analytics.preference import (
    instruction_to_preference_evidence,
    summarize_preference_evidence,
)
from tandem_backend.analytics.semantic_cascade import (
    Budget,
    attach_cache,
    observation_for,
    run_cascade,
    select_candidates,
)
from tandem_backend.analytics.semantic_cascade import provider as provider_module
from tandem_backend.analytics.semantic_cascade.provider import CodexProvider
from tandem_backend.analytics.service import analyze_bundle


def label(candidate, **changes):
    return {
        "session_uid": candidate["session_uid"],
        "event_uid": candidate["event_uid"],
        "intents": ["request"],
        "intent_quote": candidate["text"],
        "target_event_uid": None,
        "friction_types": [],
        "controls": [],
        "feedback": None,
        "abstention_reason": None,
        **changes,
    }


def control(feature, value, quote, **arguments):
    return {
        "feature": feature,
        "value": value,
        "quote": quote,
        "targets": [],
        "condition": None,
        "arguments": {
            "response_form": None,
            "detail": None,
            "execution_environment": None,
            "acceptance_requirement": None,
            **arguments,
        },
    }


def parsed(events, builder=label, budget=None):
    def provider(batch, _):
        return {"observations": [builder(c) for c in batch]}, {"test_fixture": True}

    return run_cascade(events, {"s"}, provider, budget or Budget())


def task_event(fixtures, text, uid="u", seq=1, **extra):
    _, e, _ = fixtures
    return e(text, uid, seq, task_uid="task", task_id="task", **extra)


def test_directive_produces_three_shared_observations_without_global_authority(fixtures):
    event = task_event(fixtures, "只给我能在根目录执行的命令")
    cache = parsed(
        [event],
        lambda c: label(
            c,
            controls=[
                control("format_requirements", "format", c["text"], response_form="command_only"),
                control(
                    "allowed_scope", "restricted", c["text"], execution_environment="project_root"
                ),
                control(
                    "acceptance_criteria",
                    "criterion",
                    c["text"],
                    acceptance_requirement="directly_runnable",
                ),
            ],
        ),
    )
    projected = attach_cache([event], {"s"}, cache)
    rows = extract_instruction_constraints(projected, main_ids={"s"})
    assert {c["feature"] for c in rows[0]["constraints"]} == {
        "format_requirements",
        "allowed_scope",
        "acceptance_criteria",
    }
    assert all(c["source"] == "semantic_model" for c in rows[0]["constraints"])
    prefs = instruction_to_preference_evidence(rows, [fixtures[0]()])
    assert [(p["dimension"], p["value"], p["scope"]["kind"]) for p in prefs] == [
        ("format", "command_only", "task")
    ]
    assert prefs[0]["source_id"] in {c["constraint_uid"] for c in rows[0]["constraints"]}
    summary = summarize_preference_evidence(prefs, rows, [fixtures[0]()])
    assert summary["dimensions"][0]["historical_values"] == []
    assert summary["dimensions"][0]["inferred_values"][0]["support_tasks"] == 1
    effective = resolve_instruction_scope(rows, {"session_uid": "s", "task_id": "task"})
    assert effective["active"] == []
    assert len(effective["unresolved"]) == 3


def test_correction_and_partial_feedback_share_preceding_target(fixtures):
    delivery = {
        **task_event(fixtures, "已交付", "d", 0),
        "kind": "message.assistant",
        "actor": "assistant",
    }
    delivery["attrs"]["phase"] = "final"
    event = task_event(fixtures, "这一版好多了，不过最后一段还是太长")
    es = [delivery, event]
    cache = parsed(
        es,
        lambda c: label(
            c,
            intents=["feedback", "correction"],
            target_event_uid="d",
            friction_types=["scope"],
            feedback={
                "acceptance": "partial",
                "completion": None,
                "rework": True,
                "reason": "verbosity",
                "quote": c["text"],
            },
        ),
    )
    projected = attach_cache(es, {"s"}, cache)
    interaction = analyze_interaction(projected, {"s"})
    assert interaction["confirmed_correction_count"] is None
    assert interaction["semantic_observations"]["correction_count"] == 1
    subjective = analyze_subjective_outcomes(projected, {"s"})
    assert subjective["semantic_observations"]["partial_acceptance_count"] == 1
    assert subjective["feedback"][0]["delivery_event_uid"] == "d"
    assert subjective["feedback"][0]["link_status"] == "candidate"
    assert subjective["counts"]["confirmed_completion_count"] == 0
    assert subjective["task_success"] is None


def test_verbosity_comes_from_the_same_control_and_remains_task_local(fixtures):
    event = task_event(fixtures, "解释太长了，简短点")
    cache = parsed(
        [event],
        lambda c: label(
            c, controls=[control("format_requirements", "format", c["text"], detail="concise")]
        ),
    )
    rows = extract_instruction_constraints(attach_cache([event], {"s"}, cache), main_ids={"s"})
    prefs = instruction_to_preference_evidence(rows, [fixtures[0]()])
    assert [(p["dimension"], p["value"], p["source_type"]) for p in prefs] == [
        ("detail", "concise", "semantic_task_instruction")
    ]


def test_semantic_arguments_enrich_a_rule_without_recounting_its_format(fixtures):
    event = task_event(fixtures, "请用 JSON，简短点")
    cache = parsed(
        [event],
        lambda c: label(
            c,
            controls=[
                control(
                    "format_requirements",
                    "format",
                    c["text"],
                    response_form="json",
                    detail="concise",
                )
            ],
        ),
    )
    rows = extract_instruction_constraints(attach_cache([event], {"s"}, cache), main_ids={"s"})
    prefs = instruction_to_preference_evidence(rows, [fixtures[0]()])
    assert sorted((p["dimension"], p["value"]) for p in prefs) == [
        ("detail", "concise"),
        ("format", "json"),
    ]


@pytest.mark.parametrize(
    "fault", ["quote", "event", "session", "target", "schema", "missing", "duplicate"]
)
def test_invalid_observation_rejects_the_batch_and_preserves_unknown(fixtures, fault):
    event = task_event(fixtures, "返回简单命令")

    def provider(batch, _):
        item = label(batch[0])
        rows = [item]
        if fault == "quote":
            item["intent_quote"] = "不存在的原句"
        if fault == "event":
            item["event_uid"] = "elsewhere"
        if fault == "session":
            item["session_uid"] = "elsewhere"
        if fault == "target":
            item["target_event_uid"] = "future"
        if fault == "schema":
            item["execute"] = "rm -rf"
        if fault == "missing":
            rows = []
        if fault == "duplicate":
            rows.append(copy.deepcopy(item))
        return {"observations": rows}, None

    cache = run_cascade([event], {"s"}, provider)
    assert cache["entries"] == []
    assert cache["diagnostics"]["unknown_reasons"] == {"provider_or_schema_failure": 1}


@pytest.mark.parametrize(
    "text,changes",
    [
        ("例如直接执行", {"controls": [control("requested_autonomy", "explicit", "直接执行")]}),
        (
            "如果检查通过就开始修改",
            {"controls": [control("requested_autonomy", "explicit", "如果检查通过就开始修改")]},
        ),
        (
            "如果这版可以了我会告诉你",
            {
                "intents": ["feedback"],
                "feedback": {
                    "acceptance": "accepted",
                    "completion": True,
                    "rework": False,
                    "reason": None,
                    "quote": "如果这版可以了",
                },
            },
        ),
        (
            "这版可以了吗？",
            {
                "intents": ["feedback"],
                "feedback": {
                    "acceptance": "accepted",
                    "completion": True,
                    "rework": False,
                    "reason": None,
                    "quote": "这版可以了吗？",
                },
            },
        ),
    ],
)
def test_narrative_condition_and_question_are_not_unconditional_facts(fixtures, text, changes):
    cache = parsed([task_event(fixtures, text)], lambda c: label(c, **changes))
    assert cache["entries"] == []


def test_candidate_scope_order_duplicates_and_budget(fixtures):
    events = [
        task_event(fixtures, "前一个问题", "prior", 0),
        task_event(fixtures, "当前问题", "current", 1),
        task_event(fixtures, "未来内容", "future", 2),
        task_event(fixtures, "peer", "peer", 3, origin="peer"),
        task_event(fixtures, "x" * 2001, "long", 4),
    ]
    original = copy.deepcopy(events)
    a, skipped = select_candidates(events, {"s"})
    b, _ = select_candidates(list(reversed(events)) + [events[0]], {"s"})
    assert a == b and events == original
    current = next(c for c in a if c["event_uid"] == "current")
    assert [c["event_uid"] for c in current["context"]] == ["prior"]
    assert skipped == [
        {"session_uid": "s", "event_uid": "long", "reason": "message_budget_exceeded"}
    ]
    assert select_candidates(events, set())[0] == []


@pytest.mark.parametrize(
    "mutation", ["text", "timestamp", "task", "project_scope", "model", "prompt", "schema"]
)
def test_stale_cache_is_rejected_before_analysis(fixtures, mutation):
    events = [task_event(fixtures, "返回简单命令")]
    cache = parsed(events)
    events = copy.deepcopy(events)
    if mutation == "text":
        events[0]["text"] = "新的要求"
    if mutation == "timestamp":
        events[0]["ts"] += 1
    if mutation == "task":
        events[0]["attrs"]["task_uid"] = "other"
    if mutation == "project_scope":
        events = []
    if mutation == "model":
        cache["model"] = "other"
    if mutation == "prompt":
        cache["prompt_version"] = "other"
    if mutation == "schema":
        cache["schema_version"] = "other"
    with pytest.raises(ValueError):
        attach_cache(events, {"s"}, cache)


def test_timeout_circuit_and_call_budget_do_not_become_observed_zero(fixtures):
    events = [task_event(fixtures, "一个要求", str(i), i) for i in range(4)]
    calls = []

    def failing(batch, _):
        calls.append(batch)
        raise TimeoutError("deadline")

    cache = run_cascade(events, {"s"}, failing, Budget(batch_messages=1, max_calls=2))
    assert len(calls) == 1 and cache["diagnostics"]["parsed_messages"] == 0
    assert cache["diagnostics"]["unknown_reasons"] == {
        "provider_timeout": 1,
        "provider_circuit_open": 1,
        "call_budget_exhausted": 2,
    }


def test_cache_is_idempotent_but_not_valid_for_a_different_history(fixtures):
    events = [task_event(fixtures, "一个要求")]
    cache = parsed(events)
    first = attach_cache(events, {"s"}, cache)
    assert attach_cache(first, {"s"}, cache) == first
    assert "semantic_cascade" not in events[0]["attrs"]
    altered = copy.deepcopy(first)
    altered[0]["text"] = "不同要求"
    assert observation_for(altered[0]) is None


def test_cutoff_and_unknown_input_time_cannot_backdate_an_observation(fixtures):
    event = task_event(fixtures, "一个要求")
    projected = attach_cache([event], {"s"}, parsed([event]))[0]
    assert observation_for(projected, until_ts=100) is None
    assert observation_for(projected, until_ts=101) is not None
    event["ts"] = None
    projected = attach_cache([event], {"s"}, parsed([event]))[0]
    assert observation_for(projected, until_ts=101) is None


def test_all_four_families_and_graph_use_the_same_control_identity(fixtures):
    event = task_event(fixtures, "只给我能在根目录执行的命令")
    context = AnalysisContext.select(fixtures[2]([event]), Scope())
    cache = parsed(
        context.events,
        lambda c: label(
            c,
            controls=[
                control("format_requirements", "format", c["text"], response_form="command_only")
            ],
        ),
    )
    bundle = replace(context.bundle, events=attach_cache(context.events, context.main_ids, cache))
    result = analyze_bundle(bundle, Scope(), with_text=False)
    instructions = [n for n in result["work_graph"]["nodes"] if n["kind"] == "Instruction"]
    preferences = [n for n in result["work_graph"]["nodes"] if n["kind"] == "PreferenceObservation"]
    assert len(instructions) == len(preferences) == 1
    assert instructions[0]["confidence"]["tier"] == "candidate"
    assert any(
        e["kind"] == "DERIVED_FROM"
        and e["from_node_uid"] == preferences[0]["node_uid"]
        and e["to_node_uid"] == instructions[0]["node_uid"]
        for e in result["work_graph"]["edges"]
    )
    assert result["preferences"]["records"] == []
    assert result["instruction"]["summary"]["evidence_quality"] == {
        "explicit_messages": 0, "inferred_messages": 1, "calibrated_probability": None}


def test_provider_rejects_tool_activity_even_with_schema_valid_output(fixtures, monkeypatch):
    candidates, _ = select_candidates([task_event(fixtures, "一个要求")], {"s"})

    def native(command, payload, folder, timeout):
        assert "--model" in command and command[command.index("--model") + 1] == "gpt-6.1-sol"
        assert 'model_reasoning_effort="medium"' in command
        assert "features.shell_tool=false" in command and "features.multi_agent=false" in command
        assert timeout == 1
        from pathlib import Path

        Path(command[command.index("-o") + 1]).write_text(
            json.dumps({"observations": [label(candidates[0])]})
        )
        return SimpleNamespace(
            returncode=0,
            stderr="",
            stdout=json.dumps({"type": "item.completed", "item": {"type": "command_execution"}}),
        )

    monkeypatch.setattr(provider_module, "_run_bounded", native)
    with pytest.raises(RuntimeError, match="prohibited"):
        CodexProvider(executable="test-codex")(candidates, Budget(timeout_seconds=1))


def test_correction_without_acceptance_enters_graph_as_candidate_feedback(fixtures):
    delivery = {
        **task_event(fixtures, "交付报告", "d", 0),
        "kind": "message.assistant",
        "actor": "assistant",
    }
    delivery["attrs"]["phase"] = "final"
    event = task_event(fixtures, "你理解错了，我说的是终端输出")
    context = AnalysisContext.select(fixtures[2]([delivery, event]), Scope())
    cache = parsed(
        context.events,
        lambda c: label(
            c, intents=["correction"], target_event_uid="d", friction_types=["understanding"]
        ),
    )
    result = analyze_bundle(
        replace(context.bundle, events=attach_cache(context.events, context.main_ids, cache)),
        Scope(),
        with_text=False,
    )
    edges = [e for e in result["work_graph"]["edges"] if e["kind"] == "CORRECTS"]
    assert len(edges) == 1 and edges[0]["state"] == "candidate"
    assert all(t["task_success"] is None for t in result["work_graph"]["task_trajectories"])
    assert result["overview"]["subjective_outcomes"]["counts"]["confirmed_completion_count"] == 0


@pytest.mark.parametrize(
    "values",
    [{"max_calls": 0}, {"batch_messages": 9}, {"timeout_seconds": 91}, {"max_calls": True}],
)
def test_invalid_budget_fails_early(values):
    with pytest.raises(ValueError):
        Budget(**values)


def test_cascade_context_includes_phaseless_assistant_delivery():
    from tandem_backend.analytics.semantic_cascade.candidates import select_candidates

    def ev(seq, kind, text, actor, **attrs):
        return {"event_uid": f"e{seq}", "session_uid": "s", "seq": seq, "ts": seq, "kind": kind,
                "actor": actor, "text": text, "turn_uid": None,
                "attrs": {"task_id": "t", **({"origin": "human"} if actor == "human" else {}), **attrs}}

    # Claude/Kimi shape: no attrs.phase; the last assistant message before the human reply is final.
    events = [ev(0, "message.user", "写一份周报", "human"),
              ev(1, "message.assistant", "我先看下数据", "assistant"),
              ev(2, "message.assistant", "周报如下", "assistant"),
              ev(3, "message.user", "不对，要月报", "human")]
    candidates, _ = select_candidates(events, {"s"})
    context = [c["event_uid"] for c in candidates[-1]["context"]]
    assert context == ["e0", "e2"]
