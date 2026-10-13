import csv
from pathlib import Path

from litrelay.glossary_versioning import (
    apply_glossary_overrides,
    merge_glossary_version,
    validate_glossary,
    write_batch_manifest,
)


def test_merge_glossary_version_creates_unique_canonical_rows(tmp_path: Path) -> None:
    candidates = tmp_path / "candidates.csv"
    out_csv = tmp_path / "glossary-reviewed-v1.csv"
    review_csv = tmp_path / "review-needed.csv"
    candidates.write_text(
        "\n".join(
            [
                "chapter_id,source,target_ru,type,note,confidence",
                "0001,朋克,Панк,character,main character,0.90",
                "0002,朋克,Панк,character,main character,0.95",
                "0003,朋克,Пунк,character,variant typo,0.40",
                "0003,咒法系,Школа Призыва,magic_school,magic school,0.80",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    summary = merge_glossary_version(candidates, out_csv, review_csv=review_csv, version="v1")

    rows = _read_csv(out_csv)
    assert summary.added == 2
    assert summary.preserved == 0
    assert summary.conflicts == 1
    assert [row["source"] for row in rows] == ["朋克", "咒法系"]
    assert rows[0]["target_ru"] == "Панк"
    assert rows[0]["first_seen"] == "0001"
    assert rows[0]["last_seen"] == "0003"
    assert rows[0]["source_count"] == "3"
    assert "Пунк:1" in rows[0]["alternatives"]
    assert "target_conflict" in review_csv.read_text(encoding="utf-8")


def test_merge_glossary_version_preserves_existing_target_on_conflict(tmp_path: Path) -> None:
    base_csv = tmp_path / "glossary-reviewed-v1.csv"
    candidates = tmp_path / "candidates.csv"
    out_csv = tmp_path / "glossary-reviewed-v2.csv"
    review_csv = tmp_path / "review-needed-v2.csv"
    base_csv.write_text(
        "\n".join(
            [
                "source,target_ru,type,note,confidence,first_seen,last_seen,source_count,alternatives",
                "咒法系,Школа Вызова,magic_school,accepted term,0.95,0001,0100,4,",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    candidates.write_text(
        "\n".join(
            [
                "chapter_id,source,target_ru,type,note,confidence",
                "0101,咒法系,Школа Призыва,magic_school,new candidate,0.99",
                "0101,动能静滞,Кинетический стазис,spell,spell name,0.88",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    summary = merge_glossary_version(
        candidates,
        out_csv,
        base_csv=base_csv,
        review_csv=review_csv,
        version="v2",
    )

    rows = {row["source"]: row for row in _read_csv(out_csv)}
    assert summary.preserved == 1
    assert summary.added == 1
    assert summary.conflicts == 1
    assert rows["咒法系"]["target_ru"] == "Школа Вызова"
    assert rows["动能静滞"]["target_ru"] == "Кинетический стазис"
    review_text = review_csv.read_text(encoding="utf-8")
    assert "咒法系" in review_text
    assert "Школа Вызова" in review_text
    assert "Школа Призыва" in review_text


def test_validate_glossary_reports_blank_and_duplicate_terms(tmp_path: Path) -> None:
    glossary_csv = tmp_path / "bad.csv"
    glossary_csv.write_text(
        "\n".join(
            [
                "source,target_ru,type,note,confidence",
                "朋克,Панк,character,,0.9",
                "朋克,Панк,character,,0.9",
                "咒法系,,magic_school,,0.8",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    report = validate_glossary(glossary_csv)

    assert not report.ok
    assert report.total_rows == 3
    assert {issue.code for issue in report.errors} == {"duplicate_source", "blank_target"}


def test_write_batch_manifest_records_exact_file_hashes(tmp_path: Path) -> None:
    glossary_csv = tmp_path / "glossary-reviewed-v1.csv"
    style_guide = tmp_path / "style-guide-v1.md"
    recap = tmp_path / "recap-up-to-0651.md"
    out_json = tmp_path / "manifest.json"
    glossary_csv.write_text("source,target_ru,type,note,confidence\n朋克,Панк,character,,0.9\n", encoding="utf-8")
    style_guide.write_text("Style", encoding="utf-8")
    recap.write_text("Recap", encoding="utf-8")

    manifest = write_batch_manifest(
        out_json,
        slug="netherils-glory",
        start=652,
        end=656,
        model="gpt-5.4-mini",
        glossary_csv=glossary_csv,
        glossary_version="v1",
        style_guide=style_guide,
        recap=recap,
    )

    assert manifest["slug"] == "netherils-glory"
    assert manifest["range"] == {"start": 652, "end": 656}
    assert manifest["glossary"]["version"] == "v1"
    assert len(manifest["glossary"]["sha256"]) == 64
    assert len(manifest["style_guide"]["sha256"]) == 64
    assert len(manifest["recap"]["sha256"]) == 64
    assert out_json.exists()


def test_apply_glossary_overrides_updates_targets_without_losing_metadata(tmp_path: Path) -> None:
    base_csv = tmp_path / "glossary-reviewed-v1.csv"
    overrides_csv = tmp_path / "overrides.csv"
    out_csv = tmp_path / "glossary-reviewed-v1.curated.csv"
    base_csv.write_text(
        "\n".join(
            [
                "source,target_ru,type,note,confidence,first_seen,last_seen,source_count,alternatives",
                "多元宇宙,мультивселенная,cosmology,old note,0.90,0001,0651,12,Мультивселенная:2",
                "朋克,Панк,character,stable,1.00,0001,0651,651,",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    overrides_csv.write_text(
        "\n".join(
            [
                "source,target_ru,type,note,confidence",
                "多元宇宙,Мультивселенная,cosmology,LLM chose proper noun capitalization,0.97",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    summary = apply_glossary_overrides(base_csv, overrides_csv, out_csv)

    rows = {row["source"]: row for row in _read_csv(out_csv)}
    assert summary.applied == 1
    assert summary.missing == 0
    assert rows["多元宇宙"]["target_ru"] == "Мультивселенная"
    assert rows["多元宇宙"]["first_seen"] == "0001"
    assert rows["多元宇宙"]["source_count"] == "12"
    assert rows["朋克"]["target_ru"] == "Панк"


def test_apply_glossary_overrides_adds_new_terms(tmp_path: Path) -> None:
    base_csv = tmp_path / "glossary-reviewed-v1.csv"
    overrides_csv = tmp_path / "overrides.csv"
    out_csv = tmp_path / "glossary-reviewed-v1.1.csv"
    base_csv.write_text(
        "\n".join(
            [
                "source,target_ru,type,note,confidence,first_seen,last_seen,source_count,alternatives",
                "朋克,Панк,character,stable,1.00,0001,0651,651,",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    overrides_csv.write_text(
        "\n".join(
            [
                "chapter_id,source,target_ru,type,note,confidence",
                "0655,融火爆炎,Плавящий огненный взрыв,spell,QA patch term,0.88",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    summary = apply_glossary_overrides(base_csv, overrides_csv, out_csv)

    rows = {row["source"]: row for row in _read_csv(out_csv)}
    assert summary.applied == 0
    assert summary.added == 1
    assert summary.missing == 0
    assert summary.output_rows == 2
    assert rows["融火爆炎"]["target_ru"] == "Плавящий огненный взрыв"
    assert rows["融火爆炎"]["first_seen"] == "0655"
    assert rows["融火爆炎"]["last_seen"] == "0655"
    assert rows["融火爆炎"]["source_count"] == "1"


def test_merge_glossary_version_routes_low_confidence_to_review(tmp_path: Path) -> None:
    candidates = tmp_path / "candidates.csv"
    out_csv = tmp_path / "merged.csv"
    review_csv = tmp_path / "review.csv"
    candidates.write_text(
        "source,target_ru,type,note,confidence,chapter_id\n"
        "高,Высокий,rank,ok,0.95,0652\n"
        "低,Низкий,rank,weak,0.40,0652\n",
        encoding="utf-8",
    )

    summary = merge_glossary_version(candidates, out_csv, review_csv=review_csv, version="v2", min_confidence=0.90)

    merged = out_csv.read_text(encoding="utf-8")
    review = review_csv.read_text(encoding="utf-8")
    assert "高,Высокий" in merged
    assert "低,Низкий" not in merged
    assert summary.added == 1
    assert "低" in review
    assert "low_confidence" in review


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as csv_file:
        return list(csv.DictReader(csv_file))
