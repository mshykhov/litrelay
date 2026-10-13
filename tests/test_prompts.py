from litrelay.prompts import build_glossary_prompt


def test_build_glossary_prompt_contains_inputs_and_csv_contract() -> None:
    prompt = build_glossary_prompt(
        chapter_id="0007",
        source_text="耐瑟瑞尔",
        ru_text="Нетерил",
        source_lang="Chinese",
        target_lang="Russian",
    )

    assert "chapter 0007" in prompt
    assert "source,target_ru,type,note,confidence" in prompt
    assert "耐瑟瑞尔" in prompt
    assert "Нетерил" in prompt
    assert "Chinese" in prompt
    assert "Russian" in prompt
