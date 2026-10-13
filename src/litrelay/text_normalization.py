from __future__ import annotations

import html
import re
from html.parser import HTMLParser


def normalize_html_whitespace(content: str) -> str:
    parser = _WhitespaceNormalizer()
    parser.feed(content)
    parser.close()
    return "".join(parser.parts)


class _WhitespaceNormalizer(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.parts: list[str] = []
        self.preserve = 0

    def handle_starttag(self, tag, attrs) -> None:
        self.parts.append(self.get_starttag_text())
        self.preserve += int(tag in {"pre", "code", "script", "style"})

    def handle_startendtag(self, tag, attrs) -> None:
        self.parts.append(self.get_starttag_text())

    def handle_endtag(self, tag) -> None:
        self.parts.append(f"</{tag}>")
        if tag in {"pre", "code", "script", "style"}:
            self.preserve = max(0, self.preserve - 1)

    def handle_data(self, data) -> None:
        self.parts.append(data if self.preserve else re.sub(r"\s+", " ", data))

    def handle_entityref(self, name) -> None:
        self._entity(f"&{name};")

    def handle_charref(self, name) -> None:
        self._entity(f"&#{name};")

    def _entity(self, value: str) -> None:
        self.parts.append(" " if not self.preserve and html.unescape(value).isspace() else value)

    def handle_comment(self, data) -> None:
        self.parts.append(f"<!--{data}-->")

    def handle_decl(self, decl) -> None:
        self.parts.append(f"<!{decl}>")

    def handle_pi(self, data) -> None:
        self.parts.append(f"<?{data}>")
