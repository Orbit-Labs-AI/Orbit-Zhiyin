"""Reader labels are evaluation data; empty or partial forms cannot become success."""

import json
from pathlib import Path

import pytest

from tandem_backend.cli import main
from tandem_backend.reader_eval import DIMENSIONS, make_pack, reader_results


def read(path):
    return json.loads(Path(path).read_text())


def save(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False))


def fixture(tmp_path):
    result = make_pack(tmp_path / 'reviews')
    folder = Path(result['folder'])
    return folder, Path(result['ratings']['X'])


def test_forms_reverse_the_same_variants_and_literal_facts_remain_visible(tmp_path):
    folder, _ = fixture(tmp_path)
    manifest = read(folder / 'manifest.json')
    for case in manifest['cases']:
        x = manifest['forms']['X'][case['id']]
        y = manifest['forms']['Y'][case['id']]
        assert x['A'] == y['B'] and x['B'] == y['A']
    checks = read(folder / 'checks.json')
    assert len(checks['cases']) == 6
    assert checks['human_acceptance'] == 'pending'
    assert all(not any(i['code'] == 'missing_fact' for i in v['issues'])
               for c in checks['cases'] for v in c['variants'].values())
    assert 'candidate' not in (folder / 'review-X.md').read_text()
    assert 'baseline' not in (folder / 'review-Y.md').read_text()


def test_blank_forms_preserve_unknown_scores_and_acceptance(tmp_path):
    folder, ratings = fixture(tmp_path)
    result = reader_results(folder, ratings)
    assert result['review_status'] == result['human_acceptance'] == 'pending'
    assert result['completed_cases'] == 0 and result['preference_counts'] == {}
    assert all(s == {'mean': None, 'rated': 0} for variant in result['scores'].values() for s in variant.values())
    assert result['history_updated'] is False


def test_partial_scores_and_retelling_do_not_imply_acceptance(tmp_path):
    folder, path = fixture(tmp_path)
    ratings = read(path)
    ratings['cases'][0]['variants']['A']['scores']['priority'] = 0
    ratings['cases'][0]['main_point'] = '还有条件没讲清楚。'
    save(path, ratings)
    result = reader_results(folder, path)
    assert result['review_status'] == 'partially_rated' and result['human_acceptance'] == 'pending'
    assert result['completed_cases'] == 0
    variant = read(folder / 'manifest.json')['forms']['X'][ratings['cases'][0]['id']]['A']
    assert result['scores'][variant]['priority'] == {'mean': 0.0, 'rated': 1}


def test_explicit_scoped_acceptance_requires_complete_labels_and_retelling(tmp_path):
    folder, path = fixture(tmp_path)
    ratings = read(path)
    ratings['reviewer'] = 'fictional-test-reader'
    ratings['acceptance']['decision'] = 'accept'
    save(path, ratings)
    with pytest.raises(ValueError, match='完成各案例'):
        reader_results(folder, path)
    for row in ratings['cases']:
        row['preferred'] = 'B'
        row['main_point'] = '测试中提供的要点复述。'
        row['reason_or_next_step'] = '测试中提供的判断依据。'
        for value in row['variants'].values():
            value['scores'] = dict.fromkeys(DIMENSIONS, 3)
            value['usable'] = True
    save(path, ratings)
    result = reader_results(folder, path)
    assert result['review_status'] == 'rated' and result['human_acceptance'] == 'reviewer_accepted'
    assert result['acceptance_scope'] == 'listed_cases'
    assert result['completed_cases'] == 6 and sum(result['preference_counts'].values()) == 6


def test_rebuilding_pack_preserves_reader_annotations_and_order(tmp_path):
    folder, path = fixture(tmp_path)
    ratings = read(path)
    ratings['cases'][0]['note'] = '已经填写，不能覆盖。'
    save(path, ratings)
    original = path.read_bytes()
    repeated = make_pack(tmp_path / 'reviews')
    assert repeated['folder'] == str(folder.resolve()) and path.read_bytes() == original
    other = make_pack(tmp_path / 'reviews', seed=1)
    assert other['review_id'] != repeated['review_id']


def test_modified_text_or_wrong_mapping_invalidates_old_labels(tmp_path):
    folder, ratings = fixture(tmp_path)
    target = folder / 'review-X.md'
    target.write_text(target.read_text() + '\nchanged')
    with pytest.raises(ValueError, match='正文或规则检查已改变'):
        reader_results(folder, ratings)
    with pytest.raises(ValueError, match='已有评审材料被修改'):
        make_pack(tmp_path / 'reviews')


@pytest.mark.parametrize('alter', [
    lambda r: r['cases'].append(r['cases'][0]),
    lambda r: r['cases'][0]['variants']['A']['scores'].update(priority=True),
    lambda r: r.update(manifest_sha256='wrong'),
    lambda r: r['cases'][0].update(id='unknown-case'),
])
def test_invalid_ratings_fail_closed(tmp_path, alter):
    folder, path = fixture(tmp_path)
    ratings = read(path)
    alter(ratings)
    save(path, ratings)
    with pytest.raises(ValueError):
        reader_results(folder, path)


def test_cli_reader_commands_never_create_or_update_normal_history(tmp_path, capsys):
    unused = tmp_path / 'unused.sqlite'
    existing = tmp_path / 'history.sqlite'
    existing.write_bytes(b'fictional-ledger-byte-snapshot')
    main(['--db', str(unused), 'reader-pack', '--output', str(tmp_path / 'reviews')])
    pack = json.loads(capsys.readouterr().out)
    main(['--db', str(existing), 'reader-results', '--pack', pack['folder'], '--ratings', pack['ratings']['X']])
    result = json.loads(capsys.readouterr().out)
    assert result['human_acceptance'] == 'pending'
    assert not unused.exists() and existing.read_bytes() == b'fictional-ledger-byte-snapshot'
