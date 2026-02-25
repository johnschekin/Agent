"""Tests for section_headers_survey.py classification logic."""
from scripts.section_headers_survey import classify_heading


class TestClassifyHeading:
    def test_covenant(self) -> None:
        assert classify_heading("Indebtedness") == "covenant"

    def test_covenant_liens(self) -> None:
        assert classify_heading("Liens") == "covenant"

    def test_definition(self) -> None:
        assert classify_heading("Defined Terms") == "definition"

    def test_reserved(self) -> None:
        assert classify_heading("[Reserved]") == "reserved"

    def test_intentionally_omitted(self) -> None:
        assert classify_heading("[Intentionally Omitted]") == "reserved"

    def test_financial(self) -> None:
        assert classify_heading("Financial Covenants") == "financial"

    def test_event_of_default(self) -> None:
        assert classify_heading("Events of Default") == "event_of_default"

    def test_representation(self) -> None:
        assert classify_heading("Representations and Warranties") == "representation"

    def test_facility(self) -> None:
        assert classify_heading("Commitments and Credit Extensions") == "facility"

    def test_payment(self) -> None:
        assert classify_heading("Mandatory Prepayments") == "payment"

    def test_other(self) -> None:
        assert classify_heading("Miscellaneous") == "other"

    def test_case_insensitive(self) -> None:
        assert classify_heading("INDEBTEDNESS") == "covenant"
        assert classify_heading("DEFINED TERMS") == "definition"
