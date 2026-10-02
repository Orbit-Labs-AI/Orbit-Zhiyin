"""Configuration observations survive the data-to-analytics boundary."""

from tandem_data.analysis_input import AnalysisScope, read_analysis
from tandem_data.inventory import InventoryRequest, scan_inventory
from tandem_data.store import Store

from tandem_backend.analytics.inputs import AnalysisInputBundle
from tandem_backend.analytics.service import analyze_bundle


def test_inventory_reaches_analytics_and_changes_digest(tmp_path):
    root = tmp_path / 'agent'
    root.mkdir()
    (root / 'AGENTS.md').write_text('synthetic rule')
    with Store(tmp_path / 'data') as store:
        store.rebuild()
        missing = AnalysisInputBundle.from_dict(read_analysis(store.home, AnalysisScope('UTC')))
        assert missing.inventory is None
        scan_inventory(store, InventoryRequest('codex', root))
        data = read_analysis(store.home, AnalysisScope('UTC'))
        bundle = AnalysisInputBundle.from_dict(data)
        result = analyze_bundle(bundle)
        assert result['inventory'] == data['inventory']
        assert result['inventory_scans'] == data['inventory_scans']
        assert result['coverage']['inventory']['status'] == 'available'
        assert bundle.versions['content_digest'] != missing.versions['content_digest']
        historical = read_analysis(store.home, AnalysisScope('UTC', until_ts=1))
        assert historical['inventory'] is None
