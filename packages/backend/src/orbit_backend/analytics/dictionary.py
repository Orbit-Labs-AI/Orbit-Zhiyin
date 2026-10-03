"""Machine-readable feature meanings shared by all analytics endpoints."""

from .cost_time.dictionary import FEATURES as COST_TIME_FEATURES
from .instruction.dictionary import FEATURES as INSTRUCTION_FEATURES
from .interaction.dictionary import FEATURES as INTERACTION_FEATURES
from .outcome.dictionary import FEATURES as OUTCOME_FEATURES
from .preference.dictionary import EVIDENCE_FEATURES as PREFERENCE_EVIDENCE_FEATURES
from .preference.dictionary import FEATURES as PREFERENCE_FEATURES
from .respond.dictionary import FEATURES as RESPOND_FEATURES
from .task.dictionary import FEATURES as TASK_FEATURES

FEATURES = {}


def define(names, unit, rule, source, denominator=None, kind="deterministic_derived"):
    for name in names.split():
        FEATURES[name] = {"name": name, "unit": unit, "rule": rule, "source": source,
                          "denominator": denominator, "type": kind,
                          "missing_semantics": "null if unsupported; coverage/effective_samples/unknown_counts describe known subsets",
                          "provenance": "session_uid, human_evidence_ids, call_uid, transition sequences"}


define("user_message_count", "message", "Count origin=human messages in confirmed main sessions", "message.user + actor + attrs.origin")
define("assistant_message_count", "message", "Count retained assistant messages in this session", "message.assistant")
define("turn_count", "turn", "Count distinct non-null turn_uid; no inference from message count", "event.turn_uid")
define("total_event_count", "event", "Count selected non-replayed standardized events, not raw lines", "event")
define("first_observed_ts last_observed_ts", "UTC ms", "Min/max observed event timestamps", "event.ts")
define("observed_event_dates", "local date", "Sorted distinct display_timezone dates of clocked events", "event.ts")
define("observed_timestamp_n", "event", "Events with a valid timestamp convertible in display_timezone", "event.ts")
define("time_unknown_event_count", "event", "Selected events without a usable timestamp; excluded from every time bucket", "event.ts")
define("observed_session_span_ms", "ms", "last_observed_ts - first_observed_ts; never work duration", "event.ts")
define("avg_user_message_chars median_user_message_chars avg_assistant_message_chars median_assistant_message_chars",
       "Unicode character", "Mean/median original_chars, else retained length with truncation lower bound", "message text + original_chars", "messages with measurable text")
define("call_count paired_result_count known_success_count known_failure_count rejected_count interrupted_count running_count unknown_status_count unpaired_count tool_call_count",
       "logical tool call", "One row per call; status only from explicit protocol; unpaired results never imply success", "tool_call")
define("success_rate failure_rate", "ratio", "Explicit success/failure count divided by known success + failure", "tool_call.status", "known success + known failure")
define("median_duration_ms p25_duration_ms p75_duration_ms p90_duration_ms", "ms", "Linear interpolated quantile of available nonnegative durations", "tool_call.duration_ms", "calls with duration")
define("duration_sum_ms", "ms", "Sum usable durations; retains duration source and quality", "tool_call.duration_ms")
define("reliable_interval_union_ms", "ms", "Union of reliable observed start/end intervals, including overlapping children", "tool_call native endpoints")
define("error_count branch_count rollback_rewind_count compaction_count permission_request_count interruption_count",
       "event", "Count explicitly supported event kinds; unsupported kinds return null", "event.kind + attrs")
define("repeated_transition_count", "transition", "Count edges previously seen in the same session sequence", "event.seq")
define("repeated_transition_rate", "ratio", "Repeated transition count / all observed transitions", "event.seq", "transitions")
define("max_repeated_transition_run", "transition", "Longest adjacent run of an identical edge; not repeated cycle detection", "event.seq")
define("subagent_spawn_count", "child session", "Distinct child identities observed in spawn events; events without native child identity excluded", "event.attrs.child_session_uid")
define("subagent_spawn_unknown_events", "event", "Spawn observations without a resolvable native child identity", "event.attrs")
define("transition_edge_reuse_count", "transition", "Edges previously seen within a session; topology only, not retry or bottleneck", "event.seq")
define("transition_edge_reuse_rate", "ratio", "Previously seen edge occurrences / transitions; topology only", "event.seq", "transitions")
define("consecutive_failed_calls", "adjacent failed pair", "Adjacent failed logical calls in the same session", "tool_call status + seq")
define("confirmed_same_argument_failed_retries", "adjacent failed pair", "Same tool, literal argument digest and known equal status_scope; wrapper-level only when wrapper", "tool_call + L2 attrs")
define("correction_signal_count", "human message", "Messages matching conservative correction lexical markers; evidence only", "confirmed human text", kind="proxy")
define("correction_signal_rate", "ratio", "Signal messages / confirmed human messages; null per session below 3 messages", "confirmed human text", "confirmed human messages in main sessions", "proxy")
define("correction_signal_rate_n correction_signal_rate_ci", "message / interval", "Per-session denominator and 95% Wilson interval of correction_signal_rate", "confirmed human text", "confirmed human messages in main sessions", "proxy")
define("language_signals", "file extension occurrence", "Map explicit file extensions; no guessing language from semantics", "confirmed human text", kind="proxy")
define("request_count", "model request", "Unique call_uid with call/delta and reliable boundary", "model_call")
define("total_tokens", "token", "input_tokens + cache_read_tokens + cache_write_tokens + output_tokens; reasoning already included", "compatible complete usage buckets")
define("cost_usd", "USD", "Sum complete request costs with source; price estimates require price-table version", "model_call", kind="direct_observation")
define("median_latency_ms median_ttft_ms", "ms", "Median reliable request metric, not differences between message times", "model_call", "requests with metric")
define("sessions_by_day sessions_by_hour human_messages_by_day human_messages_by_hour tool_calls_by_day model_usage_by_day active_days weekday_distribution hour_distribution",
       "record", "Bucket reported timestamps in display_timezone; unknown clocks excluded; models count requests not snapshots", "event/tool/model timestamps")
define("cluster_id embedding_x embedding_y top_terms distance_to_cluster_centroid", "representation space", "Word TF-IDF (jieba + English words, boilerplate lines stripped); cosine DBSCAN below 20 sessions, else seeded k-means chosen by silhouette with a 60% size cap, insufficient when no partition passes; PCA of character 2-4 gram TF-IDF/SVD for visual coordinates", "confirmed main-session human text", kind="unsupervised_representation")
define("novelty", "1 - cosine similarity", "Fit on strictly earlier sessions only, compare maximum similarity; unclocked/tied/no-prior cases unknown", "confirmed human text and last prompt timestamp", "earlier valid sessions", "unsupervised_representation")

FEATURES.update(INTERACTION_FEATURES)
FEATURES.update(RESPOND_FEATURES)
FEATURES.update(COST_TIME_FEATURES)
FEATURES.update(OUTCOME_FEATURES)

define("user_acceptance", "feedback message", "Explicit accepted/rejected/mixed clauses after a linked prior final delivery; no silence inference", "confirmed human text + delivery/task identity", kind="proxy")
define("user_confirmed_completion", "feedback target", "Explicit human completion/incompletion, independent of acceptance; scope retained", "confirmed human text + linked delivery", kind="proxy")
define("rework_feedback", "feedback message", "Explicit revision request; retain request and explicit reason; new requirements alone are not rework", "confirmed human text + linked delivery", kind="proxy")
define("feedback_target", "delivery relation", "Explicit same-session delivery/artifact/version or latest prior shared task; heuristic legacy task IDs remain candidates", "event.attrs + seq", kind="deterministic_derived")
define("feedback_evidence", "evidence record", "event_uid, normalized redacted evidence_text, seq, ts and available_at; missing clock is sequence-only", "confirmed human event", kind="direct_observation")
define("accepted_feedback_count rejected_feedback_count confirmed_completion_count confirmed_incompletion_count rework_feedback_count", "linked feedback message", "Count only linked explicit feedback in selected scope; not unique tasks, satisfaction or task success", "subjective_outcomes.feedback", "linked feedback messages", "proxy")
FEATURES.update(PREFERENCE_FEATURES)
FEATURES.update(PREFERENCE_EVIDENCE_FEATURES)
FEATURES.update(TASK_FEATURES)
# Family-owned definitions retain the established global lookup surface.
FEATURES.update(INSTRUCTION_FEATURES)

# UI-facing expression metrics remain lexical observations, separate from acceptance.
define("emotion", "human message label", "Explicit positive/negative/mixed/neutral expressions; hypothetical, quoted and truncated input remains unknown", "confirmed direct human text", kind="proxy")
define("expression_balance", "signed ratio [-1,1]", "(positive expressions - negative expressions) / all recognized explicit expressions, including mixed and explicit neutral", "products.feedback.messages", "recognized explicit expression messages", "proxy")
define("feedback_signal", "human message label", "Explicit acceptance/completion/rework phrase candidate; only linked subjective outcomes establish a delivery relation", "confirmed direct human text", kind="proxy")
define("emotion_explicit_n", "human message", "Count recognized explicit expression messages; silence and unrecognized text excluded", "products.feedback.messages", kind="deterministic_derived")

UI_ANALYSIS_MAP = {
    "version": "ui-analysis-map-v1",
    "instruction": {"plane": "semantic", "axis": "input", "input": "confirmed direct human messages",
                    "computation": "instruction extraction + structural counts + optional grounded semantic observations",
                    "output": "instruction.records / presentation.profile", "unknown": "no explicit signal is not absence of a preference"},
    "task": {"plane": "semantic", "axis": "input", "input": "human goals + explicit task/session relations",
             "computation": "task taxonomy, goal history, expected artifacts and topic representation",
             "output": "tasks.records / presentation.topics", "unknown": "unresolved goals and taxonomy stay null"},
    "feedback": {"plane": "semantic", "axis": "output", "input": "explicit feedback + preceding delivery/task identity",
                 "computation": "acceptance, completion and rework classified independently and linked to evidence",
                 "output": "overview.subjective_outcomes / products.feedback", "unknown": "silence never implies acceptance"},
    "preference": {"plane": "semantic", "axis": "input", "input": "repeated and scoped explicit human requirements",
                   "computation": "evidence candidates with scope, confidence and contradictions",
                   "output": "preferences.records / presentation.profile", "unknown": "task-local instructions are not persistent preference"},
    "interaction": {"plane": "observed", "axis": "input", "input": "ordered human/assistant events and task boundaries",
                    "computation": "message structure, feedback candidates, correction links and repetition",
                    "output": "bottleneck_features.interaction / presentation.diagnostics", "unknown": "lexical correction candidates are not confirmed errors"},
    "respond": {"plane": "observed", "axis": "output", "input": "tool calls/results, status and lineage",
                "computation": "known-outcome rates, sequences, transitions and explicit retry links",
                "output": "bottleneck_features.respond / products.tools", "unknown": "running, rejected, interrupted and unknown excluded from success/failure denominator"},
    "cost_time": {"plane": "observed", "axis": "output", "input": "request token buckets, explicit cost and reliable timestamps",
                  "computation": "compatible usage aggregation and interval/latency statistics",
                  "output": "bottleneck_features.cost_time / presentation.statistics", "unknown": "missing cost is not free; session span is not work duration"},
    "outcome": {"plane": "observed", "axis": "output", "input": "validation results, delivery records and linked human feedback",
                "computation": "objective check outcome separate from subjective acceptance",
                "output": "bottleneck_features.outcome / presentation.diagnostics.outcomes", "unknown": "a successful command or completion claim is not user acceptance"},
}
