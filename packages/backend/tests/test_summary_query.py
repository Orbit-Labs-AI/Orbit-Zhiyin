"""Large-range overview counts agree with the scoped feature engine on inspectable fixtures."""

import pytest

from tandem_backend.analytics.inputs import Scope
from tandem_backend.analytics.service import analyze_store
from tandem_backend.cli import demo_home
from tandem_backend.data_access.ingest import ingest
from tandem_backend.data_access.store import CanonicalStore
from tandem_backend.summary_query import overview_summary


@pytest.mark.parametrize('bounds', [
    {}, {'from_ts': 1767225603000}, {'until_ts': 1767225603000},
    {'project_ids': []}, {'model_ids': []}, {'effort_raw': []},
    {'root_session_uids': []}, {'include_children': False}, {'agent_ids': []}, {'source_ids': []},
    {'excluded_session_uids': ['fixture-root']},
])
def test_summary_counts_preserve_scope_and_human_origin(tmp_path, bounds):
    data_dir = tmp_path / 'data'
    ingest(data_dir, 'codex', demo_home(tmp_path / 'codex'))
    store = CanonicalStore(data_dir)
    if 'excluded_session_uids' in bounds:
        with store.connect() as db:
            root = db.execute("SELECT session_uid FROM session WHERE kind='main' ORDER BY session_uid LIMIT 1").fetchone()[0]
        bounds = {'excluded_session_uids': [root]}
    scope = Scope(**bounds)
    detailed = analyze_store(store, scope, with_text=False)
    compact = overview_summary(store, scope)
    for field in ('events', 'main_sessions', 'human_messages'):
        assert compact['overview']['counts'][field] == detailed['overview']['counts'][field]
    assert compact['analysis_mode'] == 'aggregate_only'
    assert compact['overview']['usage']['status'] == 'excluded'
    assert compact['overview']['usage']['total_tokens'] is None
