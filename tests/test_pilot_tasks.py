from litrelay.pilot_tasks import build_translation_pilot_task, build_translation_qa_task


def test_build_translation_pilot_task_excludes_reference_translation() -> None:
    task = build_translation_pilot_task(
        chapter_id="0101",
        source_text="第101章 测试\n中文正文",
        glossary_csv="chapter_id,source,target_ru,type,note,confidence\n0001,朋克,Панк,name,,1.0\n",
        context_chapters=[("0099", "Предыдущая глава")],
    )

    assert task["custom_id"] == "translate-0101"
    assert task["agent"] == "translation-agent"
    assert task["expected_output"]["format"] == "translation_json"
    assert task["input"]["chapter_id"] == "0101"
    assert "reference_translation" not in task["input"]
    assert "quality_gates" in task["input"]
    assert any("source residue" in gate for gate in task["input"]["quality_gates"])
    assert any("mixed Latin/Cyrillic" in gate for gate in task["input"]["quality_gates"])
    assert any("near-miss" in gate and "glossary" in gate for gate in task["input"]["quality_gates"])
    assert all("Панк" not in gate and "Понк" not in gate for gate in task["input"]["quality_gates"])


def test_build_translation_qa_task_uses_reference_for_comparison() -> None:
    task = build_translation_qa_task(
        chapter_id="0101",
        source_text="第101章 测试\n中文正文",
        generated_translation="Модельный перевод",
        reference_translation="Существующий перевод",
        glossary_csv="chapter_id,source,target_ru,type,note,confidence\n0001,朋克,Панк,name,,1.0\n",
    )

    assert task["custom_id"] == "translation-qa-0101"
    assert task["agent"] == "translation-qa"
    assert task["expected_output"]["format"] == "translation_qa_json"
    assert task["input"]["reference_translation"] == "Существующий перевод"
