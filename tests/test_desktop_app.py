"""Desktop acceptance: explicit sources, real jobs, persistence and recovery."""

import json
import shutil
import threading
import time
from pathlib import Path

from fastapi.testclient import TestClient
from tandem_data.store import Store
from tandem_data.validation.fixtures import create_sources

from tandem_backend.app_api import create_desktop_app
from tandem_backend.cli import demo_home

TOKEN = 'synthetic-desktop-token-for-tests-only'


def client_for(home, *, discovery=None):
    return TestClient(create_desktop_app(home, TOKEN, Path(__file__).parents[1] / 'docs/design/demo/tandem-demo.html',
                      discovery=discovery or (lambda: [])),
                      headers={'Authorization': 'Bearer ' + TOKEN})


def finish(client, response):
    assert response.status_code == 202, response.text
    job = response.json()
    deadline = time.monotonic() + 15
    while job['status'] in ('queued', 'running'):
        assert time.monotonic() < deadline
        time.sleep(.02)
        job = client.get('/v1/app/jobs/' + job['id']).json()
    return job


def test_desktop_multi_agent_import_pagination_export_and_restart(tmp_path):
    roots = create_sources(tmp_path / 'sources')
    roots['codex'] = demo_home(tmp_path / 'codex')
    home = tmp_path / 'data'
    with client_for(home) as client:
        assert client.get('/v1/app/state').json()['storage']['tables']['session'] == 0
        ids = []
        for agent, root in roots.items():
            response = client.post('/v1/app/sources', json={'agent': agent, 'root': str(root)})
            assert response.status_code == 200, response.text
            ids.append(response.json()['id'])
        job = finish(client, client.post('/v1/app/jobs', json={'source_ids': ids}))
        assert job['status'] == 'completed', job
        state = client.get('/v1/app/state').json()
        assert state['storage']['tables']['source'] == 7
        assert state['storage']['tables']['session'] >= 9
        listing = client.get('/v1/app/sessions?agent=codex&limit=1').json()
        assert listing['total'] == 3
        assert listing['next_offset'] == 1
        assert listing['items'][0]['display_title_source'] == 'first_message'
        assert listing['items'][0]['display_title'] != '未命名会话'
        sid = listing['items'][0]['session_uid']
        first = client.get(f'/v1/app/sessions/{sid}/events?limit=2').json()
        assert all(e['display']['title'] for e in first['items'])
        second = client.get(f'/v1/app/sessions/{sid}/events?after_seq={first["next_after_seq"]}&limit=2').json()
        assert {e['event_uid'] for e in first['items']}.isdisjoint(e['event_uid'] for e in second['items'])
        for section in ('overview', 'preferences', 'tasks', 'instruction', 'tools', 'projects', 'bottleneck_features', 'recommendations'):
            response = client.get('/v1/app/analysis', params={'section': section})
            assert response.status_code == 200, response.text
            assert section in response.json()
        exported = client.get('/v1/app/export').json()
        assert exported['input_contract'] == 'analysis-input-v1'
        assert 'sample_boundary' not in exported
        assert exported['scope']['display_timezone'] == 'UTC'
        localized = client.get('/v1/app/analysis?section=overview&display_timezone=Pacific/Auckland')
        assert localized.status_code == 200
        assert localized.json()['scope']['display_timezone'] == 'Pacific/Auckland'
        repeated = finish(client, client.post('/v1/app/jobs', json={'source_ids': ids}))
        assert all(r['changed'] == 0 for r in repeated['results'])
        backup = finish(client, client.post('/v1/app/jobs', json={'kind': 'backup'}))
        assert Path(backup['results'][0]['path'], 'tandem.db').is_file()
        client.patch('/v1/app/settings', json={'onboarded': True})
    with client_for(home) as restarted:
        state = restarted.get('/v1/app/state').json()
        assert state['settings']['onboarded'] is True
        assert state['storage']['tables']['session'] >= 9


def test_desktop_auth_origin_and_source_consent(tmp_path):
    root = demo_home(tmp_path / 'codex')
    with client_for(tmp_path / 'data') as client:
        assert client.get('/v1/app/state', headers={'Authorization': ''}).status_code == 401
        assert client.post('/v1/app/jobs', json={}, headers={'Origin': 'https://untrusted.example'}).status_code == 403
        assert client.post('/v1/app/jobs', json={'source_ids': ['unapproved']}).status_code == 422
        source = client.post('/v1/app/sources', json={'agent': 'codex', 'root': str(root), 'enabled': False}).json()
        assert client.post('/v1/app/jobs', json={'source_ids': [source['id']]}).status_code == 422
        assert client.get('/app').status_code == 200
        assert 'fonts.googleapis.com' not in client.get('/app').text


def test_stale_projection_is_recoverable_and_interrupted_tasks_survive(tmp_path):
    home = tmp_path / 'data'
    with client_for(home) as client:
        with Store(home) as store:
            store.db.execute("UPDATE projection_run SET mapper_version='obsolete'")
        assert client.get('/health').json()['readiness'] == 'rebuild_required'
        for route in ('/v1/sessions', '/v1/analytics/overview', '/v1/app/sessions'):
            response = client.get(route)
            assert response.status_code == 409, response.text
            assert response.json()['error']['code'] == 'rebuild_required'
        job = finish(client, client.post('/v1/app/jobs', json={'kind': 'rebuild'}))
        assert job['status'] == 'completed'
    path = home / 'app-state.json'
    data = json.loads(path.read_text())
    data['jobs']['interrupted'] = {'id': 'interrupted', 'status': 'running', 'kind': 'import', 'created_at': 0, 'source_ids': [], 'selection': 'full'}
    path.write_text(json.dumps(data))
    with client_for(home) as client:
        assert client.get('/v1/app/jobs/interrupted').json()['status'] == 'interrupted'


def test_cancel_conflict_and_retry_publish_only_complete_projections(tmp_path, monkeypatch):
    root = demo_home(tmp_path / 'codex')
    started, release = threading.Event(), threading.Event()
    original = Store.capture_file

    def held_capture(self, *args, **kwargs):
        started.set()
        assert release.wait(5)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Store, 'capture_file', held_capture)
    with client_for(tmp_path / 'data') as client:
        source = client.post('/v1/app/sources', json={'agent': 'codex', 'root': str(root)}).json()
        request = {'source_ids': [source['id']]}
        response = client.post('/v1/app/jobs', json=request)
        assert started.wait(5)
        assert client.post('/v1/app/jobs', json=request).status_code == 409
        job_id = response.json()['id']
        assert client.post(f'/v1/app/jobs/{job_id}/cancel', json={}).json()['cancel_requested']
        release.set()
        assert finish(client, response)['status'] == 'cancelled'
        assert client.get('/v1/app/storage').json()['readiness'] == 'rebuild_required'
        assert finish(client, client.post('/v1/app/jobs', json=request))['status'] == 'completed'
        assert client.get('/v1/app/storage').json()['readiness'] == 'ready'


def test_disappeared_source_can_be_disabled(tmp_path):
    root = tmp_path / 'empty'
    root.mkdir()
    with client_for(tmp_path / 'data') as client:
        assert client.post('/v1/app/sources', json={'agent': 'pi', 'root': str(root)}).status_code == 200
        root.rmdir()
        response = client.post('/v1/app/sources', json={'agent': 'pi', 'root': str(root), 'enabled': False})
        assert response.status_code == 200
        assert not response.json()['enabled']


def test_discovery_catalogue_is_isolated_and_does_not_grant_import_consent(tmp_path):
    roots = create_sources(tmp_path / 'sources')
    catalogue = [{'agent': agent, 'root': str(roots[agent])} for agent in ('pi', 'dsh')]
    with client_for(tmp_path / 'data', discovery=lambda: catalogue) as client:
        found = client.get('/v1/app/discovery').json()['items']
        assert {s['root'] for s in found} == {s['root'] for s in catalogue}
        assert all(not s['enabled'] for s in found)
        assert client.get('/v1/app/storage').json()['tables']['raw_record'] == 0


def test_selected_rebuild_uses_archives_after_upstream_is_removed(tmp_path, monkeypatch):
    roots = create_sources(tmp_path / 'sources')
    home = tmp_path / 'data'
    with client_for(home) as client:
        sources = {
            agent: client.post('/v1/app/sources', json={'agent': agent, 'root': str(roots[agent])}).json()['id']
            for agent in ('pi', 'dsh')
        }
        imported = finish(client, client.post('/v1/app/jobs', json={'source_ids': list(sources.values())}))
        assert imported['status'] == 'completed'
        with Store(home) as store:
            unrelated = [tuple(row) for row in store.db.execute(
                "SELECT e.* FROM event e JOIN session s USING(session_uid) WHERE s.source_id=? ORDER BY event_uid", (sources['dsh'],))]
            store.db.execute("UPDATE source_file SET watermark=json_set(watermark,'$.mapper_version','obsolete') WHERE source_id=?", (sources['pi'],))
        shutil.rmtree(roots['pi'])

        def forbid_capture(*args, **kwargs):
            raise AssertionError('Archive rebuild must not capture upstream files')

        monkeypatch.setattr(Store, 'capture_file', forbid_capture)
        repaired = finish(client, client.post('/v1/app/jobs', json={'kind': 'rebuild', 'source_ids': [sources['pi']]}))
        assert repaired['status'] == 'completed', repaired
        assert client.get('/v1/app/storage').json()['readiness'] == 'ready'
        assert client.get('/v1/app/sessions?agent=pi').json()['total'] > 0
        with Store(home) as store:
            assert unrelated == [tuple(row) for row in store.db.execute(
                "SELECT e.* FROM event e JOIN session s USING(session_uid) WHERE s.source_id=? ORDER BY event_uid", (sources['dsh'],))]
        assert client.post('/v1/app/jobs', json={'kind': 'verify', 'source_ids': [sources['pi']]}).status_code == 422


def test_rebuild_reports_remaining_unparsed_records_as_partial(tmp_path):
    home, root = tmp_path / 'data', tmp_path / 'source'
    root.mkdir()
    with client_for(home) as client:
        source = client.post('/v1/app/sources', json={'agent': 'codex', 'root': str(root)}).json()
        with Store(home) as store:
            store.add_source('codex', root)
            store.capture_stream(source['id'], 'sessions/broken.jsonl', [b'{invalid json}\n'])
        job = finish(client, client.post('/v1/app/jobs', json={'kind': 'rebuild', 'source_ids': [source['id']]}))
        assert job['status'] == 'partial'
        assert job['results'][0]['current_unparsed'] == 1


def test_analysis_budget_has_an_overview_fallback_and_actionable_export_error(tmp_path, monkeypatch):
    from tandem_data.analysis_input import AnalysisLimitExceeded

    from tandem_backend.analytics.cache import AnalyticsCache

    def exceed_budget(*args, **kwargs):
        raise AnalysisLimitExceeded('synthetic budget boundary')

    monkeypatch.setattr(AnalyticsCache, 'read', exceed_budget)
    with client_for(tmp_path / 'data') as client:
        overview = client.get('/v1/app/analysis?section=overview')
        assert overview.status_code == 200
        assert overview.json()['analysis_mode'] == 'aggregate_only'
        for route in ('/v1/app/analysis?section=tools', '/v1/app/export'):
            response = client.get(route)
            assert response.status_code == 422
            assert response.json()['error']['code'] == 'analysis_scope_too_large'
            assert '缩小范围' in response.json()['error']['message']
