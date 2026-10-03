-- Analysis input v1, staging revision 3.
-- Turn timing reported by Codex task_complete (duration_ms, time_to_first_token_ms) becomes queryable L3 data.
ALTER TABLE turn ADD COLUMN duration_ms INTEGER;
ALTER TABLE turn ADD COLUMN ttft_ms INTEGER;
-- Counter cycle of a cumulative snapshot ('thread_token_usage' or 'thread_total:<n>' after a native reset).
ALTER TABLE usage_snapshot ADD COLUMN counter_cycle TEXT;
-- Columns declared in 002 that no Codex record can populate (no approval wait times, error classes,
-- skill invocations or spawn-call/child links in the rollout format). Dropped instead of left all-NULL.
ALTER TABLE tool_call DROP COLUMN approval_wait_ms;
ALTER TABLE tool_call DROP COLUMN error_class;
ALTER TABLE tool_call DROP COLUMN skill;
ALTER TABLE tool_call DROP COLUMN subagent_session_uid;
ALTER TABLE session DROP COLUMN spawn_call_uid;
INSERT OR IGNORE INTO dirty_session SELECT DISTINCT session_uid FROM current_record WHERE session_uid IS NOT NULL;
