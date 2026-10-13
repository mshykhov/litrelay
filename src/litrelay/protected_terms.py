from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ProtectedTerm:
    forbidden_ru: str
    canonical_ru: str
    note: str


@dataclass(frozen=True)
class ProtectedTermMatch:
    path: Path
    forbidden_ru: str
    canonical_ru: str
    count: int


@dataclass(frozen=True)
class ProtectedTermReport:
    text_dir: Path
    protected_csv: Path
    files_checked: int
    matches: list[ProtectedTermMatch]

    @property
    def ok(self) -> bool:
        return not self.matches


@dataclass(frozen=True)
class ProtectedTermFixSummary:
    source_dir: Path
    out_dir: Path
    files_written: int
    replacements: int


def validate_protected_terms(text_dir: Path, protected_csv: Path) -> ProtectedTermReport:
    terms = _read_protected_terms(protected_csv)
    matches: list[ProtectedTermMatch] = []
    files_checked = 0
    for path in sorted(text_dir.glob("*.txt")):
        files_checked += 1
        text = path.read_text(encoding="utf-8")
        for term in terms:
            count = text.count(term.forbidden_ru)
            if count:
                matches.append(
                    ProtectedTermMatch(
                        path=path,
                        forbidden_ru=term.forbidden_ru,
                        canonical_ru=term.canonical_ru,
                        count=count,
                    )
                )
    return ProtectedTermReport(
        text_dir=text_dir,
        protected_csv=protected_csv,
        files_checked=files_checked,
        matches=matches,
    )


def apply_protected_term_fixes(
    source_dir: Path,
    protected_csv: Path,
    out_dir: Path,
) -> ProtectedTermFixSummary:
    terms = _read_protected_terms(protected_csv)
    out_dir.mkdir(parents=True, exist_ok=True)
    files_written = 0
    replacements = 0
    for source_path in sorted(source_dir.glob("*.txt")):
        text = source_path.read_text(encoding="utf-8")
        for term in terms:
            count = text.count(term.forbidden_ru)
            if count:
                text = text.replace(term.forbidden_ru, term.canonical_ru)
                replacements += count
        (out_dir / source_path.name).write_text(text, encoding="utf-8")
        files_written += 1
    return ProtectedTermFixSummary(
        source_dir=source_dir,
        out_dir=out_dir,
        files_written=files_written,
        replacements=replacements,
    )


def format_protected_term_report(report: ProtectedTermReport) -> str:
    lines = [
        f"text_dir={report.text_dir}",
        f"protected_csv={report.protected_csv}",
        f"files_checked={report.files_checked}",
        f"matches={len(report.matches)}",
        f"ok={str(report.ok).lower()}",
    ]
    for match in report.matches:
        lines.append(f"{match.path}: forbidden={match.forbidden_ru} canonical={match.canonical_ru} count={match.count}")
    return "\n".join(lines)


def _read_protected_terms(path: Path) -> list[ProtectedTerm]:
    with path.open(encoding="utf-8", newline="") as csv_file:
        reader = csv.DictReader(csv_file)
        return [
            ProtectedTerm(
                forbidden_ru=row.get("forbidden_ru", "").strip(),
                canonical_ru=row.get("canonical_ru", "").strip(),
                note=row.get("note", "").strip(),
            )
            for row in reader
            if row.get("forbidden_ru", "").strip() and row.get("canonical_ru", "").strip()
        ]
