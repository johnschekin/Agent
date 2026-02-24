#!/usr/bin/env python3
"""Hit rates by template group (or any grouping column).

Usage:
    python3 scripts/coverage_reporter.py --db corpus_index/corpus.duckdb \
      --strategy strategies/indebtedness.json --group-by template_family

Structured JSON output goes to stdout; human messages go to stderr.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

try:
    import orjson

    def dump_json(obj: Any) -> None:
        sys.stdout.buffer.write(orjson.dumps(obj, option=orjson.OPT_INDENT_2))
        sys.stdout.buffer.write(b"\n")
except ImportError:

    def dump_json(obj: Any) -> None:
        json.dump(obj, sys.stdout, indent=2, default=str)
        print()


from agent.corpus import CorpusIndex, load_candidate_doc_ids
from agent.structural_fingerprint import build_section_fingerprint, summarize_fingerprints
from agent.strategy import Strategy, load_strategy_with_views
from agent.textmatch import heading_matches, keyword_density, section_dna_density, score_in_range


# ---------------------------------------------------------------------------
# Scoring (shared with pattern_tester)
# ---------------------------------------------------------------------------

HEADING_SCORE = 0.80
KEYWORD_MIN = 0.40
KEYWORD_MAX = 0.70
DNA_MIN = 0.25
DNA_MAX = 0.55
HIT_THRESHOLD = 0.3
_CLUSTER_FAMILY_RE = re.compile(r"^cluster_(\d+)$")


def _load_template_classifications(path: Path) -> dict[str, dict[str, Any]]:
    """Load doc_id -> classification metadata JSON map."""
    try:
        payload = json.loads(path.read_text())
    except Exception:
        return {}
    if not isinstance(payload, dict):
        return {}
    result: dict[str, dict[str, Any]] = {}
    for raw_doc_id, raw_meta in payload.items():
        doc_id = str(raw_doc_id)
        if isinstance(raw_meta, dict):
            result[doc_id] = raw_meta
    return result


def _extract_cluster_values(
    *,
    template_family: str,
    classification: dict[str, Any] | None,
) -> tuple[str, str]:
    """Return (cluster_id_value, cluster_label) from metadata/family text."""
    if isinstance(classification, dict):
        raw_cluster = classification.get("cluster_id")
        if isinstance(raw_cluster, int):
            if raw_cluster < 0:
                return "noise", "noise"
            return str(raw_cluster), f"cluster_{raw_cluster:03d}"
        if isinstance(raw_cluster, str):
            parsed = raw_cluster.strip()
            if parsed:
                if parsed == "-1":
                    return "noise", "noise"
                if parsed.isdigit():
                    val = int(parsed)
                    return str(val), f"cluster_{val:03d}"

        family_from_meta = str(classification.get("template_family", "")).strip().lower()
        if family_from_meta:
            if family_from_meta == "noise":
                return "noise", "noise"
            m_meta = _CLUSTER_FAMILY_RE.match(family_from_meta)
            if m_meta:
                val = int(m_meta.group(1))
                return str(val), f"cluster_{val:03d}"
            return "unknown", family_from_meta

    family = (template_family or "").strip().lower()
    if not family:
        return "unknown", "unknown"
    if family == "noise":
        return "noise", "noise"
    m = _CLUSTER_FAMILY_RE.match(family)
    if m:
        val = int(m.group(1))
        return str(val), f"cluster_{val:03d}"
    return "unknown", family


def score_section(
    heading: str,
    text_lower: str,
    strategy: Strategy,
) -> tuple[float, str]:
    """Score a section against a strategy.

    Returns (score, match_method).
    """
    best_score = 0.0
    method = "none"

    # Heading match
    heading_pat = heading_matches(heading, list(strategy.heading_patterns))
    if heading_pat is not None:
        best_score = HEADING_SCORE
        method = "heading"

    # Keyword density
    kw_density, _ = keyword_density(text_lower, list(strategy.keyword_anchors))
    kw_score = score_in_range(KEYWORD_MIN, KEYWORD_MAX, kw_density)
    if kw_density > 0:
        composite = max(best_score, kw_score)
        if composite > best_score:
            best_score = composite
            method = "keyword"

    # DNA density
    dna_density, _ = section_dna_density(
        text_lower, list(strategy.dna_tier1), list(strategy.dna_tier2)
    )
    dna_score = score_in_range(DNA_MIN, DNA_MAX, dna_density)
    if dna_density > 0:
        composite = max(best_score, dna_score)
        if composite > best_score:
            best_score = composite
            method = "dna"

    # Composite boost: heading + keyword or heading + dna
    if heading_pat is not None and (kw_density > 0 or dna_density > 0):
        combined = HEADING_SCORE + kw_score * 0.3 + dna_score * 0.2
        if combined > best_score:
            best_score = combined
            method = "composite"

    return best_score, method


def best_doc_match(
    corpus: CorpusIndex,
    doc_id: str,
    strategy: Strategy,
    *,
    cohort_only: bool,
) -> dict[str, Any]:
    """Return best section match details for a document."""
    sections = corpus.search_sections(
        doc_id=doc_id,
        cohort_only=cohort_only,
        limit=9999,
    )
    best = 0.0
    best_section = ""
    best_heading = ""
    best_article_num = 0
    best_text = ""
    for sec in sections:
        text = corpus.get_section_text(doc_id, sec.section_number)
        text_lower = text.lower() if text else ""
        score, _ = score_section(sec.heading, text_lower, strategy)
        if score > best:
            best = score
            best_section = sec.section_number
            best_heading = sec.heading
            best_article_num = sec.article_num
            best_text = text
    return {
        "score": best,
        "section_number": best_section,
        "heading": best_heading,
        "article_num": best_article_num,
        "text": best_text,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run(args: argparse.Namespace) -> None:
    strategy, raw_strategy, _resolved_strategy = load_strategy_with_views(Path(args.strategy))
    group_by = args.group_by
    cohort_only = not args.include_all
    run_id = args.run_id or (
        f"coverage_reporter_{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}_{uuid4().hex[:8]}"
    )
    print(f"Loaded strategy: {strategy.concept_id} v{strategy.version}", file=sys.stderr)
    print(f"Grouping by: {group_by}", file=sys.stderr)

    template_classifications: dict[str, dict[str, Any]] = {}
    if args.template_classifications:
        classifications_path = Path(args.template_classifications)
        template_classifications = _load_template_classifications(classifications_path)
        print(
            f"Loaded template classifications: {len(template_classifications)} docs",
            file=sys.stderr,
        )

    with CorpusIndex(Path(args.db)) as corpus:
        # Determine doc list
        if args.doc_ids:
            doc_id_path = Path(args.doc_ids)
            doc_ids = [
                line.strip()
                for line in doc_id_path.read_text().splitlines()
                if line.strip()
            ]
            print(f"Loaded {len(doc_ids)} doc IDs from {args.doc_ids}", file=sys.stderr)
        elif args.sample:
            doc_ids = corpus.sample_docs(
                args.sample,
                seed=args.seed,
                cohort_only=cohort_only,
            )
            print(f"Sampled {len(doc_ids)} docs (seed={args.seed})", file=sys.stderr)
        else:
            doc_ids = corpus.doc_ids(cohort_only=cohort_only)
            print(f"Testing all {len(doc_ids)} docs", file=sys.stderr)

        source_doc_count = len(doc_ids)
        candidate_input_count = 0
        if args.family_candidates_in:
            candidate_path = Path(args.family_candidates_in)
            candidate_doc_ids = load_candidate_doc_ids(candidate_path)
            candidate_input_count = len(candidate_doc_ids)
            candidate_set = set(candidate_doc_ids)
            doc_ids = [doc_id for doc_id in doc_ids if doc_id in candidate_set]
            print(
                "Applied family candidate filter: "
                f"{len(doc_ids)}/{source_doc_count} docs remain",
                file=sys.stderr,
            )

        # Group docs and score
        group_hits: defaultdict[str, int] = defaultdict(int)
        group_totals: defaultdict[str, int] = defaultdict(int)
        group_fingerprints: defaultdict[str, list] = defaultdict(list)
        total_hits = 0
        hit_doc_ids: list[str] = []

        for i, doc_id in enumerate(doc_ids):
            if (i + 1) % 100 == 0:
                print(f"  Progress: {i + 1}/{len(doc_ids)}", file=sys.stderr)

            # Get group value
            doc_rec = corpus.get_doc(doc_id)
            classification = template_classifications.get(doc_id)
            template_family_from_doc = doc_rec.template_family if doc_rec else ""
            template_family_from_cls = (
                str(classification.get("template_family", "")).strip()
                if isinstance(classification, dict)
                else ""
            )
            resolved_template_family = (
                template_family_from_cls
                or str(template_family_from_doc or "").strip()
                or "unknown"
            )

            if group_by == "template_family":
                group_val = resolved_template_family
            elif group_by in {"cluster_id", "template_cluster"}:
                cluster_id_val, cluster_label = _extract_cluster_values(
                    template_family=resolved_template_family,
                    classification=classification,
                )
                group_val = cluster_id_val if group_by == "cluster_id" else cluster_label
            elif doc_rec is None:
                group_val = "unknown"
            else:
                group_val = getattr(doc_rec, group_by, None)
                if group_val is None:
                    group_val = "unknown"
                group_val = str(group_val)
                if not group_val:
                    group_val = "unknown"

            group_totals[group_val] += 1

            # Score document
            match = best_doc_match(
                corpus,
                doc_id,
                strategy,
                cohort_only=cohort_only,
            )
            if float(match["score"]) > HIT_THRESHOLD:
                group_hits[group_val] += 1
                total_hits += 1
                hit_doc_ids.append(doc_id)
                fp = build_section_fingerprint(
                    template_family=resolved_template_family,
                    article_num=int(match["article_num"]),
                    section_number=str(match["section_number"]),
                    heading=str(match["heading"]),
                    text=str(match["text"]),
                )
                group_fingerprints[group_val].append(fp)

        # Build output
        total = len(doc_ids)
        overall_hit_rate = round(total_hits / total, 4) if total > 0 else 0.0

        by_group: dict[str, dict[str, Any]] = {}
        for gv in sorted(group_totals.keys()):
            n = group_totals[gv]
            h = group_hits.get(gv, 0)
            by_group[gv] = {
                "hit_rate": round(h / n, 4) if n > 0 else 0.0,
                "n": n,
                "hits": h,
                "structural_fingerprint_summary": summarize_fingerprints(
                    group_fingerprints.get(gv, []),
                    top_tokens=12,
                ),
            }

        output: dict[str, Any] = {
            "schema_version": "coverage_reporter_v2",
            "run_id": run_id,
            "ontology_node_id": strategy.concept_id,
            "strategy": strategy.concept_id,
            "strategy_version": strategy.version,
            "strategy_profile": {
                "profile_type": strategy.profile_type,
                "inherits_from": strategy.inherits_from,
                "inheritance_active": bool(
                    isinstance(raw_strategy, dict)
                    and isinstance(raw_strategy.get("inherits_from"), str)
                    and raw_strategy.get("inherits_from", "").strip()
                ),
            },
            "overall": {
                "hit_rate": overall_hit_rate,
                "n": total,
                "hits": total_hits,
            },
            "by_group": by_group,
            "candidate_set": {
                "input_doc_count": source_doc_count,
                "candidate_input_count": candidate_input_count,
                "evaluated_doc_count": total,
                "pruning_ratio": (
                    round(1.0 - (total / source_doc_count), 4)
                    if source_doc_count > 0
                    else 0.0
                ),
            },
            "grouping": {
                "group_by": group_by,
                "template_classifications_loaded": len(template_classifications),
                "template_classifications_path": (
                    str(Path(args.template_classifications))
                    if args.template_classifications
                    else None
                ),
            },
        }

        if args.family_candidates_out:
            out_path = Path(args.family_candidates_out)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            candidate_payload = {
                "schema_version": "family_candidates_v1",
                "generated_at": datetime.now(UTC).isoformat(),
                "run_id": run_id,
                "ontology_node_id": strategy.concept_id,
                "strategy_version": strategy.version,
                "doc_ids": sorted(set(hit_doc_ids)),
                "source_doc_count": source_doc_count,
                "evaluated_doc_count": total,
                "hit_count": total_hits,
            }
            out_path.write_text(json.dumps(candidate_payload, indent=2))
            output["family_candidates_out"] = str(out_path)

        dump_json(output)

    print(
        f"Done: {total_hits}/{total} hits ({overall_hit_rate:.1%})",
        file=sys.stderr,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Hit rates by template group (or any grouping column)."
    )
    parser.add_argument("--db", required=True, help="Path to corpus.duckdb")
    parser.add_argument("--strategy", required=True, help="Path to strategy JSON file")
    parser.add_argument("--doc-ids", default=None, help="File with doc IDs to test (one per line)")
    parser.add_argument(
        "--group-by",
        default="template_family",
        help="Column to group by (default: template_family)",
    )
    parser.add_argument(
        "--template-classifications",
        default=None,
        help=(
            "Optional classifications JSON from template_classifier "
            "(doc_id -> cluster/template metadata). Used for template-family "
            "and cluster-id grouping."
        ),
    )
    parser.add_argument("--sample", type=int, default=None, help="Test on N random docs")
    parser.add_argument("--seed", type=int, default=42, help="Random seed for sampling")
    parser.add_argument(
        "--include-all",
        action="store_true",
        help="Include non-cohort documents (default is cohort-only).",
    )
    parser.add_argument(
        "--run-id",
        default=None,
        help="Optional run identifier for provenance; auto-generated when omitted.",
    )
    parser.add_argument(
        "--family-candidates-in",
        default=None,
        help=(
            "Optional candidate doc-id set (txt/json). "
            "When set, coverage runs only on this subset."
        ),
    )
    parser.add_argument(
        "--family-candidates-out",
        default=None,
        help="Optional path to persist hit doc_ids as a family candidate set JSON.",
    )
    args = parser.parse_args()
    run(args)


if __name__ == "__main__":
    main()
