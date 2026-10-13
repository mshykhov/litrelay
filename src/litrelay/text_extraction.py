import re
from typing import Any


def extract_ranobelib_text(payload: Any) -> str:
    data = _object(payload).get("data", payload)
    content = _object(data).get("content")
    if not isinstance(content, dict):
        raise ValueError("RanobeLib payload does not contain data.content")

    paragraphs = [_normalize_paragraph(_prosemirror_text(node)) for node in content.get("content", [])]
    return _join_paragraphs(paragraphs)


def extract_qidian_page_text(payload: Any) -> str:
    data = _object(payload)
    title = _clean_qidian_title(str(data.get("title", "")).strip())
    paragraphs = []
    if title:
        paragraphs.append(title)

    raw_paragraphs = data.get("paragraphs")
    if isinstance(raw_paragraphs, list):
        paragraphs.extend(str(paragraph) for paragraph in raw_paragraphs)
    else:
        text = str(data.get("text", ""))
        paragraphs.extend(text.splitlines())

    return _join_paragraphs(_drop_noise_lines(paragraphs))


def extract_text(payload: Any, source_format: str) -> str:
    if source_format == "ranobelib-api":
        return extract_ranobelib_text(payload)
    if source_format == "qidian-page-json":
        return extract_qidian_page_text(payload)
    raise ValueError(f"Unsupported text source format: {source_format}")


def _object(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("Expected JSON object")
    return value


def _prosemirror_text(node: Any) -> str:
    if not isinstance(node, dict):
        return ""

    node_type = node.get("type")
    if node_type == "text":
        return str(node.get("text", ""))
    if node_type == "hardBreak":
        return "\n"

    children = node.get("content")
    if not isinstance(children, list):
        return ""
    return "".join(_prosemirror_text(child) for child in children)


def _drop_noise_lines(lines: list[str]) -> list[str]:
    cleaned: list[str] = []
    for line in lines:
        normalized = _normalize_paragraph(line)
        if not normalized:
            continue
        if re.fullmatch(r"\d+", normalized):
            continue
        cleaned.append(normalized)
    return cleaned


def _clean_qidian_title(title: str) -> str:
    return re.sub(r"\s+\d+$", "", title).strip()


def _join_paragraphs(paragraphs: list[str]) -> str:
    return "\n\n".join(paragraph for paragraph in (_normalize_paragraph(p) for p in paragraphs) if paragraph)


def _normalize_paragraph(paragraph: str) -> str:
    lines = [re.sub(r"[ \t\u3000]+", " ", line).strip() for line in str(paragraph).splitlines()]
    return "\n".join(line for line in lines if line).strip()
