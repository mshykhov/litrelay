import json
from pathlib import Path

from litrelay.glossary_feedback import write_glossary_candidates


def _glossary_result(custom_id: str, csv_body: str) -> str:
    return json.dumps(
        {"custom_id": custom_id, "agent": "glossary-extractor", "status": "completed", "output": csv_body},
        ensure_ascii=False,
    )


def test_write_glossary_candidates_parses_csv_outputs(tmp_path: Path) -> None:
    results = tmp_path / "post.results.jsonl"
    out_csv = tmp_path / "candidates.csv"
    body_0652 = "source,target_ru,type,note,confidence\n叹息壁垒,Стена Вздоха,spell,canon,0.95\n"
    body_0653 = "source,target_ru,type,note,confidence\n叹息壁垒,Стена Вздоха,spell,canon,0.95\n融火爆炎,Пылающее Пламя,spell,new,0.80\n"
    results.write_text(
        _glossary_result("post-glossary-0652", body_0652)
        + "\n"
        + _glossary_result("post-glossary-0653", body_0653)
        + "\n",
        encoding="utf-8",
    )

    summary = write_glossary_candidates(results, out_csv)

    text = out_csv.read_text(encoding="utf-8")
    assert summary.candidates_written == 2  # deduped by (source, target_ru)
    assert summary.rows_skipped == 0
    assert "叹息壁垒,Стена Вздоха,spell,canon,0.95,0652" in text
    assert "融火爆炎,Пылающее Пламя,spell,new,0.80,0653" in text
    assert text.splitlines()[0] == "source,target_ru,type,note,confidence,chapter_id"
