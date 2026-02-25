#!/usr/bin/env python3
"""Bulk family linker CLI — bootstraps ontology family links across a corpus.

Evaluates heading-filter rules from ``data/family_link_rules.json`` (or the
``family_link_rules`` table in an existing links.duckdb) against every section
in the corpus, computes 7-factor confidence scores, detects cross-family
conflicts, and either previews (``--dry-run``) or persists the results.

Usage examples:

    # Dry-run: preview candidates as JSON to stdout
    python3 scripts/bulk_family_linker.py \\
      --db corpus_index/corpus.duckdb \\
      --links-db /tmp/links.duckdb \\
      --rules data/family_link_rules.json \\
      --dry-run

    # Canary: apply to first 10 docs only
    python3 scripts/bulk_family_linker.py \\
      --db corpus_index/corpus.duckdb \\
      --links-db corpus_index/links.duckdb \\
      --canary 10

    # Full run for a single family
    python3 scripts/bulk_family_linker.py \\
      --db corpus_index/corpus.duckdb \\
      --links-db corpus_index/links.duckdb \\
      --family debt_capacity.indebtedness

Output:
    --dry-run: structured JSON to stdout with candidates, tiers, conflicts
    Normal:    run summary JSON to stdout, progress to stderr
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path
from typing import Any

# orjson with stdlib fallback
_orjson: Any
try:
    import orjson  # type: ignore[import-untyped]
    _orjson = orjson
except ImportError:
    _orjson = None


def _json_dumps(obj: Any) -> str:
    if _orjson is not None:
        return _orjson.dumps(obj, option=_orjson.OPT_INDENT_2).decode("utf-8")
    return json.dumps(obj, indent=2)


def _json_dumps_compact(obj: Any) -> str:
    if _orjson is not None:
        return _orjson.dumps(obj).decode("utf-8")
    return json.dumps(obj, separators=(",", ":"))


def _log(msg: str) -> None:
    """Write human-readable message to stderr."""
    print(msg, file=sys.stderr)


# ---------------------------------------------------------------------------
# Bootstrap rule loading
# ---------------------------------------------------------------------------

def load_rules_from_json(rules_path: Path) -> list[dict[str, Any]]:
    """Load rules from the bootstrap JSON file."""
    with open(rules_path) as f:
        data = json.load(f)
    raw_rules = data.get("rules", [])
    if not raw_rules:
        raise ValueError(f"No rules found in {rules_path}")
    return raw_rules


def bootstrap_rules_into_store(
    store: Any,
    rules_path: Path,
) -> list[dict[str, Any]]:
    """Load bootstrap rules from JSON and persist to the LinkStore.

    Only bootstraps if the store has no existing published rules.
    Returns the list of rules (whether newly bootstrapped or pre-existing).
    """
    existing = store.get_rules(status="published")
    if existing:
        _log(f"  Store already has {len(existing)} published rules; skipping bootstrap")
        return existing

    raw_rules = load_rules_from_json(rules_path)
    _log(f"  Bootstrapping {len(raw_rules)} rules from {rules_path}")

    for rule in raw_rules:
        store.save_rule(rule)

    return store.get_rules(status="published")


# ---------------------------------------------------------------------------
# Heading evaluation
# ---------------------------------------------------------------------------

def heading_matches_ast(
    heading: str,
    heading_filter_ast: dict[str, Any],
) -> tuple[bool, str, str]:
    """Evaluate whether a section heading matches a heading_filter AST.

    Returns (matched, match_type, matched_value):
    - matched: True if the heading matches any value in the AST
    - match_type: "exact" | "substring" | "partial" | "none"
    - matched_value: the specific value that matched (empty if none)
    """
    heading_lower = heading.lower().strip()
    if not heading_lower:
        return (False, "none", "")

    # Extract match values from the AST (simple OR-group of match nodes)
    try:
        values = _extract_ast_match_values(heading_filter_ast)
    except ValueError:
        return (False, "none", "")
    if not values:
        return (False, "none", "")

    for val in values:
        val_lower = val.lower().strip()
        if not val_lower:
            continue

        # Exact match
        if heading_lower == val_lower:
            return (True, "exact", val)

        # Pattern is substring of heading (heading contains the pattern)
        if val_lower in heading_lower:
            return (True, "substring", val)

    # Check for partial word overlap as a weaker signal
    heading_words = set(heading_lower.split())
    for val in values:
        val_lower = val.lower().strip()
        val_words = set(val_lower.split())
        overlap = heading_words & val_words
        # Require at least 50% word overlap for partial match
        if overlap and len(overlap) >= len(val_words) * 0.5:
            return (True, "partial", val)

    return (False, "none", "")


def _extract_ast_match_values(ast: Any) -> list[str]:
    """Extract all match values from a heading_filter_ast dict.

    Handles both the bootstrap JSON format and the FilterExpression format:
    - {"type": "group", "operator": "or", "children": [{"type": "match", "value": "..."}]}
    - {"op": "or", "children": [{"value": "..."}]}
    """
    if not isinstance(ast, dict):
        return []

    # Guardrails to avoid pathological recursion/memory abuse from malformed ASTs.
    max_depth = 32
    max_nodes = 2000

    values: list[str] = []
    stack: list[tuple[dict[str, Any], int]] = [(ast, 0)]
    visited_nodes = 0

    while stack:
        node, depth = stack.pop()
        visited_nodes += 1

        if depth > max_depth:
            raise ValueError(f"heading_filter_ast exceeds max depth ({max_depth})")
        if visited_nodes > max_nodes:
            raise ValueError(f"heading_filter_ast exceeds max nodes ({max_nodes})")

        node_type = str(node.get("type", "")).lower()
        op = node.get("op") or node.get("operator")

        # Leaf node
        if "value" in node and (node_type == "match" or op is None):
            if not node.get("negate", False):
                values.append(str(node["value"]))
            continue

        # Group node
        children = node.get("children", [])
        if isinstance(children, list):
            for child in children:
                if isinstance(child, dict):
                    stack.append((child, depth + 1))

    return values


# ---------------------------------------------------------------------------
# Article concept matching
# ---------------------------------------------------------------------------

def _get_article_concept(
    corpus: Any,
    doc_id: str,
    article_num: int,
) -> str | None:
    """Get the article concept for a given doc + article number."""
    articles = corpus.get_articles(doc_id)
    for art in articles:
        if art.article_num == article_num:
            return art.concept
    return None


def _article_matches_rule(
    article_concept: str | None,
    rule_article_concepts: list[str],
) -> bool:
    """Check if the section's article concept matches the rule's requirements."""
    if not rule_article_concepts:
        return True  # No article constraint
    if article_concept is None:
        return False
    return article_concept in rule_article_concepts


# ---------------------------------------------------------------------------
# Section scanning
# ---------------------------------------------------------------------------

def _compute_rule_hash(rule: dict[str, Any]) -> str:
    """Compute a deterministic hash of the rule for change tracking."""
    # Hash the key identifying fields
    key_fields = {
        "family_id": rule.get("family_id", ""),
        "version": rule.get("version", 1),
        "heading_filter_ast": rule.get("heading_filter_ast", {}),
        "article_concepts": rule.get("article_concepts", []),
    }
    serialized = json.dumps(key_fields, sort_keys=True)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()[:16]


def _build_candidate(
    section: Any,
    rule: dict[str, Any],
    match_type: str,
    matched_value: str,
    article_concept: str | None,
    confidence_result: Any,
    conflict_info: list[dict[str, str]],
) -> dict[str, Any]:
    """Build a candidate link dict from a matching section + rule."""
    return {
        "family_id": rule.get("family_id", ""),
        "doc_id": section.doc_id,
        "section_number": section.section_number,
        "heading": section.heading,
        "article_num": section.article_num,
        "article_concept": article_concept or "",
        "rule_id": rule.get("rule_id", ""),
        "rule_version": rule.get("version", 1),
        "rule_hash": _compute_rule_hash(rule),
        "source": "bulk_linker",
        "section_char_start": section.char_start,
        "section_char_end": section.char_end,
        "link_role": "primary_covenant",
        "confidence": confidence_result.score,
        "confidence_tier": confidence_result.tier,
        "confidence_breakdown": confidence_result.breakdown,
        "why_matched": confidence_result.why_matched,
        "match_type": match_type,
        "matched_value": matched_value,
        "status": "active" if confidence_result.tier == "high" else "pending_review",
        "conflicts": conflict_info,
    }


def scan_corpus_for_family(
    corpus: Any,
    rule: dict[str, Any],
    *,
    doc_ids: list[str] | None = None,
    conflict_matrix: dict[tuple[str, str], Any] | None = None,
    existing_links_by_section: dict[str, list[str]] | None = None,
    calibration: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Scan the corpus to find sections matching a single rule.

    Parameters
    ----------
    corpus:
        CorpusIndex instance for read-only corpus access.
    rule:
        Rule dict with family_id, heading_filter_ast, article_concepts, etc.
    doc_ids:
        Optional subset of document IDs to scan (for canary mode).
    conflict_matrix:
        Dict of (family_a, family_b) -> ConflictPolicy for conflict detection.
    existing_links_by_section:
        Dict of "doc_id::section_number" -> list[family_id] for conflict check.
    calibration:
        Per-family calibration overrides for confidence thresholds.

    Returns
    -------
    list[dict[str, Any]]
        List of candidate link dicts.
    """
    from agent.link_confidence import compute_link_confidence
    from agent.query_filters import filter_expr_from_json

    family_id = rule.get("family_id", "")
    heading_ast_raw = rule.get("heading_filter_ast", {})
    article_concepts = rule.get("article_concepts", [])

    # Parse the heading filter AST into a FilterExpression for confidence scoring
    heading_filter_expr = None
    try:
        if heading_ast_raw:
            heading_filter_expr = filter_expr_from_json(heading_ast_raw)
    except (ValueError, KeyError):
        heading_filter_expr = None

    # Expected defined terms for the defined_term_grounding factor
    expected_terms = rule.get("required_defined_terms") or []

    candidates: list[dict[str, Any]] = []

    # Determine documents to scan
    target_docs = doc_ids
    if target_docs is None:
        rows = corpus._conn.execute(
            "SELECT doc_id FROM documents WHERE cohort_included = true "
            "ORDER BY doc_id",
        ).fetchall()
        target_docs = [str(r[0]) for r in rows]

    for doc_id in target_docs:
        # Get all sections for this document
        sections = corpus.search_sections(doc_id=doc_id, cohort_only=False, limit=10000)

        # Build article concept lookup
        article_concepts_by_num: dict[int, str | None] = {}

        # Get defined terms in this document (for grounding factor)
        doc_defined_terms: list[str] = []
        try:
            defs = corpus.get_definitions(doc_id)
            doc_defined_terms = [d.term for d in defs]
        except Exception:
            pass

        for section in sections:
            # Step 1: Article concept check
            if section.article_num not in article_concepts_by_num:
                article_concepts_by_num[section.article_num] = _get_article_concept(
                    corpus, doc_id, section.article_num,
                )
            art_concept = article_concepts_by_num[section.article_num]

            if not _article_matches_rule(art_concept, article_concepts):
                continue

            # Step 2: Heading match check
            matched, match_type, matched_value = heading_matches_ast(
                section.heading, heading_ast_raw,
            )
            if not matched:
                continue

            # Step 3: Compute confidence score
            conf_kwargs: dict[str, Any] = {
                "heading": section.heading,
                "article_concept": art_concept,
                "rule_article_concepts": article_concepts,
                "template_family": None,
                "defined_terms_present": doc_defined_terms,
                "expected_defined_terms": expected_terms,
                "calibration": calibration,
            }
            if heading_filter_expr is not None:
                conf_kwargs["rule_heading_ast"] = heading_filter_expr
            else:
                # Fallback: create a minimal FilterMatch
                from agent.query_filters import FilterMatch
                conf_kwargs["rule_heading_ast"] = FilterMatch(
                    value=matched_value, negate=False,
                )

            confidence_result = compute_link_confidence(**conf_kwargs)

            # Step 4: Detect conflicts
            conflict_info = _detect_conflicts(
                family_id,
                doc_id,
                section.section_number,
                conflict_matrix,
                existing_links_by_section,
            )

            # Build candidate
            candidate = _build_candidate(
                section,
                rule,
                match_type,
                matched_value,
                art_concept,
                confidence_result,
                conflict_info,
            )
            candidates.append(candidate)

    return candidates


# ---------------------------------------------------------------------------
# Conflict detection
# ---------------------------------------------------------------------------

def _detect_conflicts(
    family_id: str,
    doc_id: str,
    section_number: str,
    conflict_matrix: dict[tuple[str, str], Any] | None,
    existing_links_by_section: dict[str, list[str]] | None,
) -> list[dict[str, str]]:
    """Detect conflicts between a new candidate and existing links.

    Returns a list of conflict dicts with keys: other_family, policy, reason.
    """
    if conflict_matrix is None or existing_links_by_section is None:
        return []

    from agent.conflict_matrix import lookup_policy

    section_key = f"{doc_id}::{section_number}"
    existing_families = existing_links_by_section.get(section_key, [])

    conflicts: list[dict[str, str]] = []
    for other_family in existing_families:
        if other_family == family_id:
            continue
        policy = lookup_policy(conflict_matrix, family_id, other_family)
        if policy in ("exclusive", "warn", "compound_covenant"):
            conflicts.append({
                "other_family": other_family,
                "policy": policy,
                "reason": f"{family_id} + {other_family} → {policy}",
            })

    return conflicts


# ---------------------------------------------------------------------------
# Main scanning orchestration
# ---------------------------------------------------------------------------

def run_bulk_linking(
    corpus: Any,
    store: Any,
    rules: list[dict[str, Any]],
    *,
    family_filter: str | None = None,
    canary_n: int | None = None,
    dry_run: bool = False,
    conflict_matrix: dict[tuple[str, str], Any] | None = None,
) -> dict[str, Any]:
    """Run the full bulk linking pipeline.

    Returns a summary dict with candidates, metrics, and run info.
    """
    start_time = time.time()

    # Filter rules by family if requested
    active_rules = [
        r for r in rules
        if r.get("status") in ("published", "draft", None)
    ]
    if family_filter:
        active_rules = [r for r in active_rules if r.get("family_id") == family_filter]

    if not active_rules:
        _log("No matching rules found")
        return {
            "status": "no_rules",
            "rules_evaluated": 0,
            "candidates": [],
            "by_family": {},
            "by_tier": {"high": 0, "medium": 0, "low": 0},
            "conflicts_detected": 0,
            "duration_seconds": 0.0,
        }

    _log(f"Evaluating {len(active_rules)} rules")

    # Determine doc subset for canary mode
    doc_ids: list[str] | None = None
    if canary_n is not None:
        rows = corpus._conn.execute(
            "SELECT doc_id FROM documents WHERE cohort_included = true "
            "ORDER BY doc_id LIMIT ?",
            [canary_n],
        ).fetchall()
        doc_ids = [str(r[0]) for r in rows]
        _log(f"Canary mode: scanning first {len(doc_ids)} documents")

    # Build existing links index for conflict detection
    existing_links_by_section: dict[str, list[str]] = {}
    if store is not None and not dry_run:
        try:
            all_links = store.get_links(status="active", limit=1000000)
            for lnk in all_links:
                key = f"{lnk['doc_id']}::{lnk['section_number']}"
                if key not in existing_links_by_section:
                    existing_links_by_section[key] = []
                existing_links_by_section[key].append(lnk["family_id"])
        except Exception:
            pass  # New store with no links

    # Scan for each rule
    all_candidates: list[dict[str, Any]] = []
    for i, rule in enumerate(active_rules):
        family = rule.get("family_id", "unknown")
        _log(f"  [{i + 1}/{len(active_rules)}] Scanning family={family}")

        candidates = scan_corpus_for_family(
            corpus,
            rule,
            doc_ids=doc_ids,
            conflict_matrix=conflict_matrix,
            existing_links_by_section=existing_links_by_section,
            calibration=None,
        )

        _log(f"    Found {len(candidates)} candidates")

        # Track new candidates in the existing_links index for cross-family conflict detection
        for cand in candidates:
            key = f"{cand['doc_id']}::{cand['section_number']}"
            if key not in existing_links_by_section:
                existing_links_by_section[key] = []
            if cand["family_id"] not in existing_links_by_section[key]:
                existing_links_by_section[key].append(cand["family_id"])

        all_candidates.extend(candidates)

    # Compute summary metrics
    by_family: dict[str, dict[str, int]] = {}
    by_tier = {"high": 0, "medium": 0, "low": 0}
    conflicts_detected = 0

    for cand in all_candidates:
        fam = cand["family_id"]
        if fam not in by_family:
            by_family[fam] = {"total": 0, "high": 0, "medium": 0, "low": 0, "conflicts": 0}
        by_family[fam]["total"] += 1
        tier = cand.get("confidence_tier", "low")
        by_family[fam][tier] = by_family[fam].get(tier, 0) + 1
        by_tier[tier] = by_tier.get(tier, 0) + 1

        if cand.get("conflicts"):
            conflicts_detected += 1
            by_family[fam]["conflicts"] += 1

    duration = time.time() - start_time

    # Persist if not dry-run
    run_id: str | None = None
    links_created = 0
    evidence_saved = 0

    if not dry_run and store is not None:
        import uuid

        run_id = str(uuid.uuid4())

        # Save run metadata
        store.create_run({
            "run_id": run_id,
            "run_type": "canary" if canary_n else "full",
            "family_id": family_filter or "_all",
            "rule_id": active_rules[0].get("rule_id") if len(active_rules) == 1 else None,
            "corpus_version": "bulk_linker_v1",
            "corpus_doc_count": len(doc_ids) if doc_ids else 0,
            "parser_version": "1.0",
            "links_created": 0,
            "conflicts_detected": conflicts_detected,
        })

        # Create links for high/medium confidence candidates
        linkable = [
            c for c in all_candidates
            if c.get("confidence_tier") in ("high", "medium")
        ]
        if linkable:
            links_created = store.create_links(linkable, run_id)
            _log(f"  Created {links_created} links (run_id={run_id})")

        # Save evidence
        evidence_rows: list[dict[str, Any]] = []
        for cand in all_candidates:
            evidence_rows.append({
                "doc_id": cand["doc_id"],
                "section_number": cand["section_number"],
                "family_id": cand["family_id"],
                "rule_id": cand.get("rule_id"),
                "evidence_type": "heading_match",
                "char_start": cand.get("section_char_start"),
                "char_end": cand.get("section_char_end"),
                "payload": _json_dumps_compact({
                    "match_type": cand.get("match_type"),
                    "matched_value": cand.get("matched_value"),
                    "confidence": cand.get("confidence"),
                    "tier": cand.get("confidence_tier"),
                }),
            })
        if evidence_rows:
            evidence_saved = store.save_evidence(evidence_rows)
            _log(f"  Saved {evidence_saved} evidence rows")

        # Update run with final link count
        store.complete_run(run_id, {
            "links_created": links_created,
            "conflicts_detected": conflicts_detected,
        })

    summary: dict[str, Any] = {
        "status": "dry_run" if dry_run else "completed",
        "run_id": run_id,
        "rules_evaluated": len(active_rules),
        "documents_scanned": len(doc_ids) if doc_ids else "all",
        "total_candidates": len(all_candidates),
        "links_created": links_created,
        "evidence_saved": evidence_saved,
        "by_family": by_family,
        "by_tier": by_tier,
        "conflicts_detected": conflicts_detected,
        "duration_seconds": round(duration, 2),
    }

    if dry_run:
        # Include full candidate details in dry-run output
        summary["candidates"] = all_candidates

    return summary


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser for the bulk family linker CLI."""
    parser = argparse.ArgumentParser(
        description="Bulk family linker: evaluate rules against corpus and create links",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--db", required=True,
        help="Path to corpus DuckDB (corpus_index/corpus.duckdb)",
    )
    parser.add_argument(
        "--links-db", required=True,
        help="Path to links DuckDB (corpus_index/links.duckdb)",
    )
    parser.add_argument(
        "--rules",
        default=None,
        help="Path to bootstrap rules JSON (default: data/family_link_rules.json)",
    )
    parser.add_argument(
        "--family",
        default=None,
        help="Filter to a single family (e.g., debt_capacity.indebtedness)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview candidates as JSON without persisting",
    )
    parser.add_argument(
        "--canary",
        type=int,
        default=None,
        metavar="N",
        help="Apply to first N documents only (canary mode)",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Verbose output to stderr",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Main entry point."""
    parser = build_parser()
    args = parser.parse_args(argv)

    # Validate paths
    db_path = Path(args.db)
    if not db_path.exists():
        _log(f"Error: corpus database not found: {db_path}")
        return 1

    links_db_path = Path(args.links_db)

    # Determine rules path
    rules_path: Path | None = None
    if args.rules:
        rules_path = Path(args.rules)
        if not rules_path.exists():
            _log(f"Error: rules file not found: {rules_path}")
            return 1
    else:
        default_rules = Path(__file__).resolve().parents[1] / "data" / "family_link_rules.json"
        if default_rules.exists():
            rules_path = default_rules

    # Import agent modules
    agent_src = Path(__file__).resolve().parents[1] / "src"
    if str(agent_src) not in sys.path:
        sys.path.insert(0, str(agent_src))

    from agent.corpus import CorpusIndex
    from agent.link_store import LinkStore

    # Open corpus (read-only)
    _log(f"Opening corpus: {db_path}")
    corpus = CorpusIndex(db_path)

    # Open or create links store
    _log(f"Opening links store: {links_db_path}")
    store = LinkStore(links_db_path, create_if_missing=True)

    # Load rules
    _log("Loading rules...")
    if rules_path:
        rules = bootstrap_rules_into_store(store, rules_path)
    else:
        rules = store.get_rules(status="published")
        if not rules:
            _log("Error: no published rules in store and no --rules file specified")
            store.close()
            return 1

    _log(f"  Loaded {len(rules)} rules")

    # Build conflict matrix from ontology (if available)
    conflict_matrix_dict: dict[tuple[str, str], Any] | None = None
    try:
        from agent.conflict_matrix import build_conflict_matrix, matrix_to_dict

        ontology_path = (
            Path(__file__).resolve().parents[1]
            / "data" / "ontology" / "r36a_production_ontology_v2.5.1.json"
        )
        if ontology_path.exists():
            with open(ontology_path) as f:
                ontology_data = json.load(f)
            ontology_edges = ontology_data.get("edges", [])
            ontology_nodes = {
                n["id"]: n
                for n in _flatten_ontology_nodes(ontology_data.get("nodes", []))
            }
            policies = build_conflict_matrix(ontology_edges, ontology_nodes)
            conflict_matrix_dict = matrix_to_dict(policies)
            _log(f"  Built conflict matrix: {len(conflict_matrix_dict)} pairs")
    except Exception as e:
        _log(f"  Warning: could not build conflict matrix: {e}")

    # Run the bulk linker
    _log("Starting bulk linking...")
    summary = run_bulk_linking(
        corpus,
        store,
        rules,
        family_filter=args.family,
        canary_n=args.canary,
        dry_run=args.dry_run,
        conflict_matrix=conflict_matrix_dict,
    )

    # Output summary JSON to stdout
    print(_json_dumps(summary))

    # Log summary to stderr
    _log(f"\nDone in {summary['duration_seconds']:.1f}s")
    _log(f"  Rules evaluated: {summary['rules_evaluated']}")
    _log(f"  Total candidates: {summary['total_candidates']}")
    _log(f"  By tier: {summary['by_tier']}")
    _log(f"  Conflicts: {summary['conflicts_detected']}")
    if not args.dry_run:
        _log(f"  Links created: {summary['links_created']}")

    store.close()
    return 0


def _flatten_ontology_nodes(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Recursively flatten ontology node tree into a flat list."""
    result: list[dict[str, Any]] = []
    for node in nodes:
        # Copy without children
        flat = {k: v for k, v in node.items() if k != "children"}
        result.append(flat)
        # Recurse into children
        children = node.get("children", [])
        if children:
            result.extend(_flatten_ontology_nodes(children))
    return result


if __name__ == "__main__":
    sys.exit(main())
