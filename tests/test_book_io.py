import json
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

import pytest

from litrelay.book_export import export_book
from litrelay.book_inputs import read_chapters


def test_inputs_normalize_numbers_but_preserve_text_and_reject_wrong_titles(tmp_path: Path) -> None:
    (tmp_path / "1.txt").write_text("Chapter 1. Harbor\n\nEvery number123 survives.\nFinal paragraph.")
    assert read_chapters(tmp_path, min_chars=10)[1].endswith("Final paragraph.\n")
    (tmp_path / "2.txt").write_text("Chapter 3. Mismatch\n\nA long enough sentence.")
    with pytest.raises(ValueError, match="number"):
        read_chapters(tmp_path, min_chars=10)


def test_combined_text_and_epub_roundtrip_preserve_chapter_order_and_end(tmp_path: Path) -> None:
    text = "Chapter 1. Dawn\n\nFirst paragraph.\n\nChapter 2. Sea\n\nLast note & <literal>.\n"
    p = tmp_path / "source.txt"
    p.write_text(text)
    chapters = read_chapters(p, min_chars=10)
    files = export_book(
        chapters,
        out_dir=tmp_path / "out",
        title="Book & Sea",
        language="en",
        report={"total": 2},
        glossary="source,target,type,note,confidence\n",
    )
    assert set(files) == {"txt", "epub", "zip"}
    with zipfile.ZipFile(files["epub"]) as z:
        assert z.namelist()[0] == "mimetype" and z.getinfo("mimetype").compress_type == zipfile.ZIP_STORED
        assert z.read("mimetype") == b"application/epub+zip"
        for name in z.namelist():
            if name.endswith((".xml", ".opf", ".xhtml")):
                ET.fromstring(z.read(name))
        assert (
            len(
                ET.fromstring(z.read("EPUB/package.opf")).findall(
                    "{http://www.idpf.org/2007/opf}spine/{http://www.idpf.org/2007/opf}itemref"
                )
            )
            == 2
        )
    imported = read_chapters(files["epub"], min_chars=10)
    assert list(imported) == [1, 2] and "Last note & <literal>." in imported[2]
    with zipfile.ZipFile(files["zip"]) as z:
        assert json.loads(z.read("report.json"))["total"] == 2
        assert z.read("chapters/0002.txt").decode() == chapters[2]
        assert not any("source" in n or "project.json" in n for n in z.namelist())
