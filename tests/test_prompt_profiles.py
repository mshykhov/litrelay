import json
from pathlib import Path

from litrelay.prompt_profiles import PromptSettings, prepare_tasks


def test_profile_applies_languages_style_and_custom_prompt_to_every_stage(tmp_path: Path) -> None:
    settings = PromptSettings(
        "en",
        "uk",
        style="Keep restrained lyrical prose.",
        templates={"translation": "Custom {source_language} to {target_language}"},
    )
    p = tmp_path / "tasks.jsonl"
    p.write_text(
        "\n".join(
            json.dumps(
                {
                    "custom_id": f"{agent}-0001",
                    "agent": agent,
                    "system": "Chinese Russian old rules",
                    "input": {"recent_russian_context": [{"text": "human context"}], "quality_gates": ["Russian only"]},
                }
            )
            for agent in ["translation-agent", "translation-qa", "glossary-extractor"]
        )
    )
    rows = [json.loads(x) for x in prepare_tasks(p, settings).read_text().splitlines()]
    assert rows[0]["system"].startswith("Custom en to uk")
    assert all("uk" in r["system"] and "lyrical" in r["system"] for r in rows)
    assert rows[0]["input"]["recent_target_context"][0]["text"] == "human context"
    assert not any("Chinese" in r["system"] or "Russian" in r["system"] for r in rows)
