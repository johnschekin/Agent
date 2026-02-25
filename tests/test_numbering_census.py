"""Tests for numbering_census.py classification logic."""
from scripts.numbering_census import (
    classify_article_format,
    classify_section_depth,
    detect_anomalies,
    detect_zero_padding,
)


class TestClassifyArticleFormat:
    def test_arabic(self) -> None:
        assert classify_article_format(["1.01", "1.02", "2.01"]) == "ARABIC"

    def test_section_only(self) -> None:
        assert classify_article_format([]) == "SECTION_ONLY"

    def test_roman(self) -> None:
        assert classify_article_format(["I.01", "II.02", "III.01"]) == "ROMAN"

    def test_hybrid(self) -> None:
        assert classify_article_format(["I.01", "2.01"]) == "HYBRID"


class TestClassifySectionDepth:
    def test_two_level(self) -> None:
        assert classify_section_depth(["7.01", "7.02", "8.01"]) == 2

    def test_three_level(self) -> None:
        assert classify_section_depth(["7.01", "7.02.01", "8.01"]) == 3


class TestDetectZeroPadding:
    def test_padded(self) -> None:
        assert detect_zero_padding(["7.01", "7.02", "7.03"]) is True

    def test_not_padded(self) -> None:
        assert detect_zero_padding(["7.1", "7.2", "7.3"]) is False

    def test_mixed(self) -> None:
        # Majority padded
        assert detect_zero_padding(["7.01", "7.02", "7.3"]) is True


class TestDetectAnomalies:
    def test_no_anomalies(self) -> None:
        assert detect_anomalies(["1.01", "1.02", "2.01", "2.02"]) == []

    def test_empty(self) -> None:
        assert detect_anomalies([]) == []

    def test_mixed_padding_anomaly(self) -> None:
        nums = ["1.01", "1.02", "1.03", "2.1", "2.2", "2.3"]
        anomalies = detect_anomalies(nums)
        assert "mixed_zero_padding" in anomalies
