import json
from pathlib import Path

import pytest

from litrelay.agent_executor import build_responses_payload
from litrelay.batch_pipeline import BatchConfig, run_batch
from litrelay.prompt_profiles import PromptSettings


def test_qa_schema_requires_glossary_issues():
    task = {
        "custom_id": "qa-0001",
        "agent": "translation-qa",
        "system": "Review",
        "input": {},
        "expected_output": {"format": "translation_qa_json"},
    }
    schema = build_responses_payload(task, model="fake")["text"]["format"]["schema"]
    assert "glossary_issues" in schema["required"]
    assert schema["properties"]["glossary_issues"] == {"type": "array", "items": {"type": "string"}}


@pytest.mark.parametrize("repair", [True, False])
def test_qa_glossary_findings_persist_for_final_chapter(tmp_path: Path, repair: bool):
    source, context, published = (tmp_path / name for name in ("source", "context", "published"))
    for path in (source, context, published):
        path.mkdir()
    (source / "0001.txt").write_text("第1章 海")
    glossary = tmp_path / "glossary.csv"
    glossary.write_text("source,target_ru,type,note,confidence\n海,море,place,possibly wrong note,0.99\n")
    requests = []

    def request(payload):
        agent = payload["metadata"]["agent"]
        user = json.loads(payload["input"][1]["content"])
        requests.append((agent, user, payload["input"][0]["content"]))
        if agent == "translation-agent":
            text = json.dumps(
                {
                    "chapter_id": "0001",
                    "translation": "Исправленное море" if "previous_translation" in user else "Море",
                    "qa": {"terminology_checked": True, "omission_risk": "low", "style_match": "good", "issues": []},
                }
            )
        elif agent == "translation-qa":
            revised = user["generated_translation"] == "Исправленное море"
            score = 99 if revised else 50
            text = json.dumps(
                {
                    "chapter_id": "0001",
                    **{name: score for name in ["meaning_score", "terminology_score", "style_score", "omission_score"]},
                    "issues": ["Исправить сцену"],
                    "missing_or_changed_facts": [],
                    "glossary_issues": ["Финальное замечание" if revised else "Первое замечание"],
                    "recommended_action": "Исправить сцену",
                },
                ensure_ascii=False,
            )
        else:
            text = "source,target_ru,type,note,confidence\n"
        return {"output_text": text}

    batch = tmp_path / "batch"
    report = run_batch(
        BatchConfig(
            slug="test",
            start=1,
            end=1,
            source_dir=source,
            context_dir=context,
            published_ru_dir=published,
            glossary_csv=glossary,
            batch_dir=batch,
            requester=request,
            revise_attempts=int(repair),
            prompt_settings=PromptSettings("zh", "ru"),
        )
    )
    assert report.qa_failed == (0 if repair else 1)
    expected = "Финальное замечание" if repair else "Первое замечание"
    assert json.loads((batch / "glossary-qa-review-needed.json").read_text()) == [
        {"chapter_id": "0001", "glossary_issues": [expected]}
    ]
    qa_prompt = next(system for agent, _, system in requests if agent == "translation-qa")
    assert "Score only the translated chapter" in qa_prompt
    assert "canonical glossary notes" in qa_prompt
    assert "do not lower chapter scores" in qa_prompt
    if repair:
        revision = next(
            user for agent, user, _ in requests if agent == "translation-agent" and "previous_translation" in user
        )
        assert revision["qa_issues"] == ["Исправить сцену"]
        assert "Первое замечание" not in json.dumps(revision, ensure_ascii=False)
