import copy

import pytest

from tandem_backend.analytics.interaction import analyze_interaction


def annotation(**values):
    return {"state": "confirmed", "source": "synthetic-reviewer", "available_at": 200,
            "intents": ["request"], **values}


def test_new_requirement_is_not_correction_and_proxy_is_not_confirmation(make_event):
    es = [make_event(), make_event("u2", 2, text="不对，我要的是 A")]
    r = analyze_interaction(es, {"s"})
    assert r["confirmed_correction_count"] is None
    assert r["confirmed_correction_rate"] is None
    assert [m["candidate_intents"] for m in r["message_intents"]] == [[], ["correction"]]
    assert r["unknown_counts"]["intent_messages"] == 2


def test_confirmed_multilabel_correction_counted_once_with_known_denominator(make_event):
    es = [make_event("request", 0, interaction=annotation()),
          make_event("delivery", 1, "message.assistant"),
          make_event("correction", 2, interaction=annotation(
              intents=["correction", "feedback", "correction"], target_event_uid="delivery",
              friction_types=["scope", "scope"])), make_event("unknown", 3)]
    before = copy.deepcopy(es)
    r = analyze_interaction(es, {"s"})
    assert r["confirmed_correction_count"] == 1
    assert r["confirmed_correction_rate"] == .5
    assert r["friction_types"] == {"scope": 1}
    assert r["effective_samples"]["intent_messages"] == 2
    assert r["unknown_counts"]["intent_messages"] == 1
    assert es == before


@pytest.mark.parametrize("change", [{"task_uid": "other"}, {"seq": 3}, {"session_uid": "other"}])
def test_correction_requires_prior_target_in_same_task_and_session(make_event, change):
    target = make_event("target", 0, "message.assistant")
    if "task_uid" in change:
        target["attrs"].update(change)
    else:
        target.update(change)
    e = make_event(interaction=annotation(intents=["correction"], target_event_uid="target"))
    assert analyze_interaction([target, e], {"s"})["confirmed_correction_count"] is None


def test_repeated_requirement_needs_same_object_and_task_and_counts_message_once(make_event):
    a = annotation(requirements=[{"object_uid": "export", "requirement_uid": "csv"}])
    es = [make_event("first", 0, interaction=a), make_event("again", 1, interaction=a),
          make_event("other-task", 2, task_uid="new-task", interaction=a),
          make_event("unknown", 3, text="再强调一次")]
    r = analyze_interaction(es, {"s"})
    assert r["repeated_requirement_count"] == 1
    assert r["repeated_requirement_evidence"] == ["again"]
    assert r["unknown_counts"]["requirement_messages"] == 1


def test_interventions_follow_seq_and_task_not_wall_clock(make_event):
    es = [make_event("before", 0, "tool.result", ts=900), make_event(ts=10),
          make_event("other", 2, "tool.call", task_uid="other"),
          make_event("after", 3, "tool.call", ts=None)]
    p = analyze_interaction(es, {"s"})["intervention_points"][0]
    assert (p["previous_step_uid"], p["next_step_uid"]) == ("before", "after")
    assert p["next_step_available_at"] is None


@pytest.mark.parametrize("available", [None, 200, 300])
def test_later_or_unclocked_annotation_not_visible_at_cutoff(make_event, available):
    r = analyze_interaction([make_event(interaction=annotation(available_at=available))], {"s"}, until_ts=200)
    assert r["effective_samples"]["intent_messages"] == 0


def test_nonhuman_and_child_messages_do_not_enter_denominator(make_event):
    es = [make_event("peer", origin="peer", interaction=annotation()),
          make_event("child", sid="child", interaction=annotation()),
          make_event("unknown", origin="unknown")]
    r = analyze_interaction(es, {"s"})
    assert r["message_intents"] == []
    assert r["confirmed_correction_count"] is None
    assert r["unknown_counts"]["human_origin"] == 1
    assert analyze_interaction([], {"s"})["confirmed_correction_count"] == 0
    assert analyze_interaction(None, {"s"})["confirmed_correction_count"] is None
