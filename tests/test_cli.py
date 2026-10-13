import json
from pathlib import Path

from litrelay.cli import run


def test_cli_writes_glossary_prompts_for_paired_chapters(tmp_path: Path) -> None:
    source_dir = tmp_path / "source"
    ru_dir = tmp_path / "ru"
    out_dir = tmp_path / "prompts"
    source_dir.mkdir()
    ru_dir.mkdir()
    (source_dir / "0001.txt").write_text("耐瑟瑞尔", encoding="utf-8")
    (ru_dir / "0001.txt").write_text("Нетерил", encoding="utf-8")

    exit_code = run(
        [
            "make-glossary-prompts",
            "--source-dir",
            str(source_dir),
            "--ru-dir",
            str(ru_dir),
            "--out-dir",
            str(out_dir),
        ]
    )

    assert exit_code == 0
    prompt_path = out_dir / "0001.md"
    assert prompt_path.exists()
    prompt = prompt_path.read_text(encoding="utf-8")
    assert "耐瑟瑞尔" in prompt
    assert "Нетерил" in prompt


def test_qa_gate_command_reports_pass(tmp_path: Path, capsys) -> None:
    results = tmp_path / "qa.results.jsonl"
    output = {
        "chapter_id": "0652",
        "meaning_score": 93,
        "terminology_score": 91,
        "style_score": 86,
        "omission_score": 94,
    }
    results.write_text(
        json.dumps(
            {"custom_id": "qa-0652", "status": "completed", "output": json.dumps(output, ensure_ascii=False)},
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    code = run(["qa-gate", "--results-jsonl", str(results)])
    assert code == 0
    assert "ok=true" in capsys.readouterr().out


def test_flag_glossary_terms_command_writes_tasks(tmp_path: Path) -> None:
    glossary = tmp_path / "glossary.csv"
    ru_dir = tmp_path / "ru"
    out_jsonl = tmp_path / "reconcile.tasks.jsonl"
    ru_dir.mkdir()
    glossary.write_text(
        "source,target_ru,type,note,confidence,first_seen,last_seen,source_count,alternatives\n"
        "叹息壁垒,Барьер Вздохов,spell,не подтверждён,0.72,0648,0648,1,\n",
        encoding="utf-8",
    )
    (ru_dir / "0650.txt").write_text("Стены Вздоха.", encoding="utf-8")
    code = run(
        [
            "flag-glossary-terms",
            "--glossary-csv",
            str(glossary),
            "--published-ru-dir",
            str(ru_dir),
            "--out-jsonl",
            str(out_jsonl),
        ]
    )
    assert code == 0
    assert out_jsonl.exists()
    task = json.loads(out_jsonl.read_text(encoding="utf-8").splitlines()[0])
    assert task["custom_id"] == "reconcile-batch"
