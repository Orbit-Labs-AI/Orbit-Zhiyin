"""Configuration observations survive the data-to-analytics boundary."""

from tandem_data.analysis_input import AnalysisScope, read_analysis
from tandem_data.inventory import InventoryRequest, scan_inventory
from tandem_data.store import Store

from tandem_backend.analytics.inputs import AnalysisInputBundle
from tandem_backend.analytics.products import build_products
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
        product = build_products(bundle)
        assert product['configuration']['items'] == data['inventory']
        assert product['configuration']['status'] == 'available'
        assert result['inventory'] == data['inventory']
        assert result['inventory_scans'] == data['inventory_scans']
        assert result['coverage']['inventory']['status'] == 'available'
        assert bundle.versions['content_digest'] != missing.versions['content_digest']
        historical = read_analysis(store.home, AnalysisScope('UTC', until_ts=1))
        assert historical['inventory'] is None


def test_partial_inventory_survives_analysis_with_per_source_diagnostics(tmp_path):
    import json

    first, second = tmp_path / 'first', tmp_path / 'second'
    first.mkdir()
    second.mkdir()
    (first / 'AGENTS.md').write_text('first')
    (second / 'AGENTS.md').write_text('second')
    (second / 'settings.json').write_text(json.dumps({'packages': [None]}))
    with Store(tmp_path / 'data') as store:
        store.rebuild()
        scan_inventory(store, InventoryRequest('codex', first))
        scan_inventory(store, InventoryRequest('pi', second))
        data = read_analysis(store.home, AnalysisScope('UTC'))
        result = analyze_bundle(AnalysisInputBundle.from_dict(data), with_text=False)
        assert result['coverage']['inventory']['status'] == 'partial'
        assert result['coverage']['inventory']['rows'] == 2
        assert {item['agent'] for item in result['inventory']} == {'codex', 'pi'}
        scans = {scan['agent']: scan for scan in result['inventory_scans']}
        assert scans['codex']['diagnostics'] == []
        assert scans['pi']['coverage']['plugin']['status'] == 'partial'
        assert scans['pi']['diagnostics'][0]['code'] == 'invalid_plugin_reference'


def test_inventory_cutoff_is_utc_and_not_filtered_by_session_model(tmp_path, monkeypatch):
    root = tmp_path / 'source'
    root.mkdir()
    path = root / 'AGENTS.md'
    path.write_text('old')
    clock = iter((1000, 2000))
    monkeypatch.setattr('tandem_data.inventory.now_ms', lambda: next(clock))
    with Store(tmp_path / 'data') as store:
        store.rebuild()
        scan_inventory(store, InventoryRequest('codex', root))
        path.write_text('new')
        scan_inventory(store, InventoryRequest('codex', root))
        before = read_analysis(store.home, AnalysisScope('UTC', until_ts=2000))
        filtered = read_analysis(store.home, AnalysisScope(
            'Asia/Shanghai', until_ts=2000, from_ts=1500, model_ids=(), root_session_uids=(),
        ))
        assert filtered['sessions'] == [] and filtered['events'] == []
        assert filtered['inventory'] == before['inventory']
        assert before['inventory'][0]['observed_at'] == 1000
        # Inventory is the last observation before the cutoff, not a session-time count.
        assert read_analysis(store.home, AnalysisScope('UTC', until_ts=1000))['inventory'] is None
        assert read_analysis(store.home, AnalysisScope('UTC', until_ts=2001))['inventory'][0]['observed_at'] == 2000
