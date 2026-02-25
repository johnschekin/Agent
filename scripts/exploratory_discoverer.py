#!/usr/bin/env python3
"""Corpus-wide hypothesis-free exploratory discovery (Layer 1).

Discovers correlations between metadata fields, structural patterns,
and cross-family relationships without preconceived hypotheses.
The data speaks first; then we decide what's actionable.

Usage:
    python3 scripts/exploratory_discoverer.py \\
      --db corpus_index/corpus.duckdb \\
      --bootstrap data/bootstrap/bootstrap_all.json \\
      --ontology data/ontology/r36a_production_ontology_v2.6.0.json \\
      --family-notes docs/ontology_family_notes.json \\
      --output plans/exploratory_report.json \\
      [--sample 500] [--seed 42]

Structured JSON output goes to --output; human messages go to stderr.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

try:
    import orjson

    def _write_json(obj: Any, path: Path) -> None:
        path.write_bytes(orjson.dumps(obj, option=orjson.OPT_INDENT_2))

except ImportError:

    def _write_json(obj: Any, path: Path) -> None:
        with open(path, "w") as f:
            json.dump(obj, f, indent=2, default=str)


def log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


# ---------------------------------------------------------------------------
# Bootstrap + family notes loading
# ---------------------------------------------------------------------------

def load_bootstrap_heading_patterns(
    bootstrap_path: Path,
) -> dict[str, list[str]]:
    """Load family_id → heading_patterns from bootstrap_all.json.

    Groups concepts by family_id and merges their heading_patterns.
    """
    raw = json.loads(bootstrap_path.read_bytes())
    family_headings: dict[str, set[str]] = {}

    for concept in raw.values():
        if not isinstance(concept, dict):
            continue
        fam_id = concept.get("family_id", "")
        search = concept.get("search_strategy", {})
        if not isinstance(search, dict):
            continue
        patterns = search.get("heading_patterns", [])
        if not isinstance(patterns, list):
            continue
        if fam_id:
            family_headings.setdefault(fam_id, set()).update(
                str(p) for p in patterns if p
            )

    return {fam: sorted(pats) for fam, pats in family_headings.items()}


def load_family_notes(notes_path: Path) -> dict[str, Any]:
    """Load ontology_family_notes.json and return only active families' notes."""
    raw = json.loads(notes_path.read_bytes())
    result: dict[str, Any] = {}
    for key, val in raw.items():
        if key.startswith("_") or not isinstance(val, dict):
            continue
        status = val.get("status", "active")
        if status == "active":
            result[key] = val
    return result


# ---------------------------------------------------------------------------
# Section loading + family matching
# ---------------------------------------------------------------------------

def load_all_sections(
    corpus: Any,
    doc_ids: list[str],
) -> dict[str, list[dict[str, Any]]]:
    """Bulk-load all sections from corpus, grouped by doc_id."""
    rows = corpus.query(
        """
        SELECT doc_id, section_number, heading, article_num, char_start, word_count
        FROM sections
        WHERE doc_id = ANY(?)
        ORDER BY doc_id, char_start
        """,
        [doc_ids],
    )
    result: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        doc_id = str(row[0])
        entry = {
            "doc_id": doc_id,
            "section_number": str(row[1]),
            "heading": str(row[2]),
            "article_num": int(row[3] or 0),
            "char_start": int(row[4] or 0),
            "word_count": int(row[5] or 0),
        }
        result.setdefault(doc_id, []).append(entry)
    return result


def match_families_to_sections(
    family_heading_patterns: dict[str, list[str]],
    all_sections: dict[str, list[dict[str, Any]]],
) -> dict[str, list[tuple[str, str, int]]]:
    """Match families to sections using heading_matches().

    Returns:
        family_id → [(doc_id, section_number, article_num), ...]
    """
    from agent.textmatch import heading_matches

    result: dict[str, list[tuple[str, str, int]]] = {}

    for doc_id, sections in all_sections.items():
        for sec in sections:
            heading = sec["heading"]
            for fam_id, patterns in family_heading_patterns.items():
                if heading_matches(heading, patterns):
                    result.setdefault(fam_id, []).append((
                        doc_id,
                        sec["section_number"],
                        sec["article_num"],
                    ))

    return result


def build_ordered_sections(
    all_sections: dict[str, list[dict[str, Any]]],
) -> tuple[
    dict[str, list[tuple[str, str, int, int]]],
    dict[str, list[tuple[str, str, str, int, int]]],
]:
    """Build ordered section tuples for discovery primitives.

    Returns:
        (without_headings, with_headings) —
        without: doc_id → [(doc_id, section_number, article_num, position), ...]
        with: doc_id → [(doc_id, section_number, heading, article_num, position), ...]
    """
    without: dict[str, list[tuple[str, str, int, int]]] = {}
    with_h: dict[str, list[tuple[str, str, str, int, int]]] = {}

    for doc_id, sections in all_sections.items():
        wo_list: list[tuple[str, str, int, int]] = []
        wh_list: list[tuple[str, str, str, int, int]] = []
        for pos, sec in enumerate(sections):
            wo_list.append((
                doc_id, sec["section_number"], sec["article_num"], pos,
            ))
            wh_list.append((
                doc_id, sec["section_number"], sec["heading"], sec["article_num"], pos,
            ))
        without[doc_id] = wo_list
        with_h[doc_id] = wh_list

    return without, with_h


# ---------------------------------------------------------------------------
# Feature aggregation
# ---------------------------------------------------------------------------

def aggregate_doc_features(
    corpus: Any,
    doc_ids: list[str],
) -> dict[str, list[float | None]]:
    """Aggregate metadata + structural features per document.

    Columns: facility_size_mm, closing_ebitda_mm, word_count, section_count,
    clause_count, definition_count, avg_scope_permit_count,
    avg_preemption_depth, article_count, avg_section_word_count,
    median_clause_depth.
    """
    # Metadata from documents table
    doc_data: dict[str, dict[str, Any]] = {}
    rows = corpus.query(
        """
        SELECT doc_id, facility_size_mm, closing_ebitda_mm, word_count,
               section_count, clause_count, definition_count
        FROM documents
        WHERE doc_id = ANY(?)
        """,
        [doc_ids],
    )
    for row in rows:
        did = str(row[0])
        doc_data[did] = {
            "facility_size_mm": float(row[1]) if row[1] is not None else None,
            "closing_ebitda_mm": float(row[2]) if row[2] is not None else None,
            "word_count": float(row[3] or 0),
            "section_count": float(row[4] or 0),
            "clause_count": float(row[5] or 0),
            "definition_count": float(row[6] or 0),
        }

    # Structural aggregates from section_features
    if corpus.has_table("section_features"):
        sf_rows = corpus.query(
            """
            SELECT doc_id,
                   AVG(scope_permit_count) as avg_scope_permit,
                   AVG(preemption_estimated_depth) as avg_preemption_depth,
                   COUNT(DISTINCT article_num) as article_count,
                   AVG(word_count) as avg_section_wc
            FROM section_features
            WHERE doc_id = ANY(?)
            GROUP BY doc_id
            """,
            [doc_ids],
        )
        for row in sf_rows:
            did = str(row[0])
            if did in doc_data:
                doc_data[did]["avg_scope_permit_count"] = float(row[1] or 0)
                doc_data[did]["avg_preemption_depth"] = float(row[2] or 0)
                doc_data[did]["article_count"] = float(row[3] or 0)
                doc_data[did]["avg_section_word_count"] = float(row[4] or 0)

    # Median clause depth from clause_features
    if corpus.has_table("clause_features"):
        cf_rows = corpus.query(
            """
            SELECT doc_id, depth
            FROM clause_features
            WHERE doc_id = ANY(?)
            """,
            [doc_ids],
        )
        depth_by_doc: dict[str, list[int]] = {}
        for row in cf_rows:
            did = str(row[0])
            depth_by_doc.setdefault(did, []).append(int(row[1] or 0))

        for did, depths in depth_by_doc.items():
            if did in doc_data:
                doc_data[did]["median_clause_depth"] = float(
                    statistics.median(depths) if depths else 0
                )

    # Build columnar format
    feature_names = [
        "facility_size_mm", "closing_ebitda_mm", "word_count",
        "section_count", "clause_count", "definition_count",
        "avg_scope_permit_count", "avg_preemption_depth",
        "article_count", "avg_section_word_count", "median_clause_depth",
    ]
    columns: dict[str, list[float | None]] = {name: [] for name in feature_names}

    for did in doc_ids:
        data = doc_data.get(did, {})
        for name in feature_names:
            val = data.get(name)
            columns[name].append(float(val) if val is not None else None)

    return columns


def load_section_features_for_family(
    corpus: Any,
    family_sections: list[tuple[str, str, int]],
) -> tuple[list[dict[str, float]], list[tuple[str, str]]]:
    """Load section feature vectors for a family's matched sections.

    Returns:
        (feature_vectors, section_ids) — parallel lists.
    """
    feature_vectors: list[dict[str, float]] = []
    section_ids: list[tuple[str, str]] = []

    # Group by doc to batch queries
    by_doc: dict[str, list[str]] = {}
    for doc_id, sec_num, _ in family_sections:
        by_doc.setdefault(doc_id, []).append(sec_num)

    for doc_id, sec_nums in by_doc.items():
        doc_features = corpus.get_section_features(doc_id)
        for sec_num in sec_nums:
            feat_rec = doc_features.get(sec_num)
            if feat_rec is None:
                continue
            fv: dict[str, float] = {
                "word_count": float(feat_rec.word_count),
                "char_count": float(feat_rec.char_count),
                "scope_operator_count": float(feat_rec.scope_operator_count),
                "scope_permit_count": float(feat_rec.scope_permit_count),
                "scope_restrict_count": float(feat_rec.scope_restrict_count),
                "preemption_override_count": float(feat_rec.preemption_override_count),
                "preemption_yield_count": float(feat_rec.preemption_yield_count),
                "preemption_estimated_depth": float(feat_rec.preemption_estimated_depth),
            }
            feature_vectors.append(fv)
            section_ids.append((doc_id, sec_num))

    return feature_vectors, section_ids


# ---------------------------------------------------------------------------
# Report construction
# ---------------------------------------------------------------------------

def build_report(
    *,
    params: dict[str, Any],
    corpus_stats: dict[str, Any],
    cooccurrence: Any,
    correlations: list[Any],
    adjacency_patterns: dict[str, list[Any]],
    anomalies_by_family: dict[str, list[Any]],
    clusters_by_family: dict[str, Any],
    template_conditioned: dict[str, list[Any]],
) -> dict[str, Any]:
    """Assemble the full exploratory report."""
    # Serialize cooccurrence
    cooc_dict: dict[str, Any] = {}
    if cooccurrence is not None:
        cooc_dict = {
            "families": list(cooccurrence.families),
            "doc_level": [list(row) for row in cooccurrence.doc_matrix],
            "article_level": [list(row) for row in cooccurrence.article_matrix],
            "adjacency_level": [list(row) for row in cooccurrence.adjacency_matrix],
        }

    # Serialize correlations
    corr_list = [
        {
            "feature_a": c.feature_a,
            "feature_b": c.feature_b,
            "pearson_r": c.pearson_r,
            "spearman_rho": c.spearman_rho,
            "n": c.n,
        }
        for c in correlations
    ]

    # Serialize adjacency patterns
    adj_dict: dict[str, list[dict[str, Any]]] = {}
    for fam, patterns in adjacency_patterns.items():
        adj_dict[fam] = [
            {
                "position": p.position,
                "heading": p.neighbor_heading,
                "frequency": p.frequency,
                "doc_count": p.doc_count,
            }
            for p in patterns[:20]  # top 20 per family
        ]

    # Serialize anomalies
    anom_dict: dict[str, list[dict[str, Any]]] = {}
    for fam, anomalies in anomalies_by_family.items():
        anom_dict[fam] = [
            {
                "doc_id": a.doc_id,
                "section_number": a.section_number,
                "z_score": a.z_score,
                "top_features": [
                    {"feature": f, "value": v, "z": z}
                    for f, v, z in a.anomalous_features[:5]
                ],
            }
            for a in anomalies[:10]  # top 10 per family
        ]

    # Serialize clusters
    clust_dict: dict[str, dict[str, Any]] = {}
    for fam, cr in clusters_by_family.items():
        if cr is None:
            continue
        clust_dict[fam] = {
            "n_clusters": cr.n_clusters,
            "silhouette": cr.silhouette_score,
            "pca_variance": list(cr.pca_explained_variance),
            "feature_names": list(cr.feature_names),
            "cluster_summaries": [dict(s) for s in cr.cluster_summaries],
        }

    # Serialize template-conditioned profiles
    tpl_dict: dict[str, list[dict[str, Any]]] = {}
    for fam, profiles in template_conditioned.items():
        tpl_dict[fam] = [
            {
                "template_family": p.template_family,
                "section_count": p.section_count,
                "avg_article_num": p.avg_article_num,
                "heading_distribution": p.heading_distribution,
                "feature_means": p.feature_means,
            }
            for p in profiles[:10]  # top 10 templates per family
        ]

    return {
        "status": "ok",
        "generated_at": datetime.now(UTC).isoformat(),
        "params": params,
        "corpus_stats": corpus_stats,
        "cooccurrence": cooc_dict,
        "correlations": corr_list,
        "adjacency_patterns": adj_dict,
        "anomalies_by_family": anom_dict,
        "clusters_by_family": clust_dict,
        "template_conditioned": tpl_dict,
    }


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def run_exploratory_discovery(
    *,
    db_path: Path,
    bootstrap_path: Path,
    family_notes_path: Path | None,
    output_path: Path,
    sample: int | None,
    seed: int,
) -> dict[str, Any]:
    """Execute the full Layer 1 exploratory discovery pipeline."""
    from agent.corpus import CorpusIndex
    from agent.discovery import (
        cluster_family_sections,
        compute_cooccurrence,
        compute_correlations,
        compute_template_conditioned_profiles_with_headings,
        extract_adjacency_patterns_with_headings,
        score_anomalies,
    )

    log("Loading corpus index...")
    corpus = CorpusIndex(db_path)

    try:
        # Step 1: Load families and heading patterns
        log("Loading bootstrap heading patterns...")
        family_headings = load_bootstrap_heading_patterns(bootstrap_path)
        log(f"  Loaded {len(family_headings)} families from bootstrap")

        # Filter to active families if family notes provided
        active_family_ids: set[str] | None = None
        if family_notes_path and family_notes_path.exists():
            log("Loading family notes for active filter...")
            notes = load_family_notes(family_notes_path)
            active_family_ids = set(notes.keys())
            # Also include families whose parent is active
            for fam_id in list(family_headings.keys()):
                parts = fam_id.rsplit(".", 1)
                if len(parts) > 1 and parts[0] in active_family_ids:
                    active_family_ids.add(fam_id)
            log(f"  {len(active_family_ids)} active families from notes")

        if active_family_ids is not None:
            family_headings = {
                fam: pats for fam, pats in family_headings.items()
                if fam in active_family_ids
                or any(fam.startswith(a + ".") for a in active_family_ids)
            }
            log(f"  After filtering: {len(family_headings)} families")

        # Step 2: Load documents and sample
        if sample:
            doc_ids = corpus.sample_docs(sample, seed=seed)
            log(f"Sampled {len(doc_ids)} documents (seed={seed})")
        else:
            doc_ids = corpus.doc_ids()
            log(f"Loaded all {len(doc_ids)} cohort documents")

        # Step 3: Bulk-load sections
        log("Loading sections from corpus...")
        all_sections = load_all_sections(corpus, doc_ids)
        total_sections = sum(len(s) for s in all_sections.values())
        log(f"  Loaded {total_sections} sections from {len(all_sections)} docs")

        # Step 4: Match families to sections
        log("Matching families to sections via heading patterns...")
        family_sections = match_families_to_sections(
            family_headings, all_sections,
        )
        total_matches = sum(len(s) for s in family_sections.values())
        log(f"  Matched {total_matches} sections across {len(family_sections)} families")

        # Build ordered section structures
        ordered_no_heading, ordered_with_heading = build_ordered_sections(all_sections)

        # Step 5: Co-occurrence
        log("Computing co-occurrence matrix (3 levels)...")
        cooc = compute_cooccurrence(family_sections, ordered_no_heading)
        log(f"  {len(cooc.families)}×{len(cooc.families)} matrix computed")

        # Step 6: Metadata-structural correlations
        log("Computing metadata-structural correlations...")
        doc_features = aggregate_doc_features(corpus, doc_ids)
        correlations = compute_correlations(doc_features)
        significant = [c for c in correlations if abs(c.pearson_r) > 0.3]
        log(f"  {len(correlations)} pairs computed, {len(significant)} with |r|>0.3")

        # Step 7: Adjacency patterns
        log("Extracting adjacency patterns (per-family, window=2)...")
        adjacency = extract_adjacency_patterns_with_headings(
            family_sections, ordered_with_heading,
            window=2, min_frequency=3,
        )
        adj_count = sum(len(p) for p in adjacency.values())
        log(f"  {adj_count} adjacency patterns across {len(adjacency)} families")

        # Step 8: Anomaly scoring per family
        log("Scoring anomalies per family...")
        anomalies_by_family: dict[str, list[Any]] = {}
        for fam, sections in family_sections.items():
            if len(sections) < 10:
                continue
            fv, sids = load_section_features_for_family(corpus, sections)
            if len(fv) < 10:
                continue
            anomalies = score_anomalies(fv, sids, threshold_z=2.5)
            if anomalies:
                anomalies_by_family[fam] = anomalies
        log(f"  Anomalies found in {len(anomalies_by_family)} families")

        # Step 9: Clustering per family
        log("Clustering family sections (PCA + KMeans)...")
        clusters_by_family: dict[str, Any] = {}
        for fam, sections in family_sections.items():
            if len(sections) < 30:
                continue
            fv, _ = load_section_features_for_family(corpus, sections)
            if len(fv) < 30:
                continue
            cr = cluster_family_sections(fv, max_clusters=8, pca_components=3)
            if cr is not None:
                clusters_by_family[fam] = cr
        log(f"  Clustered {len(clusters_by_family)} families")

        # Step 10: Template-conditioned profiles
        log("Computing template-conditioned profiles...")
        # Build family sections with template info
        doc_templates: dict[str, str] = {}
        for did in doc_ids:
            doc = corpus.get_doc(did)
            if doc:
                doc_templates[did] = doc.template_family

        fam_secs_with_tpl: dict[str, list[tuple[str, str, int, str, str]]] = {}
        for fam, sections in family_sections.items():
            entries: list[tuple[str, str, int, str, str]] = []
            for doc_id, sec_num, article_num in sections:
                template = doc_templates.get(doc_id, "unknown")
                # Look up heading
                doc_secs = all_sections.get(doc_id, [])
                heading = ""
                for ds in doc_secs:
                    if ds["section_number"] == sec_num:
                        heading = ds["heading"]
                        break
                entries.append((doc_id, sec_num, article_num, template, heading))
            fam_secs_with_tpl[fam] = entries

        # Section features as dict for profiling
        sec_feat_dict: dict[tuple[str, str], dict[str, float]] = {}
        for _fam, sections in family_sections.items():
            fv, sids = load_section_features_for_family(corpus, sections)
            for feat, sid in zip(fv, sids, strict=True):
                sec_feat_dict[sid] = feat

        tpl_profiles = compute_template_conditioned_profiles_with_headings(
            fam_secs_with_tpl, sec_feat_dict,
        )
        log(f"  Profiles for {len(tpl_profiles)} families")

        # Assemble report
        report = build_report(
            params={"sample": sample, "seed": seed},
            corpus_stats={
                "docs_analyzed": len(doc_ids),
                "families_matched": len(family_sections),
                "sections_matched": total_matches,
            },
            cooccurrence=cooc,
            correlations=correlations,
            adjacency_patterns=adjacency,
            anomalies_by_family=anomalies_by_family,
            clusters_by_family=clusters_by_family,
            template_conditioned=tpl_profiles,
        )

        # Write output
        output_path.parent.mkdir(parents=True, exist_ok=True)
        _write_json(report, output_path)
        log(f"\nReport written to {output_path}")
        log(f"  {len(doc_ids)} docs | {len(family_sections)} families "
            f"| {total_matches} section matches")

        return report

    finally:
        corpus.close()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Corpus-wide hypothesis-free exploratory discovery (Layer 1)",
    )
    parser.add_argument(
        "--db", required=True, type=Path,
        help="Path to corpus DuckDB index",
    )
    parser.add_argument(
        "--bootstrap", required=True, type=Path,
        help="Path to bootstrap_all.json",
    )
    parser.add_argument(
        "--ontology", type=Path, default=None,
        help="Path to ontology JSON (reserved for future use)",
    )
    parser.add_argument(
        "--family-notes", type=Path, default=None,
        help="Path to ontology_family_notes.json (filters to active families)",
    )
    parser.add_argument(
        "--output", required=True, type=Path,
        help="Path for output JSON report",
    )
    parser.add_argument(
        "--sample", type=int, default=None,
        help="Sample N documents (default: all)",
    )
    parser.add_argument(
        "--seed", type=int, default=42,
        help="Random seed for sampling (default: 42)",
    )
    args = parser.parse_args()

    run_exploratory_discovery(
        db_path=args.db,
        bootstrap_path=args.bootstrap,
        family_notes_path=args.family_notes,
        output_path=args.output,
        sample=args.sample,
        seed=args.seed,
    )


if __name__ == "__main__":
    main()
