from pathlib import Path

from litrelay.source_text_split import split_numbered_chinese_txt


def test_split_numbered_chinese_txt_writes_zero_padded_chapters(tmp_path: Path) -> None:
    source = tmp_path / "book.txt"
    out_dir = tmp_path / "chapters"
    source.write_text(
        "header\n\n第1章 多元宇宙\n正文一\n\n第2章 虚空中的灵魂\n正文二\n",
        encoding="utf-8",
    )

    summary = split_numbered_chinese_txt(source, out_dir)

    assert summary.chapter_count == 2
    assert (out_dir / "0001.txt").read_text(encoding="utf-8") == "第1章 多元宇宙\n正文一"
    assert (out_dir / "0002.txt").read_text(encoding="utf-8") == "第2章 虚空中的灵魂\n正文二"
