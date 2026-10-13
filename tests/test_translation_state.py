from pathlib import Path

from litrelay.translation_state import (
    TranslationState,
    advance_state,
    read_state,
    write_state,
)


def test_state_roundtrip_and_advance(tmp_path: Path) -> None:
    path = tmp_path / "translation-state.json"
    write_state(path, TranslationState(last_source_chapter=648, last_ru_number=652))

    state = read_state(path)
    assert state.last_source_chapter == 648
    assert state.last_ru_number == 652

    advanced = advance_state(state, 10)
    assert advanced.last_source_chapter == 658
    assert advanced.last_ru_number == 662
