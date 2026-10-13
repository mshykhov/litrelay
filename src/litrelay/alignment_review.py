import csv
from pathlib import Path


def choose_alignment_review_indexes(
    *,
    total: int,
    sample_every: int,
    known_risks: list[int] | None = None,
) -> list[int]:
    selected = {1, 2, 3}
    selected.update(range(max(1, total - 2), total + 1))
    selected.update(range(sample_every, total + 1, sample_every))
    selected.update(index for index in known_risks or [] if 1 <= index <= total)
    return sorted(selected)


def build_alignment_review_rows(
    working_map_csv: Path,
    *,
    source_dir: Path,
    ru_dir: Path,
    indexes: list[int],
    preview_chars: int = 260,
) -> list[dict[str, str]]:
    rows_by_index = _working_rows_by_index(working_map_csv)
    review_rows: list[dict[str, str]] = []

    for index in indexes:
        chapter_id = f"{index:04d}"
        map_row = rows_by_index[index]
        source_text = (source_dir / f"{chapter_id}.txt").read_text(encoding="utf-8")
        ru_text = (ru_dir / f"{chapter_id}.txt").read_text(encoding="utf-8")
        review_rows.append(
            {
                "aligned_index": str(index),
                "ru_title": map_row["ru_title"],
                "source_title": map_row["source_title"],
                "ru_chars": str(len(ru_text)),
                "source_chars": str(len(source_text)),
                "ru_preview": _preview(ru_text, preview_chars),
                "source_preview": _preview(source_text, preview_chars),
                "review_status": "needs-review",
                "notes": "",
            }
        )

    return review_rows


def write_alignment_review_csv(rows: list[dict[str, str]], out_csv: Path) -> None:
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    fields = _fields(rows)
    with out_csv.open("w", encoding="utf-8", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _working_rows_by_index(path: Path) -> dict[int, dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as csv_file:
        return {int(row["aligned_index"]): row for row in csv.DictReader(csv_file)}


def _preview(text: str, max_chars: int) -> str:
    normalized = " ".join(line.strip() for line in text.splitlines() if line.strip())
    return normalized[:max_chars]


def _fields(rows: list[dict[str, str]]) -> list[str]:
    if not rows:
        return ["aligned_index"]
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    return fields
