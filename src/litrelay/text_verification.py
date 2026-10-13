import csv
import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class TextVerificationReport:
    expected: int
    present: int
    missing: list[str]
    too_short: list[tuple[str, int]]
    suspicious: list[tuple[str, str]]

    @property
    def ok(self) -> bool:
        return not self.missing and not self.too_short and not self.suspicious


def verify_text_directory(
    chapter_map_csv: Path,
    text_dir: Path,
    *,
    min_chars: int = 1000,
) -> TextVerificationReport:
    expected_ids = _chapter_ids_from_map(chapter_map_csv)
    missing: list[str] = []
    too_short: list[tuple[str, int]] = []
    suspicious: list[tuple[str, str]] = []
    present = 0

    for chapter_id in expected_ids:
        path = text_dir / f"{chapter_id}.txt"
        if not path.exists():
            missing.append(chapter_id)
            continue

        present += 1
        text = path.read_text(encoding="utf-8")
        if len(text) < min_chars:
            too_short.append((chapter_id, len(text)))

        reason = _suspicious_reason(text)
        if reason is not None:
            suspicious.append((chapter_id, reason))

    return TextVerificationReport(
        expected=len(expected_ids),
        present=present,
        missing=missing,
        too_short=too_short,
        suspicious=suspicious,
    )


def verify_numbered_texts(
    text_dir: Path,
    *,
    expected_count: int,
    min_chars: int = 1000,
) -> TextVerificationReport:
    expected_ids = [f"{index:04d}" for index in range(1, expected_count + 1)]
    return _verify_ids(expected_ids, text_dir, min_chars=min_chars)


def format_verification_report(report: TextVerificationReport) -> str:
    lines = [
        f"expected={report.expected}",
        f"present={report.present}",
        f"missing={len(report.missing)}",
        f"too_short={len(report.too_short)}",
        f"suspicious={len(report.suspicious)}",
    ]
    if report.missing:
        lines.append("missing_ids=" + ",".join(report.missing[:20]))
    if report.too_short:
        lines.append(
            "too_short_ids=" + ",".join(f"{chapter_id}:{chars}" for chapter_id, chars in report.too_short[:20])
        )
    if report.suspicious:
        lines.append(
            "suspicious_ids=" + ",".join(f"{chapter_id}:{reason}" for chapter_id, reason in report.suspicious[:20])
        )
    return "\n".join(lines)


def _chapter_ids_from_map(chapter_map_csv: Path) -> list[str]:
    ids: list[str] = []
    with chapter_map_csv.open(encoding="utf-8", newline="") as csv_file:
        for row in csv.DictReader(csv_file):
            ids.append(f"{int(row['aligned_index']):04d}")
    return ids


def _verify_ids(expected_ids: list[str], text_dir: Path, *, min_chars: int) -> TextVerificationReport:
    missing: list[str] = []
    too_short: list[tuple[str, int]] = []
    suspicious: list[tuple[str, str]] = []
    present = 0

    for chapter_id in expected_ids:
        path = text_dir / f"{chapter_id}.txt"
        if not path.exists():
            missing.append(chapter_id)
            continue

        present += 1
        text = path.read_text(encoding="utf-8")
        if len(text) < min_chars:
            too_short.append((chapter_id, len(text)))

        reason = _suspicious_reason(text)
        if reason is not None:
            suspicious.append((chapter_id, reason))

    return TextVerificationReport(
        expected=len(expected_ids),
        present=present,
        missing=missing,
        too_short=too_short,
        suspicious=suspicious,
    )


def _suspicious_reason(text: str) -> str | None:
    stripped = text.lstrip().lower()
    if stripped.startswith("<!doctype html") or stripped.startswith("<html"):
        return "looks-like-html"
    if stripped.startswith("{") and re.search(r'"(error|message|data)"\s*:', stripped[:500]):
        return "looks-like-json"
    if "captcha" in stripped[:1000] or "安全验证" in text[:1000]:
        return "captcha-or-check"
    return None
