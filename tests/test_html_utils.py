"""Tests for agent.html_utils module."""
import tempfile
from pathlib import Path

from agent.html_utils import (
    InverseMapEntry,
    normalize_html,
    normalize_quotes,
    read_file,
    strip_boilerplate,
    strip_html,
    strip_zero_width,
)


class TestStripHtml:
    def test_basic_extraction(self) -> None:
        html = "<p>Hello <b>world</b></p>"
        result = strip_html(html)
        assert "Hello" in result
        assert "world" in result
        assert "<" not in result

    def test_empty_input(self) -> None:
        assert strip_html("") == ""

    def test_preserves_newlines(self) -> None:
        html = "<p>First</p><p>Second</p>"
        result = strip_html(html, preserve_newlines=True)
        assert "\n" in result

    def test_no_newlines(self) -> None:
        html = "<p>First</p><p>Second</p>"
        result = strip_html(html, preserve_newlines=False)
        assert "First" in result and "Second" in result


class TestNormalizeHtml:
    def test_empty_input(self) -> None:
        text, inv_map = normalize_html("")
        assert text == ""
        assert inv_map == ()

    def test_produces_text_and_map(self) -> None:
        html = "<p>Hello world</p>"
        text, inv_map = normalize_html(html)
        assert "Hello world" in text
        assert len(inv_map) > 0

    def test_inverse_map_entries_valid(self) -> None:
        html = "<div>Some text here</div>"
        text, inv_map = normalize_html(html)
        for entry in inv_map:
            assert isinstance(entry, InverseMapEntry)
            assert entry.length > 0
            assert entry.normalized_start >= 0

    def test_whitespace_collapse(self) -> None:
        html = "<p>Hello     world</p>"
        text, _ = normalize_html(html)
        assert "Hello world" in text
        assert "     " not in text

    def test_block_newlines(self) -> None:
        html = "<p>First paragraph</p><p>Second paragraph</p>"
        text, _ = normalize_html(html)
        assert "First paragraph" in text
        assert "Second paragraph" in text


class TestInverseMapEntry:
    def test_negative_length_raises(self) -> None:
        try:
            InverseMapEntry(normalized_start=0, original_start=0, length=-1)
            assert False, "Should have raised ValueError"
        except ValueError:
            pass

    def test_frozen(self) -> None:
        entry = InverseMapEntry(normalized_start=0, original_start=10, length=5)
        try:
            entry.length = 10  # type: ignore[misc]
            assert False, "Should have raised"
        except AttributeError:
            pass


class TestReadFile:
    def test_utf8_file(self) -> None:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, encoding="utf-8") as f:
            f.write("Hello UTF-8 world")
            path = Path(f.name)
        result = read_file(path)
        assert result == "Hello UTF-8 world"
        path.unlink()

    def test_nonexistent_file(self) -> None:
        result = read_file(Path("/nonexistent/file.txt"))
        assert result == ""

    def test_min_size(self) -> None:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("small")
            path = Path(f.name)
        result = read_file(path, min_size=1000)
        assert result == ""
        path.unlink()


class TestStripZeroWidth:
    """Tests for zero-width character stripping (Imp 14)."""

    def test_removes_zwsp(self) -> None:
        assert strip_zero_width("Indebted\u200bness") == "Indebtedness"

    def test_removes_zwnj(self) -> None:
        assert strip_zero_width("some\u200ctext") == "sometext"

    def test_removes_bom(self) -> None:
        assert strip_zero_width("\ufeffHello") == "Hello"

    def test_removes_multiple(self) -> None:
        text = "\ufeff\u200bHello\u200c World\u200b"
        assert strip_zero_width(text) == "Hello World"

    def test_no_change_clean_text(self) -> None:
        assert strip_zero_width("Clean text") == "Clean text"

    def test_strip_html_applies_zero_width(self) -> None:
        """strip_html pipeline should remove zero-width chars."""
        html = "<p>Indebted\u200bness</p>"
        result = strip_html(html)
        assert "Indebtedness" in result
        assert "\u200b" not in result


class TestNormalizeQuotes:
    """Tests for straight→smart quote normalization (Imp 13)."""

    def test_basic_pair(self) -> None:
        assert normalize_quotes('"Term"') == "\u201cTerm\u201d"

    def test_multiple_pairs(self) -> None:
        text = '"First" and "Second"'
        result = normalize_quotes(text)
        assert result == "\u201cFirst\u201d and \u201cSecond\u201d"

    def test_preserves_smart_quotes(self) -> None:
        text = "\u201cAlready Smart\u201d"
        assert normalize_quotes(text) == text

    def test_no_quotes(self) -> None:
        assert normalize_quotes("No quotes here") == "No quotes here"

    def test_paragraph_spanning(self) -> None:
        """Quotes that span line breaks should still pair correctly."""
        text = '"This term\ncontinues here"'
        result = normalize_quotes(text)
        assert result.startswith("\u201c")
        assert result.endswith("\u201d")

    def test_strip_html_applies_quotes(self) -> None:
        """strip_html pipeline should normalize quotes."""
        html = '<p>"Borrower" means the party</p>'
        result = strip_html(html)
        assert "\u201c" in result
        assert "\u201d" in result


class TestStripBoilerplate:
    """Tests for EDGAR boilerplate removal (Imp 15)."""

    def test_removes_timestamp(self) -> None:
        text = "1/16/26, 1:44 PM\nActual content here"
        result = strip_boilerplate(text)
        assert "Actual content here" in result
        assert "1:44 PM" not in result

    def test_removes_sec_url(self) -> None:
        text = "https://www.sec.gov/Archives/edgar/data/12345/doc.htm\nContent"
        result = strip_boilerplate(text)
        assert "Content" in result
        assert "sec.gov" not in result

    def test_removes_page_marker(self) -> None:
        text = "Page 1 of 252\nContent"
        result = strip_boilerplate(text)
        assert "Content" in result
        assert "Page 1" not in result

    def test_removes_exhibit_header(self) -> None:
        text = "EX-10.1\nContent"
        result = strip_boilerplate(text)
        assert "Content" in result
        assert "EX-10" not in result

    def test_preserves_inline_exhibit_reference(self) -> None:
        """Inline references to exhibits should not be stripped."""
        text = "as set forth in Exhibit 10.1 attached hereto"
        result = strip_boilerplate(text)
        assert "Exhibit 10.1" in result

    def test_preserves_normal_content(self) -> None:
        text = "The Borrower shall not create any Indebtedness."
        assert strip_boilerplate(text) == text
