"""Statistical phrase discovery: TF-IDF + log-odds rank fusion.

Discovers "DNA phrases" — words and short phrases that statistically
distinguish concept sections from background text. Uses Monroe et al. (2008)
log-odds ratio with informative Dirichlet prior combined with TF-IDF
percentile ranking.

Ported from vantage_platform/l1/discovery/section_analyzer.py.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass


# ---------------------------------------------------------------------------
# Configuration defaults (tunable per-family)
# ---------------------------------------------------------------------------

DEFAULT_MIN_SECTION_RATE = 0.20   # phrase must appear in ≥20% of target sections
DEFAULT_MAX_BG_RATE = 0.05        # phrase must appear in ≤5% of background sections
DEFAULT_ALPHA = 0.01              # Dirichlet smoothing parameter
DEFAULT_TFIDF_WEIGHT = 0.70      # TF-IDF contribution to combined score
DEFAULT_TOP_K = 30                # max phrases to return


@dataclass(frozen=True, slots=True)
class DnaCandidate:
    """A candidate DNA phrase with statistical scores."""

    phrase: str
    tfidf_score: float
    log_odds_ratio: float
    combined_score: float       # 0.7 * tfidf_rank_pctile + 0.3 * log_odds_rank_pctile
    section_rate: float         # fraction of target sections containing this phrase
    background_rate: float      # fraction of background sections containing this phrase
    passed_validation: bool
    rejection_reason: str       # "" if passed; e.g., "section_rate<0.20"


@dataclass(frozen=True, slots=True)
class FamilyProfile:
    """Family-level orchestration summary for DNA candidate quality."""

    target_count: int
    background_count: int
    avg_target_words: float
    avg_background_words: float
    token_diversity_target: float
    token_diversity_background: float
    candidate_count: int
    high_signal_candidate_count: int
    avg_candidate_section_rate: float
    avg_candidate_background_rate: float


def discover_dna_phrases(
    target_texts: list[str],
    background_texts: list[str],
    *,
    min_section_rate: float = DEFAULT_MIN_SECTION_RATE,
    max_bg_rate: float = DEFAULT_MAX_BG_RATE,
    alpha: float = DEFAULT_ALPHA,
    tfidf_weight: float = DEFAULT_TFIDF_WEIGHT,
    top_k: int = DEFAULT_TOP_K,
    ngram_range: tuple[int, int] = (1, 3),
) -> list[DnaCandidate]:
    """Discover DNA phrases using TF-IDF + log-odds rank fusion.

    Algorithm:
        1. Tokenize target and background texts
        2. Compute TF-IDF scores for all n-grams in target
        3. Compute log-odds ratio (Monroe 2008) with Dirichlet prior
        4. Rank by TF-IDF percentile and log-odds percentile
        5. Combine: 0.7 * tfidf_rank_pctile + 0.3 * log_odds_rank_pctile
        6. Validate: min_section_rate, max_bg_rate gates
        7. Return top-K passed candidates

    Args:
        target_texts: Texts of sections known to contain the concept.
        background_texts: Texts of sections that do NOT contain the concept.
        min_section_rate: Minimum fraction of target sections phrase must appear in.
        max_bg_rate: Maximum fraction of background sections phrase may appear in.
        alpha: Dirichlet smoothing parameter for log-odds.
        tfidf_weight: Weight of TF-IDF rank in combined score (1-weight for log-odds).
        top_k: Maximum number of phrases to return.
        ngram_range: Range of n-gram sizes to consider.

    Returns:
        List of DnaCandidate sorted by combined_score descending.
    """
    if not target_texts:
        return []

    # Step 1: Build n-gram document frequency maps
    min_n, max_n = ngram_range
    target_ngrams = [_extract_ngrams(t, min_n, max_n) for t in target_texts]
    bg_ngrams = [_extract_ngrams(t, min_n, max_n) for t in background_texts]

    # Step 2: Compute document frequency
    target_df: Counter[str] = Counter()
    for ngrams in target_ngrams:
        for ng in set(ngrams):
            target_df[ng] += 1

    bg_df: Counter[str] = Counter()
    for ngrams in bg_ngrams:
        for ng in set(ngrams):
            bg_df[ng] += 1

    n_target = len(target_texts)
    n_bg = max(len(background_texts), 1)

    # Step 3: Compute TF-IDF and log-odds for each candidate
    all_target_ngrams: Counter[str] = Counter()
    for ngrams in target_ngrams:
        all_target_ngrams.update(ngrams)

    all_bg_ngrams: Counter[str] = Counter()
    for ngrams in bg_ngrams:
        all_bg_ngrams.update(ngrams)

    total_target_tokens = sum(all_target_ngrams.values()) or 1
    total_bg_tokens = sum(all_bg_ngrams.values()) or 1
    total_docs = n_target + n_bg

    candidates: dict[str, dict[str, float]] = {}

    for phrase, tf_count in all_target_ngrams.items():
        df = target_df[phrase] + bg_df.get(phrase, 0)
        idf = math.log(total_docs / (1 + df))
        tf = tf_count / total_target_tokens
        tfidf = tf * idf

        # Monroe et al. (2008) log-odds ratio with Dirichlet prior
        y_target = all_target_ngrams[phrase]
        y_bg = all_bg_ngrams.get(phrase, 0)
        n_t = total_target_tokens
        n_b = total_bg_tokens

        # Smoothed log-odds
        log_odds = (
            math.log((y_target + alpha) / (n_t + alpha * total_docs))
            - math.log((y_bg + alpha) / (n_b + alpha * total_docs))
        )

        sec_rate = target_df[phrase] / n_target
        bg_rate = bg_df.get(phrase, 0) / n_bg

        candidates[phrase] = {
            "tfidf": tfidf,
            "log_odds": log_odds,
            "section_rate": sec_rate,
            "background_rate": bg_rate,
        }

    if not candidates:
        return []

    # Step 4: Rank by TF-IDF percentile and log-odds percentile
    phrases_sorted_tfidf = sorted(
        candidates.keys(), key=lambda p: candidates[p]["tfidf"],
    )
    phrases_sorted_logodds = sorted(
        candidates.keys(), key=lambda p: candidates[p]["log_odds"],
    )

    n_cands = len(candidates)
    tfidf_rank: dict[str, float] = {}
    logodds_rank: dict[str, float] = {}

    for i, p in enumerate(phrases_sorted_tfidf):
        tfidf_rank[p] = i / max(n_cands - 1, 1)
    for i, p in enumerate(phrases_sorted_logodds):
        logodds_rank[p] = i / max(n_cands - 1, 1)

    # Step 5: Combined score
    logodds_weight = 1.0 - tfidf_weight
    results: list[DnaCandidate] = []

    for phrase, scores in candidates.items():
        combined = tfidf_weight * tfidf_rank[phrase] + logodds_weight * logodds_rank[phrase]

        # Step 6: Validation gates
        sec_rate = scores["section_rate"]
        bg_rate = scores["background_rate"]
        passed = True
        reason = ""

        if sec_rate < min_section_rate:
            passed = False
            reason = f"section_rate<{min_section_rate}"
        elif bg_rate > max_bg_rate:
            passed = False
            reason = f"background_rate>{max_bg_rate}"

        results.append(DnaCandidate(
            phrase=phrase,
            tfidf_score=scores["tfidf"],
            log_odds_ratio=scores["log_odds"],
            combined_score=combined,
            section_rate=sec_rate,
            background_rate=bg_rate,
            passed_validation=passed,
            rejection_reason=reason,
        ))

    # Step 7: Sort by combined score, return top-K passed
    results.sort(key=lambda c: c.combined_score, reverse=True)
    passed = [c for c in results if c.passed_validation]
    return passed[:top_k]


def _extract_ngrams(text: str, min_n: int, max_n: int) -> list[str]:
    """Extract word n-grams from text."""
    words = _tokenize(text)
    ngrams: list[str] = []
    for n in range(min_n, max_n + 1):
        for i in range(len(words) - n + 1):
            ngrams.append(" ".join(words[i:i + n]))
    return ngrams


_WORD_RE = re.compile(r"[a-z][a-z''-]+", re.IGNORECASE)


def _tokenize(text: str) -> list[str]:
    """Tokenize text into lowercase words."""
    return [m.group().lower() for m in _WORD_RE.finditer(text)]


def build_family_profile(
    target_texts: list[str],
    background_texts: list[str],
    candidates: list[DnaCandidate],
) -> FamilyProfile:
    """Build family-level profile used by orchestration/reporting tools."""
    target_tokens = [_tokenize(t) for t in target_texts]
    bg_tokens = [_tokenize(t) for t in background_texts]

    target_word_counts = [len(tokens) for tokens in target_tokens]
    bg_word_counts = [len(tokens) for tokens in bg_tokens]

    target_vocab = {tok for tokens in target_tokens for tok in tokens}
    bg_vocab = {tok for tokens in bg_tokens for tok in tokens}

    target_total_tokens = sum(target_word_counts)
    bg_total_tokens = sum(bg_word_counts)
    high_signal = [c for c in candidates if c.combined_score >= 0.8]

    avg_sec_rate = (
        sum(c.section_rate for c in candidates) / len(candidates)
        if candidates
        else 0.0
    )
    avg_bg_rate = (
        sum(c.background_rate for c in candidates) / len(candidates)
        if candidates
        else 0.0
    )

    return FamilyProfile(
        target_count=len(target_texts),
        background_count=len(background_texts),
        avg_target_words=(
            sum(target_word_counts) / len(target_word_counts)
            if target_word_counts
            else 0.0
        ),
        avg_background_words=(
            sum(bg_word_counts) / len(bg_word_counts)
            if bg_word_counts
            else 0.0
        ),
        token_diversity_target=(
            len(target_vocab) / max(1, target_total_tokens)
            if target_total_tokens > 0
            else 0.0
        ),
        token_diversity_background=(
            len(bg_vocab) / max(1, bg_total_tokens)
            if bg_total_tokens > 0
            else 0.0
        ),
        candidate_count=len(candidates),
        high_signal_candidate_count=len(high_signal),
        avg_candidate_section_rate=avg_sec_rate,
        avg_candidate_background_rate=avg_bg_rate,
    )
