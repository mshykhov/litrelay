import csv
import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from litrelay.text_extraction import extract_ranobelib_text

FetchJson = Callable[[str], dict[str, Any]]


@dataclass(frozen=True)
class RanobeLibChapterRef:
    chapter_id: str
    volume: str
    number: str
    branch_id: int


@dataclass(frozen=True)
class DownloadSummary:
    downloaded: int
    skipped: int
    failed: int


def read_ranobelib_refs_from_csv(
    path: Path,
    *,
    start_index: int | None = None,
    end_index: int | None = None,
    limit: int | None = None,
) -> list[RanobeLibChapterRef]:
    refs: list[RanobeLibChapterRef] = []
    with path.open(encoding="utf-8", newline="") as csv_file:
        for row in csv.DictReader(csv_file):
            aligned_index = int(row["aligned_index"])
            if start_index is not None and aligned_index < start_index:
                continue
            if end_index is not None and aligned_index > end_index:
                continue
            refs.append(
                RanobeLibChapterRef(
                    chapter_id=f"{aligned_index:04d}",
                    volume=row["ru_volume"],
                    number=row["ru_number"],
                    branch_id=int(row["ru_branch_id"]),
                )
            )
            if limit is not None and len(refs) >= limit:
                break
    return refs


def download_ranobelib_chapters(
    refs: list[RanobeLibChapterRef],
    *,
    api_slug: str,
    out_json_dir: Path,
    out_text_dir: Path,
    fetch_json: FetchJson | None = None,
    sleep_seconds: float = 0,
    force: bool = False,
) -> DownloadSummary:
    out_json_dir.mkdir(parents=True, exist_ok=True)
    out_text_dir.mkdir(parents=True, exist_ok=True)
    fetch = fetch_json or _fetch_json
    downloaded = 0
    skipped = 0
    failed = 0

    for ref in refs:
        json_path = out_json_dir / f"{ref.chapter_id}.json"
        text_path = out_text_dir / f"{ref.chapter_id}.txt"
        if not force and json_path.exists() and text_path.exists():
            skipped += 1
            continue

        try:
            payload = fetch(_ranobelib_chapter_api_url(api_slug, ref))
            json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            text_path.write_text(extract_ranobelib_text(payload), encoding="utf-8")
            downloaded += 1
        except Exception as error:
            failed += 1
            print(f"Failed {ref.chapter_id}: {error}")

        if sleep_seconds > 0:
            time.sleep(sleep_seconds)

    return DownloadSummary(downloaded=downloaded, skipped=skipped, failed=failed)


def _fetch_json(url: str) -> dict[str, Any]:
    request = Request(url, headers={"User-Agent": "Mozilla/5.0 novel-translation-tools/0.1"})
    with urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def _ranobelib_chapter_api_url(api_slug: str, ref: RanobeLibChapterRef) -> str:
    query = urlencode({"branch_id": ref.branch_id, "number": ref.number, "volume": ref.volume})
    return f"https://api.cdnlibs.org/api/manga/{api_slug}/chapter?{query}"
