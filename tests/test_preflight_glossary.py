import json
from dataclasses import replace
from pathlib import Path

import pytest

from litrelay.batch_pipeline import BatchConfig, StageProfile, run_batch
from litrelay.preflight_glossary import prepare_preflight_glossary

HEADER = "source,target_ru,type,note,confidence\n"


def config_for(tmp_path: Path) -> BatchConfig:
    source, context, published = (tmp_path / name for name in ("source", "context", "published"))
    for path in (source, context, published):
        path.mkdir()
    (source / "0001.txt").write_text("第1章 旧名 新名")
    glossary = tmp_path / "glossary.csv"
    glossary.write_text(HEADER + "旧名,Старое имя,person,,0.99\n")
    return BatchConfig(
        slug="test",
        start=1,
        end=1,
        source_dir=source,
        context_dir=context,
        published_ru_dir=published,
        glossary_csv=glossary,
        batch_dir=tmp_path / "batch",
        preflight_glossary=True,
        support_profile=StageProfile(model="support", backend="fake"),
    )


def model(calls, *, proposed=None, review=None, fail=None):
    def request(payload):
        agent = payload["metadata"]["agent"]
        data = json.loads(payload["input"][1]["content"])
        prompt = data.get("prompt", "")
        calls.append((agent, data, payload))
        if prompt.startswith("Before translation, extract only"):
            if fail == "draft":
                raise RuntimeError("provider error")
            text = (
                proposed if proposed is not None else HEADER + "新名,Черновик,person,,0.99\n旧名,Подмена,person,,0.99\n"
            )
        elif prompt.startswith("Review the proposed NEW"):
            if fail == "review":
                raise RuntimeError("provider error")
            text = review if review is not None else HEADER + "新名,Новое имя,person,,0.99\n旧名,Подмена,person,,0.99\n"
        elif agent == "translation-agent":
            text = json.dumps(
                {
                    "chapter_id": "0001",
                    "translation": "Старое имя и Новое имя",
                    "qa": {"terminology_checked": True, "omission_risk": "low", "style_match": "good", "issues": []},
                }
            )
        elif agent == "translation-qa":
            text = json.dumps(
                {
                    "chapter_id": "0001",
                    **{key: 99 for key in ("meaning_score", "terminology_score", "style_score", "omission_score")},
                    "issues": [],
                    "missing_or_changed_facts": [],
                    "glossary_issues": [],
                    "recommended_action": "",
                }
            )
        else:
            text = HEADER
        return {"output_text": text}

    return request


def test_preflight_review_before_translation_and_acceptance(tmp_path: Path):
    cfg = config_for(tmp_path)
    cfg = replace(cfg, support_profile=replace(cfg.support_profile, reasoning_effort="high"))
    before = cfg.glossary_csv.read_bytes()
    calls = []
    report = run_batch(replace(cfg, requester=model(calls)))
    assert [entry[0] for entry in calls[:3]] == ["glossary-extractor", "glossary-extractor", "translation-agent"]
    assert calls[0][2]["reasoning"]["effort"] == calls[1][2]["reasoning"]["effort"] == "high"
    assert "Черновик" in calls[1][1]["prompt"] and "Подмена" not in calls[1][1]["prompt"]
    assert "Новое имя" in calls[2][1]["glossary_csv"] and "Старое имя" in calls[2][1]["glossary_csv"]
    assert "Подмена" not in calls[2][1]["glossary_csv"]
    assert cfg.glossary_csv.read_bytes() == before
    assert report.published == 1 and "Новое имя" in report.next_glossary_csv.read_text()
    assert "Старое имя" in report.next_glossary_csv.read_text()


@pytest.mark.parametrize("proposed", [HEADER, HEADER + "旧名,Новое неверное имя,person,,0.99\n"])
def test_no_new_candidates_skips_review(tmp_path: Path, proposed: str):
    cfg = config_for(tmp_path)
    calls = []
    cfg.batch_dir.mkdir()
    staged = prepare_preflight_glossary(replace(cfg, requester=model(calls, proposed=proposed)))
    assert len(calls) == 1
    assert staged.read_bytes() == cfg.glossary_csv.read_bytes()


@pytest.mark.parametrize("failure", ["draft", "review"])
def test_preflight_failure_blocks_translation_preserves_base(tmp_path: Path, failure: str):
    cfg = config_for(tmp_path)
    original = cfg.glossary_csv.read_bytes()
    calls = []
    with pytest.raises(RuntimeError, match="Glossary preflight"):
        run_batch(replace(cfg, requester=model(calls, fail=failure)))
    assert all(agent != "translation-agent" for agent, _, _ in calls)
    assert cfg.glossary_csv.read_bytes() == original


def test_resume_reuses_matching_requests_and_invalidates_changed_base(tmp_path: Path):
    cfg = config_for(tmp_path)
    cfg.batch_dir.mkdir()
    calls = []
    cfg = replace(cfg, requester=model(calls))
    path = prepare_preflight_glossary(cfg)
    assert len(calls) == 2 and "Новое имя" in path.read_text()
    path.write_text("tampered")
    prepare_preflight_glossary(cfg)
    assert len(calls) == 2 and "Новое имя" in path.read_text()
    cfg.glossary_csv.write_text(HEADER + "旧名,Иной выбор,person,,0.99\n")
    prepare_preflight_glossary(cfg)
    assert len(calls) == 4 and "Иной выбор" in path.read_text()
    assert "Старое имя" not in path.read_text()
