from __future__ import annotations

import posixpath
import re
import zipfile
from pathlib import Path
from urllib.parse import unquote
from xml.etree import ElementTree as ET

HEADING = re.compile(r"^\s*(?:chapter\s+(\d+)|глава\s+(\d+)|第\s*(\d+)\s*章)", re.I)
BLOCKED = (
    "Для полного прочтения",
    "Нажмите, для загрузки полной главы",
    "请登录后阅读",
    "订阅后阅读",
    "captcha",
    "安全验证",
)


def heading_number(text: str) -> int | None:
    match = HEADING.match(text)
    return int(next(x for x in match.groups() if x)) if match else None


def validate_chapter(number: int, text: str, *, min_chars: int = 100, target_language: str | None = None) -> None:
    title, _, body = text.strip().partition("\n")
    if not 1 <= number <= 100000 or not title or len(body.strip()) < min_chars:
        raise ValueError(f"Chapter {number}: body is shorter than {min_chars} characters")
    stated = heading_number(title)
    if stated is not None and stated != number:
        raise ValueError(f"Chapter number mismatch: file {number}, heading {stated}")
    lowered = text.lower()
    if lowered.lstrip().startswith(("<html", "<!doctype", '{"error')) or any(x.lower() in lowered for x in BLOCKED):
        raise ValueError(f"Chapter {number}: HTML, preview or challenge content")
    if (
        target_language
        and target_language.lower().split("-")[0] in {"ru", "en", "uk", "de", "fr", "es", "it", "pt", "pl"}
        and re.search(r"[\u3400-\u9fff]", text)
    ):
        raise ValueError(f"Chapter {number}: untranslated Chinese residue")


def read_chapters(path: Path, *, min_chars: int = 100) -> dict[int, str]:
    if path.is_dir():
        rows = []
        for p in sorted(path.glob("*.txt")):
            if not re.fullmatch(r"[0-9]{1,8}", p.stem):
                raise ValueError(f"Expected numbered chapter filename: {p.name}")
            rows.append((int(p.stem), p.read_text(encoding="utf-8-sig")))
    elif path.suffix.lower() == ".epub":
        rows = _read_epub(path)
    elif path.suffix.lower() == ".txt":
        text = path.read_text(encoding="utf-8-sig")
        starts = [
            (m.start(), heading_number(m.group()))
            for m in re.finditer(r"^(?:Chapter\s+\d+[^\n]*|Глава\s+\d+[^\n]*|第\s*\d+\s*章[^\n]*)$", text, re.M | re.I)
        ]
        if not starts or text[: starts[0][0]].strip():
            raise ValueError(
                "Combined TXT needs numbered chapter headings and no unassigned preface; use numbered files for other layouts"
            )
        rows = [
            (n, text[start : starts[i + 1][0] if i + 1 < len(starts) else len(text)])
            for i, (start, n) in enumerate(starts)
        ]
    else:
        raise ValueError("Input must be a numbered TXT directory, combined UTF-8 TXT, or EPUB")
    result = {}
    for number, text in rows:
        text = text.replace("\r\n", "\n").strip() + "\n"
        if number in result:
            raise ValueError(f"Duplicate chapter number {number}")
        validate_chapter(number, text, min_chars=min_chars)
        result[number] = text
    if not result:
        raise ValueError(f"No chapters found in {path}")
    return dict(sorted(result.items()))


def _read_epub(path: Path) -> list[tuple[int, str]]:
    with zipfile.ZipFile(path) as archive:
        if sum(x.file_size for x in archive.infolist()) > 200_000_000:
            raise ValueError("EPUB uncompressed size exceeds200MB")
        container = ET.fromstring(archive.read("META-INF/container.xml"))
        rootfile = container.find(".//{*}rootfile")
        if rootfile is None:
            raise ValueError("EPUB has no package rootfile")
        package_path = rootfile.attrib["full-path"]
        package = ET.fromstring(archive.read(package_path))
        items = {x.attrib["id"]: x for x in package.findall("{*}manifest/{*}item")}
        rows = []
        for ref in package.findall("{*}spine/{*}itemref"):
            if ref.get("linear") == "no":
                continue
            item = items[ref.attrib["idref"]]
            if "nav" in item.get("properties", "").split():
                continue
            if item.get("media-type") != "application/xhtml+xml":
                raise ValueError("Only text XHTML EPUB spine items are supported")
            name = posixpath.normpath(
                posixpath.join(posixpath.dirname(package_path), unquote(item.attrib["href"].split("#")[0]))
            )
            document = ET.fromstring(archive.read(name))
            body = document.find("{*}body")
            if body is None:
                raise ValueError(f"EPUB item has no body: {name}")
            paragraphs = _epub_paragraphs(body)
            if not paragraphs:
                raise ValueError(f"No text chapter in EPUB item {name}; normalize its chapters first")
            text = "\n\n".join(paragraphs)
            number = heading_number(paragraphs[0]) or len(rows) + 1
            rows.append((number, text))
        return rows


def _epub_paragraphs(body: ET.Element) -> list[str]:
    paragraphs = []

    def visit(node: ET.Element) -> None:
        tag = node.tag.rsplit("}", 1)[-1]
        if tag in {"script", "style", "nav"}:
            return
        if tag in {"h1", "h2", "h3", "p", "li", "pre", "blockquote"}:
            content = "".join(node.itertext()).strip()
            if content:
                paragraphs.append(content)
            return
        for child in node:
            visit(child)

    visit(body)
    return paragraphs
