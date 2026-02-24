"""Native metadata extraction — fully typed, pyright-strict clean.

Extracts per-CA metadata from normalized credit agreement text:
    1. Borrower name + confidence (extract_borrower)
    2. Administrative Agent (extract_admin_agent)
    3. Effective/Closing date (extract_effective_date)
    4. Filing date from EDGAR accession number (extract_filing_date)
    5. Facility size (extract_facility_sizes)
    6. Grower baskets + closing EBITDA (extract_grower_baskets)

All regex patterns are preserved verbatim from the original TI extractor.

Ported from vantage_platform l0/_metadata_impl.py — full version.
No VP imports — completely self-contained.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Suffixes to strip for normalized borrower name
CORP_SUFFIXES: re.Pattern[str] = re.compile(
    r'(?:^|(?<=\s)|(?<=,))\s*,?\s*'
    r'(?:'
    r'Inc\.?|LLC|L\.L\.C\.|Corp\.?|Corporation|'
    r'Ltd\.?|Limited|L\.P\.|LP|plc|PLC|'
    r'N\.V\.|S\.A\.|GmbH|AG|'
    r'Co\.|Company|Holdings?|Group'
    r')'
    r'(?:\s*,)?'
    r'\s*$',
    re.IGNORECASE,
)

# Entity type markers that appear after "a [state]" in preamble
ENTITY_TYPES: re.Pattern[str] = re.compile(
    r'\b(?:corporation|limited liability company|limited partnership|'
    r'company|partnership|gesellschaft|public limited company)\b',
    re.IGNORECASE,
)

# US state names for "a [State] [entity_type]" detection
US_STATES: str = (
    'Alabama|Alaska|Arizona|Arkansas|California|Colorado|Connecticut|'
    'Delaware|Florida|Georgia|Hawaii|Idaho|Illinois|Indiana|Iowa|Kansas|'
    'Kentucky|Louisiana|Maine|Maryland|Massachusetts|Michigan|Minnesota|'
    'Mississippi|Missouri|Montana|Nebraska|Nevada|New Hampshire|New Jersey|'
    'New Mexico|New York|North Carolina|North Dakota|Ohio|Oklahoma|Oregon|'
    'Pennsylvania|Rhode Island|South Carolina|South Dakota|Tennessee|Texas|'
    'Utah|Vermont|Virginia|Washington|West Virginia|Wisconsin|Wyoming|'
    'District of Columbia'
)

# Noise fragments that indicate a candidate borrower name is garbage
BORROWER_NOISE_FRAGMENTS: list[str] = [
    'subsidiary borrower', 'signature page', 'named herein',
    'the foregoing', 'listed as', 'the subsidiaries of',
    'the subsidiary', 'other borrower', 'each of the',
    'exhibit', 'credit agreement', 'loan agreement',
    'hereto', 'table of contents', 'execution version',
    'designation of', 'subsidiaries of', 'party hereto',
    'lenders party', 'agents party',
]

# Role qualifier that appears before "Borrower" in the preamble
BORROWER_ROLE: str = (
    r'(?:(?:Lead|Parent|Initial|Co-?|Administrative|Escrow|U\.S\.|U\.K\.)\s+)?Borrowers?'
)

# Corp suffix pattern for fallback extraction
CORP_SUFFIX_PAT: str = (
    r'(?:Inc\.?|LLC|L\.L\.C\.|Corp\.?|Corporation|Ltd\.?|Limited|'
    r'L\.P\.|LP|plc|PLC|Co\.?|Company|Incorporated|Fund)'
)

# Lender/agent words to exclude from positional extraction
LENDER_AGENT_WORDS: set[str] = {
    'bank', 'trust', 'securities', 'capital', 'financial',
    'morgan', 'barclays', 'citibank', 'wells fargo',
    'administrative agent', 'collateral agent', 'jpmorgan',
    'goldman sachs', 'credit suisse', 'bofa', 'bnp',
}

# Month name -> 2-digit month number
MONTH_MAP: dict[str, str] = {
    'january': '01', 'february': '02', 'march': '03', 'april': '04',
    'may': '05', 'june': '06', 'july': '07', 'august': '08',
    'september': '09', 'october': '10', 'november': '11', 'december': '12',
}

# Context exclusion patterns for grower basket false-positive filtering
_CONTEXT_EXCLUDE: list[re.Pattern[str]] = [
    re.compile(r'(?:add[- ]?back|added\s+back)', re.I),
    re.compile(r'(?:monitoring|consulting|management)\s.*?fees?', re.I),
    re.compile(r'["\u201c][\w\s]+["\u201d]\s+(?:means|shall\s+mean)', re.I),
    re.compile(r'(?:Increased?|Incremental)\s+(?:Commitments?|Facility)', re.I),
    re.compile(r'(?:commitment|closing|arrangement)\s+fees?', re.I),
    re.compile(r'(?:Aggregate|Total)\s+(?:Secured\s+)?(?:Debt|Indebtedness)', re.I),
    re.compile(r'(?:Maximum|Max)\s+(?:Secured\s+)?(?:Leverage|Debt)', re.I),
    re.compile(
        r'Senior\s+Secured\s+(?:First\s+Lien\s+)?(?:Net\s+)?Leverage\s+Ratio',
        re.I,
    ),
]

# Known agent normalizations (uppercase key -> canonical form)
KNOWN_AGENTS: dict[str, str] = {
    'JPMORGAN CHASE BANK, N.A.': 'JPMorgan Chase Bank, N.A.',
    'JPMORGAN CHASE BANK N.A.': 'JPMorgan Chase Bank, N.A.',
    'JPMORGAN CHASE BANK': 'JPMorgan Chase Bank, N.A.',
    'JP MORGAN CHASE BANK, N.A.': 'JPMorgan Chase Bank, N.A.',
    'BANK OF AMERICA, N.A.': 'Bank of America, N.A.',
    'BANK OF AMERICA N.A.': 'Bank of America, N.A.',
    'WELLS FARGO BANK, NATIONAL ASSOCIATION': 'Wells Fargo Bank, National Association',
    'WELLS FARGO BANK NATIONAL ASSOCIATION': 'Wells Fargo Bank, National Association',
    'CITIBANK, N.A.': 'Citibank, N.A.',
    'CITIBANK N.A.': 'Citibank, N.A.',
    'GOLDMAN SACHS BANK USA': 'Goldman Sachs Bank USA',
    'MORGAN STANLEY SENIOR FUNDING, INC.': 'Morgan Stanley Senior Funding, Inc.',
    'MORGAN STANLEY SENIOR FUNDING INC.': 'Morgan Stanley Senior Funding, Inc.',
    'DEUTSCHE BANK AG NEW YORK BRANCH': 'Deutsche Bank AG New York Branch',
    'DEUTSCHE BANK SECURITIES, INC.': 'Deutsche Bank Securities, Inc.',
    'BARCLAYS BANK PLC': 'Barclays Bank PLC',
    'CREDIT SUISSE AG, CAYMAN ISLANDS BRANCH': 'Credit Suisse AG, Cayman Islands Branch',
    'CREDIT SUISSE LOAN FUNDING LLC': 'Credit Suisse Loan Funding LLC',
    'CREDIT SUISSE AG': 'Credit Suisse AG',
    'UBS AG, STAMFORD BRANCH': 'UBS AG, Stamford Branch',
    'ROYAL BANK OF CANADA': 'Royal Bank of Canada',
    'GENERAL ELECTRIC CAPITAL CORPORATION': 'General Electric Capital Corporation',
    'MACQUARIE CAPITAL FUNDING LLC': 'Macquarie Capital Funding LLC',
    'BMO HARRIS BANK N.A.': 'BMO Harris Bank N.A.',
    'PNC BANK, NATIONAL ASSOCIATION': 'PNC Bank, National Association',
    'SUNTRUST BANK': 'SunTrust Bank',
    'REGIONS BANK': 'Regions Bank',
    'TRUIST BANK': 'Truist Bank',
    'FIFTH THIRD BANK': 'Fifth Third Bank',
    'FIFTH THIRD BANK, NATIONAL ASSOCIATION': 'Fifth Third Bank, National Association',
    'CITIZENS BANK, N.A.': 'Citizens Bank, N.A.',
    'CITIZENS BANK N.A.': 'Citizens Bank, N.A.',
    'KKR CAPITAL MARKETS LLC': 'KKR Capital Markets LLC',
    'JEFFERIES FINANCE LLC': 'Jefferies Finance LLC',
    'NOMURA CORPORATE FUNDING AMERICAS, LLC': 'Nomura Corporate Funding Americas, LLC',
    'MUFG UNION BANK, N.A.': 'MUFG Union Bank, N.A.',
    'KEYBANK NATIONAL ASSOCIATION': 'KeyBank National Association',
    'U.S. BANK NATIONAL ASSOCIATION': 'U.S. Bank National Association',
    'TD BANK, N.A.': 'TD Bank, N.A.',
    'ALLY BANK': 'Ally Bank',
    'ARES CAPITAL CORPORATION': 'Ares Capital Corporation',
    'OWL ROCK CAPITAL CORPORATION': 'Owl Rock Capital Corporation',
    'CORTLAND CAPITAL MARKET SERVICES LLC': 'Cortland Capital Market Services LLC',
    'WILMINGTON TRUST, NATIONAL ASSOCIATION': 'Wilmington Trust, National Association',
    'WILMINGTON SAVINGS FUND SOCIETY, FSB': 'Wilmington Savings Fund Society, FSB',
    'GLAS TRUST COMPANY LLC': 'GLAS Trust Company LLC',
    'ANKURA TRUST COMPANY, LLC': 'Ankura Trust Company, LLC',
    'HSBC BANK USA, NATIONAL ASSOCIATION': 'HSBC Bank USA, National Association',
    'HSBC BANK USA, N.A.': 'HSBC Bank USA, N.A.',
    'HSBC BANK USA N.A.': 'HSBC Bank USA, N.A.',
    'COÖPERATIEVE RABOBANK U.A., NEW YORK BRANCH': 'Cooperatieve Rabobank U.A., New York Branch',
    'COÖPERATIEVE RABOBANK U.A.': 'Cooperatieve Rabobank U.A.',
    'MIZUHO BANK, LTD.': 'Mizuho Bank, Ltd.',
    'SUMITOMO MITSUI BANKING CORPORATION': 'Sumitomo Mitsui Banking Corporation',
    'MUFG BANK, LTD.': 'MUFG Bank, Ltd.',
    'CRÉDIT AGRICOLE CORPORATE AND INVESTMENT BANK': 'Credit Agricole Corporate and Investment Bank',
    'NATIXIS, NEW YORK BRANCH': 'Natixis, New York Branch',
    'BNP PARIBAS': 'BNP Paribas',
    'SOCIETE GENERALE': 'Societe Generale',
    'ING CAPITAL LLC': 'ING Capital LLC',
}

# Abbreviations preserved as-is during title casing
_TITLE_ABBREVIATIONS: set[str] = {
    'LLC', 'LP', 'INC', 'CORP', 'LTD', 'PLC', 'NA', 'N.A.',
    'USA', 'US', 'II', 'III', 'IV', 'VI', 'VII', 'VIII',
    'L.P.', 'L.L.C.', 'N.V.', 'S.A.', 'FSB',
}

# Known company name abbreviations that stay uppercase
_COMPANY_ABBREVS: set[str] = {
    'AES', 'ADT', 'AT&T', 'IBM', 'HP', 'GE', 'GM', 'AMD', 'BMW',
    'CVS', 'UPS', 'FMC', 'ITT', 'PPG', 'RSC', 'EMC', 'AIG', 'BHP',
    'CIT', 'CSX', 'NCR', 'TRW', 'MGM', 'CBS', 'AOL', 'HSN', 'QVC',
    'CDW', 'DSW', 'JBS', 'BWX', 'CNX', 'HCA', 'SBA', 'KBR', 'ABB',
}

# Grower basket metric regexes
_EBITDA_METRICS: str = (
    r'(?:Consolidated\s+)?(?:Adjusted\s+)?(?:Pro\s+Forma\s+)?EBITDA(?:X)?'
    r'|Relevant\s+EBITDA'
    r'|LTM\s+EBITDA'
    r'|(?:Annualized|Run[- ]Rate|TTM)\s+EBITDA'
    r'|Credit\s+Agreement\s+EBITDA'
)

_ASSET_METRICS: str = (
    r'(?:Consolidated\s+)?Total\s+Assets'
    r'|(?:Consolidated\s+)?Net\s+(?:Tangible\s+)?Assets'
    r'|Total\s+Consolidated\s+Assets'
    r'|(?:Consolidated\s+)?(?:Shareholders?\s+|Stockholders?\s+)?Equity'
    r'|(?:Consolidated\s+)?Net\s+(?:Income|Revenue)'
    r'|(?:Consolidated\s+)?(?:Total\s+)?(?:Tangible\s+)?Assets'
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _is_noise(name: str) -> bool:
    """Check if a candidate borrower name is noise."""
    nl: str = name.lower()
    return (
        any(frag in nl for frag in BORROWER_NOISE_FRAGMENTS)
        or len(name) < 4
        or len(name) > 200
    )


def _clean_entity_name(name: str) -> str:
    """Remove role qualifiers embedded in multi-entity names."""
    # Strip parentheticals like "(BRY)", "(as successor...)", "(f/k/a ...)"
    name = re.sub(r'\s*\([^)]*\)', '', name).strip()
    # If name contains ", as " (a role marker), take only part before
    role_split: list[str] = re.split(
        r'\s*,?\s+as\s+(?:the\s+)?'
        r'(?:Holdings|Parent|Guarantor|Agent|Lender|Company|Issuer)',
        name, flags=re.IGNORECASE,
    )
    if role_split:
        name = role_split[0].strip().rstrip(',').strip()
    # Remove trailing ", the Borrowers/Lenders referred to herein" etc.
    name = re.sub(
        r'\s*,\s+the\s+(?:Borrower|Lender|Guarantor)s?\s+.*$',
        '', name, flags=re.IGNORECASE,
    )
    # Remove leading "among" / "between" / "by and among"
    name = re.sub(
        r'^(?:among|between|by\s+and\s+among|by|and|the)\s+',
        '', name, flags=re.IGNORECASE,
    ).strip()
    # Strip trailing ", a [State] [entity_type]"
    name = re.sub(
        r'\s*,\s+a\s+(?:' + US_STATES + r')\s+'
        r'(?:corporation|limited\s+liability\s+company|limited\s+partnership|'
        r'company|partnership|public\s+limited\s+company)\s*$',
        '', name, flags=re.IGNORECASE,
    ).strip()
    # Also handle bare ", a State" at end (without entity type)
    name = re.sub(
        r'\s*,\s+a\s+(?:' + US_STATES + r')\s*$',
        '', name, flags=re.IGNORECASE,
    ).strip()
    return name.strip().rstrip(',').strip()


def _normalize_borrower_name(full_name: str) -> str:
    """Strip corporate suffixes for normalized name."""
    name: str = full_name.strip().rstrip(',').strip()
    for _ in range(3):
        prev: str = name
        name = CORP_SUFFIXES.sub('', name).strip().rstrip(',').strip()
        if name == prev:
            break
    return name


def _title_case_name(name: str) -> str:
    """Convert ALL CAPS name to Title Case, handling special cases."""
    words: list[str] = name.split()
    result: list[str] = []
    for w in words:
        w_upper: str = w.upper().rstrip(',').rstrip('.')
        if w_upper in _TITLE_ABBREVIATIONS or w in _TITLE_ABBREVIATIONS:
            result.append(
                w.upper()
                if w.upper() in {'LLC', 'LP', 'INC', 'PLC', 'USA', 'US'}
                else w
            )
        elif w_upper in _COMPANY_ABBREVS:
            suffix: str = w[len(w_upper):]
            result.append(w_upper + suffix)
        elif w.endswith(','):
            inner: str = w[:-1]
            if inner.upper() in _TITLE_ABBREVIATIONS or inner.upper() in _COMPANY_ABBREVS:
                result.append(inner.upper() + ',')
            else:
                result.append(inner.title() + ',')
        elif w.endswith('.'):
            inner = w[:-1]
            if inner.upper() in _TITLE_ABBREVIATIONS or inner.upper() in _COMPANY_ABBREVS:
                result.append(inner.upper() + '.')
            else:
                result.append(inner.title() + '.')
        else:
            result.append(w.title())
    return ' '.join(result)


def _normalize_agent_name(name: str) -> str:
    """Normalize agent name to consistent casing and format."""
    upper_name: str = name.upper().strip()
    for key, val in KNOWN_AGENTS.items():
        if upper_name == key or upper_name.startswith(key):
            return val
    for key, val in KNOWN_AGENTS.items():
        if key in upper_name:
            return val
    if name == name.upper() and len(name) > 5:
        return _title_case_name(name)
    return name


def _parse_dollar_amount(raw: str) -> float | None:
    """Parse a dollar amount string to millions."""
    raw = raw.strip().replace(',', '').replace(' ', '')

    multiplier: float | None = 1.0
    if 'billion' in raw.lower():
        multiplier = 1000.0
        raw = re.sub(r'(?i)\s*billion.*', '', raw)
    elif 'million' in raw.lower():
        multiplier = 1.0
        raw = re.sub(r'(?i)\s*million.*', '', raw)
    else:
        multiplier = None

    num_match: re.Match[str] | None = re.search(r'([0-9]+\.?[0-9]*)', raw)
    if not num_match:
        return None

    value: float = float(num_match.group(1))

    if multiplier is not None:
        return value * multiplier
    else:
        if value >= 1_000_000:
            return value / 1_000_000
        elif value >= 1_000:
            return value / 1_000
        else:
            return value


def _parse_date(date_str: str) -> str | None:
    """Parse a natural language date to YYYY-MM-DD format."""
    date_str = date_str.strip()

    # Pattern 1: "Month DD, YYYY"
    m: re.Match[str] | None = re.match(
        r'(\w+)\s+(\d{1,2})\s*,?\s*(\d{4})', date_str,
    )
    if m:
        month_name: str = m.group(1).lower()
        day: int = int(m.group(2))
        year: int = int(m.group(3))
        month: str | None = MONTH_MAP.get(month_name)
        if month and 1 <= day <= 31 and 1990 <= year <= 2030:
            return f"{year}-{month}-{day:02d}"

    # Pattern 2: "DD Month YYYY"
    m = re.match(r'(\d{1,2})\s+(\w+)\s*,?\s*(\d{4})', date_str)
    if m:
        day = int(m.group(1))
        month_name = m.group(2).lower()
        year = int(m.group(3))
        month = MONTH_MAP.get(month_name)
        if month and 1 <= day <= 31 and 1990 <= year <= 2030:
            return f"{year}-{month}-{day:02d}"

    return None


def _is_false_positive_context(text: str, match_start: int) -> bool:
    """Check if 300 chars before a 'greater of' match suggest a false positive."""
    prefix: str = text[max(0, match_start - 300):match_start]
    return any(pat.search(prefix) for pat in _CONTEXT_EXCLUDE)


def _round_to_5(x: float) -> float:
    """Round to nearest $5M for clustering."""
    return round(x / 5) * 5


# ---------------------------------------------------------------------------
# Facility size regex patterns
# ---------------------------------------------------------------------------

# Tier 1: Aggregate commitment / principal amount (highest confidence)
_FACILITY_AGGREGATE: re.Pattern[str] = re.compile(
    r'(?:aggregate|total)\s+'
    r'(?:principal\s+)?'
    r'(?:commitments?|amount|facility)\s+'
    r'(?:of\s+)?(?:up\s+to\s+)?'
    r'\$\s*([0-9][0-9,. ]*(?:\s*(?:million|billion))?)',
    re.IGNORECASE,
)

# Tier 2: Tranche-level -- "$X Term Loan" / "$X Revolving Credit"
_FACILITY_TRANCHE: re.Pattern[str] = re.compile(
    r'\$\s*([0-9][0-9,. ]*(?:\s*(?:million|billion))?)\s+'
    r'(?:'
    r'Term\s+Loan(?:\s+[A-Z])?\s+(?:Facility|Commitment)'
    r'|Term\s+Loan(?:\s+[A-Z])?(?:\s|,|$)'
    r'|Revolving\s+(?:Credit\s+)?(?:Facility|Commitment|Loan)'
    r'|Senior\s+Secured\s+(?:Term|Revolving|Credit)'
    r'|(?:First|Second)\s+Lien\s+(?:Term|Revolving)'
    r'|(?:Delayed\s+Draw\s+)?Term\s+Loan'
    r'|(?:Initial\s+)?Term\s+(?:Facility|Commitment)'
    r')',
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Public API -- 6 extraction functions
# ---------------------------------------------------------------------------


def extract_facility_sizes(text: str) -> dict[str, Any]:
    """Extract facility size(s) from the title page and recitals.

    Searches the first 15K characters (title page + preamble) where
    facility amounts are typically stated.

    Returns dict with:
        facility_size_mm: Total facility size in millions (float or None)
        facility_confidence: "high", "medium", or "low"
        facility_tranches: List of (amount_mm, label) tuples
    """
    preamble: str = text[:15000]

    tranches: list[tuple[float, str]] = []

    # Tier 1: Aggregate commitment
    aggregate_amount: float | None = None
    for m in _FACILITY_AGGREGATE.finditer(preamble):
        amt = _parse_dollar_amount(m.group(1))
        if amt is not None and 1.0 <= amt <= 100_000.0:
            aggregate_amount = amt
            break  # first match is typically the right one

    # Tier 2: Tranche-level amounts
    seen_amounts: set[float] = set()
    for m in _FACILITY_TRANCHE.finditer(preamble):
        amt = _parse_dollar_amount(m.group(1))
        if amt is not None and 1.0 <= amt <= 100_000.0 and amt not in seen_amounts:
            seen_amounts.add(amt)
            # Extract label from the matched text after the amount
            label = m.group(0).split(m.group(1), 1)[-1].strip()
            tranches.append((amt, label))

    # Determine facility size and confidence
    tranche_total = sum(t[0] for t in tranches) if tranches else 0.0

    if aggregate_amount is not None and tranches:
        # Both sources: high confidence (cross-validated)
        return {
            "facility_size_mm": aggregate_amount,
            "facility_confidence": "high",
            "facility_tranches": tranches,
        }
    elif aggregate_amount is not None:
        # Aggregate only: medium confidence
        return {
            "facility_size_mm": aggregate_amount,
            "facility_confidence": "medium",
            "facility_tranches": [],
        }
    elif len(tranches) >= 2:
        # 2+ tranches: medium confidence (sum of tranches)
        return {
            "facility_size_mm": round(tranche_total, 2),
            "facility_confidence": "medium",
            "facility_tranches": tranches,
        }
    elif len(tranches) == 1:
        # Single tranche: low confidence
        return {
            "facility_size_mm": tranches[0][0],
            "facility_confidence": "low",
            "facility_tranches": tranches,
        }
    else:
        return {
            "facility_size_mm": None,
            "facility_confidence": "none",
            "facility_tranches": [],
        }


def extract_borrower(
    text: str,
    filename: str | None = None,
) -> dict[str, Any]:
    """Extract borrower name(s) from the title page / preamble.

    Returns dict with 'borrower', 'borrower_full', 'borrower_confidence',
    optionally 'co_borrowers'.
    """
    preamble: str = text[:15000]
    borrowers: list[str] = []
    borrowers_full: list[str] = []

    preamble_flat: str = re.sub(r'\s+', ' ', preamble)
    preamble_no_parens: str = re.sub(r'\s*\([^)]*\)', '', preamble_flat)

    # Pass A: Direct capture -- text between delimiter and ", as [the] Borrower"
    pat_direct: re.Pattern[str] = re.compile(
        r'(?:among\s+|between\s+|by\s+and\s+among\s+)'
        r'([A-Z][\w,.\'\-& /]+?)'
        r'\s*,?\s+[Aa]s\s+(?:the\s+)?' + BORROWER_ROLE + r'\b',
        re.UNICODE,
    )
    for source in [preamble_flat, preamble_no_parens]:
        for m in pat_direct.finditer(source):
            name: str = _clean_entity_name(m.group(1))
            if not _is_noise(name):
                borrowers.append(name)
        if borrowers:
            break

    # Pass A1b: Without requiring "among" prefix
    if not borrowers:
        pat_noprefix: re.Pattern[str] = re.compile(
            r'([A-Z][\w,.\'\-& ]{2,80}?'
            r'(?:Inc\.?|LLC|L\.L\.C\.|Corp\.?|Corporation|Ltd\.?|Limited|'
            r'L\.P\.|LP|plc|PLC|Co\.?|Incorporated))'
            r'\s*,?\s+[Aa]s\s+(?:the\s+)?(?:a\s+)?' + BORROWER_ROLE + r'\b',
            re.UNICODE | re.IGNORECASE,
        )
        for source in [preamble_no_parens, preamble_flat]:
            for m in pat_noprefix.finditer(source):
                name = _clean_entity_name(m.group(1))
                if not _is_noise(name):
                    borrowers.append(name)
            if borrowers:
                break

    # Pass A2: Simpler -- "[Name] Corp, as [the] Borrower"
    if not borrowers:
        pat_simple: re.Pattern[str] = re.compile(
            r'([A-Z][\w.\'\-& ]{2,80}?'
            r'(?:Inc\.?|LLC|L\.L\.C\.|Corp\.?|Corporation|Ltd\.?|Limited|'
            r'L\.P\.|LP|plc|PLC|Co\.))'
            r'\s*,?\s+as\s+(?:the\s+)?' + BORROWER_ROLE + r'\b',
            re.UNICODE | re.IGNORECASE,
        )
        for m in pat_simple.finditer(preamble_flat):
            name = _clean_entity_name(m.group(1))
            if not _is_noise(name):
                borrowers.append(name)

    # Pass A3: Compound roles -- "as Parent, a Borrower"
    if not borrowers:
        pat_compound: re.Pattern[str] = re.compile(
            r'([A-Z][\w.\'\-& ]{2,80}?'
            r'(?:Inc\.?|LLC|L\.L\.C\.|Corp\.?|Corporation|Ltd\.?|Limited|'
            r'L\.P\.|LP|plc|PLC|Co\.))'
            r'\s*,?\s+as\s+(?:the\s+)?(?:Parent|Company|Holdings|Intermediate Holdings)'
            r'[\s,]+(?:and\s+)?(?:a\s+)?Borrower\b',
            re.UNICODE | re.IGNORECASE,
        )
        for m in pat_compound.finditer(preamble_flat):
            name = _clean_entity_name(m.group(1))
            if not _is_noise(name):
                borrowers.append(name)

    # Pass A4: "as the Company" pattern (common in IG revolvers)
    if not borrowers:
        pat_company: re.Pattern[str] = re.compile(
            r'(?:among\s+|between\s+|by\s+and\s+among\s+)'
            r'([A-Z][\w,.\'\-& /]+?)'
            r'\s*,?\s+as\s+(?:the\s+)?Company\b',
            re.UNICODE,
        )
        for source in [preamble_no_parens, preamble_flat]:
            for m in pat_company.finditer(source):
                name = _clean_entity_name(m.group(1))
                if not _is_noise(name):
                    borrowers.append(name)
            if borrowers:
                break
        if not borrowers:
            pat_company2: re.Pattern[str] = re.compile(
                r'([A-Z][\w.\'\-& ]{2,80}?'
                r'(?:Inc\.?|LLC|L\.L\.C\.|Corp\.?|Corporation|Ltd\.?|Limited|'
                r'L\.P\.|LP|plc|PLC|Co\.))'
                r'\s*,?\s+as\s+(?:the\s+)?Company\b',
                re.UNICODE | re.IGNORECASE,
            )
            for m in pat_company2.finditer(preamble_flat):
                name = _clean_entity_name(m.group(1))
                if not _is_noise(name):
                    borrowers.append(name)

    # Pass B: Newline-based backward search
    if not borrowers:
        pat_marker: re.Pattern[str] = re.compile(
            r',?\s+as\s+(?:the\s+)?' + BORROWER_ROLE + r'(?:s)?\b',
            re.IGNORECASE,
        )
        for m in pat_marker.finditer(preamble):
            prefix: str = preamble[:m.start()]
            lines: list[str] = [ln.strip() for ln in prefix.split('\n') if ln.strip()]
            if not lines:
                continue
            last_line: str = lines[-1]
            name_match: re.Match[str] | None = re.search(
                r'(?:among|between|by and among|and|by)\s+'
                r'([A-Z][\w,.\'\-& ]+?)$',
                last_line,
                re.IGNORECASE,
            )
            if name_match:
                name = _clean_entity_name(name_match.group(1))
            else:
                name = last_line.rstrip(',').strip()
                name = _clean_entity_name(name)
            if not _is_noise(name):
                borrowers.append(name)

    # Pattern 2: "is entered into ... among [Name], a [state] [entity_type]"
    pat_entered: re.Pattern[str] = re.compile(
        r'(?:is entered into|is made and entered|is dated)\s+.*?'
        r'(?:among|between|by and among)\s+'
        r'([A-Z][A-Za-z0-9,.\'\-& ]+?)\s*,\s+'
        r'a\s+(?:' + US_STATES + r')\s+',
        re.IGNORECASE | re.DOTALL,
    )
    for m in pat_entered.finditer(preamble):
        name = m.group(1).strip()
        if 3 < len(name) < 200:
            borrowers.append(name)

    # Pattern 3: "This Credit Agreement ... among [Name],"
    pat_this: re.Pattern[str] = re.compile(
        r'This\s+.*?(?:Credit Agreement|Loan Agreement|Financing Agreement)\s*.*?'
        r'(?:among|between|by and among)\s+'
        r'([A-Z][A-Za-z0-9,.\'\-& ]+?)\s*,',
        re.IGNORECASE | re.DOTALL,
    )
    for m in pat_this.finditer(preamble[:8000]):
        name = m.group(1).strip()
        if 3 < len(name) < 200 and 'lender' not in name.lower():
            borrowers.append(name)

    # Pattern 4: Full description "Name, a State EntityType"
    pat_full: re.Pattern[str] = re.compile(
        r'([A-Z][A-Za-z0-9,.\'\-& ]+?)\s*,\s+'
        r'(a\s+(?:' + US_STATES + r')\s+\w[\w\s]*'
        r'(?:corporation|limited liability company|'
        r'limited partnership|company))',
        re.IGNORECASE,
    )
    for m in pat_full.finditer(preamble):
        entity: str = m.group(1).strip()
        entity = re.sub(
            r'^(?:among|between|by\s+and\s+among|by|and|the)\s+',
            '', entity, flags=re.IGNORECASE,
        ).strip()
        borrowers_full.append(f"{entity}, {m.group(2).strip()}")

    # Pattern 5: "among [Entity] The Lenders Party Hereto"
    if not borrowers:
        pat_among_lenders: re.Pattern[str] = re.compile(
            r'(?:among|between|by\s+and\s+among)\s+'
            r'([A-Z][A-Za-z0-9,.\'\-& ]+?'
            + CORP_SUFFIX_PAT + r')'
            r'\s*,?\s+(?:The\s+(?:Lender|Subsidiary|Guarantor|Borrowing Subsidiar)'
            r'(?:ies|y|s)?|the\s+(?:Lender|Borrowing Subsidiar)(?:ies|s|y)?|'
            r'and\s+(?:the\s+)?(?:Various|Other|Certain)\s+|'
            r'THE\s+(?:LENDER|SUBSIDIARY|BORROWING)S?|'
            r'THE\s+(?:BANK|FINANCIAL\s+INSTITUTION)S?)',
            re.UNICODE | re.IGNORECASE,
        )
        for source in [preamble_no_parens, preamble_flat]:
            for m in pat_among_lenders.finditer(source):
                name = _clean_entity_name(m.group(1))
                if not _is_noise(name):
                    borrowers.append(name)
                    break
            if borrowers:
                break

    # Pattern 6: Positional -- first ALL-CAPS entity with corp suffix
    if not borrowers:
        title_zone: str = preamble_no_parens[:5000]
        ca_start: re.Match[str] | None = re.search(
            r'(?:CREDIT\s+AGREEMENT|LOAN\s+AGREEMENT|FINANCING\s+AGREEMENT)',
            title_zone, re.IGNORECASE,
        )
        search_zones: list[str] = []
        if ca_start:
            search_zones.append(title_zone[ca_start.end():])
        if ca_start and ca_start.start() > 50:
            search_zones.append(title_zone[:ca_start.start()])

        pat_positional: re.Pattern[str] = re.compile(
            r'([A-Z][A-Z0-9,.\'\-& ]{3,80}?'
            r'(?:INC\.?|LLC|L\.L\.C\.|CORP\.?|CORPORATION|LTD\.?|LIMITED|'
            r'L\.P\.|LP|PLC|CO\.|COMPANY|INCORPORATED|FUND))'
            r'(?:\s*,|\s+(?:a|as|the|THE|The|for|dated|among|between|AND|and|'
            r'THE\s+LENDER|CREDIT\s+AGREEMENT))',
            re.UNICODE,
        )
        for zone in search_zones:
            for m in pat_positional.finditer(zone):
                name = _clean_entity_name(m.group(1))
                nl: str = name.lower()
                if any(w in nl for w in LENDER_AGENT_WORDS):
                    continue
                if not _is_noise(name):
                    borrowers.append(name)
                    break
            if borrowers:
                break

    # Pattern 7: EDGAR filename fallback
    if not borrowers and filename:
        parts: list[str] = filename.split("__")
        if len(parts) >= 2:
            raw_name: str = parts[0]
            name = raw_name.replace("_", " ").strip()
            if name and len(name) > 2:
                name = _title_case_name(name)
                if not _is_noise(name):
                    borrowers.append(name)

    # Deduplicate while preserving order
    seen: set[str] = set()
    unique_borrowers: list[str] = []
    for b in borrowers:
        key: str = b.upper().strip()
        if key not in seen:
            seen.add(key)
            unique_borrowers.append(b)

    if not unique_borrowers:
        return {"borrower": None, "borrower_full": None, "borrower_confidence": "none"}

    primary: str = unique_borrowers[0]
    if primary == primary.upper() and len(primary) > 5:
        primary = _title_case_name(primary)

    normalized: str = _normalize_borrower_name(primary)
    full: str = borrowers_full[0] if borrowers_full else primary

    if full == full.upper() and len(full) > 5:
        full = _title_case_name(full)

    # Score confidence
    confidence: str = "none"
    if normalized:
        if full and any(
            s in full
            for s in ("Inc", "LLC", "Corp", "Ltd", "L.P.", "PLC", "N.A.")
        ):
            confidence = "high"
        elif len(normalized) > 3 and normalized[0].isupper():
            confidence = "medium"
        else:
            confidence = "low"

    result: dict[str, Any] = {
        "borrower": normalized,
        "borrower_full": full,
        "borrower_confidence": confidence,
    }
    if len(unique_borrowers) > 1:
        result["co_borrowers"] = [
            _title_case_name(b) if b == b.upper() and len(b) > 5 else b
            for b in unique_borrowers[1:]
        ]
    return result


def extract_admin_agent(text: str) -> str | None:
    """Extract Administrative Agent from title page / preamble."""
    preamble: str = text[:10000]
    preamble_flat: str = re.sub(r'\s+', ' ', preamble)

    agent_patterns: list[str] = [
        r'as\s+(?:the\s+)?(?:[\w]+\s+)*?Administrative\s+Agent',
        r'as\s+(?:the\s+)?Agent\b',
    ]

    boundary_pat: re.Pattern[str] = re.compile(
        r'(?:'
        r'as\s+(?:the\s+)?(?:\w+\s+)*?Borrower(?:s)?\b'
        r'|HERETO|HEREIN|hereto|herein'
        r'|as\s+(?:the\s+)?(?:\w+\s+)*?Agent(?:s)?\b(?=\s+(?:and|,|$))'
        r'|as\s+(?:the\s+)?(?:\w+\s+)*?(?:Lender)s?\b(?=\s+(?:and|,|$))'
        r'|Lenders?\s+Party'
        r'|Guarantors?\s+Named'
        r'|Borrowers?\s+Named'
        r'|Joint\s+Lead\s+Arrangers?\b'
        r'|as\s+(?:Co-?)?(?:Syndication|Documentation)\s+Agent\b'
        r'|as\s+(?:the\s+)?(?:\w+\s+)*?(?:Guarantor|Issuer|Arranger|Bookrunner)s?\b'
        r'|as\s+(?:the\s+)?(?:\w+\s+)*?(?:General\s+Partner|Holdings|Parent)\b'
        r')',
        re.IGNORECASE,
    )

    for agent_pattern in agent_patterns:
        for region in [preamble_flat, re.sub(r'\s+', ' ', text[:20000])]:
            aa_match: re.Match[str] | None = re.search(
                agent_pattern, region, re.IGNORECASE,
            )
            if not aa_match:
                continue

            start_pos: int = max(0, aa_match.start() - 200)
            prefix: str = region[start_pos:aa_match.start()].rstrip().rstrip(',').rstrip()

            boundaries: list[re.Match[str]] = list(boundary_pat.finditer(prefix))
            if boundaries:
                last_boundary: re.Match[str] = boundaries[-1]
                name_text: str = prefix[last_boundary.end():].strip()
            else:
                name_text = prefix.strip()

            name_text = re.sub(r'^[\s,;]+', '', name_text)
            name_text = re.sub(r'^(?:and|by|the|THE|The|AND)\s+', '', name_text).strip()
            name_text = re.sub(r'^[\s,;]+', '', name_text)

            if 3 <= len(name_text) <= 120:
                name_text = _normalize_agent_name(name_text)
                return name_text

    return None


def extract_effective_date(text: str) -> dict[str, str | None]:
    """Extract the effective/closing date from the title page.

    Returns dict with 'closing_date' (ISO) and 'closing_date_raw'.
    """
    preamble: str = text[:8000]

    patterns: list[re.Pattern[str]] = [
        re.compile(r'[Dd]ated\s+as\s+of\s+(\w+\s+\d{1,2}\s*,?\s*\d{4})', re.IGNORECASE),
        re.compile(r'[Ee]ffective\s+(?:as\s+of\s+)?(\w+\s+\d{1,2}\s*,?\s*\d{4})', re.IGNORECASE),
        re.compile(
            r'entered\s+into\s+(?:as\s+of\s+)?(\w+\s+\d{1,2}\s*,?\s*\d{4})',
            re.IGNORECASE,
        ),
        re.compile(r'[Dd]ated\s+(\w+\s+\d{1,2}\s*,?\s*\d{4})', re.IGNORECASE),
    ]

    for pat in patterns:
        m: re.Match[str] | None = pat.search(preamble)
        if m:
            raw: str = m.group(1).strip()
            iso: str | None = _parse_date(raw)
            if iso:
                return {"closing_date": iso, "closing_date_raw": raw}

    return {"closing_date": None, "closing_date_raw": None}


def extract_filing_date(filename: str) -> str | None:
    """Extract filing date from EDGAR filename."""
    # Strategy 1: Extract year from EDGAR accession number
    acc_match: re.Match[str] | None = re.search(r'_(\d{10})(\d{2})(\d{6})_', filename)
    filing_year: int | None = None
    if acc_match:
        year_short: int = int(acc_match.group(2))
        if 0 <= year_short <= 50:
            filing_year = 2000 + year_short
        elif 90 <= year_short <= 99:
            filing_year = 1900 + year_short

    # Strategy 2: Look for YYYYMMDD date in exhibit filename portion
    parts: list[str] = filename.rsplit('_', 1)
    exhibit_part: str = parts[-1] if len(parts) > 1 else filename

    m: re.Match[str] | None = re.search(
        r'(\d{4})(0[1-9]|1[012])(0[1-9]|[12]\d|3[01])', exhibit_part,
    )
    if m:
        year: int = int(m.group(1))
        month: int = int(m.group(2))
        day: int = int(m.group(3))
        if 2000 <= year <= 2030:
            return f"{year}-{month:02d}-{day:02d}"

    if filing_year:
        return str(filing_year)

    return None


def extract_grower_baskets(text: str) -> dict[str, Any]:
    """Extract grower basket dollar amounts from the full CA text.

    Returns dict with closing_ebitda_mm, ebitda_source, has_grower_baskets,
    grower_basket_amounts_mm, ebitda_confidence, and other details.
    """
    DOLLAR_CAP: str = r'\$\s*([0-9][0-9,. ]*(?:\s*(?:million|billion))?)'
    PCT_CAP: str = r'([0-9]+\.?[0-9]*)\s*%'
    ENUM_PREFIX: str = r'(?:\(?\s*(?:[xia-z0-9]+\s*\)\s*)?)?'

    def _build_patterns(
        metric_re: str,
    ) -> tuple[re.Pattern[str], re.Pattern[str], re.Pattern[str]]:
        """Build forward, reverse, and multiplier patterns for a metric group."""
        fwd: re.Pattern[str] = re.compile(
            r'greater\s+of\s+' + ENUM_PREFIX
            + DOLLAR_CAP + r'\s+and\s+' + ENUM_PREFIX
            + PCT_CAP + r'\s*of\s+(?:' + metric_re + r')',
            re.IGNORECASE,
        )
        rev: re.Pattern[str] = re.compile(
            r'greater\s+of\s+' + ENUM_PREFIX
            + PCT_CAP + r'\s*of\s+(?:' + metric_re + r')\s+'
            r'and\s+' + ENUM_PREFIX + DOLLAR_CAP,
            re.IGNORECASE,
        )
        mult: re.Pattern[str] = re.compile(
            r'greater\s+of\s+' + ENUM_PREFIX
            + DOLLAR_CAP + r'\s+and\s+' + ENUM_PREFIX
            + r'([0-9]+\.?[0-9]*)\s+times?\s+'
            r'(?:the\s+)?(?:' + metric_re + r')',
            re.IGNORECASE,
        )
        return fwd, rev, mult

    pat_ebitda, pat_ebitda_rev, pat_ebitda_mult = _build_patterns(_EBITDA_METRICS)
    pat_asset, pat_asset_rev, _ = _build_patterns(_ASSET_METRICS)

    ebitda_pairs: list[tuple[float, float, float]] = []
    asset_amounts: list[float] = []
    context_excluded: int = 0
    ebitda_source: str = "grower_basket"

    def _collect_fwd_pairs(
        pat: re.Pattern[str],
        dest: list[tuple[float, float, float]],
        src_text: str,
    ) -> None:
        nonlocal context_excluded
        for m in pat.finditer(src_text):
            if _is_false_positive_context(src_text, m.start()):
                context_excluded += 1
                continue
            dollar_str: str = m.group(1).strip()
            pct: float = float(m.group(2))
            if 1.0 <= pct <= 500.0:
                amt: float | None = _parse_dollar_amount(dollar_str)
                if amt is not None and 0.1 <= amt <= 50000:
                    implied: float = round(amt / (pct / 100), 2)
                    dest.append((round(amt, 2), pct, implied))

    def _collect_fwd_scalars(
        pat: re.Pattern[str],
        dest: list[float],
        src_text: str,
    ) -> None:
        nonlocal context_excluded
        for m in pat.finditer(src_text):
            if _is_false_positive_context(src_text, m.start()):
                context_excluded += 1
                continue
            dollar_str: str = m.group(1).strip()
            pct: float = float(m.group(2))
            if 1.0 <= pct <= 500.0:
                amt: float | None = _parse_dollar_amount(dollar_str)
                if amt is not None and 0.1 <= amt <= 50000:
                    dest.append(round(amt, 2))

    def _collect_rev_pairs(
        pat: re.Pattern[str],
        dest: list[tuple[float, float, float]],
        src_text: str,
    ) -> None:
        nonlocal context_excluded
        for m in pat.finditer(src_text):
            if _is_false_positive_context(src_text, m.start()):
                context_excluded += 1
                continue
            pct: float = float(m.group(1))
            dollar_str: str = m.group(2).strip()
            if 1.0 <= pct <= 500.0:
                amt: float | None = _parse_dollar_amount(dollar_str)
                if amt is not None and 0.1 <= amt <= 50000:
                    implied: float = round(amt / (pct / 100), 2)
                    dest.append((round(amt, 2), pct, implied))

    def _collect_rev_scalars(
        pat: re.Pattern[str],
        dest: list[float],
        src_text: str,
    ) -> None:
        nonlocal context_excluded
        for m in pat.finditer(src_text):
            if _is_false_positive_context(src_text, m.start()):
                context_excluded += 1
                continue
            pct: float = float(m.group(1))
            dollar_str: str = m.group(2).strip()
            if 1.0 <= pct <= 500.0:
                amt: float | None = _parse_dollar_amount(dollar_str)
                if amt is not None and 0.1 <= amt <= 50000:
                    dest.append(round(amt, 2))

    # EBITDA-metric matches
    _collect_fwd_pairs(pat_ebitda, ebitda_pairs, text)
    _collect_rev_pairs(pat_ebitda_rev, ebitda_pairs, text)

    for m in pat_ebitda_mult.finditer(text):
        if _is_false_positive_context(text, m.start()):
            context_excluded += 1
            continue
        dollar_str: str = m.group(1).strip()
        multiplier_val: float = float(m.group(2))
        if 0.001 <= multiplier_val <= 10.0:
            amt: float | None = _parse_dollar_amount(dollar_str)
            if amt is not None and 0.1 <= amt <= 50000:
                implied: float = round(amt / multiplier_val, 2)
                ebitda_pairs.append((round(amt, 2), multiplier_val * 100, implied))
                ebitda_source = "grower_basket_multiplier"

    # Asset-metric matches
    _collect_fwd_scalars(pat_asset, asset_amounts, text)
    _collect_rev_scalars(pat_asset_rev, asset_amounts, text)

    # Apply plausibility bounds
    valid_pairs: list[tuple[float, float, float]] = [
        (amt_v, pct_v, imp_v) for amt_v, pct_v, imp_v in ebitda_pairs
        if 1.0 <= amt_v <= 15000.0 and 1.0 <= imp_v <= 50000.0
    ]
    ebitda_amounts: list[float] = [p[0] for p in valid_pairs]
    implied_ebitdas: list[float] = [p[2] for p in valid_pairs]

    if not ebitda_amounts:
        return {
            "closing_ebitda_mm": None,
            "ebitda_source": None,
            "has_grower_baskets": len(asset_amounts) > 0,
            "grower_basket_amounts_mm": [],
            "ebitda_confidence": "none",
            "asset_metric_amounts_mm": asset_amounts if asset_amounts else None,
            "context_excluded_count": context_excluded,
        }

    # Compute implied EBITDA via ratio method
    implied_rounded: list[float] = [_round_to_5(imp) for imp in implied_ebitdas]
    implied_counter: Counter[float] = Counter(implied_rounded)
    mode_implied: float = implied_counter.most_common(1)[0][0]
    mode_implied_count: int = implied_counter.most_common(1)[0][1]

    raw_counter: Counter[float] = Counter(ebitda_amounts)
    raw_mode: float = raw_counter.most_common(1)[0][0]

    if mode_implied_count >= 3:
        confidence: str = "high"
    elif mode_implied_count == 2:
        confidence = "medium"
    else:
        confidence = "low"

    distinct_amounts: list[float] = sorted(set(ebitda_amounts))
    distinct_implied: list[float] = sorted(set(implied_rounded))
    multi_base: bool = len(distinct_amounts) > 1

    return {
        "closing_ebitda_mm": mode_implied,
        "ebitda_source": ebitda_source,
        "has_grower_baskets": True,
        "grower_basket_amounts_mm": ebitda_amounts,
        "grower_basket_distinct_amounts_mm": distinct_amounts if multi_base else None,
        "grower_basket_implied_ebitdas_mm": distinct_implied if len(distinct_implied) > 1 else None,
        "grower_basket_mode_count": mode_implied_count,
        "grower_basket_raw_mode_mm": raw_mode,
        "ebitda_confidence": confidence,
        "asset_metric_amounts_mm": asset_amounts if asset_amounts else None,
        "context_excluded_count": context_excluded,
    }
