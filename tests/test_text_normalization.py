from litrelay.text_normalization import normalize_html_whitespace


def test_explicit_breaks_and_preformatted_text_are_preserved() -> None:
    source = "<p>Первая\nфраза.<br>Вторая\tфраза.</p><pre>строка 1\n  строка 2</pre>"
    assert normalize_html_whitespace(source) == "<p>Первая фраза.<br>Вторая фраза.</p><pre>строка 1\n  строка 2</pre>"


def test_entities_and_inline_markup_preserve_words() -> None:
    source = "<p>Он&nbsp;сказал: &lt;текст&gt;, <b>сло</b>во.\nДальше.</p>"
    assert normalize_html_whitespace(source) == "<p>Он сказал: &lt;текст&gt;, <b>сло</b>во. Дальше.</p>"
