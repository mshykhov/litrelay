def build_glossary_prompt(
    *,
    chapter_id: str,
    source_text: str,
    ru_text: str,
    source_lang: str,
    target_lang: str,
) -> str:
    return f"""You are helping build a glossary for a web novel translation.

Task: extract stable terms from chapter {chapter_id}.

Language pair:
- Source: {source_lang}
- Target: {target_lang}

Extract only terms that must stay consistent across chapters:
- character names;
- organizations, races, civilizations;
- places;
- ranks and power levels;
- spells, abilities, artifacts;
- key cosmology concepts.

Do not include ordinary words.

Return CSV only, without markdown:
source,target_ru,type,note,confidence

Every data row must have exactly five comma-separated fields.
Do not use commas inside any field; replace internal commas with semicolons.

<SOURCE_CHAPTER>
{source_text.strip()}
</SOURCE_CHAPTER>

<RUSSIAN_TRANSLATION>
{ru_text.strip()}
</RUSSIAN_TRANSLATION>
"""
