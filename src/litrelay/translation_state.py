from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class TranslationState:
    last_source_chapter: int
    last_ru_number: int


def read_state(path: Path) -> TranslationState:
    data = json.loads(path.read_text(encoding="utf-8"))
    return TranslationState(
        last_source_chapter=int(data["last_source_chapter"]),
        last_ru_number=int(data["last_ru_number"]),
    )


def write_state(path: Path, state: TranslationState) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "last_source_chapter": state.last_source_chapter,
        "last_ru_number": state.last_ru_number,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def advance_state(state: TranslationState, count: int) -> TranslationState:
    return TranslationState(
        last_source_chapter=state.last_source_chapter + count,
        last_ru_number=state.last_ru_number + count,
    )
