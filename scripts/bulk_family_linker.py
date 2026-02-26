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
import re
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
    actual = _normalize_article_token(article_concept)
    if not actual:
        return False
    for raw_rule_value in rule_article_concepts:
        token = _normalize_article_token(raw_rule_value)
        if not token:
            continue
        # Support exact and coarse substring matching so
        # "negative" can match "NEGATIVE_COVENANTS".
        if actual == token or token in actual or actual in token:
            return True
    return False


def _normalize_article_token(value: str | None) -> str:
    raw = str(value or "").strip().lower()
    if not raw:
        return ""
    raw = re.sub(r"[^a-z0-9]+", "_", raw)
    raw = re.sub(r"_+", "_", raw).strip("_")
    return raw


def _extract_article_concepts_from_filter_dsl(filter_dsl: str) -> list[str]:
    """Best-effort extraction of article constraints from filter DSL."""
    text = str(filter_dsl or "").strip()
    if not text:
        return []
    try:
        from agent.rule_dsl import parse_dsl  # Lazy import for script startup speed
        from agent.query_filters import filter_expr_to_json
    except Exception:
        return []

    try:
        parsed = parse_dsl(text)
    except Exception:
        return []
    if not parsed.ok:
        return []

    article_expr = parsed.text_fields.get("article")
    if article_expr is None:
        return []
    try:
        values = _extract_ast_match_values(filter_expr_to_json(article_expr))
    except Exception:
        return []

    normalized = []
    seen: set[str] = set()
    for value in values:
        token = _normalize_article_token(value)
        if token and token not in seen:
            seen.add(token)
            normalized.append(token)
    return normalized


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
        "ontology_node_id": rule.get("ontology_node_id", rule.get("family_id", "")),
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


def _family_ancestors(family_id: str) -> list[str]:
    """Return nearest-to-root ancestors for dotted family IDs."""
    parts = [p for p in str(family_id or "").split(".") if p]
    if len(parts) <= 1:
        return []
    ancestors: list[str] = []
    for i in range(len(parts) - 1, 0, -1):
        ancestors.append(".".join(parts[:i]))
    return ancestors


def _rule_scope_id(rule: dict[str, Any]) -> str:
    ontology_node_id = str(rule.get("ontology_node_id") or "").strip()
    if ontology_node_id:
        return ontology_node_id
    return str(rule.get("family_id") or "").strip()


def _select_latest_rules_per_scope(rules: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep only the highest-version rule per ontology scope (or family fallback)."""
    best_by_scope: dict[str, dict[str, Any]] = {}
    for rule in rules:
        scope_id = _rule_scope_id(rule)
        if not scope_id:
            continue
        existing = best_by_scope.get(scope_id)
        if existing is None:
            best_by_scope[scope_id] = rule
            continue
        if int(rule.get("version") or 0) > int(existing.get("version") or 0):
            best_by_scope[scope_id] = rule
    return list(best_by_scope.values())


def _resolve_parent_family(rule: dict[str, Any], families_with_rules: set[str]) -> str | None:
    explicit_parent = str(rule.get("parent_family_id") or "").strip()
    if explicit_parent and explicit_parent in families_with_rules:
        return explicit_parent
    family_id = str(rule.get("family_id") or "").strip()
    for ancestor in _family_ancestors(family_id):
        if ancestor in families_with_rules:
            return ancestor
    return None


def _order_rules_by_hierarchy(rules: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Sort rules so likely parents run before descendants."""
    return sorted(
        rules,
        key=lambda rule: (
            str(rule.get("family_id") or "").count("."),
            str(rule.get("family_id") or ""),
            -int(rule.get("version") or 0),
        ),
    )


def _resolve_inherited_scope_sections(
    store: Any,
    *,
    parent_run_id: str | None,
    parent_family_id: str | None,
    doc_ids: list[str] | None,
) -> dict[str, set[str]]:
    """Resolve section-level inherited scope from parent run or family links."""
    rows: list[tuple[Any, ...]] = []
    if parent_run_id:
        rows = store._conn.execute(  # noqa: SLF001
            "SELECT doc_id, section_number FROM family_links "
            "WHERE run_id = ? AND status <> 'unlinked'",
            [parent_run_id],
        ).fetchall()
    if not rows and parent_family_id:
        rows = store._conn.execute(  # noqa: SLF001
            "SELECT doc_id, section_number FROM family_links "
            "WHERE family_id = ? AND status <> 'unlinked'",
            [parent_family_id],
        ).fetchall()

    doc_filter = set(doc_ids or []) if doc_ids is not None else None
    scoped: dict[str, set[str]] = {}
    for row in rows:
        doc_id = str(row[0])
        section_number = str(row[1])
        if doc_filter is not None and doc_id not in doc_filter:
            continue
        scoped.setdefault(doc_id, set()).add(section_number)
    return scoped


def scan_corpus_for_family(
    corpus: Any,
    rule: dict[str, Any],
    *,
    doc_ids: list[str] | None = None,
    allowed_sections_by_doc: dict[str, set[str]] | None = None,
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
        if allowed_sections_by_doc is not None and doc_id not in allowed_sections_by_doc:
            continue
        # Get all sections for this document
        sections = corpus.search_sections(doc_id=doc_id, cohort_only=False, limit=10000)
        allowed_sections = allowed_sections_by_doc.get(doc_id) if allowed_sections_by_doc is not None else None

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
            if allowed_sections is not None and str(section.section_number) not in allowed_sections:
                continue
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
    active_rules = [r for r in rules if r.get("status") in ("published", "draft", None)]
    if family_filter:
        requested_scope = str(family_filter).strip()
        scope_aliases: set[str] = {requested_scope}
        if store is not None and hasattr(store, "resolve_scope_aliases"):
            try:
                scope_aliases.update(store.resolve_scope_aliases(requested_scope))
            except Exception:
                pass
        active_rules = [
            r
            for r in active_rules
            if str(r.get("family_id") or "").strip() in scope_aliases
            or _rule_scope_id(r) in scope_aliases
        ]
    active_rules = _select_latest_rules_per_scope(active_rules)
    active_rules = _order_rules_by_hierarchy(active_rules)

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

    # Prepare run tracking before scanning so children can inherit freshly-created parent links.
    run_id: str | None = None
    if not dry_run and store is not None:
        import uuid

        run_id = str(uuid.uuid4())
        store.create_run({
            "run_id": run_id,
            "run_type": "canary" if canary_n else "full",
            "family_id": family_filter or "_all",
            "rule_id": active_rules[0].get("rule_id") if len(active_rules) == 1 else None,
            "corpus_version": "bulk_linker_v1",
            "corpus_doc_count": len(doc_ids) if doc_ids else 0,
            "parser_version": "1.0",
            "links_created": 0,
            "conflicts_detected": 0,
            "scope_mode": "corpus",
        })

    families_with_rules = {str(rule.get("family_id") or "") for rule in active_rules}

    # Scan for each rule
    all_candidates: list[dict[str, Any]] = []
    links_created = 0
    links_unlinked = 0
    evidence_saved = 0
    for i, rule in enumerate(active_rules):
        family = rule.get("family_id", "unknown")
        scope_id = _rule_scope_id(rule) or str(family)
        effective_rule = dict(rule)
        if not effective_rule.get("article_concepts"):
            derived_article_concepts = _extract_article_concepts_from_filter_dsl(
                str(effective_rule.get("filter_dsl") or ""),
            )
            if derived_article_concepts:
                effective_rule["article_concepts"] = derived_article_concepts
        scope_mode = str(rule.get("scope_mode") or "corpus").strip().lower()
        if scope_mode not in {"corpus", "inherited"}:
            scope_mode = "corpus"

        parent_family = _resolve_parent_family(rule, families_with_rules)
        parent_run_id = str(rule.get("parent_run_id") or "").strip() or None
        allowed_sections_by_doc: dict[str, set[str]] | None = None
        if scope_mode == "inherited" and parent_family and store is not None:
            allowed_sections_by_doc = _resolve_inherited_scope_sections(
                store,
                parent_run_id=parent_run_id,
                parent_family_id=parent_family,
                doc_ids=doc_ids,
            )
            _log(
                f"  [{i + 1}/{len(active_rules)}] Scanning family={family} "
                f"(inherited from {parent_family}, scoped docs={len(allowed_sections_by_doc)})",
            )
        else:
            _log(f"  [{i + 1}/{len(active_rules)}] Scanning family={family}")

        candidates = scan_corpus_for_family(
            corpus,
            effective_rule,
            doc_ids=doc_ids,
            allowed_sections_by_doc=allowed_sections_by_doc,
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

        if not dry_run and store is not None and run_id:
            linkable = [c for c in candidates if c.get("confidence_tier") in ("high", "medium")]
            if linkable:
                created_now = store.create_links(linkable, run_id)
                links_created += created_now
                _log(f"    Linked {created_now} rows for family={family}")

            # Reconcile family scope: links not matched by the current latest rule set
            # should no longer remain active/pending from older runs.
            keep_sections = {
                (str(c.get("doc_id", "")), str(c.get("section_number", "")))
                for c in linkable
            }
            existing_rows = store._conn.execute(  # noqa: SLF001
                "SELECT link_id, doc_id, section_number "
                "FROM family_links "
                "WHERE family_id = ? "
                "AND COALESCE(NULLIF(ontology_node_id, ''), family_id) = ? "
                "AND status <> 'unlinked'",
                [family, scope_id],
            ).fetchall()
            stale_ids = [
                str(row[0])
                for row in existing_rows
                if (str(row[1]), str(row[2])) not in keep_sections
            ]
            for link_id in stale_ids:
                store.unlink(link_id, "superseded_by_rule_run")
            if stale_ids:
                links_unlinked += len(stale_ids)
                _log(f"    Unlinked {len(stale_ids)} stale rows for family={family}")

    # Compute summary metrics
    by_family: dict[str, dict[str, int]] = {}
    by_tier = {"high": 0, "medium": 0, "low": 0}
    conflicts_detected = 0

    for cand in all_candidates:
        fam = str(cand.get("ontology_node_id") or cand["family_id"])
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
    if not dry_run and store is not None and run_id:
        # Save evidence (best-effort): map created links back to candidates.
        evidence_rows: list[dict[str, Any]] = []
        if links_created > 0:
            created_rows = store._conn.execute(  # noqa: SLF001
                "SELECT link_id, family_id, ontology_node_id, doc_id, section_number, section_text_hash "
                "FROM family_links WHERE run_id = ?",
                [run_id],
            ).fetchall()
            link_id_by_key = {
                f"{str(r[2] or r[1])}::{str(r[3])}::{str(r[4])}": {
                    "link_id": str(r[0]),
                    "text_hash": str(r[5]) if r[5] else None,
                }
                for r in created_rows
            }

            for cand in all_candidates:
                key = (
                    f"{cand.get('ontology_node_id') or cand.get('family_id', '')}"
                    f"::{cand.get('doc_id', '')}::{cand.get('section_number', '')}"
                )
                matched = link_id_by_key.get(key)
                if not matched:
                    continue
                evidence_rows.append(
                    {
                        "link_id": matched["link_id"],
                        "family_id": cand.get("family_id"),
                        "doc_id": cand.get("doc_id"),
                        "section_number": cand.get("section_number"),
                        "evidence_type": "heading_match",
                        "char_start": cand.get("section_char_start"),
                        "char_end": cand.get("section_char_end"),
                        "text_hash": cand.get("section_text_hash") or matched.get("text_hash"),
                        "matched_pattern": cand.get("matched_value"),
                        "reason_code": "heading_match",
                        "score": cand.get("confidence", 1.0),
                        "metadata": {
                            "match_type": cand.get("match_type"),
                            "matched_value": cand.get("matched_value"),
                            "confidence": cand.get("confidence"),
                            "tier": cand.get("confidence_tier"),
                        },
                    }
                )

        if evidence_rows:
            try:
                evidence_saved = store.save_evidence(evidence_rows)
                _log(f"  Saved {evidence_saved} evidence rows")
            except Exception as exc:
                _log(f"  Warning: could not save evidence rows: {exc}")

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
        "links_unlinked": links_unlinked,
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
        _log(f"  Links unlinked: {summary.get('links_unlinked', 0)}")

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
