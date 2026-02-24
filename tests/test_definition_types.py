"""Tests for definition type classifier utilities."""

from agent.definition_types import classify_definition_records, classify_definition_text


def test_classify_direct_definition() -> None:
    result = classify_definition_text('"Indebtedness" means obligations for borrowed money.')
    assert result.primary_type in {"DIRECT", "FORMULAIC", "INCORPORATION", "ENUMERATIVE", "TABLE_REGULATORY"}
    assert "DIRECT" in result.detected_types
    assert 0.0 <= result.confidence <= 1.0


def test_classify_formulaic_hybrid() -> None:
    text = (
        '"Consolidated EBITDA" means the sum of Net Income plus interest expense '
        'and the greater of clause (a) and clause (b).'
    )
    result = classify_definition_text(text)
    assert "FORMULAIC" in result.detected_types
    assert "ENUMERATIVE" in result.detected_types or "HYBRID" in result.detected_types


def test_classify_definition_records_enrichment() -> None:
    enriched = classify_definition_records(
        [
            {"term": "X", "definition_text": '"X" means the sum of A plus B.'},
            {"term": "Y", "definition_text": '"Y" has the meaning set forth in Section 1.01.'},
        ]
    )
    assert len(enriched) == 2
    for row in enriched:
        assert "definition_type" in row
        assert "definition_types" in row
        assert "type_confidence" in row
        assert isinstance(row["definition_types"], list)

