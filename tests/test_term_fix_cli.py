import json

from test_term_fix_apply import PATTERN, prepared

from litrelay import project_cli
from litrelay.cli import run


def test_cli_preview_leaves_book_unchanged_and_saved_apply_makes_no_model_call(tmp_path, monkeypatch, capsys):
    project, path = prepared(tmp_path)
    plan = json.loads(path.read_text())
    before = {p: p.read_bytes() for p in [*project.glob('work/accepted/*.txt'), project / 'project.json',
                                            project / 'work/glossary/active.csv', project / 'work/progress.json']}
    calls = []

    def fake_plan(*args, **kwargs):
        calls.append((args, kwargs))
        return plan

    monkeypatch.setattr(project_cli, 'propose_term_fix', fake_plan)
    assert run(['fix-term', 'book', '--workspace', str(tmp_path), '--source-term', '修士', '--target', 'культиватор',
                '--pattern', PATTERN, '--model', 'fake', '--reasoning-effort', 'medium']) == 0
    output = json.loads(capsys.readouterr().out)
    assert output['matches'] == 6 and output['uncertain'] == 0 and output['plan_path'] == str(path)
    assert calls[0][1]['model'] == 'fake' and calls[0][1]['reasoning_effort'] == 'medium'
    assert all(p.read_bytes() == value for p, value in before.items())
    assert not (project / 'input/term-overrides.csv').exists()
    monkeypatch.setattr(project_cli, 'propose_term_fix', lambda *a, **kw: (_ for _ in ()).throw(AssertionError('LLM')))
    assert run(['apply-term-fix', 'book', '--workspace', str(tmp_path), '--plan', str(path)]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result['replacements'] == 6 and result['complete']
    assert 'культиватор' in (project / 'output/book.txt').read_text()


def test_cli_apply_runs_actual_transaction(tmp_path, monkeypatch, capsys):
    project, path = prepared(tmp_path)
    plan = json.loads(path.read_text())
    monkeypatch.setattr(project_cli, 'propose_term_fix', lambda *a, **kw: plan)
    assert run(['fix-term', 'book', '--workspace', str(tmp_path), '--source-term', '修士', '--target', 'культиватор',
                '--pattern', PATTERN, '--apply']) == 0
    result = json.loads(capsys.readouterr().out)
    assert result['replacements'] == 6 and result['changed_chapters'] == [1, 2]
    assert (project / 'input/term-overrides.csv').exists()
    assert json.loads((path.parent / 'transaction.json').read_text())['status'] == 'applied'
