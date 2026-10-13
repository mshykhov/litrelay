from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ChapterPair:
    chapter_id: str
    source_path: Path
    ru_path: Path


def discover_pairs(source_dir: Path, ru_dir: Path) -> list[ChapterPair]:
    source_files = _chapter_files_by_id(source_dir)
    ru_files = _chapter_files_by_id(ru_dir)

    return [
        ChapterPair(chapter_id=chapter_id, source_path=source_files[chapter_id], ru_path=ru_files[chapter_id])
        for chapter_id in sorted(source_files.keys() & ru_files.keys())
    ]


def _chapter_files_by_id(directory: Path) -> dict[str, Path]:
    if not directory.exists():
        raise FileNotFoundError(f"Chapter directory does not exist: {directory}")
    if not directory.is_dir():
        raise NotADirectoryError(f"Chapter path is not a directory: {directory}")

    files: dict[str, Path] = {}
    for path in directory.glob("*.txt"):
        chapter_id = path.stem
        if chapter_id.isdigit():
            files[chapter_id] = path
    return files
