import json
from pathlib import Path

from litrelay.batch_pipeline import BatchConfig, run_batch


def _fake_requester(payload: dict) -> dict:
    agent = payload["metadata"]["agent"]
    custom_id = payload["metadata"]["custom_id"]
    chapter_id = custom_id.split("-")[-1]
    if agent == "translation-agent":
        output = json.dumps(
            {
                "chapter_id": chapter_id,
                "translation": f"Глава {chapter_id}. Панк сотворил «Стена Вздоха».",
                "qa": {"terminology_checked": True, "omission_risk": "low", "style_match": "good", "issues": []},
            },
            ensure_ascii=False,
        )
    elif agent == "translation-qa":
        output = json.dumps(
            {
                "chapter_id": chapter_id,
                "meaning_score": 93,
                "terminology_score": 91,
                "style_score": 86,
                "omission_score": 94,
                "verdict": "needs_revision",
                "strengths": [],
                "issues": [],
                "missing_or_changed_facts": [],
                "recommended_action": "",
            },
            ensure_ascii=False,
        )
    else:
        output = "source,target_ru,type,note,confidence\n叹息壁垒,Стена Вздоха,spell,from published,0.97\n"
    return {"id": "resp_x", "model": "fake", "output": [{"content": [{"type": "output_text", "text": output}]}]}


def test_run_batch_produces_published_chapters_and_next_glossary(tmp_path: Path) -> None:
    source_dir = tmp_path / "source"
    context_dir = tmp_path / "ru"
    ru_dir = tmp_path / "published-ru"
    batch_dir = tmp_path / "batch"
    glossary = tmp_path / "glossary.csv"
    for d in (source_dir, context_dir, ru_dir):
        d.mkdir()
    (source_dir / "0652.txt").write_text("第652章 叹息壁垒", encoding="utf-8")
    (context_dir / "0651.txt").write_text("Глава 651", encoding="utf-8")
    (ru_dir / "0650.txt").write_text("Барьер «Стены Вздоха» держался.", encoding="utf-8")
    glossary.write_text(
        "source,target_ru,type,note,confidence,first_seen,last_seen,source_count,alternatives\n"
        "叹息壁垒,Барьер Вздохов,spell,прямой перевод не подтверждён,0.72,0648,0648,1,\n",
        encoding="utf-8",
    )

    config = BatchConfig(
        slug="demo",
        start=652,
        end=652,
        source_dir=source_dir,
        context_dir=context_dir,
        published_ru_dir=ru_dir,
        glossary_csv=glossary,
        batch_dir=batch_dir,
        glossary_conf_threshold=0.90,
        requester=_fake_requester,
    )

    report = run_batch(config)

    assert report.translated == 1
    assert report.qa_passed == 1
    assert report.published == 1
    assert (batch_dir / "published" / "0652.txt").exists()
    assert (batch_dir / "glossary-next.curated.csv").exists()
    assert (batch_dir / "needs-revision.txt").exists()
    proposals = (batch_dir / "glossary-reconcile-proposals.csv").read_text(encoding="utf-8")
    assert "Стена Вздоха" in proposals


def _revise_requester(payload: dict) -> dict:
    agent = payload["metadata"]["agent"]
    chapter = payload["metadata"]["custom_id"].split("-")[-1]
    user = json.loads(payload["input"][1]["content"])
    if agent == "translation-agent":
        revised = "previous_translation" in user
        translation = f"REVISED {chapter}" if revised else f"orig {chapter}"
        out = json.dumps(
            {
                "chapter_id": chapter,
                "translation": translation,
                "qa": {"terminology_checked": True, "omission_risk": "low", "style_match": "good", "issues": []},
            },
            ensure_ascii=False,
        )
    elif agent == "translation-qa":
        good = str(user.get("generated_translation", "")).startswith("REVISED")
        score = 95 if good else 70
        out = json.dumps(
            {
                "chapter_id": chapter,
                "meaning_score": score,
                "terminology_score": score,
                "style_score": score,
                "omission_score": score,
                "verdict": "pass" if good else "needs_revision",
                "strengths": [],
                "issues": ["term drift"],
                "missing_or_changed_facts": [],
                "recommended_action": "fix",
            },
            ensure_ascii=False,
        )
    else:
        out = "source,target_ru,type,note,confidence\n"
    return {"id": "x", "model": "fake", "output": [{"content": [{"type": "output_text", "text": out}]}]}


def test_run_batch_revises_failed_chapter(tmp_path: Path) -> None:
    source = tmp_path / "source"
    ctx = tmp_path / "ru"
    pub = tmp_path / "pub"
    bd = tmp_path / "batch"
    gl = tmp_path / "g.csv"
    for d in (source, ctx, pub):
        d.mkdir()
    (source / "0652.txt").write_text("第652章 测试", encoding="utf-8")
    gl.write_text(
        "source,target_ru,type,note,confidence,first_seen,last_seen,source_count,alternatives\n", encoding="utf-8"
    )

    config = BatchConfig(
        slug="t",
        start=652,
        end=652,
        source_dir=source,
        context_dir=ctx,
        published_ru_dir=pub,
        glossary_csv=gl,
        batch_dir=bd,
        revise_attempts=1,
        requester=_revise_requester,
    )
    report = run_batch(config)

    assert report.qa_passed == 1
    assert report.qa_failed == 0
    assert "REVISED 0652" in (bd / "published" / "0652.txt").read_text(encoding="utf-8")
    assert (bd / "needs-revision.txt").read_text(encoding="utf-8").strip() == ""


def _chain_requester(seen_context: dict):
    def req(payload: dict) -> dict:
        agent = payload["metadata"]["agent"]
        chapter = payload["metadata"]["custom_id"].split("-")[-1]
        user = json.loads(payload["input"][1]["content"])
        if agent == "translation-agent":
            seen_context[chapter] = user.get("recent_russian_context", [])
            out = json.dumps(
                {
                    "chapter_id": chapter,
                    "translation": f"RU-{chapter}",
                    "qa": {"terminology_checked": True, "omission_risk": "low", "style_match": "good", "issues": []},
                },
                ensure_ascii=False,
            )
        elif agent == "translation-qa":
            out = json.dumps(
                {
                    "chapter_id": chapter,
                    "meaning_score": 95,
                    "terminology_score": 95,
                    "style_score": 95,
                    "omission_score": 95,
                    "verdict": "pass",
                    "strengths": [],
                    "issues": [],
                    "missing_or_changed_facts": [],
                    "recommended_action": "",
                },
                ensure_ascii=False,
            )
        else:
            out = "source,target_ru,type,note,confidence\n"
        return {"id": "x", "model": "fake", "output": [{"content": [{"type": "output_text", "text": out}]}]}

    return req


def test_run_batch_chain_feeds_prior_translation_as_context(tmp_path: Path) -> None:
    source = tmp_path / "source"
    ctx = tmp_path / "ru"
    pub = tmp_path / "pub"
    bd = tmp_path / "batch"
    gl = tmp_path / "g.csv"
    for d in (source, ctx, pub):
        d.mkdir()
    (source / "0001.txt").write_text("第1章 测试", encoding="utf-8")
    (source / "0002.txt").write_text("第2章 测试", encoding="utf-8")
    gl.write_text(
        "source,target_ru,type,note,confidence,first_seen,last_seen,source_count,alternatives\n", encoding="utf-8"
    )
    seen: dict = {}

    config = BatchConfig(
        slug="t",
        start=1,
        end=2,
        source_dir=source,
        context_dir=ctx,
        published_ru_dir=pub,
        glossary_csv=gl,
        batch_dir=bd,
        chain=True,
        context_window=5,
        requester=_chain_requester(seen),
    )
    run_batch(config)

    assert seen["0001"] == []
    assert any("RU-0001" in c.get("text", "") for c in seen["0002"])


def _incremental_requester(seen_glossary: dict):
    def req(payload: dict) -> dict:
        agent = payload["metadata"]["agent"]
        chapter = payload["metadata"]["custom_id"].split("-")[-1]
        user = json.loads(payload["input"][1]["content"])
        if agent == "translation-agent":
            seen_glossary[chapter] = user.get("glossary_csv", "")
            out = json.dumps(
                {
                    "chapter_id": chapter,
                    "translation": f"RU-{chapter} Битва Языка Огней",
                    "qa": {"terminology_checked": True, "omission_risk": "low", "style_match": "good", "issues": []},
                },
                ensure_ascii=False,
            )
        elif agent == "translation-qa":
            out = json.dumps(
                {
                    "chapter_id": chapter,
                    "meaning_score": 95,
                    "terminology_score": 95,
                    "style_score": 95,
                    "omission_score": 95,
                    "verdict": "pass",
                    "strengths": [],
                    "issues": [],
                    "missing_or_changed_facts": [],
                    "recommended_action": "",
                },
                ensure_ascii=False,
            )
        elif agent == "glossary-extractor":
            if chapter == "0001":
                out = "source,target_ru,type,note,confidence\n灯语之战,Битва Языка Огней,event,arc title,0.95\n"
            else:
                out = "source,target_ru,type,note,confidence\n"
        else:
            out = "source,target_ru,type,note,confidence\n"
        return {"id": "x", "model": "fake", "output": [{"content": [{"type": "output_text", "text": out}]}]}

    return req


def test_chain_incremental_glossary_injects_coined_term_into_next_chapter(tmp_path: Path) -> None:
    source = tmp_path / "source"
    ctx = tmp_path / "ru"
    pub = tmp_path / "pub"
    bd = tmp_path / "batch"
    gl = tmp_path / "g.csv"
    for d in (source, ctx, pub):
        d.mkdir()
    (source / "0001.txt").write_text("第1章 灯语之战（1）", encoding="utf-8")
    (source / "0002.txt").write_text("第2章 灯语之战（2）", encoding="utf-8")
    gl.write_text(
        "source,target_ru,type,note,confidence,first_seen,last_seen,source_count,alternatives\n", encoding="utf-8"
    )
    seen: dict = {}

    config = BatchConfig(
        slug="t",
        start=1,
        end=2,
        source_dir=source,
        context_dir=ctx,
        published_ru_dir=pub,
        glossary_csv=gl,
        batch_dir=bd,
        chain=True,
        incremental_glossary=True,
        requester=_incremental_requester(seen),
    )
    run_batch(config)

    assert "Битва Языка Огней" not in seen["0001"]
    assert "Битва Языка Огней" in seen["0002"]
    assert (bd / "glossary-next.curated.csv").exists()


def test_chain_incremental_glossary_disabled_does_not_inject(tmp_path: Path) -> None:
    source = tmp_path / "source"
    ctx = tmp_path / "ru"
    pub = tmp_path / "pub"
    bd = tmp_path / "batch"
    gl = tmp_path / "g.csv"
    for d in (source, ctx, pub):
        d.mkdir()
    (source / "0001.txt").write_text("第1章 灯语之战（1）", encoding="utf-8")
    (source / "0002.txt").write_text("第2章 灯语之战（2）", encoding="utf-8")
    gl.write_text(
        "source,target_ru,type,note,confidence,first_seen,last_seen,source_count,alternatives\n", encoding="utf-8"
    )
    seen: dict = {}

    config = BatchConfig(
        slug="t",
        start=1,
        end=2,
        source_dir=source,
        context_dir=ctx,
        published_ru_dir=pub,
        glossary_csv=gl,
        batch_dir=bd,
        chain=True,
        incremental_glossary=False,
        requester=_incremental_requester(seen),
    )
    run_batch(config)

    assert "Битва Языка Огней" not in seen["0002"]


def test_batch_never_publishes_failed_qa(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "0001.txt").write_text("第1章 测试")
    gl = tmp_path / "g.csv"
    gl.write_text("source,target_ru,type,note,confidence\n")
    config = BatchConfig(
        slug="t",
        start=1,
        end=1,
        source_dir=source,
        context_dir=source,
        published_ru_dir=source,
        glossary_csv=gl,
        batch_dir=tmp_path / "batch",
        requester=_revise_requester,
        revise_attempts=0,
    )
    report = run_batch(config)
    assert report.qa_failed == 1
    assert report.published == 0
    assert not (config.batch_dir / "published/0001.txt").exists()


def test_chain_starts_with_existing_human_context(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    context = tmp_path / "context"
    context.mkdir()
    (source / "0002.txt").write_text("第2章 测试")
    (context / "0001.txt").write_text("Глава 1\n\nЧеловеческий перевод.")
    gl = tmp_path / "g.csv"
    gl.write_text("source,target_ru,type,note,confidence\n")
    seen = {}
    run_batch(
        BatchConfig(
            slug="t",
            start=2,
            end=2,
            source_dir=source,
            context_dir=context,
            published_ru_dir=context,
            glossary_csv=gl,
            batch_dir=tmp_path / "batch",
            chain=True,
            requester=_chain_requester(seen),
        )
    )
    assert any("Человеческий перевод" in x["text"] for x in seen["0002"])
