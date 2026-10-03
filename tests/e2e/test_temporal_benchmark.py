"""Fictional measurements verify temporal leakage guards and benchmark algebra."""

import importlib
from pathlib import Path

import pytest
from pydantic import ValidationError


@pytest.fixture
def api(monkeypatch):
    return tuple(
        importlib.import_module("evals.benchmark." + n)
        for n in ("contracts", "metrics", "temporal")
    )


def sample(api, tasks=2):
    c, _, t = api
    anchor = 40 * t.DAY_MS
    return c.TemporalSample(
        sample_id="fictional-sample",
        user_id="fictional-user",
        anchor_ts=anchor,
        history_days=7,
        history_from_ts=anchor - 7 * t.DAY_MS,
        history_until_ts=anchor,
        future_task_limit=tasks or 1,
        future_until_ts=anchor + t.FUTURE_MS,
        future_tasks=[
            c.Episode(
                task_uid=f"task-{i}",
                root_session_uids=["root"],
                project_id="p",
                start_ts=anchor + i,
                end_ts=anchor + 10,
                human_event_uids=[f"u-{i}"],
                boundary_quality="explicit",
                goal_observed=True,
                review_status="independent_human_reviewed",
                checkpoint_status="verified_exact",
            )
            for i in range(tasks)
        ],
        observed_until_ts=anchor + t.FUTURE_MS,
        future_complete=True,
    )


def execution(api, s, uid, method, *, passed=True, action=None, **updates):
    c = api[0]
    values = {
        "sample_id": s.sample_id,
        "task_uid": uid,
        "action_id": action or (c.NONE_ACTION if method == "no_recommendation" else "skill-a"),
        "method": method,
        "seed": 0,
        "source": "paired_execution",
        "checkpoint_digest": "a" * 64,
        "task_input_digest": "b" * 64,
        "environment_digest": "c" * 64,
        "check_definition_digest": "d" * 64,
        "intervention_digest": "e" * 64,
        "skill_body_digest": None if method == "no_recommendation" else "1" * 64,
        "run_log_digest": "f" * 64,
        "model_id": "fictional-model",
        "reasoning_effort": "medium",
        "budget": {"total_tokens": 10000, "turns": 20, "tool_calls": 50, "wall_ms": 60000},
        "passed": passed,
        "input_tokens": 1000,
        "cache_read_tokens": 100,
        "cache_write_tokens": 0,
        "output_tokens": 100,
        "recommendation_tokens": 0,
        "turns": 4,
        "tool_calls": 6,
        "wall_ms": 1000,
        "termination": "completed",
        "recommendation_anchor_ts": s.anchor_ts,
    }
    values.update(updates)
    return c.ExecutionRecord.model_validate(values)


def test_temporal_selection_uses_task_starts_and_never_future_messages_in_history(api):
    c, _, t = api
    anchor = 40 * t.DAY_MS
    episodes = [
        c.Episode(
            task_uid=uid,
            root_session_uids=["root"],
            project_id="p",
            start_ts=ts,
            end_ts=anchor + t.FUTURE_MS + 10,
            human_event_uids=[uid + "-start", uid + "-late"],
            boundary_quality="candidate",
            goal_observed=True,
        )
        for uid, ts in [
            ("ongoing", anchor - 1),
            ("at-anchor", anchor),
            ("later", anchor + 1),
            ("at-end", anchor + t.FUTURE_MS),
        ]
    ]
    index = {
        "episodes": episodes,
        "event_times": {e.task_uid + "-start": e.start_ts for e in episodes}
        | {e.task_uid + "-late": anchor + t.FUTURE_MS for e in episodes},
        "observed_until_ts": anchor + t.FUTURE_MS + 1,
        "observed_from_ts": 0,
    }
    s = t.make_sample(index, user_id="u", anchor_ts=anchor, future_task_limit=5)
    assert [e.task_uid for e in s.future_tasks] == ["at-anchor", "later"]
    assert all(len(e.human_event_uids) == 1 and e.end_ts is None for e in s.future_tasks)
    assert t.history_scope(s).contains(anchor - 1) and not t.history_scope(s).contains(anchor)
    assert s.future_complete
    assert (
        s.sample_id
        == t.make_sample(index, user_id="u", anchor_ts=anchor, future_task_limit=5).sample_id
    )


def test_right_censor_and_duplicate_messages_cannot_inflate_complete_tasks(api):
    c, _, t = api
    s = sample(api, 1).model_dump()
    s.update(future_task_limit=5, observed_until_ts=s["anchor_ts"] + 1, future_complete=False)
    assert not c.TemporalSample.model_validate(s).future_complete
    with pytest.raises(ValidationError, match="right-censored"):
        c.TemporalSample.model_validate({**s, "future_complete": True})
    s["future_tasks"] *= 2
    with pytest.raises(ValidationError, match="Repeated messages"):
        c.TemporalSample.model_validate(s)
    with pytest.raises(ValueError):
        t.rolling_anchors({"observed_until_ts": None}, 3)


def test_forward_budget_counts_failures_and_includes_recommendation_cost(api):
    _, m, _ = api
    s = sample(api)
    records = [
        execution(api, s, f"task-{i}", method, passed=i == 0)
        for i in range(2)
        for method in ("no_recommendation", "ours")
    ]
    records[-2] = execution(api, s, "task-1", "no_recommendation", passed=False)
    records[-1] = execution(
        api, s, "task-1", "ours", passed=True, input_tokens=9900, recommendation_tokens=100
    )
    result = m.forward_utility([s], records, budgets=(10000,))
    ours = next(r for r in result["rows"] if r["method"] == "ours")
    assert ours["status"] == "measured" and ours["pass_at_budget"] == 0.5
    assert ours["paired_runs"] == 2
    assert ours["efficiency_reductions"]["tokens"]["paired_success_n"] == 1
    assert records[-1].total_tokens == 10200 and records[-1].pass_at_budget is False


@pytest.mark.parametrize(
    "updates",
    [
        {"input_tokens": None},
        {"passed": None},
        {"run_log_digest": None},
        {"source": "historical_observation"},
    ],
)
def test_unknown_or_historical_measurements_never_become_headline_utility(api, updates):
    _, m, _ = api
    s = sample(api, 1)
    records = [
        execution(api, s, "task-0", "no_recommendation"),
        execution(api, s, "task-0", "ours", **updates),
    ]
    ours = next(
        r
        for r in m.forward_utility([s], records, budgets=(10000,))["rows"]
        if r["method"] == "ours"
    )
    assert ours["status"] == "unproven" and ours["pass_at_budget"] is None
    assert ours["efficiency_reductions"] is None


def test_mismatched_checkpoint_or_environment_disallows_paired_uplift(api):
    _, m, _ = api
    s = sample(api, 1)
    for axis in ("checkpoint_digest", "environment_digest", "check_definition_digest"):
        records = [
            execution(api, s, "task-0", "no_recommendation"),
            execution(api, s, "task-0", "ours", **{axis: "9" * 64}),
        ]
        ours = next(
            r
            for r in m.forward_utility([s], records, budgets=(10000,))["rows"]
            if r["method"] == "ours"
        )
        assert ours["control_conflicts"] == 1 and ours["pass_at_budget"] is None


def test_future_recommendation_and_duplicate_run_are_invalid(api):
    _, m, _ = api
    s = sample(api, 1)
    r = execution(api, s, "task-0", "ours", recommendation_anchor_ts=s.anchor_ts + 1)
    checked = m.forward_utility([s], [r, r], budgets=(10000,))
    assert checked["status"] == "invalid"
    assert {i["code"] for i in checked["issues"]} >= {
        "recommendation_not_frozen_at_anchor",
        "duplicate_execution",
    }


def test_constructed_or_unreviewed_samples_remain_separate_from_real_claims(api):
    _, m, _ = api
    s = sample(api, 1)
    records = [
        execution(api, s, "task-0", method, source="constructed_execution")
        for method in ("no_recommendation", "ours")
    ]
    ours = next(
        r
        for r in m.forward_utility([s], records, budgets=(10000,))["rows"]
        if r["method"] == "ours"
    )
    assert ours["status"] == "constructed_only" and ours["pass_at_budget"] is None
    s.future_tasks[0].review_status = "unreviewed"
    records = [execution(api, s, "task-0", method) for method in ("no_recommendation", "ours")]
    assert all(
        r["pass_at_budget"] is None
        for r in m.forward_utility([s], records, budgets=(10000,))["rows"]
    )


def test_human_label_alone_cannot_replace_checkpoint_or_meaningful_goal(api):
    c, m, _ = api
    s = sample(api, 1)
    methods = [execution(api, s, "task-0", name) for name in ("no_recommendation", "ours")]
    sweep = [
        execution(api, s, "task-0", "oracle", action=a, purpose="action_sweep")
        for a in (c.NONE_ACTION, "skill-a")
    ]
    for change in ("checkpoint", "goal"):
        task = s.future_tasks[0]
        task.checkpoint_status = "missing" if change == "checkpoint" else "verified_exact"
        task.goal_observed = change != "goal"
        ours = next(
            r
            for r in m.forward_utility([s], methods, budgets=(10000,))["rows"]
            if r["method"] == "ours"
        )
        assert ours["pass_at_budget"] is None and ours["status"] == "unproven"
        assert (
            m.recommendation_quality([s], sweep, {s.sample_id: ["skill-a"]}, ["skill-a"])[
                "regret_at_1"
            ]
            is None
        )


def test_regret_top_k_harm_and_no_intervention_use_same_complete_action_sweep(api):
    c, m, _ = api
    s = sample(api)
    records = []
    for action, results in (
        (c.NONE_ACTION, [True, False]),
        ("skill-a", [True, True]),
        ("skill-b", [False, False]),
    ):
        records.extend(
            execution(
                api, s, f"task-{i}", "oracle", action=action, purpose="action_sweep", passed=passed
            )
            for i, passed in enumerate(results)
        )
    quality = m.recommendation_quality(
        [s], records, {s.sample_id: ["skill-b", "skill-a"]}, ["skill-a", "skill-b"], top_k=2
    )
    assert quality["status"] == "measured"
    assert quality["regret_at_1"] == 1 and quality["regret_at_k"] == 0 and quality["harm_rate"] == 1
    assert quality["unnecessary_intervention_rate"] is None
    incomplete = m.recommendation_quality(
        [s], records[:-1], {s.sample_id: ["skill-b"]}, ["skill-a", "skill-b"]
    )
    assert incomplete["status"] == "unproven" and incomplete["regret_at_1"] is None


def test_no_intervention_wins_ties_and_zero_utility_is_not_missing(api):
    c, m, _ = api
    s = sample(api, 1)
    for passed in (True, False):
        records = [
            execution(api, s, "task-0", "oracle", action=a, purpose="action_sweep", passed=passed)
            for a in (c.NONE_ACTION, "skill-a")
        ]
        quality = m.recommendation_quality([s], records, {s.sample_id: ["skill-a"]}, ["skill-a"])
        assert quality["status"] == "measured" and quality["harm_rate"] == 0
        assert quality["regret_at_1"] == 0 and quality["unnecessary_intervention_rate"] == 1


def test_strict_measurements_reject_negative_nan_or_boolean_counts(api):
    s = sample(api, 1)
    for updates in ({"input_tokens": -1}, {"turns": True}, {"wall_ms": float("nan")}):
        with pytest.raises(ValidationError):
            execution(api, s, "task-0", "ours", **updates)


def test_native_history_replay_keeps_future_out_of_recommendation_and_writes_all_families(
    api, tmp_path, monkeypatch
):
    import json

    from tandem_backend.cli import demo_home
    from tandem_backend.data_access.ingest import ingest

    local = importlib.import_module("evals.benchmark.local")
    monkeypatch.setattr(local, "ROOT", tmp_path)
    source, home = demo_home(tmp_path / "source"), tmp_path / "data"
    ingest(home, "codex", source)
    anchor = 1767225602000
    called = []
    original = local.recommend

    def observe(analysis, **kwargs):
        called.append(analysis["scope"])
        assert analysis["scope"]["until_ts"] == anchor
        return original(analysis, **kwargs)

    monkeypatch.setattr(local, "recommend", observe)
    output = tmp_path / ".local/benchmark"
    report = local.run(home, output, anchors=[anchor], history_days=(7,), future_counts=(1, 3, 5))
    assert report["status"] == "passed" and report["model_calls"] == 0
    assert report["forward_utility_status"] == "unproven"
    assert report["source_snapshot_unchanged"] and called
    assert any(r["status"] == "unavailable" for r in report["cases"])
    for row in report["cases"]:
        if row["status"] != "passed":
            continue
        grouped = json.loads(Path(row["diagnostics"]).read_text())
        assert len(grouped["families"]) == 8 and len(grouped["skills"]["items"]) == 4
        manifest = json.loads(Path(row["diagnostics"]).with_name("input-manifest.json").read_text())
        assert manifest["future_event_uids_seen"] == []
        views = json.loads(
            Path(row["diagnostics"]).with_name("representation-inputs.json").read_text()
        )
        structured = views["structured_features"]
        assert not structured["truncated"]
        assert set(json.loads(structured["content"])) == set(grouped["families"])
    future = json.loads((output / f"anchor-{anchor}-future/observations.json").read_text())
    assert future and all(
        t["task_pass"] is None and t["recommendation_uplift"] is None for t in future
    )
    score = importlib.import_module("evals.benchmark.score")
    monkeypatch.setattr(score, "ROOT", tmp_path)
    scored = score.run(output, tmp_path / ".local/scored")
    assert scored["status"] == "completed" and scored["forward_utility_status"] == "unproven"
    prepare = importlib.import_module("evals.benchmark.prepare")
    monkeypatch.setattr(prepare, "ROOT", tmp_path)
    packet = tmp_path / ".local/prepared"
    prepared = prepare.run(output, packet)
    assert prepared["future_tasks"] == 3 and prepared["measurements"] == prepared["reviews"] == 0
    assert json.loads((packet / "task-reviews.json").read_text()) == []
    assert json.loads((packet / "executions.json").read_text()) == []
    rows = json.loads((packet / "execution-grid.json").read_text())["rows"]
    assert rows and all(row["measurement"] is None for row in rows)
    representation = output / f"anchor-{anchor}-history-7/representation-inputs.json"
    original_bytes = representation.read_bytes()
    representation.write_bytes(original_bytes + b"\n")
    with pytest.raises(ValueError, match="artifact changed"):
        score.run(output, tmp_path / ".local/changed-model-input")
    representation.write_bytes(original_bytes)
    with (output / "method-plan.json").open("a") as handle:
        handle.write("\n")
    with pytest.raises(ValueError, match="artifact changed"):
        score.run(output, tmp_path / ".local/tampered")


def test_later_reviews_only_change_evaluation_and_actions_match_frozen_prediction(api):
    c = api[0]
    score = importlib.import_module("evals.benchmark.score")
    s = sample(api, 1)
    s.future_tasks[0].review_status = "unreviewed"
    config = {
        "model": "fictional-model",
        "reasoning_effort": "medium",
        "seeds": [0],
        "token_budgets": [10000],
        "turn_budget": 20,
        "tool_call_budget": 50,
        "wall_budget_ms": 60000,
    }
    plan = {
        "common_execution": config,
        "generic_policy": {"action": "skill-a"},
        "ours_rankings": {s.sample_id: ["skill-a"]},
        "skill_body_digests": {"skill-a": "1" * 64},
    }
    review = c.TaskReview(
        task_uid="task-0",
        reviewer_id="fictional-independent-reviewer",
        source="independent_human",
        boundary_correct=True,
        meaningful_goal=True,
        evidence_event_uids=["u-0"],
        checkpoint_digest="a" * 64,
        check_definition_digest="d" * 64,
        available_at=s.anchor_ts + 100,
    )
    records = [execution(api, s, "task-0", method) for method in ("no_recommendation", "ours")]
    reviewed, issues, ids = score.bind_measurements([s], plan, records, [review])
    assert not issues and ids == {"task-0"}
    for body in (None, "2" * 64):
        changed = execution(api, s, "task-0", "ours", skill_body_digest=body)
        assert "execution_skill_body_differs_from_frozen_catalog" in {
            i["code"] for i in score.bind_measurements([s], plan, [changed], [review])[1]
        }
    assert reviewed[0].future_tasks[0].review_status == "independent_human_reviewed"
    assert s.future_tasks[0].review_status == "unreviewed"
    wrong = execution(api, s, "task-0", "ours", action="skill-b")
    assert "action_differs_from_frozen_prediction" in {
        i["code"] for i in score.bind_measurements([s], plan, [wrong], [review])[1]
    }
    sweep = execution(api, s, "task-0", "oracle", action="unregistered", purpose="action_sweep")
    assert "action_outside_frozen_plausible_set" in {
        i["code"] for i in score.bind_measurements([s], plan, [sweep], [review])[1]
    }
    review.boundary_correct = False
    assert "task_unit_rejected_requires_new_cohort" in {
        i["code"] for i in score.bind_measurements([s], plan, records, [review])[1]
    }


@pytest.mark.parametrize("reimport", [False, True])
def test_wrong_user_ablation_rejects_copied_native_history(api, tmp_path, monkeypatch, reimport):
    import shutil

    from tandem_backend.cli import demo_home
    from tandem_backend.data_access.ingest import ingest

    local = importlib.import_module("evals.benchmark.local")
    monkeypatch.setattr(local, "ROOT", tmp_path)
    source, home = demo_home(tmp_path / "source"), tmp_path / "data"
    ingest(home, "codex", source)
    copied = tmp_path / "another-data"
    if reimport:
        another_source = tmp_path / "another-source"
        shutil.copytree(source, another_source)
        ingest(copied, "codex", another_source)
    else:
        shutil.copytree(home, copied)
    output = tmp_path / ".local/wrong-user"
    with pytest.raises(ValueError, match="distinct native main sessions"):
        local.run(home, output, wrong_user_home=copied, wrong_user_id="another-user")
    assert not output.exists()


def test_profile_input_budget_keeps_work_mix_and_complete_review_counts(api):
    import json

    local = importlib.import_module("evals.benchmark.local")
    rows = [
        {
            "task_uid": str(i),
            "observed_counts": {"validation_failed": i},
            "evidence_node_uids": {"ModelCall": [f"node-{n}" for n in range(2000)]},
        }
        for i in range(20)
    ]
    profile = {
        "work_mix": {"domain": {"software": 13}},
        "collaboration": {},
        "iteration": {"review_candidates": rows, "validation_results": {"failed": 29}},
    }
    before = local.bounded_view(profile)
    assert before["truncated"] and "work_mix" not in before["content"]
    after = local.bounded_view(local.profile_input(profile))
    assert not after["truncated"]
    value = json.loads(after["content"])
    assert value["work_mix"] == profile["work_mix"]
    assert value["iteration"]["review_candidate_count"] == 20
    assert len(value["iteration"]["review_candidates"]) == 8
    assert value["iteration"]["review_candidates"][0]["evidence_node_counts"] == {"ModelCall": 2000}
    assert profile["iteration"]["review_candidates"] == rows


def test_frozen_manifest_coverage_pin_and_unactionable_forecast_are_enforced(
    api, tmp_path, monkeypatch
):
    import json

    score = importlib.import_module("evals.benchmark.score")
    monkeypatch.setattr(score, "ROOT", tmp_path)
    s = sample(api, 1)
    study = tmp_path / ".local/study"
    folder = study / f"anchor-{s.anchor_ts}-history-7"
    folder.mkdir(parents=True)
    plan = {
        "common_execution": {
            "model": "fictional-model",
            "reasoning_effort": "medium",
            "seeds": [0],
            "token_budgets": [10000],
            "turn_budget": 20,
            "tool_call_budget": 50,
            "wall_budget_ms": 60000,
        },
        "generic_policy": {"action": "skill-a"},
        "ours_rankings": {s.sample_id: ["skill-a"]},
        "plausible_actions": [api[0].NONE_ACTION, "skill-a"],
        "skill_body_digests": {"skill-a": "1" * 64},
    }
    for path, value in (
        (study / "samples.json", [s.model_dump()]),
        (study / "method-plan.json", plan),
        (study / "episode-index.json", {}),
        (study / "skill-catalog.json", {"schema_version": "recommendation-catalog-v1", "family": "skills", "items": [{"identity": {"id": "skill-a", "name": "fictional-skill", "version": "f" * 40}, "family": "skills", "source": {"origin": "github", "status": "verified", "url": "https://example.invalid/fictional", "source_path": "SKILL.md", "verified_sha": "f" * 40, "blob_sha": "b" * 40, "content_sha256": "1" * 64}}]}),
        (folder / "input-manifest.json", {}),
        (folder / "representation-inputs.json", {}),
        (
            folder / "recommendations.json",
            {
                "recommendations": [
                    {"resource_id": "skill-a", "recommendation_status": "needs_context"}
                ]
            },
        ),
    ):
        path.write_text(json.dumps(value))
    score.freeze_study(study)
    digest = score.file_digest(study / "study-manifest.json")
    assert (
        score.read_study(study, expected_manifest_digest=digest)[2][s.sample_id]
        == "requires_context_or_adaptation"
    )
    with pytest.raises(ValueError, match="independently recorded"):
        score.read_study(study, expected_manifest_digest="9" * 64)
    output = tmp_path / ".local/scored"
    report = score.run(
        study, output, measurements=[execution(api, s, "task-0", "ours").model_dump()]
    )
    assert report["status"] == "invalid"
    result = json.loads((output / "forward-utility.json").read_text())
    assert "prediction_not_actionable_at_anchor_requires_new_contextual_study" in {
        i["code"] for i in result["issues"]
    }
    # Editing and re-signing a catalog still cannot silently change the registered body.
    catalog = json.loads((study / "skill-catalog.json").read_text())
    catalog["items"][0]["source"]["content_sha256"] = "2" * 64
    (study / "skill-catalog.json").write_text(json.dumps(catalog))
    with pytest.raises(ValueError, match="artifact changed"):
        score.read_study(study)
    score.freeze_study(study)
    with pytest.raises(ValueError, match="Skill body differs"):
        score.read_study(study)
    (study / "study-manifest.json").write_text(
        json.dumps({"schema_version": "frozen-benchmark-study-v2", "artifacts": {}})
    )
    with pytest.raises(ValueError, match="artifact coverage"):
        score.read_study(study)


def test_action_sweep_is_checked_against_the_registered_sweep_budget(api):
    """The sweep budget comes from the registered plan (or the median registered budget),
    never from a constant: a study registering 20000 accepts 20000-token sweeps only."""
    score = importlib.import_module("evals.benchmark.score")
    m = api[1]
    s = sample(api, 1)
    config = {"model": "fictional-model", "reasoning_effort": "medium", "seeds": [0],
              "token_budgets": [5000, 10000, 20000], "action_sweep_budget": 20000,
              "turn_budget": 20, "tool_call_budget": 50, "wall_budget_ms": 60000}
    plan = {"common_execution": config, "plausible_actions": ["skill-a"],
            "skill_body_digests": {"skill-a": "1" * 64}}

    def sweep_issues(budget, plan=plan):
        record = execution(api, s, "task-0", "oracle", purpose="action_sweep",
                           budget={"total_tokens": budget, "turns": 20, "tool_calls": 50,
                                   "wall_ms": 60000})
        _, issues, _ = score.bind_measurements([s], plan, [record], ())
        return {i["code"] for i in issues}

    code = "action_sweep_differs_from_registered_budget_or_seed"
    assert code not in sweep_issues(20000)
    assert code in sweep_issues(10000)
    # Unregistered: the median of the registered budgets (5000, 10000, 20000) → 10000.
    median_plan = {**plan, "common_execution": {k: v for k, v in config.items()
                                                if k != "action_sweep_budget"}}
    assert code not in sweep_issues(10000, median_plan)
    assert code in sweep_issues(20000, median_plan)
    assert m.action_sweep_budget({"token_budgets": [3000, 1000, 2000, 4000]}) == 2000
    with pytest.raises(ValueError, match="not a registered token budget"):
        m.action_sweep_budget({"token_budgets": [5000, 10000], "action_sweep_budget": 7000})
