import json
from pathlib import Path

from test_project_workflow import _revision_project, fake_model

from litrelay.batch_pipeline import BatchConfig, _prepare_glossary_review, run_batch
from litrelay.project_revision import revise_project_chapter


def test_candidates_for_each_chapter_are_not_deduplicated(tmp_path: Path):
    source = tmp_path / "source"
    source.mkdir()
    for chapter in ("0001", "0002"):
        (source / f"{chapter}.txt").write_text("词")
    glossary = tmp_path / "glossary.csv"
    glossary.write_text("source,target_ru,type,note,confidence\n")
    batch = tmp_path / "batch"
    batch.mkdir()
    translations = batch / "translation.results.jsonl"
    translations.write_text(
        "".join(
            json.dumps({"status": "completed", "output": json.dumps({"chapter_id": cid, "translation": "Термин"})})
            + "\n"
            for cid in ("0001", "0002")
        )
    )
    qa = batch / "qa.tasks.jsonl"
    qa.write_text("".join(json.dumps({"input": {"chapter_id": cid}}) + "\n" for cid in ("0001", "0002")))
    results = batch / "post-glossary.results.jsonl"
    results.write_text(
        "".join(
            json.dumps(
                {
                    "custom_id": f"post-glossary-{cid}",
                    "status": "completed",
                    "output": "source,target_ru,type,note,confidence\n词,Термин,concept,,0.99\n",
                }
            )
            + "\n"
            for cid in ("0001", "0002")
        )
    )
    cfg = BatchConfig(
        slug="test",
        start=1,
        end=2,
        source_dir=source,
        context_dir=source,
        published_ru_dir=source,
        glossary_csv=glossary,
        batch_dir=batch,
    )
    _prepare_glossary_review(cfg, translations, qa, precomputed=results)
    tasks = [json.loads(line) for line in qa.read_text().splitlines()]
    assert [task["input"]["provisional_glossary_candidates"][0]["chapter_id"] for task in tasks] == ["0001", "0002"]


def test_final_extraction_uses_canonical_glossary_after_revision(tmp_path: Path):
    source, context, published = (tmp_path / name for name in ("source", "context", "published"))
    for path in (source, context, published):
        path.mkdir()
    for cid in ("0001", "0002"):
        (source / f"{cid}.txt").write_text(f"第{int(cid)}章 词")
    glossary = tmp_path / "glossary.csv"
    glossary.write_text("source,target_ru,type,note,confidence\n")
    qa_seen = []
    extract_glossaries = []

    def request(payload):
        agent = payload["metadata"]["agent"]
        data = json.loads(payload["input"][1]["content"])
        cid = data["chapter_id"]
        if agent == "translation-agent":
            revised = "previous_translation" in data
            text = "Старый термин" if cid == "0001" and not revised else "Новый термин"
            output = {
                "chapter_id": cid,
                "translation": text,
                "qa": {"terminology_checked": True, "omission_risk": "low", "style_match": "good", "issues": []},
            }
        elif agent == "translation-qa":
            qa_seen.append((cid, data["provisional_glossary_candidates"]))
            score = 50 if data["generated_translation"] == "Старый термин" else 99
            output = {
                "chapter_id": cid,
                **{key: score for key in ["meaning_score", "terminology_score", "style_score", "omission_score"]},
                "issues": [],
                "missing_or_changed_facts": [],
                "recommended_action": "",
            }
        else:
            prompt = data["prompt"]
            current = prompt.split("<CURRENT_GLOSSARY>")[1].split("</CURRENT_GLOSSARY>")[0]
            extract_glossaries.append((cid, current))
            term = (
                "Старый термин"
                if "Старый термин" in prompt.split("<GENERATED_RUSSIAN_TRANSLATION>")[1]
                else "Новый термин"
            )
            return {"output_text": f"source,target_ru,type,note,confidence\n词,{term},concept,,0.99\n"}
        return {"output_text": json.dumps(output, ensure_ascii=False)}

    report = run_batch(
        BatchConfig(
            slug="test",
            start=1,
            end=2,
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
    assert report.published == 2
    assert "Новый термин" in report.next_glossary_csv.read_text()
    assert "Старый термин" not in report.next_glossary_csv.read_text()
    # The final extraction of chapter 2 must not see chapter 1's provisional term as canonical.
    assert "Старый термин" not in [current for cid, current in extract_glossaries if cid == "0002"][-1]
    assert {cid for cid, _ in qa_seen} == {"0001", "0002"}


def test_user_revision_supplies_provisional_candidates_to_first_qa(tmp_path: Path):
    project = _revision_project(tmp_path)
    calls = []
    revise_project_chapter(project, chapter=2, from_scratch=True, requester=fake_model(calls))
    qa = next(user for agent, user in calls if agent == "translation-qa")
    assert qa["provisional_glossary_candidates"][0]["source"] == "海"
