import json
from pathlib import Path

from litrelay.batch_pipeline import BatchConfig, run_batch


def test_chained_glossary_uses_qa_revised_translation(tmp_path: Path) -> None:
    source = tmp_path / "source"
    context = tmp_path / "context"
    published = tmp_path / "published"
    for folder in [source, context, published]:
        folder.mkdir()
    (source / "0001.txt").write_text("第1章 词")
    glossary = tmp_path / "glossary.csv"
    glossary.write_text("source,target_ru,type,note,confidence\n")
    extracts = []

    def request(payload):
        agent = payload["metadata"]["agent"]
        data = json.loads(payload["input"][1]["content"])
        if agent == "translation-agent":
            text = "Исправленный термин" if "previous_translation" in data else "Старый термин"
            out = {
                "chapter_id": "0001",
                "translation": text,
                "qa": {"terminology_checked": True, "omission_risk": "low", "style_match": "good", "issues": []},
            }
        elif agent == "translation-qa":
            candidates = data["provisional_glossary_candidates"]
            expected = "Исправленный термин" if "Исправленный" in data["generated_translation"] else "Старый термин"
            assert candidates[0]["target_ru"] == expected
            score = 99 if "Исправленный" in data["generated_translation"] else 50
            out = {
                "chapter_id": "0001",
                **{key: score for key in ["meaning_score", "terminology_score", "style_score", "omission_score"]},
                "issues": ["Fix term"],
                "missing_or_changed_facts": [],
                "recommended_action": "Fix term",
            }
        else:
            prompt = data["prompt"]
            extracts.append(prompt)
            term = "Исправленный термин" if "Исправленный" in prompt else "Старый термин"
            return {"output_text": f"source,target_ru,type,note,confidence\n词,{term},concept,confirmed,0.99\n"}
        return {"output_text": json.dumps(out)}

    report = run_batch(
        BatchConfig(
            slug="test",
            start=1,
            end=1,
            source_dir=source,
            context_dir=context,
            published_ru_dir=published,
            glossary_csv=glossary,
            batch_dir=tmp_path / "batch",
            chain=True,
            revise_attempts=1,
            requester=request,
        )
    )
    assert report.published == 1
    assert len(extracts) == 2
    result = report.next_glossary_csv.read_text()
    assert "Исправленный термин" in result
    assert "Старый термин" not in result
