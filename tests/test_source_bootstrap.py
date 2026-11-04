import json
from pathlib import Path

import pytest

from litrelay.project_config import initialize_project
from litrelay.project_workflow import _bootstrap, _inputs, run_project

HEADER = 'source,target_ru,type,note,confidence\n'


def make_project(tmp_path: Path, *, seed: bool = False, count: int = 4) -> Path:
    source = tmp_path / 'source'
    source.mkdir()
    for n in range(1, count + 1):
        (source / f'{n:04d}.txt').write_text(f'第{n}章 独特标记{n}\n' + f'完整章节内容{n}。' * 20)
    seed_path = None
    if seed:
        seed_path = tmp_path / 'seed.csv'
        seed_path.write_text(HEADER + '独特标记1,Имя из семени,person,,0.99\n')
    project = tmp_path / 'book'
    initialize_project(project, source=source, glossary=seed_path, min_chars=30)
    config_path = project / 'project.json'
    config = json.loads(config_path.read_text())
    config['translation']['model'] = 'translation-model'
    config['support']['model'] = 'support-model'
    config_path.write_text(json.dumps(config))
    return project


def fake_request(calls: list, *, fail: str = ''):
    def request(payload):
        agent = payload['metadata']['agent']
        data = json.loads(payload['input'][1]['content'])
        prompt = data.get('prompt', '')
        calls.append((agent, payload['model'], data))
        if 'Prepare an initial glossary BEFORE' in prompt:
            if fail == 'draft':
                raise RuntimeError('draft failure')
            text = HEADER + '独特标记1,Черновое имя,person,,0.99\n'
        elif 'Review this PROPOSED initial glossary' in prompt:
            if fail == 'review':
                raise RuntimeError('review failure')
            if fail == 'invalid':
                text = 'not a valid glossary'
            else:
                text = HEADER + '独特标记1,Исправленное имя,person,,0.99\n' + '不确定,Неуверенно,concept,,0.2\n'
        elif agent == 'translation-agent':
            cid = data['chapter_id']
            text = json.dumps({'chapter_id': cid, 'translation': f'Глава {int(cid)}. Имя\n' + 'Исправленное имя идёт домой. ' * 10,
                               'qa': {'terminology_checked': True, 'omission_risk': 'low', 'style_match': 'good', 'issues': []}},
                              ensure_ascii=False)
        elif agent == 'translation-qa':
            text = json.dumps({'chapter_id': data['chapter_id'], **{k: 99 for k in
                              ('meaning_score', 'terminology_score', 'style_score', 'omission_score')},
                              'verdict': 'pass', 'strengths': [], 'issues': [], 'missing_or_changed_facts': [],
                              'recommended_action': ''})
        else:
            text = HEADER
        return {'id': 'fake', 'model': payload['model'], 'output_text': text}
    return request


def test_source_samples_review_and_curated_glossary_precede_translation(tmp_path: Path):
    project = make_project(tmp_path)
    calls = []
    result = run_project(project, max_chapters=1, requester=fake_request(calls))
    assert result['accepted'] == 1
    draft, review, translation = calls[:3]
    assert draft[:2] == ('glossary-extractor', 'translation-model')
    assert review[:2] == ('glossary-extractor', 'support-model')
    assert translation[0] == 'translation-agent'
    prompt = draft[2]['prompt']
    for n in range(1, 4):
        assert (project / f'input/source/{n:04d}.txt').read_text().strip() in prompt
    assert '独特标记4' not in prompt
    assert 'Черновое имя' in review[2]['prompt']
    assert 'Исправленное имя' in translation[2]['glossary_csv']
    assert 'Черновое имя' not in translation[2]['glossary_csv']
    assert 'Неуверенно' not in translation[2]['glossary_csv']
    ready = json.loads(next(project.glob('work/bootstrap/*/ready.json')).read_text())
    assert ready['source_samples'] == [1, 2, 3]


def test_seed_skips_source_bootstrap(tmp_path: Path):
    project = make_project(tmp_path, seed=True)
    calls = []
    run_project(project, max_chapters=1, requester=fake_request(calls))
    assert calls[0][0] == 'translation-agent'
    assert 'Имя из семени' in calls[0][2]['glossary_csv']
    assert not any('initial glossary' in data.get('prompt', '') for _, _, data in calls)
    ready = json.loads(next(project.glob('work/bootstrap/*/ready.json')).read_text())
    assert ready['source_samples'] == []


@pytest.mark.parametrize('failure', ['draft', 'review', 'invalid'])
def test_bootstrap_failure_blocks_translation(tmp_path: Path, failure: str):
    project = make_project(tmp_path)
    calls = []
    with pytest.raises(RuntimeError, match='Source glossary'):
        run_project(project, max_chapters=1, requester=fake_request(calls, fail=failure))
    assert not any(agent == 'translation-agent' for agent, _, _ in calls)
    assert not list(project.glob('work/bootstrap/*/ready.json'))
    assert not list(project.glob('work/accepted/*.txt'))


def test_bootstrap_cache_reuse_and_source_fingerprint_change(tmp_path: Path):
    project = make_project(tmp_path)
    config, source, existing, fp = _inputs(project)
    calls = []
    first = _bootstrap(project, config, source, existing, fp, fake_request(calls))
    assert len(calls) == 2
    assert _bootstrap(project, config, source, existing, fp, lambda _: pytest.fail('unexpected request')) == first
    path = project / 'input/source/0002.txt'
    path.write_text(path.read_text() + '\nНовый фрагмент')
    config2, source2, existing2, fp2 = _inputs(project)
    assert fp2 != fp
    second = _bootstrap(project, config2, source2, existing2, fp2, fake_request(calls))
    assert len(calls) == 4 and first != second
    assert 'Новый фрагмент' in calls[2][2]['prompt']


def test_source_count_is_bounded_and_persisted(tmp_path: Path):
    project = make_project(tmp_path, count=2)
    config, source, existing, fp = _inputs(project)
    calls = []
    path = _bootstrap(project, config, source, existing, fp, fake_request(calls))
    assert json.loads((path.parent / 'ready.json').read_text())['source_samples'] == [1, 2]


def test_changed_sample_count_invalidates_bootstrap_cache(tmp_path: Path):
    project = make_project(tmp_path)
    calls = []
    config, source, existing, fp = _inputs(project)
    _bootstrap(project, config, source, existing, fp, fake_request(calls))
    config['bootstrap_source_chapters'] = 2
    (project / 'project.json').write_text(json.dumps(config))
    config, source, existing, next_fp = _inputs(project)
    assert next_fp != fp
    result = _bootstrap(project, config, source, existing, next_fp, fake_request(calls))
    assert json.loads((result.parent / 'ready.json').read_text())['source_samples'] == [1, 2]
    assert '独特标记3' not in calls[2][2]['prompt']


def test_tampered_curated_glossary_is_rebuilt_from_matching_cached_results(tmp_path: Path):
    project = make_project(tmp_path)
    config, source, existing, fp = _inputs(project)
    calls = []
    path = _bootstrap(project, config, source, existing, fp, fake_request(calls))
    path.write_text(HEADER + '独特标记1,Подмена,person,,0.99\n')
    rebuilt = _bootstrap(project, config, source, existing, fp, lambda _: pytest.fail('unexpected request'))
    assert 'Исправленное имя' in rebuilt.read_text()
    assert 'Подмена' not in rebuilt.read_text()
    assert len(calls) == 2
