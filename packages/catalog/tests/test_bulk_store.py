"""Bulk ingestion keeps index-only text local and resumes without loading old bodies."""
import hashlib
import json

from orbit_catalog.contracts import SourceSpec
from orbit_catalog.snapshot import build_snapshot, load_seed
from orbit_catalog.store import CatalogStore
from orbit_catalog.sync import CatalogSync


def test_index_only_source_is_searchable_but_never_a_distributed_body(tmp_path, monkeypatch):
    content = '---\nname: local-index\ndescription: Review debugging evidence\n---\n# Evidence\nDistinctiveIndexOnlyPhrase'
    source_file = tmp_path / 'source.jsonl'
    source_file.write_text(json.dumps({'content': content, 'repo': 'example/skills', 'path': 'debug/SKILL.md'}) + '\n')
    store = CatalogStore(tmp_path / 'catalog.db')
    spec = SourceSpec(source_id='corpus', kind='bulk', url='https://example.org/corpus',
                      config={'file': str(source_file), 'revision': 'fixed-v1'})
    store.register([spec])
    monkeypatch.setattr(store, 'known_resources', lambda *_: (_ for _ in ()).throw(AssertionError('bulk must not load all old bodies')))
    first = CatalogSync(store, None).sync(['corpus'], force=True)
    assert first[0]['status'] == 'completed' and first[0]['changed'] == 1
    item_id = 'skill:sha256:' + hashlib.sha256(content.encode()).hexdigest()
    with store.connect(True) as conn:
        assert conn.execute("SELECT count(*) FROM chunk_fts WHERE chunk_fts MATCH 'distinctiveindexonlyphrase'").fetchone()[0] > 0
    detail = store.detail(item_id)
    assert detail['resource']['body'] == '' and detail['readme'] is None
    assert all(not c['text'] for c in detail['chunks'] if c['field'] == 'body')
    seed = load_seed(build_snapshot(store))
    assert not any(r['item_id'] == item_id for source in seed['sources'].values() for r in source['items'])
    again = CatalogSync(store, None).sync(['corpus'], force=True)
    assert again[0]['status'] == 'completed' and again[0]['changed'] == 0
    assert store.stats()['items'] == 1 and store.verify()['ok']


def test_full_passage_policy_covers_existing_future_and_rebuilt_resources(tmp_path):
    from orbit_catalog.contracts import Page, Record, Resource
    store = CatalogStore(tmp_path / 'catalog.db')
    store.register([SourceSpec(source_id='fixture', kind='bundle', url='bundle:')])

    def publish(name):
        resource = Resource(item_id=name, type='skill', name=name, url='https://example.org',
                            body='\n'.join(f'# Section {i}\nDistinct paragraph {i} about testing.' for i in range(10)),
                            body_policy='licensed', license='MIT')
        with store.writer():
            run = store.begin_run('fixture')
            store.stage(run['run_id'], Page(records=[Record(native_id=name, resource=resource)], complete=True, mode='incremental'))
            store.publish(run['run_id'])

    publish('first')
    with store.reader() as db:
        assert db.execute('SELECT count(*) FROM resource_chunk WHERE embed=0').fetchone()[0] > 0
    assert store.enable_all_embeddings()['newly_eligible_chunks'] > 0
    publish('second')
    store.rebuild()
    with store.reader() as db:
        assert db.execute('SELECT count(*) FROM resource_chunk WHERE embed=0 OR text_hash IS NULL').fetchone()[0] == 0
        assert db.execute("SELECT value FROM catalog_meta WHERE key='embedding_policy'").fetchone()[0] == 'all'
    assert store.enable_all_embeddings()['newly_eligible_chunks'] == 0
