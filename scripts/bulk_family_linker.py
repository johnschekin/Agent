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
import contextlib
import hashlib
import json
import re
import sys
import time
from datetime import UTC, datetime
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
    *,
    article_filter_expr: Any = None,
    article_num: int | None = None,
    article_title: str | None = None,
    article_label: str | None = None,
) -> bool:
    """Check whether an article satisfies concept constraints + DSL article AST."""
    concept_ok = True
    if rule_article_concepts:
        if article_concept is None:
            concept_ok = False
        else:
            actual = _normalize_article_token(article_concept)
            concept_ok = False
            if actual:
                for raw_rule_value in rule_article_concepts:
                    token = _normalize_article_token(raw_rule_value)
                    if not token:
                        continue
                    # Support exact and coarse substring matching so
                    # "negative" can match "NEGATIVE_COVENANTS".
                    if actual == token or token in actual or actual in token:
                        concept_ok = True
                        break
    if not concept_ok:
        return False

    if article_filter_expr is None:
        return True

    return _article_expr_matches(
        article_filter_expr,
        article_concept=article_concept,
        article_num=article_num,
        article_title=article_title,
        article_label=article_label,
    )


def _normalize_article_token(value: str | None) -> str:
    raw = str(value or "").strip().lower()
    if not raw:
        return ""
    raw = re.sub(r"[^a-z0-9]+", "_", raw)
    raw = re.sub(r"_+", "_", raw).strip("_")
    return raw


def _parse_article_number_hint(value: str | None) -> int | None:
    raw = str(value or "").strip().lower()
    if not raw:
        return None
    raw = re.sub(r"^(?:article|art\.?)\s+", "", raw).strip()
    if re.fullmatch(r"\d+", raw):
        return int(raw)
    roman = re.sub(r"[^ivxlcdm]", "", raw)
    if not roman:
        return None
    roman_map = {"i": 1, "v": 5, "x": 10, "l": 50, "c": 100, "d": 500, "m": 1000}
    total = 0
    prev = 0
    for ch in reversed(roman):
        val = roman_map.get(ch, 0)
        if val < prev:
            total -= val
        else:
            total += val
            prev = val
    return total if total > 0 else None


def _article_leaf_matches(
    value: str,
    *,
    article_concept: str | None,
    article_num: int | None,
    article_title: str | None,
    article_label: str | None,
) -> bool:
    num_hint = _parse_article_number_hint(value)
    if num_hint is not None and article_num is not None and num_hint == int(article_num):
        return True

    needle = _normalize_article_token(value)
    if not needle:
        return False

    candidates = [
        _normalize_article_token(article_concept),
        _normalize_article_token(article_title),
        _normalize_article_token(article_label),
    ]
    if article_num is not None:
        candidates.append(_normalize_article_token(f"article {int(article_num)}"))
        candidates.append(_normalize_article_token(str(int(article_num))))

    for candidate in candidates:
        if not candidate:
            continue
        if candidate == needle or needle in candidate or candidate in needle:
            return True
    return False


def _article_expr_matches(
    expr: Any,
    *,
    article_concept: str | None,
    article_num: int | None,
    article_title: str | None,
    article_label: str | None,
) -> bool:
    try:
        from agent.query_filters import FilterGroup, FilterMatch
    except Exception:
        return True

    if isinstance(expr, FilterMatch):
        matched = _article_leaf_matches(
            str(expr.value or ""),
            article_concept=article_concept,
            article_num=article_num,
            article_title=article_title,
            article_label=article_label,
        )
        return (not matched) if bool(expr.negate) else matched

    if isinstance(expr, FilterGroup):
        children = list(expr.children or [])
        if not children:
            return True
        if str(expr.operator).lower() == "and":
            return all(
                _article_expr_matches(
                    child,
                    article_concept=article_concept,
                    article_num=article_num,
                    article_title=article_title,
                    article_label=article_label,
                )
                for child in children
            )
        return any(
            _article_expr_matches(
                child,
                article_concept=article_concept,
                article_num=article_num,
                article_title=article_title,
                article_label=article_label,
            )
            for child in children
        )

    return True


def _text_expr_matches(expr: Any, text: str) -> bool:
    try:
        from agent.query_filters import FilterGroup, FilterMatch
    except Exception:
        return True

    if isinstance(expr, FilterMatch):
        needle = str(expr.value or "").strip().lower()
        haystack = str(text or "").lower()
        matched = needle in haystack if needle else False
        return (not matched) if bool(expr.negate) else matched
    if isinstance(expr, FilterGroup):
        children = list(expr.children or [])
        if not children:
            return True
        if str(expr.operator).lower() == "and":
            return all(_text_expr_matches(child, text) for child in children)
        return any(_text_expr_matches(child, text) for child in children)
    return True


def _extract_text_fields_from_filter_dsl(filter_dsl: str) -> dict[str, Any]:
    text = str(filter_dsl or "").strip()
    if not text:
        return {}
    try:
        from agent.rule_dsl import parse_dsl
    except Exception:
        return {}
    try:
        parsed = parse_dsl(text)
    except Exception:
        return {}
    if not parsed.ok:
        return {}
    fields = parsed.text_fields if isinstance(parsed.text_fields, dict) else {}
    return {str(k): v for k, v in fields.items() if v is not None}


def _resolve_scoped_sections_from_text_fields(
    corpus: Any,
    text_fields: dict[str, Any],
    *,
    doc_ids: list[str] | None,
) -> dict[str, set[str]] | None:
    if not text_fields:
        return None
    try:
        from agent.query_filters import build_multi_field_sql
    except Exception:
        return None

    where_sql, where_params, joins = build_multi_field_sql(text_fields)
    if where_sql == "1=1":
        return None

    where_parts = [where_sql]
    params: list[Any] = [*where_params]
    if doc_ids is not None:
        if not doc_ids:
            return {}
        placeholders = ", ".join("?" for _ in doc_ids)
        where_parts.append(f"s.doc_id IN ({placeholders})")
        params.extend(doc_ids)

    join_sql = f" {' '.join(sorted(joins))}" if joins else ""
    sql = (
        "SELECT DISTINCT s.doc_id, s.section_number "
        f"FROM sections s{join_sql} "
        f"WHERE {' AND '.join(where_parts)}"
    )
    rows = corpus._conn.execute(sql, params).fetchall()
    scoped: dict[str, set[str]] = {}
    for row in rows:
        doc_id = str(row[0])
        section_number = str(row[1])
        scoped.setdefault(doc_id, set()).add(section_number)
    return scoped


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


def _utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _canonical_section_name(heading: str) -> str:
    lowered = str(heading or "").strip().lower()
    lowered = re.sub(r"[^a-z0-9._\s]+", " ", lowered)
    lowered = re.sub(r"\s+", " ", lowered)
    return lowered.strip().strip(".")


def _normalized_clause_path(value: str | None) -> str:
    clause_path = str(value or "").strip()
    return clause_path if clause_path else "__section__"


def _compute_anchor_ids(candidate: dict[str, Any]) -> dict[str, Any]:
    """Compute deterministic Wave 3 anchor identity fields for a candidate."""
    document_id = str(candidate.get("document_id") or candidate.get("doc_id") or "").strip()
    section_path = str(candidate.get("section_number") or "").strip()
    section_reference_key = f"{document_id}:{section_path}"

    clause_path = _normalized_clause_path(
        str(candidate.get("clause_path") or candidate.get("clause_id") or ""),
    )
    clause_key = f"{section_reference_key}:{clause_path}"

    span_start_raw = candidate.get("clause_char_start")
    span_end_raw = candidate.get("clause_char_end")
    node_type = "clause"
    if span_start_raw is None or span_end_raw is None:
        node_type = "section"
        span_start_raw = candidate.get("section_char_start")
        span_end_raw = candidate.get("section_char_end")
    if candidate.get("defined_term"):
        node_type = "defined_term"
    span_start = int(span_start_raw or 0)
    span_end = int(span_end_raw or 0)
    anchor_text = str(candidate.get("clause_text") or candidate.get("heading") or "").strip()
    text_sha256 = hashlib.sha256(anchor_text.encode("utf-8")).hexdigest()
    chunk_payload = (
        f"{document_id}|{section_reference_key}|{clause_key}|"
        f"{span_start}|{span_end}|{text_sha256}"
    )
    chunk_id = hashlib.sha256(chunk_payload.encode("utf-8")).hexdigest()
    return {
        "section_path": section_path,
        "section_reference_key": section_reference_key,
        "clause_path": clause_path,
        "clause_key": clause_key,
        "node_type": node_type,
        "span_start": span_start,
        "span_end": span_end,
        "anchor_text": anchor_text,
        "text_sha256": text_sha256,
        "chunk_id": chunk_id,
        "anchor_valid": bool(document_id and section_path and section_reference_key and span_end > span_start),
    }


def _compute_policy_decision(
    *,
    score_calibrated: float,
    must_threshold: float,
    review_threshold: float,
    grounded: bool,
    anchor_valid: bool,
    ontology_valid: bool,
    conflicts: list[dict[str, str]],
) -> tuple[str, list[str]]:
    """Map score + grounding + validity into deterministic policy decision."""
    reasons: list[str] = []
    if not anchor_valid:
        reasons.append("anchor.invalid")
    if not ontology_valid:
        reasons.append("ontology.invalid")
    if any(str(c.get("policy")) == "exclusive" for c in conflicts):
        reasons.append("conflict.exclusive")
    if score_calibrated >= must_threshold:
        reasons.append("threshold.must.met")
    elif score_calibrated >= review_threshold:
        reasons.append("threshold.review.met")
    else:
        reasons.append("threshold.review.not_met")
    reasons.append("grounded.true" if grounded else "grounded.false")

    if not anchor_valid or not ontology_valid or "conflict.exclusive" in reasons:
        return ("reject", reasons)
    if score_calibrated >= must_threshold and grounded:
        return ("must", reasons)
    if score_calibrated >= review_threshold:
        return ("review", reasons)
    # allow review when ungrounded but heading signal is strong and anchor/ontology are valid
    if not grounded and score_calibrated >= (review_threshold * 0.8):
        reasons.append("ungrounded.sufficient_evidence")
        return ("review", reasons)
    return ("reject", reasons)


def _refresh_candidate_anchor_and_policy(
    candidate: dict[str, Any],
    *,
    must_threshold: float,
    review_threshold: float,
) -> None:
    anchors = _compute_anchor_ids(candidate)
    policy_decision, policy_reasons = _compute_policy_decision(
        score_calibrated=float(candidate.get("score_calibrated", candidate.get("confidence", 0.0))),
        must_threshold=must_threshold,
        review_threshold=review_threshold,
        grounded=bool(candidate.get("grounded")),
        anchor_valid=bool(anchors.get("anchor_valid")),
        ontology_valid=bool(candidate.get("ontology_node_id")),
        conflicts=list(candidate.get("conflicts") or []),
    )
    candidate.update(anchors)
    candidate["policy_decision"] = policy_decision
    candidate["policy_reasons"] = policy_reasons
    if policy_decision == "must":
        candidate["status"] = "active"
    elif policy_decision == "review":
        candidate["status"] = "pending_review"
    else:
        candidate["status"] = "rejected"


def _build_candidate(
    section: Any,
    rule: dict[str, Any],
    match_type: str,
    matched_value: str,
    article_concept: str | None,
    confidence_result: Any,
    conflict_info: list[dict[str, str]],
    *,
    document_id: str | None = None,
    ontology_version: str = "unknown",
    threshold_profile_id: str | None = None,
    must_threshold: float | None = None,
    review_threshold: float | None = None,
    valid_ontology_node_ids: set[str] | None = None,
) -> dict[str, Any]:
    """Build a candidate link dict from a matching section + rule."""
    score_raw = float(confidence_result.score)
    score_calibrated = float(confidence_result.score)
    must_thr = float(must_threshold if must_threshold is not None else 0.8)
    review_thr = float(review_threshold if review_threshold is not None else 0.5)
    grounded = float(confidence_result.breakdown.get("defined_term_grounding", 1.0)) >= 0.5
    ontology_node_id = str(rule.get("ontology_node_id", rule.get("family_id", "")) or "")
    ontology_valid = bool(ontology_node_id)
    if ontology_valid and valid_ontology_node_ids is not None:
        ontology_valid = ontology_node_id in valid_ontology_node_ids
    base: dict[str, Any] = {
        "document_id": str(document_id or section.doc_id),
        "family_id": rule.get("family_id", ""),
        "ontology_node_id": ontology_node_id,
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
        "confidence": score_calibrated,
        "score_raw": score_raw,
        "score_calibrated": score_calibrated,
        "threshold_profile_id": threshold_profile_id,
        "confidence_tier": confidence_result.tier,
        "confidence_breakdown": confidence_result.breakdown,
        "why_matched": confidence_result.why_matched,
        "match_type": match_type,
        "matched_value": matched_value,
        "status": "active" if confidence_result.tier == "high" else "pending_review",
        "conflicts": conflict_info,
        "grounded": grounded,
        "ontology_version": ontology_version,
    }
    anchors = _compute_anchor_ids(base)
    policy_decision, policy_reasons = _compute_policy_decision(
        score_calibrated=score_calibrated,
        must_threshold=must_thr,
        review_threshold=review_thr,
        grounded=grounded,
        anchor_valid=bool(anchors.get("anchor_valid")),
        ontology_valid=ontology_valid,
        conflicts=conflict_info,
    )
    base.update(anchors)
    base["policy_decision"] = policy_decision
    base["policy_reasons"] = policy_reasons
    if policy_decision == "must":
        base["status"] = "active"
    elif policy_decision == "review":
        base["status"] = "pending_review"
    else:
        base["status"] = "rejected"
    return base


def _candidate_clause_key(candidate: dict[str, Any]) -> str:
    clause_key = str(candidate.get("clause_key") or "").strip()
    if clause_key:
        return clause_key
    clause_id = str(candidate.get("clause_id") or "").strip()
    if clause_id:
        return clause_id
    return "__section__"


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


def _resolve_section_text_hash(
    corpus: Any,
    doc_id: str,
    section_number: str,
    cache: dict[tuple[str, str], str],
) -> str:
    """Return a stable, non-empty text hash for a section."""
    key = (str(doc_id), str(section_number))
    cached = cache.get(key)
    if cached:
        return cached

    section_text: str | None = None
    get_section_text = getattr(corpus, "get_section_text", None)
    if callable(get_section_text):
        with contextlib.suppress(Exception):
            raw = get_section_text(key[0], key[1])
            if raw is not None:
                section_text = str(raw)

    material = section_text if section_text else f"{key[0]}::{key[1]}"
    text_hash = hashlib.sha256(material.encode("utf-8")).hexdigest()
    cache[key] = text_hash
    return text_hash


def _resolve_document_id(
    corpus: Any,
    doc_id: str,
    cache: dict[str, str],
) -> str:
    """Resolve deterministic document_id (sha256 of source bytes when available)."""
    doc_key = str(doc_id or "").strip()
    if not doc_key:
        return ""
    cached = cache.get(doc_key)
    if cached:
        return cached

    material: bytes | None = None
    get_doc = getattr(corpus, "get_doc", None)
    if callable(get_doc):
        with contextlib.suppress(Exception):
            doc_record = get_doc(doc_key)
            path_value = str(getattr(doc_record, "path", "") or "").strip()
            if path_value:
                path = Path(path_value)
                if path.exists() and path.is_file():
                    material = path.read_bytes()

    if material is None:
        material = doc_key.encode("utf-8")

    resolved = hashlib.sha256(material).hexdigest()
    cache[doc_key] = resolved
    return resolved


def scan_corpus_for_family(
    corpus: Any,
    rule: dict[str, Any],
    *,
    doc_ids: list[str] | None = None,
    allowed_sections_by_doc: dict[str, set[str]] | None = None,
    conflict_matrix: dict[tuple[str, str], Any] | None = None,
    existing_links_by_section: dict[str, list[str]] | None = None,
    calibration: dict[str, Any] | None = None,
    ontology_version: str = "unknown",
    valid_ontology_node_ids: set[str] | None = None,
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
    filter_dsl_text = str(rule.get("filter_dsl") or "").strip()
    dsl_text_fields = _extract_text_fields_from_filter_dsl(filter_dsl_text)
    dsl_article_expr = dsl_text_fields.get("article")
    dsl_heading_expr = dsl_text_fields.get("heading")
    dsl_defined_term_expr = dsl_text_fields.get("defined_term")
    effective_result_granularity = str(rule.get("result_granularity") or "section").strip().lower()
    if effective_result_granularity not in {"section", "clause", "defined_term"}:
        effective_result_granularity = "section"
    if effective_result_granularity == "section" and dsl_defined_term_expr is not None:
        effective_result_granularity = "defined_term"
    dsl_scope_expr_fields: dict[str, Any] = {}
    if dsl_text_fields.get("clause") is not None:
        dsl_scope_expr_fields["clause"] = dsl_text_fields["clause"]
    if dsl_defined_term_expr is not None:
        dsl_scope_expr_fields["defined_term"] = dsl_defined_term_expr

    # Parse the heading filter AST into a FilterExpression for confidence scoring
    heading_filter_expr = None
    try:
        if heading_ast_raw:
            heading_filter_expr = filter_expr_from_json(heading_ast_raw)
    except (ValueError, KeyError):
        heading_filter_expr = None
    if heading_filter_expr is None and dsl_heading_expr is not None:
        heading_filter_expr = dsl_heading_expr

    # Expected defined terms for the defined_term_grounding factor
    expected_terms = rule.get("required_defined_terms") or []
    must_threshold = float((calibration or {}).get("high_threshold", 0.8))
    review_threshold = float((calibration or {}).get("medium_threshold", 0.5))
    threshold_profile_id = str(
        (calibration or {}).get("threshold_profile_id")
        or f"scope:{_rule_scope_id(rule) or rule.get('family_id', '')}:ontology:{ontology_version}"
    )

    candidates: list[dict[str, Any]] = []
    document_id_cache: dict[str, str] = {}

    # Determine documents to scan
    target_docs = doc_ids
    if target_docs is None:
        rows = corpus._conn.execute(
            "SELECT doc_id FROM documents WHERE cohort_included = true "
            "ORDER BY doc_id",
        ).fetchall()
        target_docs = [str(r[0]) for r in rows]

    dsl_allowed_sections_by_doc = _resolve_scoped_sections_from_text_fields(
        corpus,
        dsl_scope_expr_fields,
        doc_ids=target_docs,
    ) if dsl_scope_expr_fields else None

    heading_values: list[str] = []
    try:
        heading_values = _extract_ast_match_values(heading_ast_raw)
    except ValueError:
        heading_values = []
    has_heading_constraint = bool(heading_values) or dsl_heading_expr is not None

    for doc_id in target_docs:
        if allowed_sections_by_doc is not None and doc_id not in allowed_sections_by_doc:
            continue
        if dsl_allowed_sections_by_doc is not None and doc_id not in dsl_allowed_sections_by_doc:
            continue
        document_id = _resolve_document_id(corpus, doc_id, document_id_cache)
        # Get all sections for this document
        sections = corpus.search_sections(doc_id=doc_id, cohort_only=False, limit=10000)
        sections = sorted(
            sections,
            key=lambda sec: (
                str(getattr(sec, "section_number", "")),
                int(getattr(sec, "char_start", 0) or 0),
                int(getattr(sec, "char_end", 0) or 0),
            ),
        )
        inherited_allowed = (
            set(allowed_sections_by_doc.get(doc_id, set()))
            if allowed_sections_by_doc is not None
            else None
        )
        dsl_allowed = (
            set(dsl_allowed_sections_by_doc.get(doc_id, set()))
            if dsl_allowed_sections_by_doc is not None
            else None
        )
        if inherited_allowed is None:
            allowed_sections = dsl_allowed
        elif dsl_allowed is None:
            allowed_sections = inherited_allowed
        else:
            allowed_sections = inherited_allowed & dsl_allowed
        if allowed_sections is not None and not allowed_sections:
            continue

        # Build article metadata lookup
        article_meta_by_num: dict[int, tuple[str | None, str | None, str | None]] = {}
        try:
            for art in corpus.get_articles(doc_id):
                article_number = int(getattr(art, "article_num", 0) or 0)
                if article_number <= 0:
                    continue
                article_meta_by_num[article_number] = (
                    str(getattr(art, "concept", "") or "").strip() or None,
                    str(getattr(art, "title", "") or "").strip() or None,
                    str(getattr(art, "label", "") or "").strip() or None,
                )
        except Exception:
            article_meta_by_num = {}

        # Get defined terms in this document (for grounding factor + term-level links)
        doc_definitions: list[Any] = []
        doc_defined_terms: list[str] = []
        try:
            defs = corpus.get_definitions(doc_id)
            doc_definitions = list(defs or [])
            doc_defined_terms = [str(getattr(d, "term", "") or "") for d in doc_definitions]
        except Exception:
            pass

        for section in sections:
            if allowed_sections is not None and str(section.section_number) not in allowed_sections:
                continue
            # Step 1: Article concept check
            art_concept, art_title, art_label = article_meta_by_num.get(
                int(section.article_num),
                (None, None, None),
            )
            if art_concept is None:
                art_concept = _get_article_concept(corpus, doc_id, section.article_num)

            if not _article_matches_rule(
                art_concept,
                article_concepts,
                article_filter_expr=dsl_article_expr,
                article_num=int(section.article_num),
                article_title=art_title,
                article_label=art_label,
            ):
                continue

            # Step 2: Heading match check
            matched = True
            match_type = "none"
            matched_value = ""
            if has_heading_constraint:
                if heading_values:
                    matched, match_type, matched_value = heading_matches_ast(
                        section.heading, heading_ast_raw,
                    )
                elif dsl_heading_expr is not None:
                    matched = _text_expr_matches(dsl_heading_expr, str(section.heading))
                    match_type = "dsl"
                    matched_value = str(section.heading)
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

            if effective_result_granularity == "defined_term" and dsl_defined_term_expr is not None:
                matched_terms: list[dict[str, Any]] = []
                matched_term_without_span = False
                section_start = int(getattr(section, "char_start", 0) or 0)
                section_end = int(getattr(section, "char_end", 0) or 0)
                for definition in doc_definitions:
                    term = str(getattr(definition, "term", "") or "").strip()
                    if not term or not _text_expr_matches(dsl_defined_term_expr, term):
                        continue
                    try:
                        def_start = int(getattr(definition, "char_start", None))
                        def_end = int(getattr(definition, "char_end", None))
                    except (TypeError, ValueError):
                        matched_term_without_span = True
                        continue
                    if not (section_start <= def_start and def_end <= section_end):
                        continue
                    matched_terms.append(
                        {
                            "term": term,
                            "char_start": def_start,
                            "char_end": def_end,
                            "definition_text": str(getattr(definition, "definition_text", "") or ""),
                        },
                    )
                if not matched_terms:
                    if doc_definitions and not matched_term_without_span:
                        continue
                if matched_terms:
                    for term_match in matched_terms:
                        candidate = _build_candidate(
                            section,
                            rule,
                            match_type,
                            matched_value,
                            art_concept,
                            confidence_result,
                            conflict_info,
                            document_id=document_id,
                            ontology_version=ontology_version,
                            threshold_profile_id=threshold_profile_id,
                            must_threshold=must_threshold,
                            review_threshold=review_threshold,
                            valid_ontology_node_ids=valid_ontology_node_ids,
                        )
                        clause_id = (
                            f"__def__:{term_match['char_start']}:{term_match['char_end']}:"
                            f"{term_match['term']}"
                        )
                        candidate["clause_id"] = clause_id
                        candidate["clause_key"] = clause_id
                        candidate["clause_char_start"] = int(term_match["char_start"])
                        candidate["clause_char_end"] = int(term_match["char_end"])
                        candidate["clause_text"] = term_match["definition_text"]
                        candidate["defined_term"] = term_match["term"]
                        candidate["definition_char_start"] = int(term_match["char_start"])
                        candidate["definition_char_end"] = int(term_match["char_end"])
                        candidate["definition_text"] = term_match["definition_text"]
                        candidate["clause_path"] = clause_id
                        _refresh_candidate_anchor_and_policy(
                            candidate,
                            must_threshold=must_threshold,
                            review_threshold=review_threshold,
                        )
                        candidates.append(candidate)
                    continue

            # Build candidate
            candidate = _build_candidate(
                section,
                rule,
                match_type,
                matched_value,
                art_concept,
                confidence_result,
                conflict_info,
                document_id=document_id,
                ontology_version=ontology_version,
                threshold_profile_id=threshold_profile_id,
                must_threshold=must_threshold,
                review_threshold=review_threshold,
                valid_ontology_node_ids=valid_ontology_node_ids,
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


def _derive_ruleset_version(rules: list[dict[str, Any]]) -> str:
    rows = sorted(
        (
            str(r.get("rule_id") or ""),
            str(r.get("family_id") or ""),
            int(r.get("version") or 0),
            str(r.get("ontology_node_id") or ""),
        )
        for r in rules
    )
    digest = hashlib.sha256(_json_dumps_compact(rows).encode("utf-8")).hexdigest()
    return f"ruleset-{digest[:16]}"


_PLACEHOLDER_LINEAGE_VALUES = {
    "",
    "unknown",
    "parser-unknown",
    "bulk_linker_v1",
    "worker_v1",
    "1.0",
}


def _is_placeholder_lineage(value: str | None) -> bool:
    text = str(value or "").strip().lower()
    return text in _PLACEHOLDER_LINEAGE_VALUES


def _best_effort_git_sha() -> str:
    with contextlib.suppress(Exception):
        from agent.run_manifest import git_commit_hash

        value = git_commit_hash(search_from=Path(__file__).resolve().parents[1])
        if value:
            return str(value).strip()
    return ""


def _sanitize_lineage_value(value: Any, fallback: str) -> str:
    text = str(value or "").strip()
    if _is_placeholder_lineage(text):
        return fallback
    return text


def _resolve_rule_ontology_version(rules: list[dict[str, Any]]) -> str:
    versions = sorted(
        {
            str(rule.get("ontology_version") or "").strip()
            for rule in rules
            if not _is_placeholder_lineage(str(rule.get("ontology_version") or "").strip())
        }
    )
    if len(versions) == 1:
        return versions[0]
    if len(versions) > 1:
        digest = hashlib.sha256(_json_dumps_compact(versions).encode("utf-8")).hexdigest()
        return f"ontology-mixed-{digest[:12]}"
    return "ontology-unversioned"


def _resolve_parser_seed() -> str:
    with contextlib.suppress(Exception):
        from agent import parsing_types

        value = str(getattr(parsing_types, "__version__", "") or "").strip()
        if value:
            return f"parser-v{value}"
    return ""


def _validate_runtime_versions(runtime_versions: dict[str, str], *, for_write: bool) -> None:
    required = ("corpus_version", "corpus_snapshot_id", "parser_version", "ontology_version", "ruleset_version")
    if for_write:
        required = (*required, "git_sha")
    invalid = [
        field for field in required
        if _is_placeholder_lineage(runtime_versions.get(field))
    ]
    if invalid:
        joined = ", ".join(sorted(invalid))
        raise ValueError(f"Invalid runtime lineage values (placeholder or empty): {joined}")


def _resolve_runtime_versions(
    corpus: Any,
    rules: list[dict[str, Any]],
    *,
    corpus_version: str | None = None,
    corpus_snapshot_id: str | None = None,
    parser_version: str | None = None,
    ontology_version: str | None = None,
    ruleset_version: str | None = None,
    git_sha: str | None = None,
) -> dict[str, str]:
    manifest: dict[str, Any] = {}
    get_run_manifest = getattr(corpus, "get_run_manifest", None)
    if callable(get_run_manifest):
        with contextlib.suppress(Exception):
            manifest_raw = get_run_manifest()
            if isinstance(manifest_raw, dict):
                manifest = manifest_raw

    schema_version = str(getattr(corpus, "schema_version", "") or "").strip()
    resolved_git_sha = _sanitize_lineage_value(
        git_sha or manifest.get("git_commit") or _best_effort_git_sha(),
        "",
    )
    if not resolved_git_sha:
        digest = hashlib.sha256(_json_dumps_compact(sorted(str(r.get("rule_id") or "") for r in rules)).encode("utf-8")).hexdigest()
        resolved_git_sha = f"nogit-{digest[:12]}"

    resolved_corpus_version = _sanitize_lineage_value(
        corpus_version
        or manifest.get("schema_version")
        or schema_version
        or "",
        f"corpus-{Path(str(getattr(corpus, '_db_path', 'index'))).stem}",
    )
    resolved_corpus_snapshot_id = _sanitize_lineage_value(
        corpus_snapshot_id
        or manifest.get("run_id")
        or resolved_corpus_version
        or "",
        f"{resolved_corpus_version}-snapshot",
    )
    resolved_ontology_version = _sanitize_lineage_value(
        ontology_version
        or manifest.get("ontology_version")
        or _resolve_rule_ontology_version(rules)
        or "",
        _resolve_rule_ontology_version(rules),
    )
    resolved_ruleset_version = _sanitize_lineage_value(
        ruleset_version
        or _derive_ruleset_version(rules)
        or "",
        _derive_ruleset_version(rules),
    )
    resolved_parser_version = _sanitize_lineage_value(
        parser_version
        or manifest.get("parser_version")
        or _resolve_parser_seed()
        or (f"parser-{resolved_git_sha[:12]}" if resolved_git_sha else ""),
        f"parser-{resolved_git_sha[:12]}",
    )

    versions = {
        "corpus_version": resolved_corpus_version,
        "corpus_snapshot_id": resolved_corpus_snapshot_id,
        "parser_version": resolved_parser_version,
        "ontology_version": resolved_ontology_version,
        "ruleset_version": resolved_ruleset_version,
        "git_sha": resolved_git_sha,
        "created_at_utc": _utc_now_iso(),
    }
    _validate_runtime_versions(versions, for_write=True)
    return versions


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
    corpus_version: str | None = None,
    corpus_snapshot_id: str | None = None,
    parser_version: str | None = None,
    ontology_version: str | None = None,
    ruleset_version: str | None = None,
    git_sha: str | None = None,
    valid_ontology_node_ids: set[str] | None = None,
) -> dict[str, Any]:
    """Run the full bulk linking pipeline.

    Returns a summary dict with candidates, metrics, and run info.
    """
    start_time = time.time()

    runtime_versions = _resolve_runtime_versions(
        corpus,
        rules,
        corpus_version=corpus_version,
        corpus_snapshot_id=corpus_snapshot_id,
        parser_version=parser_version,
        ontology_version=ontology_version,
        ruleset_version=ruleset_version,
        git_sha=git_sha,
    )

    # Filter rules by family if requested
    active_rules = [r for r in rules if r.get("status") in ("published", "draft", None)]
    if family_filter:
        requested_scope = str(family_filter).strip()
        scope_aliases: set[str] = {requested_scope}
        if store is not None and hasattr(store, "resolve_scope_aliases"):
            try:
                scope_aliases.update(
                    store.resolve_scope_aliases(
                        requested_scope,
                        ontology_version=runtime_versions["ontology_version"],
                    )
                )
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
            "corpus_version": runtime_versions["corpus_version"],
            "corpus_snapshot_id": runtime_versions["corpus_snapshot_id"],
            "corpus_doc_count": len(doc_ids) if doc_ids else 0,
            "parser_version": runtime_versions["parser_version"],
            "ontology_version": runtime_versions["ontology_version"],
            "ruleset_version": runtime_versions["ruleset_version"],
            "git_sha": runtime_versions["git_sha"],
            "created_at_utc": runtime_versions["created_at_utc"],
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
    section_text_hash_cache: dict[tuple[str, str], str] = {}
    for i, rule in enumerate(active_rules):
        family = rule.get("family_id", "unknown")
        scope_id = _rule_scope_id(rule) or str(family)
        effective_rule = dict(rule)
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

        calibration: dict[str, Any] | None = None
        if store is not None and hasattr(store, "get_calibration"):
            with contextlib.suppress(Exception):
                calibration = store.get_calibration(
                    scope_id,
                    ontology_version=runtime_versions["ontology_version"],
                )

        candidates = scan_corpus_for_family(
            corpus,
            effective_rule,
            doc_ids=doc_ids,
            allowed_sections_by_doc=allowed_sections_by_doc,
            conflict_matrix=conflict_matrix,
            existing_links_by_section=existing_links_by_section,
            calibration=calibration,
            ontology_version=runtime_versions["ontology_version"],
            valid_ontology_node_ids=valid_ontology_node_ids,
        )
        candidates = sorted(
            candidates,
            key=lambda c: (
                str(c.get("doc_id", "")),
                str(c.get("section_number", "")),
                str(c.get("clause_key", "")),
                str(c.get("ontology_node_id") or c.get("family_id", "")),
            ),
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
            linkable = [c for c in candidates if c.get("policy_decision") in ("must", "review")]
            if linkable:
                for candidate in linkable:
                    if candidate.get("section_text_hash"):
                        continue
                    candidate["section_text_hash"] = _resolve_section_text_hash(
                        corpus,
                        str(candidate.get("doc_id", "")),
                        str(candidate.get("section_number", "")),
                        section_text_hash_cache,
                    )
                    candidate["corpus_version"] = runtime_versions["corpus_version"]
                    candidate["parser_version"] = runtime_versions["parser_version"]
                    candidate["ontology_version"] = runtime_versions["ontology_version"]
                    candidate["threshold_profile_id"] = (
                        candidate.get("threshold_profile_id")
                        or f"scope:{scope_id}:ontology:{runtime_versions['ontology_version']}"
                    )
                created_now = store.create_links(linkable, run_id)
                links_created += created_now
                _log(f"    Linked {created_now} rows for family={family}")
                term_bindings_by_key: dict[str, list[dict[str, Any]]] = {}
                for candidate in linkable:
                    term = str(candidate.get("defined_term") or "").strip()
                    if not term:
                        continue
                    start = (
                        candidate.get("definition_char_start")
                        if candidate.get("definition_char_start") is not None
                        else candidate.get("clause_char_start")
                    )
                    end = (
                        candidate.get("definition_char_end")
                        if candidate.get("definition_char_end") is not None
                        else candidate.get("clause_char_end")
                    )
                    try:
                        start_i = int(start)
                        end_i = int(end)
                    except (TypeError, ValueError):
                        continue
                    key = (
                        f"{candidate.get('ontology_node_id') or candidate.get('family_id', '')}"
                        f"::{candidate.get('doc_id', '')}::{candidate.get('section_number', '')}"
                        f"::{_candidate_clause_key(candidate)}"
                    )
                    term_bindings_by_key.setdefault(key, []).append(
                        {
                            "term": term,
                            "definition_section_path": str(candidate.get("section_number") or ""),
                            "definition_char_start": start_i,
                            "definition_char_end": end_i,
                            "confidence": float(candidate.get("confidence", 1.0) or 1.0),
                            "extraction_engine": "bulk_linker_defined_term",
                        },
                    )
                if term_bindings_by_key:
                    created_rows = store._conn.execute(  # noqa: SLF001
                        "SELECT link_id, family_id, ontology_node_id, doc_id, section_number, "
                        "COALESCE(NULLIF(TRIM(clause_key), ''), NULLIF(TRIM(clause_id), ''), '__section__') AS clause_key_norm "
                        "FROM family_links WHERE run_id = ?",
                        [run_id],
                    ).fetchall()
                    link_id_by_key = {
                        f"{str(r[2] or r[1])}::{str(r[3])}::{str(r[4])}::{str(r[5])}": str(r[0])
                        for r in created_rows
                    }
                    for key, bindings in term_bindings_by_key.items():
                        link_id = link_id_by_key.get(key)
                        if not link_id:
                            continue
                        with contextlib.suppress(Exception):
                            store.save_link_defined_terms(link_id, bindings)

            # Reconcile family scope: links not matched by the current latest rule set
            # should no longer remain active/pending from older runs.
            keep_rows = {
                (
                    str(c.get("doc_id", "")),
                    str(c.get("section_number", "")),
                    _candidate_clause_key(c),
                )
                for c in linkable
            }
            existing_rows = store._conn.execute(  # noqa: SLF001
                "SELECT link_id, doc_id, section_number, "
                "COALESCE(NULLIF(TRIM(clause_key), ''), NULLIF(TRIM(clause_id), ''), '__section__') AS clause_key_norm "
                "FROM family_links "
                "WHERE family_id = ? "
                "AND COALESCE(NULLIF(ontology_node_id, ''), family_id) = ? "
                "AND status <> 'unlinked'",
                [family, scope_id],
            ).fetchall()
            stale_ids = [
                str(row[0])
                for row in existing_rows
                if (str(row[1]), str(row[2]), str(row[3])) not in keep_rows
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
                "SELECT link_id, family_id, ontology_node_id, doc_id, section_number, "
                "section_text_hash, COALESCE(NULLIF(TRIM(clause_key), ''), NULLIF(TRIM(clause_id), ''), '__section__') AS clause_key_norm "
                "FROM family_links WHERE run_id = ?",
                [run_id],
            ).fetchall()
            link_id_by_key = {
                f"{str(r[2] or r[1])}::{str(r[3])}::{str(r[4])}::{str(r[6])}": {
                    "link_id": str(r[0]),
                    "text_hash": str(r[5]) if r[5] else None,
                }
                for r in created_rows
            }

            for cand in all_candidates:
                key = (
                    f"{cand.get('ontology_node_id') or cand.get('family_id', '')}"
                    f"::{cand.get('doc_id', '')}::{cand.get('section_number', '')}"
                    f"::{_candidate_clause_key(cand)}"
                )
                matched = link_id_by_key.get(key)
                if not matched:
                    continue
                text_hash = cand.get("section_text_hash") or matched.get("text_hash")
                if not text_hash:
                    text_hash = _resolve_section_text_hash(
                        corpus,
                        str(cand.get("doc_id", "")),
                        str(cand.get("section_number", "")),
                        section_text_hash_cache,
                    )
                evidence_rows.append(
                    {
                        "link_id": matched["link_id"],
                        "run_id": run_id,
                        "document_id": cand.get("document_id"),
                        "family_id": cand.get("family_id"),
                        "doc_id": cand.get("doc_id"),
                        "section_number": cand.get("section_number"),
                        "section_reference_key": cand.get("section_reference_key"),
                        "clause_key": cand.get("clause_key"),
                        "evidence_type": "heading_match",
                        "node_type": cand.get("node_type"),
                        "section_path": cand.get("section_path"),
                        "clause_path": cand.get("clause_path"),
                        "char_start": cand.get("span_start", cand.get("section_char_start")),
                        "char_end": cand.get("span_end", cand.get("section_char_end")),
                        "anchor_text": cand.get("anchor_text"),
                        "text_hash": text_hash,
                        "text_sha256": cand.get("text_sha256"),
                        "chunk_id": cand.get("chunk_id"),
                        "matched_pattern": cand.get("matched_value"),
                        "reason_code": "heading_match",
                        "score": cand.get("score_calibrated", cand.get("confidence", 1.0)),
                        "score_raw": cand.get("score_raw", cand.get("confidence", 1.0)),
                        "score_calibrated": cand.get("score_calibrated", cand.get("confidence", 1.0)),
                        "threshold_profile_id": cand.get("threshold_profile_id"),
                        "policy_decision": cand.get("policy_decision"),
                        "policy_reasons": cand.get("policy_reasons", []),
                        "corpus_version": runtime_versions["corpus_version"],
                        "parser_version": runtime_versions["parser_version"],
                        "ontology_version": runtime_versions["ontology_version"],
                        "ruleset_version": runtime_versions["ruleset_version"],
                        "git_sha": runtime_versions["git_sha"],
                        "created_at_utc": runtime_versions["created_at_utc"],
                        "metadata": {
                            "match_type": cand.get("match_type"),
                            "matched_value": cand.get("matched_value"),
                            "confidence": cand.get("confidence"),
                            "tier": cand.get("confidence_tier"),
                            "policy_decision": cand.get("policy_decision"),
                            "policy_reasons": cand.get("policy_reasons", []),
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
        "runtime_versions": runtime_versions,
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
    parser.add_argument(
        "--ontology-json",
        default=None,
        help="Path to ontology JSON (default: data/ontology/r36a_production_ontology_v2.5.1.json)",
    )
    parser.add_argument("--corpus-version", default=None, help="Override corpus_version metadata")
    parser.add_argument("--corpus-snapshot-id", default=None, help="Override corpus snapshot id")
    parser.add_argument("--parser-version", default=None, help="Override parser_version metadata")
    parser.add_argument("--ontology-version", default=None, help="Override ontology_version metadata")
    parser.add_argument("--ruleset-version", default=None, help="Override ruleset_version metadata")
    parser.add_argument("--git-sha", default=None, help="Override git sha metadata")
    parser.add_argument(
        "--strict-ontology",
        action="store_true",
        help="Fail if ontology is loaded but conflict policy matrix is empty",
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
    resolved_ontology_version: str | None = args.ontology_version
    valid_ontology_node_ids: set[str] | None = None
    try:
        from agent.conflict_matrix import build_conflict_matrix, matrix_to_dict

        ontology_path = (
            Path(args.ontology_json).resolve()
            if args.ontology_json
            else (
                Path(__file__).resolve().parents[1]
                / "data" / "ontology" / "r36a_production_ontology_v2.5.1.json"
            )
        )
        if ontology_path.exists():
            from agent.ontology_contract import normalize_ontology

            with open(ontology_path) as f:
                ontology_data = json.load(f)
            normalized = normalize_ontology(ontology_data)
            valid_ontology_node_ids = set(normalized.nodes_by_id.keys())
            policies = build_conflict_matrix(
                normalized.edges,
                normalized.nodes_by_id,
                ontology_version=normalized.ontology_version,
            )
            if not resolved_ontology_version:
                resolved_ontology_version = normalized.ontology_version
            if args.strict_ontology and normalized.edges and not policies:
                _log(
                    "Error: ontology loaded but produced 0 conflict policies in strict mode"
                )
                store.close()
                return 2
            conflict_matrix_dict = matrix_to_dict(policies)
            _log(
                f"  Built conflict matrix: {len(conflict_matrix_dict)} pairs "
                f"(ontology_version={normalized.ontology_version})"
            )
    except Exception as e:
        _log(f"  Warning: could not build conflict matrix: {e}")

    if valid_ontology_node_ids:
        rules_for_validation = list(rules)
        if args.family:
            requested_scope = str(args.family).strip()
            rules_for_validation = [
                rule
                for rule in rules
                if str(rule.get("family_id") or "").strip() == requested_scope
                or str(rule.get("ontology_node_id") or "").strip() == requested_scope
            ]
            if not rules_for_validation:
                rules_for_validation = list(rules)
        invalid_rule_ids = [
            str(rule.get("rule_id") or "")
            for rule in rules_for_validation
            if str(rule.get("ontology_node_id") or rule.get("family_id") or "").strip()
            not in valid_ontology_node_ids
        ]
        if invalid_rule_ids:
            _log(
                "Error: rules reference unknown ontology_node_id values: "
                + ", ".join(sorted(invalid_rule_ids))
            )
            store.close()
            return 2

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
        corpus_version=args.corpus_version,
        corpus_snapshot_id=args.corpus_snapshot_id,
        parser_version=args.parser_version,
        ontology_version=resolved_ontology_version,
        ruleset_version=args.ruleset_version,
        git_sha=args.git_sha,
        valid_ontology_node_ids=valid_ontology_node_ids,
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
    from agent.ontology_contract import normalize_ontology

    payload = {"domains": nodes, "edges": []}
    normalized = normalize_ontology(payload)
    return list(normalized.nodes_by_id.values())


def _load_ontology_nodes(ontology_data: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Flatten domains/nodes payload into deterministic node-id map."""
    from agent.ontology_contract import normalize_ontology

    return normalize_ontology(ontology_data).nodes_by_id


if __name__ == "__main__":
    sys.exit(main())
