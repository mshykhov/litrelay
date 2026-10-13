from __future__ import annotations

import json
import uuid
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from xml.sax.saxutils import escape, quoteattr

XHTML = "http://www.w3.org/1999/xhtml"


def export_book(
    chapters: dict[int, str], *, out_dir: Path, title: str, language: str, report: dict, glossary: str
) -> dict[str, Path]:
    if not chapters:
        raise ValueError("Cannot export an empty book")
    out_dir.mkdir(parents=True, exist_ok=True)
    files = {kind: out_dir / f"book.{kind}" for kind in ("txt", "epub", "zip")}
    text = "\n\n".join(chapters[n].rstrip() for n in sorted(chapters)) + "\n"
    temp = files["txt"].with_suffix(".txt.tmp")
    temp.write_text(text, encoding="utf-8")
    temp.replace(files["txt"])
    _write_epub(chapters, files["epub"], title, language)
    temp = files["zip"].with_suffix(".zip.tmp")
    with zipfile.ZipFile(temp, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.write(files["txt"], "book.txt")
        z.write(files["epub"], "book.epub")
        for n in sorted(chapters):
            z.writestr(f"chapters/{n:04d}.txt", chapters[n].encode("utf-8"))
        z.writestr("glossary.csv", glossary.encode("utf-8"))
        z.writestr("report.json", json.dumps(report, ensure_ascii=False, indent=2).encode("utf-8"))
    temp.replace(files["zip"])
    return files


def _page(title: str, body: str, language: str) -> str:
    return f'<?xml version="1.0" encoding="utf-8"?><html xmlns="{XHTML}" xmlns:epub="http://www.idpf.org/2007/ops" lang={quoteattr(language)} xml:lang={quoteattr(language)}><head><title>{escape(title)}</title><meta charset="utf-8"/></head><body>{body}</body></html>'


def _write_epub(chapters: dict[int, str], path: Path, title: str, language: str) -> None:
    temp = path.with_suffix(".epub.tmp")
    items = []
    spine = []
    links = []
    with zipfile.ZipFile(temp, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        z.writestr(
            "META-INF/container.xml",
            '<?xml version="1.0"?><container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles><rootfile full-path="EPUB/package.opf" media-type="application/oebps-package+xml"/></rootfiles></container>',
        )
        for n, text in sorted(chapters.items()):
            lines = text.strip().splitlines()
            chapter_title = lines[0]
            body = (
                "<h1>"
                + escape(chapter_title)
                + "</h1>"
                + "".join("<p>" + escape(x) + "</p>" for x in lines[1:] if x.strip())
            )
            name = f"chapters/{n:04d}.xhtml"
            z.writestr("EPUB/" + name, _page(chapter_title, body, language).encode("utf-8"))
            items.append(f'<item id="ch{n}" href="{name}" media-type="application/xhtml+xml"/>')
            spine.append(f'<itemref idref="ch{n}"/>')
            links.append(f'<li><a href="{name}">{escape(chapter_title)}</a></li>')
        nav = '<nav epub:type="toc" id="toc"><h1>' + escape(title) + "</h1><ol>" + "".join(links) + "</ol></nav>"
        z.writestr("EPUB/nav.xhtml", _page(title, nav, language).encode("utf-8"))
        modified = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        package = (
            f'<?xml version="1.0" encoding="utf-8"?><package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="bookid"><metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:identifier id="bookid">urn:uuid:{uuid.uuid4()}</dc:identifier><dc:title>{escape(title)}</dc:title><dc:language>{escape(language)}</dc:language><meta property="dcterms:modified">{modified}</meta></metadata><manifest><item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>'
            + "".join(items)
            + "</manifest><spine>"
            + "".join(spine)
            + "</spine></package>"
        )
        z.writestr("EPUB/package.opf", package.encode("utf-8"))
    temp.replace(path)
