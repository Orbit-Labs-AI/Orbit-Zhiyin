import pytest
from test_supplemental_requirements import run

from orbit_backend.feedback import reader_context
from orbit_backend.pipeline_eval import evidence_checks
from orbit_backend.privacy import redact
from orbit_backend.recommend import recommend


@pytest.mark.parametrize('text', ['请解释如何成为开发者。', '写一篇关于如何成为开发者的文章。'])
def test_becoming_a_developer_is_a_subject_not_an_audience(text):
    assert reader_context(text, 'u') == []


def test_explicit_delivery_after_an_unrelated_caveat_has_a_body_gap(tmp_path):
    _, data = run(tmp_path, [('user','请写通俗的报告。'), ('assistant','尚未核对格式，但已保存 [报告](report.md)。')])
    assert data['data_gaps'][0]['code'] == 'artifact_body_missing'


@pytest.mark.parametrize('text,value', [
    ('password="supersecret"','supersecret'), ('"api_key": "abcdefghijklmnop"','abcdefghijklmnop'),
    ("'access_token': 'abcdef123456'",'abcdef123456'), ('secret="abc\\\"defghijkl"','defghijkl'),
])
def test_quoted_credentials_keep_delimiters_and_hide_values(text, value):
    output=redact(text)
    assert value not in output and '[密钥已隐藏]' in output
    assert output.count('"') == text.count('"') or '\\"' in text


def test_quoted_credential_is_removed_before_store_and_report_generation(tmp_path):
    store, _ = run(tmp_path, [('user','请继续。'), ('assistant','password="supersecret"')])
    assert all('supersecret' not in e.text for e in store.events())


def test_language_evaluation_accepts_both_permitted_languages(tmp_path):
    store, data = run(tmp_path, [('user','请写文档，中文或英文都可以，回复不超过10字。'), ('assistant','这份长回复只用于验证允许的语言与资源是否匹配。')])
    recs=recommend(data)
    assert any(r['resource_id']=='humanizer' for r in recs)
    assert evidence_checks(store, data, recs)['deliverable_language_preserved']
