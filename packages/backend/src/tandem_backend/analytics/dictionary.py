"""Machine-readable feature meanings shared by all analytics endpoints."""

from .cost_time.dictionary import FEATURES as COST_TIME_FEATURES
from .instruction.dictionary import FEATURES as INSTRUCTION_FEATURES
from .interaction.dictionary import FEATURES as INTERACTION_FEATURES
from .outcome.dictionary import FEATURES as OUTCOME_FEATURES
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
define("observed_session_span_ms", "ms", "last_observed_ts - first_observed_ts; never work duration", "event.ts")
define("avg_user_message_chars median_user_message_chars avg_assistant_message_chars median_assistant_message_chars",
       "Unicode character", "Mean/median original_chars, else retained length with truncation lower bound", "message text + original_chars", "messages with measurable text")
define("call_count paired_result_count known_success_count known_failure_count rejected_count interrupted_count running_count unknown_status_count unpaired_count tool_call_count",
       "logical tool call", "One row per call; status only from explicit protocol; unpaired results never imply success", "tool_call")
define("success_rate failure_rate", "ratio", "Explicit success/failure count divided by known success + failure", "tool_call.status", "known success + known failure")
define("median_duration_ms p25_duration_ms p75_duration_ms p90_duration_ms", "ms", "Linear interpolated quantile of available nonnegative durations", "tool_call.duration_ms", "calls with duration")
define("duration_sum_ms", "ms", "Sum usable durations; retains duration source and quality", "tool_call.duration_ms")
define("reliable_interval_union_ms", "ms", "Union of reliable observed start/end intervals, including overlapping children", "tool_call native endpoints")
define("error_count branch_count rollback_rewind_count compaction_count permission_request_count subagent_spawn_count interruption_count",
       "event", "Count explicitly supported event kinds; unsupported kinds return null", "event.kind + attrs")
define("repeated_transition_count", "transition", "Count edges previously seen in the same session sequence", "event.seq")
define("repeated_transition_rate", "ratio", "Repeated transition count / all observed transitions", "event.seq", "transitions")
define("max_repeated_transition_run", "transition", "Longest adjacent run of an identical edge; not repeated cycle detection", "event.seq")
define("consecutive_failed_calls", "adjacent failed pair", "Adjacent failed logical calls in the same session", "tool_call status + seq")
define("confirmed_same_argument_failed_retries", "adjacent failed pair", "Same tool, literal argument digest and known equal status_scope; wrapper-level only when wrapper", "tool_call + L2 attrs")
define("correction_signal_count", "human message", "Messages matching conservative correction lexical markers; evidence only", "confirmed human text", kind="proxy")
define("correction_signal_rate", "ratio", "Signal messages / confirmed human messages", "confirmed human text", "confirmed human messages in main sessions", "proxy")
define("language_signals", "file extension occurrence", "Map explicit file extensions; no guessing language from semantics", "confirmed human text", kind="proxy")
define("request_count", "model request", "Unique call_uid with call/delta and reliable boundary", "model_call")
define("total_tokens", "token", "input_tokens + cache_read_tokens + cache_write_tokens + output_tokens; reasoning already included", "compatible complete usage buckets")
define("cost_usd", "USD", "Sum complete request costs with source; price estimates require price-table version", "model_call", kind="direct_observation")
define("median_latency_ms median_ttft_ms", "ms", "Median reliable request metric, not differences between message times", "model_call", "requests with metric")
define("sessions_by_day sessions_by_hour human_messages_by_day human_messages_by_hour tool_calls_by_day model_usage_by_day active_days weekday_distribution hour_distribution",
       "record", "Bucket reported timestamps in display_timezone; unknown clocks excluded; models count requests not snapshots", "event/tool/model timestamps")
define("cluster_id embedding_x embedding_y top_terms distance_to_cluster_centroid", "representation space", "Character 2-4 gram TF-IDF, seeded SVD, normalization, cosine DBSCAN; PCA visual coordinates", "confirmed main-session human text", kind="unsupervised_representation")
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
FEATURES.update(TASK_FEATURES)
# Family-owned definitions retain the established global lookup surface.
FEATURES.update(INSTRUCTION_FEATURES)
