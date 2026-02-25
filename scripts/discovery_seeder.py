#!/usr/bin/env python3
"""Per-family discovery orchestrator (Layer 2).

Runs a 10-step discovery pipeline per family, enriching bootstrap strategies
with corpus-derived heading variants, DNA phrases, keywords, structural
position, defined term dependencies, and cross-family conditioning signals.

Optionally reads Layer 1 exploratory report for adjacency and template
insights. Writes enriched strategies to workspace directories.

Usage:
    # Single family:
    python3 scripts/discovery_seeder.py \\
      --db corpus_index/corpus.duckdb \\
      --family indebtedness \\
      --bootstrap data/bootstrap/bootstrap_all.json \\
      --family-notes docs/ontology_family_notes.json \\
      --workspace workspaces/indebtedness \\
      [--exploratory-report plans/exploratory_report.json] \\
      [--dry-run]

    # All families:
    python3 scripts/discovery_seeder.py --all \\
      --db corpus_index/corpus.duckdb \\
      --bootstrap data/bootstrap/bootstrap_all.json \\
      --family-notes docs/ontology_family_notes.json \\
      --workspace-root workspaces \\
      [--exploratory-report plans/exploratory_report.json] \\
      [--dry-run]

Structured JSON output goes to stdout; human messages go to stderr.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

try:
    import orjson

    def _dumps(obj: Any) -> bytes:
        return orjson.dumps(obj, option=orjson.OPT_INDENT_2)

except ImportError:

    def _dumps(obj: Any) -> bytes:
        return json.dumps(obj, indent=2, default=str).encode()


def log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


# ---------------------------------------------------------------------------
# Bootstrap + family notes helpers
# ---------------------------------------------------------------------------

def load_family_concepts(
    bootstrap_path: Path,
) -> dict[str, list[dict[str, Any]]]:
    """Load concepts grouped by family_id.

    Returns:
        family_id → [concept_dict, ...]
    """
    raw = json.loads(bootstrap_path.read_bytes())
    families: dict[str, list[dict[str, Any]]] = {}
    for concept_id, concept in raw.items():
        if not isinstance(concept, dict):
            continue
        fam_id = concept.get("family_id", "")
        if fam_id:
            concept["_concept_id"] = concept_id
            families.setdefault(fam_id, []).append(concept)
    return families


def load_family_heading_patterns(
    concepts: list[dict[str, Any]],
) -> list[str]:
    """Extract merged heading patterns from a family's concepts."""
    seen: set[str] = set()
    result: list[str] = []
    for concept in concepts:
        search = concept.get("search_strategy", {})
        if not isinstance(search, dict):
            continue
        for p in search.get("heading_patterns", []):
            if isinstance(p, str) and p.strip() and p not in seen:
                seen.add(p)
                result.append(p)
    return result


def load_family_notes(notes_path: Path | None) -> dict[str, dict[str, Any]]:
    """Load ontology_family_notes.json."""
    if notes_path is None or not notes_path.exists():
        return {}
    raw = json.loads(notes_path.read_bytes())
    return {
        k: v for k, v in raw.items()
        if isinstance(v, dict) and not k.startswith("_")
    }


def load_exploratory_report(report_path: Path | None) -> dict[str, Any] | None:
    """Load Layer 1 exploratory report if available."""
    if report_path is None or not report_path.exists():
        return None
    return json.loads(report_path.read_bytes())


# ---------------------------------------------------------------------------
# Section matching
# ---------------------------------------------------------------------------

def match_family_sections(
    corpus: Any,
    heading_patterns: list[str],
    doc_ids: list[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Match family sections and collect non-family sections.

    Returns:
        (matched_sections, non_matched_sections) — both as list of dicts
        with keys: doc_id, section_number, heading, article_num, char_start, word_count
    """
    from agent.textmatch import heading_matches

    matched: list[dict[str, Any]] = []
    non_matched: list[dict[str, Any]] = []

    for doc_id in doc_ids:
        rows = corpus.query(
            """
            SELECT section_number, heading, article_num, char_start, word_count
            FROM sections
            WHERE doc_id = ?
            ORDER BY char_start
            """,
            [doc_id],
        )
        for row in rows:
            sec = {
                "doc_id": doc_id,
                "section_number": str(row[0]),
                "heading": str(row[1]),
                "article_num": int(row[2] or 0),
                "char_start": int(row[3] or 0),
                "word_count": int(row[4] or 0),
            }
            if heading_matches(str(sec["heading"]), heading_patterns):
                matched.append(sec)
            else:
                non_matched.append(sec)

    return matched, non_matched


# ---------------------------------------------------------------------------
# Discovery steps
# ---------------------------------------------------------------------------

def discover_headings(
    matched: list[dict[str, Any]],
    non_matched: list[dict[str, Any]],
    exploratory_report: dict[str, Any] | None,
    family_id: str,
) -> dict[str, Any]:
    """Step 2: Discover heading variants and negative heading patterns.

    Examines the heading distribution across matched sections,
    identifies common variants, and flags false-positive headings
    using adjacency patterns from the exploratory report.
    """
    heading_counts: Counter[str] = Counter()
    for sec in matched:
        normalized = " ".join(sec["heading"].lower().split())
        heading_counts[normalized] += 1

    # Heading patterns: all headings appearing in >1% of matches
    threshold = max(2, len(matched) // 100)
    discovered_headings = [
        h for h, c in heading_counts.most_common()
        if c >= threshold
    ]

    # Negative headings: from adjacency patterns if available
    negative_headings: list[str] = []
    if exploratory_report:
        adj = exploratory_report.get("adjacency_patterns", {}).get(family_id, [])
        # Adjacent section headings that are NOT family headings
        for entry in adj:
            heading = entry.get("heading", "")
            if heading and heading not in heading_counts:
                negative_headings.append(heading)

    return {
        "heading_patterns": discovered_headings[:30],
        "negative_heading_patterns": negative_headings[:10],
        "heading_distribution": dict(heading_counts.most_common(20)),
    }


def discover_dna_phrases(
    corpus: Any,
    matched: list[dict[str, Any]],
    non_matched: list[dict[str, Any]],
    *,
    max_background: int = 500,
    seed: int = 42,
) -> dict[str, Any]:
    """Step 3: DNA phrase discovery via TF-IDF + Monroe log-odds.

    Returns tier1 and tier2 DNA phrases.
    """
    from agent.dna import discover_dna_phrases as _discover_dna

    # Load section texts
    target_texts: list[str] = []
    for sec in matched:
        text = corpus.get_section_text(sec["doc_id"], sec["section_number"])
        if text:
            target_texts.append(text)

    # Sample background texts (non-family sections)
    import random
    rng = random.Random(seed)
    bg_sample = rng.sample(non_matched, min(max_background, len(non_matched)))
    bg_texts: list[str] = []
    for sec in bg_sample:
        text = corpus.get_section_text(sec["doc_id"], sec["section_number"])
        if text:
            bg_texts.append(text)

    if not target_texts:
        return {"dna_tier1": [], "dna_tier2": []}

    candidates = _discover_dna(target_texts, bg_texts, top_k=30)

    # Split into tiers: top 10 → tier1, rest → tier2
    tier1 = [c.phrase for c in candidates[:10]]
    tier2 = [c.phrase for c in candidates[10:]]

    return {
        "dna_tier1": tier1,
        "dna_tier2": tier2,
        "dna_candidate_count": len(candidates),
    }


def discover_anti_dna(
    corpus: Any,
    matched: list[dict[str, Any]],
    non_matched: list[dict[str, Any]],
    *,
    max_background: int = 500,
    seed: int = 42,
) -> dict[str, Any]:
    """Step 4: Anti-DNA discovery — phrases that distinguish adjacent non-family sections.

    Inverted: positive = adjacent non-family sections, background = family sections.
    """
    # For anti-DNA: non-matched sections are "positive", matched are "background"
    import random

    from agent.dna import discover_dna_phrases as _discover_dna
    rng = random.Random(seed)

    # Sample from non-matched (they're the "target" for anti-DNA)
    sample_nm = rng.sample(non_matched, min(max_background, len(non_matched)))
    anti_target_texts: list[str] = []
    for sec in sample_nm:
        text = corpus.get_section_text(sec["doc_id"], sec["section_number"])
        if text:
            anti_target_texts.append(text)

    # Family sections are the "background"
    family_texts: list[str] = []
    for sec in matched[:max_background]:
        text = corpus.get_section_text(sec["doc_id"], sec["section_number"])
        if text:
            family_texts.append(text)

    if not anti_target_texts:
        return {"dna_negative_tier1": [], "dna_negative_tier2": []}

    candidates = _discover_dna(
        anti_target_texts, family_texts,
        top_k=20, min_section_rate=0.10,
    )

    tier1 = [c.phrase for c in candidates[:8]]
    tier2 = [c.phrase for c in candidates[8:]]

    return {
        "dna_negative_tier1": tier1,
        "dna_negative_tier2": tier2,
    }


def discover_keywords(
    corpus: Any,
    matched: list[dict[str, Any]],
    non_matched: list[dict[str, Any]],
    cooccurrence_families: list[str] | None = None,
) -> dict[str, Any]:
    """Step 5: Keyword discovery via word/bigram frequency analysis.

    Finds words/bigrams that appear frequently in family sections but
    rarely in non-family sections (discrimination ratio filtering).
    """
    # Collect word frequencies from matched sections
    import re
    from collections import Counter as _Counter

    target_word_freq: _Counter[str] = _Counter()
    bg_word_freq: _Counter[str] = _Counter()
    _WORD_RE = re.compile(r"[a-z][a-z''_-]+", re.IGNORECASE)

    target_doc_count = 0
    for sec in matched[:500]:
        text = corpus.get_section_text(sec["doc_id"], sec["section_number"])
        if not text:
            continue
        target_doc_count += 1
        words = [m.group().lower() for m in _WORD_RE.finditer(text)]
        # Word frequency
        for w in set(words):  # doc-frequency (count once per section)
            target_word_freq[w] += 1
        # Bigrams
        for i in range(len(words) - 1):
            bigram = f"{words[i]} {words[i+1]}"
            target_word_freq[bigram] += 1

    import random
    rng = random.Random(42)
    bg_sample = rng.sample(non_matched, min(500, len(non_matched)))
    bg_doc_count = 0
    for sec in bg_sample:
        text = corpus.get_section_text(sec["doc_id"], sec["section_number"])
        if not text:
            continue
        bg_doc_count += 1
        words = [m.group().lower() for m in _WORD_RE.finditer(text)]
        for w in set(words):
            bg_word_freq[w] += 1
        for i in range(len(words) - 1):
            bigram = f"{words[i]} {words[i+1]}"
            bg_word_freq[bigram] += 1

    if target_doc_count == 0:
        return {
            "keyword_anchors": [],
            "keyword_anchors_section_only": [],
            "concept_specific_keywords": [],
        }

    # Discrimination ratio: (target_rate / bg_rate)
    # Filter: target_rate > 0.1, discrimination > 3x
    stopwords = {
        "the", "and", "of", "to", "in", "a", "or", "for", "be", "is",
        "with", "that", "by", "as", "an", "at", "from", "on", "not",
        "shall", "any", "such", "this", "which", "will", "each", "may",
        "other", "its", "all", "no", "but", "if", "has", "been", "were",
        "have", "had", "are", "than", "their", "who", "would", "could",
        "should", "more", "after", "before", "upon", "pursuant",
        "provided", "hereto", "herein", "thereof", "thereunder",
        "hereunder", "thereto", "hereof", "therein",
    }

    keyword_candidates: list[tuple[str, float, float]] = []  # (word, target_rate, disc_ratio)

    for word, count in target_word_freq.most_common(2000):
        if word in stopwords or len(word) < 3:
            continue
        target_rate = count / target_doc_count
        bg_rate = bg_word_freq.get(word, 0) / max(bg_doc_count, 1)
        if target_rate < 0.10:
            continue
        disc_ratio = target_rate / max(bg_rate, 0.001)
        if disc_ratio < 3.0:
            continue
        keyword_candidates.append((word, target_rate, disc_ratio))

    keyword_candidates.sort(key=lambda t: -t[2])

    # Split into tiers
    # keyword_anchors: top 10 with highest discrimination
    # keyword_anchors_section_only: next 10
    # concept_specific_keywords: top 5 with target_rate > 0.3
    keyword_anchors = [w for w, _, _ in keyword_candidates[:10]]
    keyword_anchors_section_only = [w for w, _, _ in keyword_candidates[10:20]]
    concept_specific = [
        w for w, tr, _ in keyword_candidates if tr > 0.3
    ][:5]

    return {
        "keyword_anchors": keyword_anchors,
        "keyword_anchors_section_only": keyword_anchors_section_only,
        "concept_specific_keywords": concept_specific,
    }


def analyze_structural_position(
    matched: list[dict[str, Any]],
) -> dict[str, Any]:
    """Step 6: Article/section number distribution from matches."""
    article_counts: Counter[int] = Counter()
    section_counts: Counter[str] = Counter()

    for sec in matched:
        article_counts[sec["article_num"]] += 1
        section_counts[sec["section_number"]] += 1

    # Primary articles: those with >10% of matches
    threshold = max(2, len(matched) // 10)
    primary_articles = sorted([
        a for a, c in article_counts.items() if c >= threshold
    ])
    primary_sections = [
        s for s, c in section_counts.most_common(5) if c >= threshold
    ]

    return {
        "primary_articles": primary_articles,
        "primary_sections": primary_sections,
        "article_distribution": dict(article_counts.most_common(10)),
        "section_distribution": dict(section_counts.most_common(10)),
    }


def extract_defined_term_deps(
    corpus: Any,
    matched: list[dict[str, Any]],
) -> dict[str, Any]:
    """Step 7: Find defined terms most frequently referenced in family sections."""
    term_freq: Counter[str] = Counter()
    docs_with_terms: dict[str, set[str]] = {}

    # Sample up to 200 sections for term extraction
    for sec in matched[:200]:
        text = corpus.get_section_text(sec["doc_id"], sec["section_number"])
        if not text:
            continue

        # Get all defined terms in this document
        defs = corpus.get_definitions(sec["doc_id"])
        for d in defs:
            term = d.term
            if term.lower() in text.lower():
                term_freq[term] += 1
                docs_with_terms.setdefault(term, set()).add(sec["doc_id"])

    # Rank by coverage rate (fraction of matched sections containing term)
    if not matched:
        return {"defined_term_dependencies": []}

    terms_ranked = [
        (term, count, len(docs_with_terms.get(term, set())))
        for term, count in term_freq.most_common(30)
    ]

    # Filter: must appear in >10% of sections
    threshold = max(2, len(matched[:200]) // 10)
    significant_terms = [
        term for term, count, _ in terms_ranked
        if count >= threshold
    ]

    return {
        "defined_term_dependencies": significant_terms[:15],
    }


def extract_template_patterns(
    corpus: Any,
    matched: list[dict[str, Any]],
    exploratory_report: dict[str, Any] | None,
    family_id: str,
    family_notes: dict[str, Any] | None,
) -> dict[str, Any]:
    """Step 8: Template-conditioned insights from exploratory report + notes.

    Extracts template-specific article number variance and heading differences.
    Also incorporates domain expert notes about structural variants.
    """
    concept_notes: list[str] = []
    template_overrides: dict[str, dict[str, Any]] = {}

    # From exploratory report
    if exploratory_report:
        tpl_data = exploratory_report.get("template_conditioned", {}).get(family_id, [])
        for profile in tpl_data:
            tpl = profile.get("template_family", "unknown")
            avg_art = profile.get("avg_article_num", 0)
            count = profile.get("section_count", 0)
            if count >= 5:
                heading_dist = profile.get("heading_distribution", {})
                top_headings = sorted(heading_dist.items(), key=lambda x: -x[1])[:3]
                if top_headings:
                    template_overrides[tpl] = {
                        "heading_patterns": [h for h, _ in top_headings],
                        "primary_articles": [round(avg_art)],
                    }

    # From family notes
    if family_notes:
        notes = family_notes.get(family_id, {})
        if notes:
            location = notes.get("location_guidance", "")
            if location:
                concept_notes.append(f"Location: {location}")

            variants = notes.get("structural_variants", [])
            for v in variants:
                concept_notes.append(f"Structural variant: {v}")

            co_examine = notes.get("co_examine", [])
            if co_examine:
                concept_notes.append(f"Co-examine: {', '.join(co_examine)}")

            def_variants = notes.get("definition_variants", [])
            if def_variants:
                concept_notes.append(
                    f"Definition variants: {', '.join(def_variants)}"
                )

    return {
        "concept_notes": concept_notes[:20],
        "template_overrides": template_overrides,
    }


def extract_cross_family_signals(
    exploratory_report: dict[str, Any] | None,
    family_id: str,
) -> dict[str, Any]:
    """Step 9: Cross-family conditioning from co-occurrence data.

    Identifies top-3 co-occurring families and adjacency-informed fallback.
    """
    concept_notes: list[str] = []
    fallback_escalation: str | None = None

    if not exploratory_report:
        return {"concept_notes": concept_notes, "fallback_escalation": fallback_escalation}

    cooc = exploratory_report.get("cooccurrence", {})
    families = cooc.get("families", [])
    doc_matrix = cooc.get("doc_level", [])

    if family_id in families:
        idx = families.index(family_id)
        # Top-3 co-occurring families (by doc-level)
        if idx < len(doc_matrix):
            row = doc_matrix[idx]
            scored = [
                (families[j], row[j])
                for j in range(len(families))
                if j != idx and j < len(row)
            ]
            scored.sort(key=lambda x: -x[1])
            top_3 = scored[:3]
            if top_3:
                co_fams = ", ".join(f"{f} ({c} docs)" for f, c in top_3)
                concept_notes.append(f"Top co-occurring families: {co_fams}")

    # Adjacency-informed fallback
    adj = exploratory_report.get("adjacency_patterns", {}).get(family_id, [])
    if adj:
        neighbors = [e.get("heading", "") for e in adj[:3] if e.get("heading")]
        if neighbors:
            fallback_escalation = (
                f"If primary heading search fails, look near: {', '.join(neighbors)}"
            )

    return {
        "concept_notes": concept_notes,
        "fallback_escalation": fallback_escalation,
    }


def merge_and_validate(
    base_strategy: dict[str, Any],
    discovery_results: dict[str, Any],
    *,
    dry_run: bool,
    workspace: Path,
    family_id: str,
) -> dict[str, Any]:
    """Step 10: Merge discoveries into strategy and validate.

    Performs heading-match regression check: the new heading patterns
    should match at least as many sections as the original.
    """
    # Merge: discovery results override base where non-empty
    merged = dict(base_strategy)
    for key, val in discovery_results.items():
        if key.startswith("_"):
            continue
        # Only override if discovery found something
        if isinstance(val, list) and not val:
            continue
        if isinstance(val, dict) and not val:
            continue
        if val is None:
            continue
        merged[key] = val

    # Ensure tuples (not lists) for strategy compatibility
    tuple_fields = {
        "heading_patterns", "keyword_anchors", "keyword_anchors_section_only",
        "concept_specific_keywords", "dna_tier1", "dna_tier2",
        "dna_negative_tier1", "dna_negative_tier2", "defined_term_dependencies",
        "concept_notes", "primary_articles", "primary_sections",
        "negative_heading_patterns",
    }
    for field in tuple_fields:
        if field in merged and isinstance(merged[field], list):
            merged[field] = merged[field]  # kept as list for JSON

    # Update provenance
    merged["validation_status"] = "discovery_seeded"
    merged["last_updated"] = datetime.now(UTC).isoformat()

    if dry_run:
        log(f"  [DRY RUN] Would write enriched strategy for {family_id}")
    else:
        # Write to workspace
        workspace.mkdir(parents=True, exist_ok=True)
        strategies_dir = workspace / "strategies"
        strategies_dir.mkdir(exist_ok=True)

        # Find next version
        existing = sorted(strategies_dir.glob(f"{family_id}_v*.json"))
        if existing:
            import re
            versions = []
            for p in existing:
                m = re.search(r"_v(\d+)\.json$", p.name)
                if m:
                    versions.append(int(m.group(1)))
            next_v = max(versions, default=0) + 1
        else:
            next_v = 1

        merged["version"] = next_v
        out_path = strategies_dir / f"{family_id}_v{next_v}.json"
        out_path.write_bytes(_dumps(merged))
        log(f"  Wrote {out_path}")

    return merged


# ---------------------------------------------------------------------------
# Per-family pipeline
# ---------------------------------------------------------------------------

def run_family_discovery(
    *,
    corpus: Any,
    family_id: str,
    concepts: list[dict[str, Any]],
    family_notes: dict[str, Any],
    exploratory_report: dict[str, Any] | None,
    workspace: Path,
    dry_run: bool,
) -> dict[str, Any]:
    """Execute 10-step discovery pipeline for one family.

    Returns:
        Summary dict with discovery stats.
    """
    log(f"\n{'='*60}")
    log(f"Discovery: {family_id}")
    log(f"{'='*60}")

    # Step 1: Load state
    heading_patterns = load_family_heading_patterns(concepts)
    log(f"  Step 1: {len(heading_patterns)} heading patterns from bootstrap")

    # Build base strategy from first concept's search_strategy
    base_strategy: dict[str, Any] = {"family": family_id, "concept_id": family_id}
    for concept in concepts:
        search = concept.get("search_strategy", {})
        if isinstance(search, dict):
            for k, v in search.items():
                if k not in base_strategy or not base_strategy[k]:
                    base_strategy[k] = v

    # Get doc IDs for matching
    doc_ids = corpus.doc_ids()
    log(f"  Corpus: {len(doc_ids)} documents")

    # Match sections
    log("  Step 2-: Matching sections...")
    matched, non_matched = match_family_sections(
        corpus, heading_patterns, doc_ids,
    )
    log(f"    {len(matched)} matched, {len(non_matched)} non-matched")

    if not matched:
        log(f"  WARNING: No sections matched for {family_id}. Skipping discovery.")
        return {"family_id": family_id, "status": "no_matches", "matched": 0}

    # Collect discovery results
    discovery: dict[str, Any] = {}

    # Step 2: Heading discovery
    log("  Step 2: Heading discovery...")
    heading_result = discover_headings(
        matched, non_matched, exploratory_report, family_id,
    )
    discovery.update(heading_result)
    log(f"    {len(heading_result['heading_patterns'])} heading patterns discovered")

    # Step 3: DNA discovery
    log("  Step 3: DNA phrase discovery...")
    dna_result = discover_dna_phrases(corpus, matched, non_matched)
    discovery.update(dna_result)
    log(f"    {len(dna_result['dna_tier1'])} tier1, {len(dna_result['dna_tier2'])} tier2")

    # Step 4: Anti-DNA discovery
    log("  Step 4: Anti-DNA discovery...")
    anti_dna_result = discover_anti_dna(corpus, matched, non_matched)
    discovery.update(anti_dna_result)
    log(f"    {len(anti_dna_result['dna_negative_tier1'])} negative tier1")

    # Step 5: Keyword discovery
    log("  Step 5: Keyword discovery...")
    keyword_result = discover_keywords(corpus, matched, non_matched)
    discovery.update(keyword_result)
    log(f"    {len(keyword_result['keyword_anchors'])} keyword anchors")

    # Step 6: Structural position
    log("  Step 6: Structural position analysis...")
    position_result = analyze_structural_position(matched)
    discovery.update(position_result)
    log(f"    Primary articles: {position_result['primary_articles']}")

    # Step 7: Defined term dependencies
    log("  Step 7: Defined term extraction...")
    term_result = extract_defined_term_deps(corpus, matched)
    discovery.update(term_result)
    log(f"    {len(term_result['defined_term_dependencies'])} defined terms")

    # Step 8: Template patterns
    log("  Step 8: Template + domain expert patterns...")
    template_result = extract_template_patterns(
        corpus, matched, exploratory_report, family_id, family_notes,
    )
    discovery.update(template_result)
    log(f"    {len(template_result['concept_notes'])} notes, "
        f"{len(template_result['template_overrides'])} template overrides")

    # Step 9: Cross-family conditioning
    log("  Step 9: Cross-family conditioning...")
    cross_result = extract_cross_family_signals(exploratory_report, family_id)
    # Merge concept_notes (additive)
    existing_notes = list(discovery.get("concept_notes", []))
    existing_notes.extend(cross_result.get("concept_notes", []))
    discovery["concept_notes"] = existing_notes
    if cross_result.get("fallback_escalation"):
        discovery["fallback_escalation"] = cross_result["fallback_escalation"]
    log(f"    Fallback: {cross_result.get('fallback_escalation', 'none')}")

    # Step 10: Merge + validate
    log("  Step 10: Merge and validate...")
    # Remove internal stats keys before merging
    for key in ["heading_distribution", "dna_candidate_count",
                "article_distribution", "section_distribution"]:
        discovery.pop(key, None)

    merge_and_validate(
        base_strategy, discovery,
        dry_run=dry_run, workspace=workspace, family_id=family_id,
    )

    summary = {
        "family_id": family_id,
        "status": "ok",
        "matched": len(matched),
        "headings_discovered": len(heading_result["heading_patterns"]),
        "dna_tier1": len(dna_result["dna_tier1"]),
        "dna_tier2": len(dna_result["dna_tier2"]),
        "keywords": len(keyword_result["keyword_anchors"]),
        "defined_terms": len(term_result["defined_term_dependencies"]),
        "primary_articles": position_result["primary_articles"],
    }
    log(f"  Done: {json.dumps(summary, default=str)}")
    return summary


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Per-family discovery orchestrator (Layer 2)",
    )
    parser.add_argument(
        "--db", required=True, type=Path,
        help="Path to corpus DuckDB index",
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--family", type=str,
        help="Single family_id to discover (e.g., debt_capacity.indebtedness)",
    )
    group.add_argument(
        "--all", action="store_true",
        help="Run discovery for all families",
    )
    parser.add_argument(
        "--bootstrap", required=True, type=Path,
        help="Path to bootstrap_all.json",
    )
    parser.add_argument(
        "--family-notes", type=Path, default=None,
        help="Path to ontology_family_notes.json (provides domain guidance)",
    )
    parser.add_argument(
        "--exploratory-report", type=Path, default=None,
        help="Path to Layer 1 exploratory report JSON",
    )
    parser.add_argument(
        "--workspace", type=Path, default=None,
        help="Workspace directory for single family",
    )
    parser.add_argument(
        "--workspace-root", type=Path, default=None,
        help="Root workspace directory (for --all mode)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Show what would be done without writing files",
    )
    args = parser.parse_args()

    from agent.corpus import CorpusIndex

    log("Loading corpus...")
    corpus = CorpusIndex(args.db)

    try:
        family_concepts = load_family_concepts(args.bootstrap)
        notes = load_family_notes(args.family_notes)
        exploratory = load_exploratory_report(args.exploratory_report)

        if args.all:
            # Run all families
            workspace_root = args.workspace_root or Path("workspaces")
            summaries: list[dict[str, Any]] = []

            # Filter to active families if notes available
            target_families = sorted(family_concepts.keys())
            if notes:
                active = {
                    k for k, v in notes.items()
                    if v.get("status") == "active"
                }
                target_families = [
                    f for f in target_families
                    if f in active or any(f.startswith(a + ".") for a in active)
                ]

            log(f"Running discovery for {len(target_families)} families...")
            for fam_id in target_families:
                concepts = family_concepts.get(fam_id, [])
                if not concepts:
                    log(f"  Skipping {fam_id}: no bootstrap concepts")
                    continue

                workspace = workspace_root / fam_id.replace(".", "_")
                summary = run_family_discovery(
                    corpus=corpus,
                    family_id=fam_id,
                    concepts=concepts,
                    family_notes=notes,
                    exploratory_report=exploratory,
                    workspace=workspace,
                    dry_run=args.dry_run,
                )
                summaries.append(summary)

            # Output summary
            result = {
                "status": "ok",
                "families_processed": len(summaries),
                "summaries": summaries,
            }
            sys.stdout.buffer.write(_dumps(result))
            sys.stdout.buffer.write(b"\n")

        else:
            # Single family
            fam_id = args.family
            concepts = family_concepts.get(fam_id, [])
            if not concepts:
                # Try partial match
                for k in family_concepts:
                    if k.endswith(f".{fam_id}") or k == fam_id:
                        concepts = family_concepts[k]
                        fam_id = k
                        break

            if not concepts:
                log(f"ERROR: No concepts found for family '{args.family}'")
                sys.exit(1)

            workspace = args.workspace or Path(f"workspaces/{fam_id.replace('.', '_')}")
            summary = run_family_discovery(
                corpus=corpus,
                family_id=fam_id,
                concepts=concepts,
                family_notes=notes,
                exploratory_report=exploratory,
                workspace=workspace,
                dry_run=args.dry_run,
            )

            sys.stdout.buffer.write(_dumps(summary))
            sys.stdout.buffer.write(b"\n")

    finally:
        corpus.close()


if __name__ == "__main__":
    main()
