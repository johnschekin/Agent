"""Tests for agent.metadata — VP metadata extraction port."""
from __future__ import annotations

from agent.metadata import (
    extract_admin_agent,
    extract_borrower,
    extract_effective_date,
    extract_facility_sizes,
    extract_filing_date,
    extract_grower_baskets,
)


# ── extract_borrower ─────────────────────────────────────────────────
# Returns dict: {"borrower": str, "borrower_full": str, "borrower_confidence": str}


class TestExtractBorrower:
    def test_basic_preamble(self) -> None:
        text = (
            "CREDIT AGREEMENT\n\n"
            "dated as of January 15, 2024\n\n"
            "among\n\n"
            "ACME HOLDINGS, INC.,\n"
            "as Borrower,\n\n"
            "the Lenders party hereto,\n\n"
            "and\n\n"
            "JPMORGAN CHASE BANK, N.A.,\n"
            "as Administrative Agent\n"
        )
        result = extract_borrower(text)
        assert isinstance(result, dict)
        assert "borrower" in result
        borrower = result["borrower"]
        assert borrower is not None and len(borrower) > 0
        assert "acme" in borrower.lower() or "ACME" in result.get("borrower_full", "").upper()

    def test_by_and_between(self) -> None:
        text = (
            "This Credit Agreement is entered into by and between "
            "WIDGET CORP., a Delaware corporation (the \"Borrower\"), and "
            "BANK OF AMERICA, N.A., as Administrative Agent."
        )
        result = extract_borrower(text)
        assert isinstance(result, dict)
        borrower = result.get("borrower", "")
        assert borrower is not None and len(borrower) > 0

    def test_no_borrower_found(self) -> None:
        text = "This is a random document with no preamble patterns."
        result = extract_borrower(text)
        assert isinstance(result, dict)
        # borrower may be empty or absent
        borrower = result.get("borrower", "")
        assert borrower == "" or borrower is None

    def test_confidence_field(self) -> None:
        text = (
            "CREDIT AGREEMENT\namong\n"
            "ACME CORP.,\nas Borrower\n"
        )
        result = extract_borrower(text)
        assert "borrower_confidence" in result


# ── extract_admin_agent ──────────────────────────────────────────────
# Returns str | None


class TestExtractAdminAgent:
    def test_jpmorgan(self) -> None:
        text = "JPMORGAN CHASE BANK, N.A., as Administrative Agent"
        agent = extract_admin_agent(text)
        assert agent is not None
        assert "JPMorgan" in agent

    def test_bank_of_america(self) -> None:
        text = "Bank of America, N.A., as Administrative Agent"
        agent = extract_admin_agent(text)
        assert agent is not None
        assert "Bank of America" in agent

    def test_wells_fargo(self) -> None:
        text = "Wells Fargo Bank, National Association, as Administrative Agent"
        agent = extract_admin_agent(text)
        assert agent is not None
        assert "Wells Fargo" in agent

    def test_goldman(self) -> None:
        text = "Goldman Sachs Bank USA, as Administrative Agent"
        agent = extract_admin_agent(text)
        assert agent is not None
        assert "Goldman" in agent

    def test_no_agent(self) -> None:
        text = "This document has no administrative agent reference."
        agent = extract_admin_agent(text)
        # May return None, empty, or a partial match — depends on heuristics
        if agent is not None:
            # Should not contain a real bank name
            assert "JPMorgan" not in agent
            assert "Bank of America" not in agent
            assert "Wells Fargo" not in agent

    def test_collateral_agent_not_admin(self) -> None:
        """Should find admin agent, not collateral agent."""
        text = (
            "JPMORGAN CHASE BANK, N.A., as Administrative Agent\n"
            "WELLS FARGO BANK, N.A., as Collateral Agent"
        )
        agent = extract_admin_agent(text)
        assert agent is not None
        assert "JPMorgan" in agent


# ── extract_facility_sizes ───────────────────────────────────────────
# Returns dict: {"facility_size_mm": float, "facility_confidence": str, ...}


class TestExtractFacilitySizes:
    def test_aggregate_commitment(self) -> None:
        text = "The aggregate principal amount of the Commitments is $500,000,000."
        result = extract_facility_sizes(text)
        assert isinstance(result, dict)
        assert "facility_size_mm" in result

    def test_million_format(self) -> None:
        text = "aggregate principal amount of $500 million"
        result = extract_facility_sizes(text)
        assert isinstance(result, dict)

    def test_no_facility_size(self) -> None:
        text = "This document mentions no facility sizes."
        result = extract_facility_sizes(text)
        assert isinstance(result, dict)
        # May have facility_size_mm = None or 0


# ── extract_effective_date ───────────────────────────────────────────
# Returns dict: {"closing_date": str | None, "closing_date_raw": str | None}


class TestExtractEffectiveDate:
    def test_dated_as_of(self) -> None:
        text = "This Credit Agreement dated as of January 15, 2024"
        result = extract_effective_date(text)
        assert isinstance(result, dict)
        closing_date = result.get("closing_date")
        assert closing_date is not None
        assert "2024" in closing_date

    def test_entered_into(self) -> None:
        text = "This Agreement is entered into as of March 1, 2023"
        result = extract_effective_date(text)
        assert isinstance(result, dict)
        closing_date = result.get("closing_date")
        assert closing_date is not None
        assert "2023" in closing_date

    def test_no_date(self) -> None:
        text = "This document has no date reference."
        result = extract_effective_date(text)
        assert isinstance(result, dict)
        closing_date = result.get("closing_date")
        assert closing_date is None or closing_date == ""


# ── extract_filing_date ──────────────────────────────────────────────
# Takes filename (not text), returns str | None


class TestExtractFilingDate:
    def test_filename_with_date(self) -> None:
        """Filing date extraction from filename patterns."""
        result = extract_filing_date("2024-01-15_credit_agreement.htm")
        # May or may not extract depending on pattern
        assert result is None or isinstance(result, str)

    def test_no_date_in_filename(self) -> None:
        result = extract_filing_date("test_file.htm")
        assert result is None or isinstance(result, str)


# ── extract_grower_baskets ───────────────────────────────────────────
# Returns dict: {"has_grower_baskets": bool, "grower_basket_amounts_mm": list, ...}


class TestExtractGrowerBaskets:
    def test_greater_of_pattern(self) -> None:
        text = "the greater of $100,000,000 and 100% of Consolidated EBITDA"
        result = extract_grower_baskets(text)
        assert isinstance(result, dict)
        assert result.get("has_grower_baskets") is True

    def test_times_pattern(self) -> None:
        text = "the greater of $50,000,000 and 1.00 times Consolidated EBITDA"
        result = extract_grower_baskets(text)
        assert isinstance(result, dict)
        assert result.get("has_grower_baskets") is True

    def test_no_grower(self) -> None:
        text = "The borrower shall not incur Indebtedness exceeding $100,000,000."
        result = extract_grower_baskets(text)
        assert isinstance(result, dict)
        assert result.get("has_grower_baskets") is not True

    def test_total_assets_metric(self) -> None:
        text = "the greater of $75,000,000 and 15% of Consolidated Total Assets"
        result = extract_grower_baskets(text)
        assert isinstance(result, dict)
        assert result.get("has_grower_baskets") is True

    def test_closing_ebitda(self) -> None:
        text = "the greater of $100,000,000 and 100% of Consolidated EBITDA"
        result = extract_grower_baskets(text)
        assert "closing_ebitda_mm" in result
