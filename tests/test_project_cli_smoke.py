import json
import os
import subprocess
import sys
from pathlib import Path


def test_public_cli_import_run_resume_and_archive_with_fake_provider(tmp_path: Path) -> None:
    root = Path(__file__).parents[1]
    tools = tmp_path / "bin"
    tools.mkdir()
    worker = tools / "codex"
    worker.write_text(
        f"#!{sys.executable}\n"
        + """import sys,json
payload=next(json.loads(line) for line in sys.stdin.read().splitlines() if line.startswith('{'))
cid=payload.get('chapter_id','0001')
if 'generated_translation' in payload:
 data={'chapter_id':cid,'meaning_score':97,'omission_score':99,'terminology_score':97,'style_score':94,'verdict':'pass','strengths':[],'issues':[],'missing_or_changed_facts':[],'recommended_action':''}
 text=json.dumps(data)
elif 'source_title' in payload:
 text=json.dumps({'chapter_id':cid,'verdict':'aligned','confidence':0.99,'evidence':['matched'],'issues':[],'recommended_action':''})
elif 'prompt' in payload:
 text='source,target_ru,type,note,confidence\\nMara,Мара,character,established,0.99\\n'
else:
 text=json.dumps({'chapter_id':cid,'translation':'Глава '+str(int(cid))+'. Возвращение\\n\\n'+('На рассвете Мара вернулась к причалу. Все три лодки были на месте. Она обещала вернуться через семь дней. '*3),'qa':{'terminology_checked':True,'omission_risk':'low','style_match':'good','issues':[]}},ensure_ascii=False)
print(json.dumps({'type':'item.completed','item':{'type':'agent_message','text':text}},ensure_ascii=False))
"""
    )
    worker.chmod(0o755)
    env = {**os.environ, "PATH": str(tools) + os.pathsep + os.environ["PATH"], "PYTHONPATH": str(root / "src")}

    def cli(*args):
        p = subprocess.run(
            [sys.executable, "-c", "from litrelay.cli import main;main()", *args],
            cwd=tmp_path,
            env=env,
            text=True,
            capture_output=True,
            timeout=60,
        )
        assert p.returncode == 0, p.stdout + p.stderr
        return p.stdout

    cli(
        "init",
        "demo",
        "--source",
        str(root / "examples/demo/source"),
        "--translation",
        str(root / "examples/demo/translation"),
        "--source-lang",
        "en",
        "--target-lang",
        "ru",
    )
    assert '"complete": true' in cli("run", "demo")
    project = tmp_path / "projects/demo"
    before = (project / "work/progress.json").read_bytes()
    assert (project / "output/book.zip").exists()
    assert '"missing_preview": []' in cli("status", "demo")
    assert '"complete": true' in cli("run", "demo")
    assert (project / "work/progress.json").read_bytes() == before
    report = json.loads((project / "output/report.json").read_text())
    assert report["total"] == 2 and report["generated"] == 1
