-- Physical indexes only: independent of the logical user_version/row contract.
-- Reapply idempotently on open so existing canonical databases gain the indexes.
-- Deferred FK reconciliation on parent INSERT otherwise scans growing child tables.
CREATE INDEX IF NOT EXISTS projection_fk_tool_session ON tool_call(session_uid);
CREATE INDEX IF NOT EXISTS projection_fk_tool_turn ON tool_call(turn_uid);
CREATE INDEX IF NOT EXISTS projection_fk_model_session ON model_call(session_uid);
CREATE INDEX IF NOT EXISTS projection_fk_model_turn ON model_call(turn_uid);
CREATE INDEX IF NOT EXISTS projection_fk_link_session ON link(session_uid);
CREATE INDEX IF NOT EXISTS projection_fk_link_turn ON link(turn_uid);
CREATE INDEX IF NOT EXISTS projection_fk_session_spawn ON session(spawn_call_uid);
