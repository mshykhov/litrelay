from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REQUIRED_GLOSSARY_COLUMNS = ("source", "target_ru", "type", "note", "confidence")
CANONICAL_GLOSSARY_COLUMNS = (
    "source",
    "target_ru",
    "type",
    "note",
    "confidence",
    "first_seen",
    "last_seen",
    "source_count",
    "alternatives",
)
REVIEW_COLUMNS = (
    "code",
    "source",
    "current_target",
    "candidate_target",
    "candidate_count",
    "note",
)


@dataclass(frozen=True)
class GlossaryIssue:
    code: str
    row_number: int
    source: str
    message: str


@dataclass(frozen=True)
class GlossaryValidationReport:
    path: Path
    total_rows: int
    unique_terms: int
    errors: list[GlossaryIssue]

    @property
    def ok(self) -> bool:
        return not self.errors


@dataclass(frozen=True)
class GlossaryMergeSummary:
    added: int
    preserved: int
    conflicts: int
    output_rows: int


@dataclass(frozen=True)
class GlossaryOverrideSummary:
    applied: int
    added: int
    missing: int
    output_rows: int


@dataclass(frozen=True)
class _Candidate:
    source: str
    target_ru: str
    term_type: str
    note: str
    confidence: float
    chapter_id: str
    order: int


def validate_glossary(
    glossary_csv: Path,
    *,
    previous_csv: Path | None = None,
    allow_target_changes: bool = False,
) -> GlossaryValidationReport:
    rows, fieldnames = _read_csv_rows(glossary_csv)
    errors: list[GlossaryIssue] = []
    missing_columns = [column for column in REQUIRED_GLOSSARY_COLUMNS if column not in fieldnames]
    if missing_columns:
        errors.append(
            GlossaryIssue(
                code="missing_columns",
                row_number=0,
                source="",
                message="Missing required columns: " + ", ".join(missing_columns),
            )
        )

    seen_sources: dict[str, int] = {}
    for index, row in enumerate(rows, start=2):
        source = (row.get("source") or "").strip()
        target = (row.get("target_ru") or "").strip()
        if not source:
            errors.append(GlossaryIssue("blank_source", index, source, "Glossary row has blank source"))
            continue
        if not target:
            errors.append(GlossaryIssue("blank_target", index, source, "Glossary row has blank target_ru"))
        if source in seen_sources:
            errors.append(
                GlossaryIssue(
                    "duplicate_source",
                    index,
                    source,
                    f"Duplicate source term; first seen on row {seen_sources[source]}",
                )
            )
        else:
            seen_sources[source] = index

    if previous_csv is not None and not allow_target_changes:
        previous_rows = _rows_by_source(previous_csv)
        for index, row in enumerate(rows, start=2):
            source = (row.get("source") or "").strip()
            target = (row.get("target_ru") or "").strip()
            previous = previous_rows.get(source)
            if previous is None:
                continue
            previous_target = (previous.get("target_ru") or "").strip()
            if target and previous_target and target != previous_target:
                errors.append(
                    GlossaryIssue(
                        "target_changed",
                        index,
                        source,
                        f"target_ru changed from {previous_target!r} to {target!r}",
                    )
                )

    return GlossaryValidationReport(
        path=glossary_csv,
        total_rows=len(rows),
        unique_terms=len(seen_sources),
        errors=errors,
    )


def format_glossary_validation_report(report: GlossaryValidationReport) -> str:
    lines = [
        f"path={report.path}",
        f"total_rows={report.total_rows}",
        f"unique_terms={report.unique_terms}",
        f"errors={len(report.errors)}",
        f"ok={str(report.ok).lower()}",
    ]
    for issue in report.errors:
        lines.append(f"{issue.code}: row={issue.row_number} source={issue.source} message={issue.message}")
    return "\n".join(lines)


def merge_glossary_version(
    candidates_csv: Path,
    out_csv: Path,
    *,
    base_csv: Path | None = None,
    review_csv: Path | None = None,
    changelog: Path | None = None,
    version: str = "",
    min_confidence: float = 0.0,
) -> GlossaryMergeSummary:
    candidate_groups = _read_candidate_groups(candidates_csv)
    base_rows = _read_canonical_rows(base_csv) if base_csv is not None else []
    base_by_source = {row["source"].strip(): row for row in base_rows}

    output_rows: list[dict[str, str]] = []
    review_rows: list[dict[str, str]] = []
    added = 0
    preserved = 0
    conflict_sources: set[str] = set()

    for base_row in base_rows:
        source = base_row["source"].strip()
        output_rows.append(_canonicalize_existing_row(base_row))
        preserved += 1
        if source in candidate_groups:
            selected, variants = _select_preferred_candidate(candidate_groups[source])
            current_target = (base_row.get("target_ru") or "").strip()
            if selected.target_ru and selected.target_ru != current_target:
                conflict_sources.add(source)
                review_rows.append(
                    _review_row(
                        source=source,
                        current_target=current_target,
                        candidate_target=selected.target_ru,
                        candidate_count=_target_count(variants, selected.target_ru),
                        note=f"preserved existing target in {version}".strip(),
                    )
                )

    for source, candidates in candidate_groups.items():
        if source in base_by_source:
            continue
        selected, variants = _select_preferred_candidate(candidates)
        if selected.confidence < min_confidence:
            review_rows.append(
                {
                    "code": "low_confidence",
                    "source": source,
                    "current_target": "",
                    "candidate_target": selected.target_ru,
                    "candidate_count": str(_target_count(variants, selected.target_ru)),
                    "note": f"confidence {selected.confidence:.2f} < {min_confidence:.2f}".strip(),
                }
            )
            continue
        alternatives = _format_alternatives(variants, selected.target_ru)
        if alternatives:
            conflict_sources.add(source)
            review_rows.extend(
                _review_row(
                    source=source,
                    current_target=selected.target_ru,
                    candidate_target=target,
                    candidate_count=count,
                    note=f"candidate variant in {version}".strip(),
                )
                for target, count in variants.items()
                if target != selected.target_ru
            )
        output_rows.append(_canonical_row(selected, candidates, variants, alternatives))
        added += 1

    _write_canonical_rows(out_csv, output_rows)
    if review_csv is not None:
        _write_review_rows(review_csv, review_rows)
    if changelog is not None:
        _append_changelog(
            changelog,
            version=version,
            candidates_csv=candidates_csv,
            base_csv=base_csv,
            out_csv=out_csv,
            added=added,
            preserved=preserved,
            conflicts=len(conflict_sources),
        )

    return GlossaryMergeSummary(
        added=added,
        preserved=preserved,
        conflicts=len(conflict_sources),
        output_rows=len(output_rows),
    )


def apply_glossary_overrides(
    base_csv: Path,
    overrides_csv: Path,
    out_csv: Path,
) -> GlossaryOverrideSummary:
    base_rows = _read_canonical_rows(base_csv)
    override_rows, _ = _read_csv_rows(overrides_csv)
    overrides = {
        (row.get("source") or "").strip(): row
        for row in override_rows
        if (row.get("source") or "").strip() and (row.get("target_ru") or "").strip()
    }
    applied = 0
    added = 0
    output_rows = []
    seen_sources = set()
    for base_row in base_rows:
        source = (base_row.get("source") or "").strip()
        row = _canonicalize_existing_row(base_row)
        override = overrides.get(source)
        if override is not None:
            row["target_ru"] = (override.get("target_ru") or "").strip()
            row["type"] = override.get("type", row["type"]).strip() or row["type"]
            row["note"] = override.get("note", row["note"]).strip() or row["note"]
            row["confidence"] = override.get("confidence", row["confidence"]).strip() or row["confidence"]
            applied += 1
            seen_sources.add(source)
        output_rows.append(row)

    for source, override in overrides.items():
        if source in seen_sources or any(row.get("source") == source for row in output_rows):
            continue
        output_rows.append(_canonical_row_from_override(override))
        seen_sources.add(source)
        added += 1

    _write_canonical_rows(out_csv, output_rows)
    return GlossaryOverrideSummary(
        applied=applied,
        added=added,
        missing=len(set(overrides) - seen_sources),
        output_rows=len(output_rows),
    )


def write_batch_manifest(
    out_json: Path,
    *,
    slug: str,
    start: int,
    end: int,
    model: str,
    glossary_csv: Path,
    glossary_version: str,
    style_guide: Path | None = None,
    recap: Path | None = None,
    prompt_version: str = "translation-agent-v1",
) -> dict[str, Any]:
    manifest: dict[str, Any] = {
        "slug": slug,
        "range": {"start": start, "end": end},
        "model": model,
        "prompt_version": prompt_version,
        "created_at": datetime.now(UTC).isoformat(),
        "glossary": _file_lock(glossary_csv) | {"version": glossary_version},
        "style_guide": _optional_file_lock(style_guide),
        "recap": _optional_file_lock(recap),
    }
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def _read_csv_rows(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    with path.open(encoding="utf-8", newline="") as csv_file:
        reader = csv.DictReader(csv_file)
        return list(reader), list(reader.fieldnames or [])


def _rows_by_source(path: Path) -> dict[str, dict[str, str]]:
    rows, _ = _read_csv_rows(path)
    return {(row.get("source") or "").strip(): row for row in rows if (row.get("source") or "").strip()}


def _read_candidate_groups(path: Path) -> dict[str, list[_Candidate]]:
    rows, _ = _read_csv_rows(path)
    groups: dict[str, list[_Candidate]] = {}
    for order, row in enumerate(rows):
        source = (row.get("source") or "").strip()
        target = (row.get("target_ru") or "").strip()
        if not source or not target:
            continue
        groups.setdefault(source, []).append(
            _Candidate(
                source=source,
                target_ru=target,
                term_type=(row.get("type") or "").strip(),
                note=(row.get("note") or "").strip(),
                confidence=_parse_confidence(row.get("confidence", "")),
                chapter_id=(row.get("chapter_id") or row.get("first_seen") or "").strip(),
                order=order,
            )
        )
    return groups


def _read_canonical_rows(path: Path | None) -> list[dict[str, str]]:
    if path is None:
        return []
    rows, _ = _read_csv_rows(path)
    return [row for row in rows if (row.get("source") or "").strip()]


def _select_preferred_candidate(candidates: list[_Candidate]) -> tuple[_Candidate, dict[str, int]]:
    variants: dict[str, int] = {}
    confidence_sum: dict[str, float] = {}
    first_order: dict[str, int] = {}
    for candidate in candidates:
        variants[candidate.target_ru] = variants.get(candidate.target_ru, 0) + 1
        confidence_sum[candidate.target_ru] = confidence_sum.get(candidate.target_ru, 0.0) + candidate.confidence
        first_order.setdefault(candidate.target_ru, candidate.order)

    selected_target = sorted(
        variants,
        key=lambda target: (
            -variants[target],
            -(confidence_sum[target] / variants[target]),
            first_order[target],
        ),
    )[0]
    selected = sorted(
        [candidate for candidate in candidates if candidate.target_ru == selected_target],
        key=lambda candidate: (-candidate.confidence, candidate.order),
    )[0]
    return selected, variants


def _canonical_row(
    selected: _Candidate,
    candidates: list[_Candidate],
    variants: dict[str, int],
    alternatives: str,
) -> dict[str, str]:
    group_count = sum(variants.values())
    return {
        "source": selected.source,
        "target_ru": selected.target_ru,
        "type": selected.term_type,
        "note": selected.note,
        "confidence": f"{selected.confidence:.2f}",
        "first_seen": _first_seen(candidates, selected.chapter_id),
        "last_seen": _last_seen(candidates, selected.chapter_id),
        "source_count": str(group_count),
        "alternatives": alternatives,
    }


def _canonicalize_existing_row(row: dict[str, str]) -> dict[str, str]:
    return {column: (row.get(column) or "").strip() for column in CANONICAL_GLOSSARY_COLUMNS}


def _canonical_row_from_override(row: dict[str, str]) -> dict[str, str]:
    chapter_id = (row.get("chapter_id") or row.get("first_seen") or "").strip()
    return {
        "source": (row.get("source") or "").strip(),
        "target_ru": (row.get("target_ru") or "").strip(),
        "type": (row.get("type") or "").strip(),
        "note": (row.get("note") or "").strip(),
        "confidence": (row.get("confidence") or "").strip(),
        "first_seen": chapter_id,
        "last_seen": (row.get("last_seen") or chapter_id).strip(),
        "source_count": (row.get("source_count") or "1").strip(),
        "alternatives": (row.get("alternatives") or "").strip(),
    }


def _write_canonical_rows(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=list(CANONICAL_GLOSSARY_COLUMNS))
        writer.writeheader()
        writer.writerows(rows)


def _write_review_rows(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=list(REVIEW_COLUMNS))
        writer.writeheader()
        writer.writerows(rows)


def _review_row(
    *,
    source: str,
    current_target: str,
    candidate_target: str,
    candidate_count: int,
    note: str,
) -> dict[str, str]:
    return {
        "code": "target_conflict",
        "source": source,
        "current_target": current_target,
        "candidate_target": candidate_target,
        "candidate_count": str(candidate_count),
        "note": note,
    }


def _format_alternatives(variants: dict[str, int], selected_target: str) -> str:
    alternatives = [f"{target}:{count}" for target, count in variants.items() if target != selected_target]
    return "; ".join(alternatives)


def _target_count(variants: dict[str, int], target: str) -> int:
    return variants.get(target, 0)


def _first_seen(candidates: list[_Candidate], fallback: str) -> str:
    values = sorted(candidate.chapter_id for candidate in candidates if candidate.chapter_id)
    return values[0] if values else fallback


def _last_seen(candidates: list[_Candidate], fallback: str) -> str:
    values = sorted(candidate.chapter_id for candidate in candidates if candidate.chapter_id)
    return values[-1] if values else fallback


def _parse_confidence(value: str | None) -> float:
    if value is None:
        return 0.0
    normalized = value.strip().lower()
    if normalized == "high":
        return 0.9
    if normalized == "medium":
        return 0.6
    if normalized == "low":
        return 0.3
    try:
        return float(normalized)
    except ValueError:
        return 0.0


def _append_changelog(
    path: Path,
    *,
    version: str,
    candidates_csv: Path,
    base_csv: Path | None,
    out_csv: Path,
    added: int,
    preserved: int,
    conflicts: int,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    entry = "\n".join(
        [
            f"## {datetime.now(UTC).date().isoformat()} {version}".strip(),
            "",
            f"- candidates: `{candidates_csv}`",
            f"- base: `{base_csv}`",
            f"- output: `{out_csv}`",
            f"- added: {added}",
            f"- preserved: {preserved}",
            f"- conflicts: {conflicts}",
            "",
        ]
    )
    mode = "a" if path.exists() else "w"
    with path.open(mode, encoding="utf-8") as changelog_file:
        changelog_file.write(entry)


def _file_lock(path: Path) -> dict[str, str]:
    return {
        "path": str(path),
        "sha256": _sha256(path),
    }


def _optional_file_lock(path: Path | None) -> dict[str, str] | None:
    if path is None:
        return None
    return _file_lock(path)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
