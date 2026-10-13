from pathlib import Path

from litrelay.protected_terms import (
    apply_protected_term_fixes,
    format_protected_term_report,
    validate_protected_terms,
)


def test_validate_protected_terms_reports_forbidden_variants(tmp_path: Path) -> None:
    protected_csv = tmp_path / "protected.csv"
    text_dir = tmp_path / "accepted"
    text_dir.mkdir()
    protected_csv.write_text(
        "forbidden_ru,canonical_ru,note\nПонком,Панком,name typo\n",
        encoding="utf-8",
    )
    (text_dir / "0655.txt").write_text("Расстояние между ним и Понком сократилось.", encoding="utf-8")

    report = validate_protected_terms(text_dir, protected_csv)

    assert not report.ok
    assert len(report.matches) == 1
    assert report.matches[0].path == text_dir / "0655.txt"
    assert report.matches[0].forbidden_ru == "Понком"
    assert "ok=false" in format_protected_term_report(report)


def test_apply_protected_term_fixes_rewrites_forbidden_variants(tmp_path: Path) -> None:
    protected_csv = tmp_path / "protected.csv"
    source_dir = tmp_path / "accepted"
    out_dir = tmp_path / "fixed"
    source_dir.mkdir()
    protected_csv.write_text(
        "\n".join(
            [
                "forbidden_ru,canonical_ru,note",
                "Понк,Панк,name typo",
                "Понком,Панком,name typo",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (source_dir / "0655.txt").write_text("Понк говорил с Понком.", encoding="utf-8")
    (source_dir / "0656.txt").write_text("Панк молчал.", encoding="utf-8")

    summary = apply_protected_term_fixes(source_dir, protected_csv, out_dir)

    assert summary.files_written == 2
    assert summary.replacements == 2
    assert (out_dir / "0655.txt").read_text(encoding="utf-8") == "Панк говорил с Панком."
    assert validate_protected_terms(out_dir, protected_csv).ok
