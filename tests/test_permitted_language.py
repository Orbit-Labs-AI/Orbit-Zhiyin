import pytest
from test_supplemental_requirements import run

from tandem_backend.feedback import language_constraints, signals, task_contexts
from tandem_backend.models import Event
from tandem_backend.recommend import recommend


@pytest.mark.parametrize('text', ['请解释引用来源的定义。', '什么是说明依据？'])
def test_sourcing_topic_does_not_supply_a_grounding_requirement(text):
    assert not any(s.dimension == 'grounding' for s in signals([Event('u','s',1,'user_message',None,text=text)]))


@pytest.mark.parametrize('text', ['请用中文或英文回答。', '中英文版本都可以。', '请用英文或者中文回答。'])
def test_permitted_languages_remain_alternatives(text):
    assert language_constraints(text)[0] == 'zh_or_en'


def test_later_exclusive_instruction_and_exclusion_resolve_alternatives():
    assert language_constraints('请用中文或英文回答，最后用中文就好。')[0] == 'zh'
    events = [Event('a','s',1,'user_message',None,text='请写文档，中文或英文都可以。'),
              Event('b','s',2,'user_message',None,text='继续，不用中文。')]
    assert task_contexts(events)['b']['language'] == 'en'


def test_alternative_does_not_exclude_an_english_resource(tmp_path):
    _, data = run(tmp_path, [('user', '请写通俗的文档，中文或英文都可以。'), ('assistant', '旧说明。'), ('user', '没看懂，请给个例子。')])
    resource = {'id':'fictional', 'kind':'skill', 'name':'Fictional', 'dimensions':['clarity'], 'problem_types':['explanation_revision'],
                'scenes':['document'], 'language':'en', 'verified_sha':'a'*40, 'verification':'repository_and_skill_read',
                'url':'https://example.test', 'source_path':'SKILL.md', 'limitations':'效果未测', 'summary':'读者测试', 'trial':'复述思路'}
    assert recommend(data, catalog=[resource])


def test_bare_unit_replacement_removes_the_obsolete_limit(tmp_path):
    _, data = run(tmp_path, [('user','回答不超过100字，改为200字。'), ('assistant','甲'*150)])
    assert data['bottlenecks'] == []
    assert next(p for p in data['preferences'] if p['dimension']=='brevity')
