"""Tests for agent.html_utils module."""
import tempfile
from pathlib import Path

from agent.html_utils import (
    InverseMapEntry,
    normalize_html,
    read_file,
    strip_html,
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
