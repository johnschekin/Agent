"""FastAPI server for the Corpus Dashboard.

Reads from corpus_index/corpus.duckdb via the CorpusIndex class and exposes
JSON endpoints for the Next.js frontend.

Usage:
    cd /Users/johnchtchekine/Projects/Agent/dashboard
    PYTHONPATH=../src uvicorn api.server:app --reload --port 8000
"""
from __future__ import annotations

import asyncio
import json
import math
import re
import sys
import uuid
from collections import Counter
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import orjson
from fastapi import Body, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import ORJSONResponse
from pydantic import BaseModel, Field
from starlette.responses import StreamingResponse

# Add Agent src to path so we can import agent modules
_agent_src = Path(__file__).resolve().parents[2] / "src"
if str(_agent_src) not in sys.path:
    sys.path.insert(0, str(_agent_src))

from agent.corpus import CorpusIndex  # noqa: E402

# ---------------------------------------------------------------------------
# Globals
#
# IMPORTANT: DuckDB connections are NOT thread-safe. This server MUST run with
# a single uvicorn worker (the default) and all endpoints MUST remain async def
# so they execute on the single event loop thread. Do NOT convert endpoints to
# sync def (which would use a thread pool) or use --workers N > 1.
# ---------------------------------------------------------------------------
_corpus: CorpusIndex | None = None
_corpus_db_path = Path(__file__).resolve().parents[2] / "corpus_index" / "corpus.duckdb"

# Ontology in-memory data (loaded at startup from production JSON)
_ontology_nodes: dict[str, dict[str, Any]] = {}
_ontology_tree: list[dict[str, Any]] = []
_ontology_edges: list[dict[str, Any]] = []
_ontology_edge_index: dict[str, list[dict[str, Any]]] = {}  # node_id -> edges
_ontology_stats: dict[str, Any] = {}
_ontology_metadata: dict[str, Any] = {}
_ontology_path = Path(__file__).resolve().parents[2] / "data" / "ontology" / "r36a_production_ontology_v2.5.1.json"

# Strategy in-memory data (loaded at startup from workspace JSON files)
_strategies: dict[str, dict[str, Any]] = {}       # concept_id -> normalized flat dict
_strategy_families: dict[str, list[str]] = {}      # family -> list of concept_ids
_workspace_root = Path(__file__).resolve().parents[2] / "workspaces"

# Feedback backlog (mutable JSON file)
_feedback_path = Path(__file__).resolve().parents[2] / "data" / "feedback_backlog.json"
_feedback_items: list[dict[str, Any]] = []
_feedback_lock = asyncio.Lock()

# Ontology notes (mutable JSON sidecar — node_id -> note text)
_ontology_notes_path = Path(__file__).resolve().parents[2] / "data" / "ontology_notes.json"
_ontology_notes: dict[str, str] = {}
_ontology_notes_lock = asyncio.Lock()


def _get_corpus() -> CorpusIndex:
    """Get the corpus index, raising 503 if not available."""
    if _corpus is None:
        raise HTTPException(
            status_code=503,
            detail="Corpus index not available. Run build_corpus_index.py first.",
        )
    return _corpus


def _get_ontology() -> None:
    """Raise 503 if ontology not loaded."""
    if not _ontology_nodes:
        raise HTTPException(status_code=503, detail="Ontology not loaded")


def _build_ontology_indexes(raw: dict[str, Any]) -> None:
    """Build in-memory indexes from raw ontology JSON."""
    global _ontology_nodes, _ontology_tree, _ontology_edges  # noqa: PLW0603
    global _ontology_edge_index, _ontology_stats, _ontology_metadata  # noqa: PLW0603

    _ontology_metadata = raw.get("metadata", {})
    _ontology_edges = raw.get("edges", [])

    # Flatten nodes recursively (strip children, store all other fields)
    def _flatten(node: dict[str, Any]) -> None:
        node_id = node["id"]
        children = node.get("children", [])
        flat = {k: v for k, v in node.items() if k != "children"}
        flat["children_ids"] = [c["id"] for c in children]
        _ontology_nodes[node_id] = flat
        for child in children:
            _flatten(child)

    for domain in raw.get("domains", []):
        _flatten(domain)

    # Build lightweight tree for frontend
    def _tree_node(node: dict[str, Any]) -> dict[str, Any]:
        children = node.get("children", [])
        return {
            "id": node["id"],
            "name": node["name"],
            "type": node["type"],
            "level": node["level"],
            "domain_id": node.get("domain_id", node["id"]),
            "family_id": node.get("family_id"),
            "corpus_prevalence": node.get("corpus_prevalence"),
            "extraction_difficulty": node.get("extraction_difficulty"),
            "child_count": len(children),
            "children": [_tree_node(c) for c in children] if children else [],
        }

    _ontology_tree = [_tree_node(d) for d in raw.get("domains", [])]

    # Build edge index (node_id -> list of edges where node is source or target)
    _ontology_edge_index.clear()
    for edge in _ontology_edges:
        src = edge["source_id"]
        tgt = edge["target_id"]
        _ontology_edge_index.setdefault(src, []).append(edge)
        if tgt != src:
            _ontology_edge_index.setdefault(tgt, []).append(edge)

    # Pre-compute stats
    type_counts: Counter[str] = Counter(n["type"] for n in _ontology_nodes.values())
    edge_type_counts: Counter[str] = Counter(e["edge_type"] for e in _ontology_edges)

    def _count_descendants(node: dict[str, Any]) -> int:
        count = 1
        for c in node.get("children", []):
            count += _count_descendants(c)
        return count

    domain_breakdown = [
        {
            "domain_id": d["id"],
            "domain_name": d["name"],
            "family_count": len(d.get("children", [])),
            "node_count": _count_descendants(d),
        }
        for d in raw.get("domains", [])
    ]

    _ontology_stats = {
        "node_count": len(_ontology_nodes),
        "edge_count": len(_ontology_edges),
        "domain_count": type_counts.get("domain", 0),
        "family_count": type_counts.get("family", 0),
        "concept_count": type_counts.get("concept", 0),
        "sub_component_count": type_counts.get("sub_component", 0),
        "parameter_count": type_counts.get("parameter", 0),
        "edge_type_counts": dict(edge_type_counts.most_common()),
        "domain_breakdown": domain_breakdown,
        "version": _ontology_metadata.get("version", "unknown"),
        "production_date": _ontology_metadata.get("production_date", ""),
    }


def _normalize_workspace_strategy(raw: dict[str, Any]) -> dict[str, Any]:
    """Normalize a workspace strategy (nested format) to flat API format."""
    ss = raw.get("search_strategy", {})
    family_id = raw.get("family_id", "")
    # Extract family short name from dotted family_id (e.g. "debt_capacity.indebtedness" -> "indebtedness")
    family = family_id.rsplit(".", 1)[-1] if family_id else raw.get("concept_area", "")
    return {
        "concept_id": raw.get("id", ""),
        "concept_name": raw.get("name", ""),
        "family": family,
        "heading_patterns": ss.get("heading_patterns", []),
        "keyword_anchors": ss.get("keyword_anchors", []),
        "keyword_anchors_section_only": ss.get("keyword_anchors_in_section_only", []),
        "concept_specific_keywords": ss.get("concept_specific_keywords", []),
        "dna_tier1": ss.get("dna_tier1", []),
        "dna_tier2": ss.get("dna_tier2", []),
        "defined_term_dependencies": ss.get("defined_term_dependencies", []),
        "concept_notes": ss.get("concept_specific_notes", ss.get("concept_notes", [])),
        "fallback_escalation": ss.get("fallback_escalation"),
        "xref_follow": ss.get("xref_follow", []),
        "primary_articles": ss.get("primary_articles", []),
        "primary_sections": ss.get("primary_sections", []),
        "definitions_article": ss.get("definitions_article"),
        "heading_hit_rate": raw.get("heading_hit_rate", 0.0),
        "keyword_precision": raw.get("keyword_precision", 0.0),
        "corpus_prevalence": raw.get("corpus_prevalence", 0.0),
        "cohort_coverage": raw.get("cohort_coverage", 0.0),
        "dna_phrase_count": raw.get("dna_phrase_count", 0),
        "dropped_headings": raw.get("dropped_headings", []),
        "false_positive_keywords": raw.get("false_positive_keywords", []),
        "template_overrides": raw.get("template_overrides", []),
        "validation_status": raw.get("validation_status", "bootstrap"),
        "version": raw.get("version", 1),
        "last_updated": raw.get("last_updated", ""),
        "update_notes": raw.get("update_notes", []),
    }


def _load_strategies() -> None:
    """Scan workspace directories and load all strategy JSON files."""
    global _strategies, _strategy_families  # noqa: PLW0603
    _strategies = {}
    _strategy_families = {}

    if not _workspace_root.exists():
        return

    for family_dir in sorted(_workspace_root.iterdir()):
        if not family_dir.is_dir():
            continue

        # Load individual strategies from strategies/ dir
        strategies_dir = family_dir / "strategies"
        if strategies_dir.exists():
            for fp in sorted(strategies_dir.glob("*.json")):
                try:
                    raw = orjson.loads(fp.read_bytes())
                    # Detect format: nested (has "search_strategy") vs flat (has "concept_id")
                    if "search_strategy" in raw:
                        normalized = _normalize_workspace_strategy(raw)
                    elif "concept_id" in raw:
                        normalized = raw  # Already flat format
                    else:
                        continue
                    cid = normalized["concept_id"]
                    if cid:
                        _strategies[cid] = normalized
                except Exception:
                    continue

        # Also load bootstrap strategies (array of nested objects)
        bootstrap = family_dir / "context" / "bootstrap_strategy.json"
        if bootstrap.exists():
            try:
                items = orjson.loads(bootstrap.read_bytes())
                if isinstance(items, list):
                    for raw_item in items:
                        cid = raw_item.get("id", "")
                        if cid and cid not in _strategies:  # Don't overwrite versioned
                            _strategies[cid] = _normalize_workspace_strategy(raw_item)
            except Exception:
                pass

    # Build family index
    _strategy_families = {}
    for cid, s in _strategies.items():
        fam = s.get("family", "unknown")
        _strategy_families.setdefault(fam, []).append(cid)


def _load_feedback() -> None:
    """Load feedback backlog from JSON file."""
    global _feedback_items  # noqa: PLW0603
    if _feedback_path.exists():
        try:
            _feedback_items = orjson.loads(_feedback_path.read_bytes())
            if not isinstance(_feedback_items, list):
                _feedback_items = []
        except Exception:
            _feedback_items = []
    else:
        _feedback_items = []


def _save_feedback() -> None:
    """Save feedback backlog atomically."""
    _feedback_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = _feedback_path.with_suffix(".tmp")
    tmp.write_bytes(orjson.dumps(_feedback_items, option=orjson.OPT_INDENT_2))
    import os
    os.replace(tmp, _feedback_path)


def _load_ontology_notes() -> None:
    """Load ontology notes from JSON sidecar."""
    global _ontology_notes  # noqa: PLW0603
    if _ontology_notes_path.exists():
        try:
            _ontology_notes = orjson.loads(_ontology_notes_path.read_bytes())
            if not isinstance(_ontology_notes, dict):
                _ontology_notes = {}
        except Exception:
            _ontology_notes = {}
    else:
        _ontology_notes = {}


def _save_ontology_notes() -> None:
    """Save ontology notes atomically."""
    _ontology_notes_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = _ontology_notes_path.with_suffix(".tmp")
    tmp.write_bytes(orjson.dumps(_ontology_notes, option=orjson.OPT_INDENT_2 | orjson.OPT_SORT_KEYS))
    import os
    os.replace(tmp, _ontology_notes_path)


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):  # noqa: ARG001
    global _corpus  # noqa: PLW0603
    if _corpus_db_path.exists():
        try:
            _corpus = CorpusIndex(_corpus_db_path)
            print(f"[dashboard] Corpus loaded: {_corpus.doc_count} documents")
        except Exception as e:
            print(f"[dashboard] Warning: could not open corpus: {e}")
            _corpus = None
    else:
        print(f"[dashboard] No corpus at {_corpus_db_path} — running in demo mode")
        _corpus = None

    # Load ontology
    if _ontology_path.exists():
        try:
            _onto_raw = orjson.loads(_ontology_path.read_bytes())
            _build_ontology_indexes(_onto_raw)
            del _onto_raw
            print(f"[dashboard] Ontology loaded: {len(_ontology_nodes)} nodes, {len(_ontology_edges)} edges")
        except Exception as e:
            print(f"[dashboard] Warning: could not load ontology: {e}")
    else:
        print(f"[dashboard] No ontology at {_ontology_path}")

    # Load ontology notes sidecar
    _load_ontology_notes()
    if _ontology_notes:
        print(f"[dashboard] Ontology notes loaded: {len(_ontology_notes)} nodes with notes")

    # Load strategies from workspace JSON files
    try:
        _load_strategies()
        print(f"[dashboard] Strategies loaded: {len(_strategies)} concepts in {len(_strategy_families)} families")
    except Exception as e:
        print(f"[dashboard] Warning: could not load strategies: {e}")

    # Load feedback backlog
    try:
        _load_feedback()
        print(f"[dashboard] Feedback loaded: {len(_feedback_items)} items")
    except Exception as e:
        print(f"[dashboard] Warning: could not load feedback: {e}")

    yield
    if _corpus is not None:
        _corpus.close()


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
app = FastAPI(
    title="Corpus Dashboard API",
    version="0.1.0",
    default_response_class=ORJSONResponse,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:3001",
        "http://localhost:3002",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:3001",
        "http://127.0.0.1:3002",
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _safe_stat(values: list[float], fn: Any, default: float = 0.0) -> float:
    """Compute a statistic safely, returning default on empty list."""
    if not values:
        return default
    try:
        return float(fn(values))
    except Exception:
        return default


def _median(values: list[float]) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    n = len(s)
    if n % 2 == 1:
        return s[n // 2]
    return (s[n // 2 - 1] + s[n // 2]) / 2


def _percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    k = (len(s) - 1) * p
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return s[int(k)]
    return s[f] * (c - k) + s[c] * (k - f)


def _stdev(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    variance = sum((x - mean) ** 2 for x in values) / (len(values) - 1)
    return math.sqrt(variance)


def _histogram(
    values: list[float], bins: int = 25
) -> list[dict[str, float]]:
    """Compute histogram bins from a list of values."""
    if not values:
        return []
    lo = min(values)
    hi = max(values)
    if lo == hi:
        return [{"bin_center": lo, "count": len(values)}]
    bin_width = (hi - lo) / bins
    counts = [0] * bins
    for v in values:
        idx = min(int((v - lo) / bin_width), bins - 1)
        counts[idx] += 1
    return [
        {"bin_center": lo + (i + 0.5) * bin_width, "count": counts[i]}
        for i in range(bins)
    ]


def _build_where(*conditions: str) -> str:
    """Join non-empty conditions into a WHERE clause."""
    parts = [c for c in conditions if c]
    if not parts:
        return ""
    return " WHERE " + " AND ".join(parts)


# ---------------------------------------------------------------------------
# Routes: Health
# ---------------------------------------------------------------------------
@app.get("/api/health")
async def health():
    return {
        "status": "ok",
        "corpus_loaded": _corpus is not None,
        "doc_count": _corpus.doc_count if _corpus else 0,
    }


# ---------------------------------------------------------------------------
# Routes: Overview
# ---------------------------------------------------------------------------
_DISTRIBUTION_METRICS = {
    "doc_type", "market_segment", "word_count", "definition_count",
    "facility_size_mm", "section_count", "clause_count",
}

@app.get("/api/overview/kpis")
async def overview_kpis(cohort_only: bool = Query(False)):
    """KPI cards for the overview page."""
    corpus = _get_corpus()
    where = "WHERE cohort_included = true" if cohort_only else ""
    row = corpus.query(
        f"""
        SELECT
            COUNT(*) as total_docs,
            SUM(CASE WHEN cohort_included THEN 1 ELSE 0 END) as cohort_docs,
            SUM(CASE WHEN section_count > 0 THEN 1 ELSE 0 END) as docs_with_sections,
            SUM(section_count) as total_sections,
            SUM(definition_count) as total_definitions,
            SUM(clause_count) as total_clauses,
            AVG(section_count) as avg_sections,
            AVG(definition_count) as avg_definitions,
            AVG(word_count) as avg_word_count,
            MEDIAN(word_count) as median_word_count,
            MEDIAN(facility_size_mm) as median_facility_size
        FROM documents
        {where}
        """
    )[0]

    total = int(row[0]) if row[0] else 0
    docs_with_sections = int(row[2]) if row[2] else 0

    return {
        "total_docs": total,
        "cohort_docs": int(row[1]) if row[1] else 0,
        "parse_success_rate": round(docs_with_sections / total * 100, 1) if total > 0 else 0,
        "total_sections": int(row[3]) if row[3] else 0,
        "total_definitions": int(row[4]) if row[4] else 0,
        "total_clauses": int(row[5]) if row[5] else 0,
        "avg_sections_per_doc": round(float(row[6]), 1) if row[6] else 0,
        "avg_definitions_per_doc": round(float(row[7]), 1) if row[7] else 0,
        "avg_word_count": round(float(row[8]), 0) if row[8] else 0,
        "median_word_count": round(float(row[9]), 0) if row[9] else 0,
        "median_facility_size_mm": round(float(row[10]), 1) if row[10] else None,
        "schema_version": corpus.schema_version,
    }


@app.get("/api/overview/distributions")
async def overview_distributions(
    metric: str = Query(
        ...,
        description="Metric to compute distribution for",
    ),
    bins: int = Query(25, ge=5, le=100),
    cohort_only: bool = Query(False),
):
    """Distribution data for a metric (categorical or numeric)."""
    corpus = _get_corpus()

    # C2/M5: Explicit whitelist check (defense-in-depth, not just regex)
    if metric not in _DISTRIBUTION_METRICS:
        raise HTTPException(
            400,
            f"Invalid metric: {metric}. Must be one of: {', '.join(sorted(_DISTRIBUTION_METRICS))}",
        )

    categorical_metrics = {"doc_type", "market_segment"}

    if metric in categorical_metrics:
        where = _build_where("cohort_included = true" if cohort_only else "")
        rows = corpus.query(
            f"SELECT {metric}, COUNT(*) FROM documents{where} "
            f"GROUP BY {metric} ORDER BY COUNT(*) DESC"
        )
        return {
            "metric": metric,
            "type": "categorical",
            "categories": [
                {"label": str(r[0]) if r[0] else "unknown", "count": int(r[1])}
                for r in rows
            ],
        }
    else:
        # C2 FIX: Use _build_where to avoid double WHERE
        where = _build_where(
            "cohort_included = true" if cohort_only else "",
            f"{metric} IS NOT NULL",
        )
        rows = corpus.query(f"SELECT {metric} FROM documents{where}")
        values = [float(r[0]) for r in rows if r[0] is not None]

        if not values:
            return {
                "metric": metric,
                "type": "numeric",
                "histogram": [],
                "stats": None,
            }

        return {
            "metric": metric,
            "type": "numeric",
            "histogram": _histogram(values, bins),
            "stats": {
                "count": len(values),
                "mean": round(sum(values) / len(values), 2),
                "median": round(_median(values), 2),
                "stdev": round(_stdev(values), 2),
                "min": round(min(values), 2),
                "max": round(max(values), 2),
                "p5": round(_percentile(values, 0.05), 2),
                "p95": round(_percentile(values, 0.95), 2),
            },
        }


@app.get("/api/overview/cohort-funnel")
async def overview_cohort_funnel():
    """Cohort funnel: total -> by doc_type -> by market_segment."""
    corpus = _get_corpus()

    doc_type_rows = corpus.query(
        "SELECT doc_type, COUNT(*) FROM documents GROUP BY doc_type ORDER BY COUNT(*) DESC"
    )
    segment_rows = corpus.query(
        "SELECT market_segment, COUNT(*) FROM documents "
        "WHERE doc_type = 'credit_agreement' "
        "GROUP BY market_segment ORDER BY COUNT(*) DESC"
    )

    return {
        "total": corpus.doc_count,
        "by_doc_type": [
            {"label": str(r[0]), "count": int(r[1])} for r in doc_type_rows
        ],
        "by_market_segment": [
            {"label": str(r[0]), "count": int(r[1])} for r in segment_rows
        ],
        "cohort_count": corpus.cohort_count(),
    }


# ---------------------------------------------------------------------------
# Routes: Documents
# ---------------------------------------------------------------------------
@app.get("/api/documents")
async def list_documents(
    page: int = Query(0, ge=0),
    page_size: int = Query(50, ge=1, le=1000),
    sort_by: str = Query("borrower"),
    sort_dir: str = Query("asc", pattern="^(asc|desc)$"),
    search: str | None = Query(None),
    doc_type: str | None = Query(None),
    market_segment: str | None = Query(None),
    cohort_only: bool = Query(False),
):
    """Paginated, sortable, filterable document list."""
    corpus = _get_corpus()

    # Allowed sort columns (prevent SQL injection)
    allowed_sorts = {
        "borrower", "admin_agent", "facility_size_mm", "doc_type",
        "market_segment", "section_count", "definition_count",
        "word_count", "cohort_included", "doc_id", "clause_count",
    }
    if sort_by not in allowed_sorts:
        sort_by = "borrower"

    conditions: list[str] = []
    params: list[Any] = []

    if cohort_only:
        conditions.append("cohort_included = true")
    if doc_type:
        conditions.append("doc_type = ?")
        params.append(doc_type)
    if market_segment:
        conditions.append("market_segment = ?")
        params.append(market_segment)
    if search:
        conditions.append("(borrower ILIKE ? OR admin_agent ILIKE ? OR doc_id ILIKE ?)")
        like_pat = f"%{search}%"
        params.extend([like_pat, like_pat, like_pat])

    where = " WHERE " + " AND ".join(conditions) if conditions else ""

    # Count
    count_row = corpus.query(f"SELECT COUNT(*) FROM documents{where}", params)
    total = int(count_row[0][0])

    # Fetch page
    offset = page * page_size
    query = (
        f"SELECT doc_id, borrower, admin_agent, facility_size_mm, closing_date, "
        f"doc_type, doc_type_confidence, market_segment, segment_confidence, "
        f"cohort_included, word_count, section_count, clause_count, "
        f"definition_count, text_length "
        f"FROM documents{where} "
        f"ORDER BY {sort_by} {sort_dir} "
        f"LIMIT ? OFFSET ?"
    )
    rows = corpus.query(query, [*params, page_size, offset])

    columns = [
        "doc_id", "borrower", "admin_agent", "facility_size_mm", "closing_date",
        "doc_type", "doc_type_confidence", "market_segment", "segment_confidence",
        "cohort_included", "word_count", "section_count", "clause_count",
        "definition_count", "text_length",
    ]

    documents = []
    for r in rows:
        doc = {}
        for i, col in enumerate(columns):
            val = r[i]
            if val is None:
                doc[col] = None
            elif col == "cohort_included":
                doc[col] = bool(val)
            elif col in ("facility_size_mm",):
                doc[col] = float(val) if val is not None else None
            elif col in ("word_count", "section_count", "clause_count",
                         "definition_count", "text_length"):
                doc[col] = int(val)
            else:
                doc[col] = str(val)
        documents.append(doc)

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "documents": documents,
    }


@app.get("/api/documents/{doc_id}")
async def get_document(doc_id: str):
    """Full document record with sections summary."""
    corpus = _get_corpus()
    doc = corpus.get_doc(doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail=f"Document not found: {doc_id}")

    sections = corpus.search_sections(doc_id=doc_id, cohort_only=False, limit=1000)

    return {
        "doc": {
            "doc_id": doc.doc_id,
            "cik": doc.cik,
            "accession": doc.accession,
            "path": doc.path,
            "borrower": doc.borrower,
            "admin_agent": doc.admin_agent,
            "facility_size_mm": doc.facility_size_mm,
            "facility_confidence": doc.facility_confidence,
            "closing_ebitda_mm": doc.closing_ebitda_mm,
            "ebitda_confidence": doc.ebitda_confidence,
            "closing_date": doc.closing_date,
            "filing_date": doc.filing_date,
            "form_type": doc.form_type,
            "section_count": doc.section_count,
            "clause_count": doc.clause_count,
            "definition_count": doc.definition_count,
            "text_length": doc.text_length,
            "template_family": doc.template_family,
            "doc_type": doc.doc_type,
            "doc_type_confidence": doc.doc_type_confidence,
            "market_segment": doc.market_segment,
            "segment_confidence": doc.segment_confidence,
            "cohort_included": doc.cohort_included,
            "word_count": doc.word_count,
        },
        "sections": [
            {
                "section_number": s.section_number,
                "heading": s.heading,
                "article_num": s.article_num,
                "word_count": s.word_count,
            }
            for s in sections
        ],
        "definition_count": doc.definition_count,
        "clause_count": doc.clause_count,
    }


# ---------------------------------------------------------------------------
# Routes: Scatter Analysis
# ---------------------------------------------------------------------------
_NUMERIC_COLUMNS = {
    "word_count", "definition_count", "clause_count",
    "section_count", "facility_size_mm", "text_length",
}
_CATEGORICAL_COLUMNS = {"doc_type", "market_segment"}
_COLOR_COLUMNS = _NUMERIC_COLUMNS | _CATEGORICAL_COLUMNS
_ALLOWED_GROUP_BY = {"doc_type", "market_segment", "template_family", "admin_agent", "cohort_included"}
_MAX_GROUPS = 50


@app.get("/api/scatter")
async def scatter(
    x: str = Query("definition_count", description="X-axis metric"),
    y: str = Query("word_count", description="Y-axis metric"),
    color: str | None = Query(None, description="Color metric or category"),
    cohort_only: bool = Query(False),
    limit: int = Query(5000, ge=100, le=30000),
):
    """Scatter plot data for any two numeric dimensions."""
    corpus = _get_corpus()

    # L9: Clean error messages with sorted list
    if x not in _NUMERIC_COLUMNS:
        raise HTTPException(400, f"Invalid x metric: {x}. Must be one of: {', '.join(sorted(_NUMERIC_COLUMNS))}")
    if y not in _NUMERIC_COLUMNS:
        raise HTTPException(400, f"Invalid y metric: {y}. Must be one of: {', '.join(sorted(_NUMERIC_COLUMNS))}")
    if color and color not in _COLOR_COLUMNS:
        raise HTTPException(400, f"Invalid color metric: {color}. Must be one of: {', '.join(sorted(_COLOR_COLUMNS))}")

    # Build WHERE clause
    where = _build_where(
        "cohort_included = true" if cohort_only else "",
        f"{x} IS NOT NULL",
        f"{y} IS NOT NULL",
    )

    # Build select clause
    select_cols = f"doc_id, borrower, {x}, {y}"
    if color:
        select_cols += f", {color}"

    # M7: Parameterize limit; M8: Add ORDER BY for deterministic results
    rows = corpus.query(
        f"SELECT {select_cols} FROM documents{where} ORDER BY doc_id LIMIT ?",
        [limit],
    )

    points = []
    x_vals: list[float] = []
    y_vals: list[float] = []

    for r in rows:
        xv = float(r[2])
        yv = float(r[3])
        point: dict[str, Any] = {
            "doc_id": str(r[0]),
            "borrower": str(r[1]) if r[1] else "",
            "x": xv,
            "y": yv,
        }
        if color:
            val = r[4]
            # L10: Normalize null handling — always use None for missing values
            if val is None:
                point["color"] = None
            elif color in _CATEGORICAL_COLUMNS:
                point["color"] = str(val)
            else:
                point["color"] = float(val)
        points.append(point)
        x_vals.append(xv)
        y_vals.append(yv)

    def _quick_stats(vals: list[float]) -> dict[str, float]:
        if not vals:
            return {"count": 0, "mean": 0, "median": 0, "min": 0, "max": 0}
        return {
            "count": len(vals),
            "mean": round(sum(vals) / len(vals), 2),
            "median": round(_median(vals), 2),
            "min": round(min(vals), 2),
            "max": round(max(vals), 2),
        }

    return {
        "x_metric": x,
        "y_metric": y,
        "color_metric": color,
        "total_points": len(points),
        "points": points,
        "x_stats": _quick_stats(x_vals),
        "y_stats": _quick_stats(y_vals),
    }


# ---------------------------------------------------------------------------
# Routes: Corpus Statistics
# ---------------------------------------------------------------------------
@app.get("/api/stats/metric")
async def stats_metric(
    metric: str = Query(
        "word_count",
        description="Metric to analyze",
    ),
    group_by: str | None = Query(
        None,
        description="Column to group by (categorical)",
    ),
    cohort_only: bool = Query(False),
    bins: int = Query(25, ge=5, le=100),
):
    """Detailed statistics for a numeric metric, optionally grouped."""
    corpus = _get_corpus()

    # M5: Explicit whitelist checks (defense-in-depth)
    if metric not in _NUMERIC_COLUMNS:
        raise HTTPException(
            400,
            f"Invalid metric: {metric}. Must be one of: {', '.join(sorted(_NUMERIC_COLUMNS))}",
        )
    if group_by and group_by not in _ALLOWED_GROUP_BY:
        raise HTTPException(
            400,
            f"Invalid group_by: {group_by}. Must be one of: {', '.join(sorted(_ALLOWED_GROUP_BY))}",
        )

    where = _build_where(
        "cohort_included = true" if cohort_only else "",
        f"{metric} IS NOT NULL",
    )

    # Overall stats
    rows = corpus.query(f"SELECT {metric} FROM documents{where}")
    values = [float(r[0]) for r in rows if r[0] is not None]

    if not values:
        return {
            "metric": metric,
            "group_by": group_by,
            "overall": None,
            "histogram": [],
            "groups": [],
            "outliers": [],
            "fences": {"lower": 0, "upper": 0},
        }

    mean = sum(values) / len(values)
    overall = {
        "count": len(values),
        "mean": round(mean, 2),
        "median": round(_median(values), 2),
        "stdev": round(_stdev(values), 2),
        "min": round(min(values), 2),
        "max": round(max(values), 2),
        "p5": round(_percentile(values, 0.05), 2),
        "p95": round(_percentile(values, 0.95), 2),
        "sum": round(sum(values), 2),
    }

    histogram = _histogram(values, bins)

    # Groups — H8: Cap at _MAX_GROUPS, compute from single query
    groups: list[dict[str, Any]] = []
    if group_by:
        group_rows = corpus.query(
            f"SELECT {group_by}, {metric} FROM documents{where} "
            f"AND {group_by} IS NOT NULL"
        )
        group_map: dict[str, list[float]] = {}
        for r in group_rows:
            key = str(r[0]) if r[0] else "unknown"
            if key not in group_map:
                group_map[key] = []
            group_map[key].append(float(r[1]))

        # H8: Sort by count descending and cap at _MAX_GROUPS
        sorted_groups = sorted(group_map.items(), key=lambda x: -len(x[1]))
        for grp, vals in sorted_groups[:_MAX_GROUPS]:
            grp_mean = sum(vals) / len(vals)
            groups.append({
                "group": grp,
                "count": len(vals),
                "mean": round(grp_mean, 2),
                "median": round(_median(vals), 2),
                "stdev": round(_stdev(vals), 2),
                "min": round(min(vals), 2),
                "max": round(max(vals), 2),
                "p5": round(_percentile(vals, 0.05), 2),
                "p95": round(_percentile(vals, 0.95), 2),
            })

    # IQR outliers
    q1 = _percentile(values, 0.25)
    q3 = _percentile(values, 0.75)
    iqr = q3 - q1
    lower_fence = q1 - 1.5 * iqr
    upper_fence = q3 + 1.5 * iqr

    outliers: list[dict[str, Any]] = []

    # M14: Skip outlier detection when IQR is 0 (all values identical or near-identical)
    if iqr > 0:
        # M6: Use parameterized queries for fence values
        group_col = f", {group_by}" if group_by else ""
        outlier_rows = corpus.query(
            f"SELECT doc_id, borrower, {metric}{group_col} "
            f"FROM documents{where} "
            f"AND ({metric} < ? OR {metric} > ?) "
            f"ORDER BY {metric} DESC LIMIT 100",
            [lower_fence, upper_fence],
        )
        for r in outlier_rows:
            val = float(r[2])
            outliers.append({
                "doc_id": str(r[0]),
                "borrower": str(r[1]) if r[1] else "",
                "value": round(val, 2),
                "direction": "high" if val > upper_fence else "low",
                "group": str(r[3]) if group_by and len(r) > 3 and r[3] else None,
            })

    return {
        "metric": metric,
        "group_by": group_by,
        "overall": overall,
        "histogram": histogram,
        "groups": groups,
        "outliers": outliers,
        "fences": {"lower": round(lower_fence, 2), "upper": round(upper_fence, 2)},
    }


# ---------------------------------------------------------------------------
# Routes: Corpus Text Search (KWIC)
# ---------------------------------------------------------------------------
@app.get("/api/search/text")
async def search_text(
    q: str = Query(
        ...,
        min_length=1,
        max_length=500,
        description="Search pattern (case-insensitive substring match)",
    ),
    context_chars: int = Query(200, ge=20, le=1000),
    max_results: int = Query(100, ge=1, le=500),
    cohort_only: bool = Query(True),
):
    """Full-text KWIC search across all section text in the corpus.

    Returns keyword-in-context results with surrounding text for each match.
    The ``truncated`` flag indicates whether results were capped by max_results.
    """
    corpus = _get_corpus()
    # Request one extra to detect truncation (M7)
    results = corpus.search_text(
        q,
        context_chars=context_chars,
        max_results=max_results + 1,
        cohort_only=cohort_only,
    )

    truncated = len(results) > max_results
    if truncated:
        results = results[:max_results]

    # Compute unique document count
    unique_docs = len({r["doc_id"] for r in results})

    # Enrich with borrower info (batch query for all unique doc_ids)
    borrower_map: dict[str, str] = {}
    if results:
        doc_ids = list({r["doc_id"] for r in results})
        placeholders = ",".join(["?"] * len(doc_ids))
        rows = corpus.query(
            f"SELECT doc_id, borrower FROM documents WHERE doc_id IN ({placeholders})",
            doc_ids,
        )
        borrower_map = {str(r[0]): str(r[1]) if r[1] else "" for r in rows}

    return {
        "query": q,
        "total_matches": len(results),
        "unique_documents": unique_docs,
        "context_chars": context_chars,
        "truncated": truncated,
        "matches": [
            {
                "doc_id": r["doc_id"],
                "borrower": borrower_map.get(r["doc_id"], ""),
                "section_number": r["section_number"],
                "heading": r["heading"],
                "article_num": r["article_num"],
                "char_offset": r["char_offset"],
                "matched_text": r["matched_text"],
                "context_before": r["context_before"],
                "context_after": r["context_after"],
            }
            for r in results
        ],
    }


# ---------------------------------------------------------------------------
# Routes: Definition Explorer
# ---------------------------------------------------------------------------
@app.get("/api/definitions/frequency")
async def definition_frequency(
    term_pattern: str | None = Query(
        None,
        max_length=200,
        description="Optional ILIKE pattern to filter terms",
    ),
    cohort_only: bool = Query(True),
    limit: int = Query(100, ge=1, le=1000),
):
    """Corpus-wide definition term frequency — how many docs define each term."""
    corpus = _get_corpus()

    cohort_condition = (
        "d.doc_id IN (SELECT doc_id FROM documents WHERE cohort_included = true)"
        if cohort_only else "1=1"
    )

    term_condition = ""
    params: list[Any] = []
    if term_pattern:
        term_condition = "AND d.term ILIKE ?"
        params.append(f"%{term_pattern}%")

    # H1: Get true total count of unique terms (before LIMIT)
    count_rows = corpus.query(
        f"""
        SELECT COUNT(DISTINCT d.term)
        FROM definitions d
        WHERE {cohort_condition} {term_condition}
        """,
        list(params),
    )
    total_terms = int(count_rows[0][0]) if count_rows else 0

    rows = corpus.query(
        f"""
        SELECT d.term,
               COUNT(DISTINCT d.doc_id) as doc_count,
               COUNT(*) as total_occurrences,
               AVG(d.confidence) as avg_confidence,
               LIST(DISTINCT d.pattern_engine ORDER BY d.pattern_engine) as engines
        FROM definitions d
        WHERE {cohort_condition} {term_condition}
        GROUP BY d.term
        ORDER BY doc_count DESC
        LIMIT ?
        """,
        [*params, limit],
    )

    return {
        "total_terms": total_terms,
        "terms": [
            {
                "term": str(r[0]),
                "doc_count": int(r[1]),
                "total_occurrences": int(r[2]),
                "avg_confidence": round(float(r[3]), 3) if r[3] else 0.0,
                "engines": list(r[4]) if r[4] else [],
            }
            for r in rows
        ],
    }


@app.get("/api/definitions/variants/{term:path}")
async def definition_variants(
    term: str,
    cohort_only: bool = Query(True),
    limit: int = Query(50, ge=1, le=200),
):
    """Cross-document variants of a specific defined term.

    Shows how different documents define the same term, allowing
    comparison across templates and law firms.
    """
    # L6: Validate path parameter length
    if not term or len(term) > 500:
        raise HTTPException(status_code=400, detail="term must be 1-500 characters")

    corpus = _get_corpus()

    cohort_condition = (
        "d.doc_id IN (SELECT doc_id FROM documents WHERE cohort_included = true)"
        if cohort_only else "1=1"
    )

    # H2: Use case-insensitive exact match (not ILIKE which is a substring match).
    # The user clicked a specific term in the frequency table and expects only
    # that exact term's variants, not partial matches like "Total Indebtedness".
    rows = corpus.query(
        f"""
        SELECT d.doc_id, d.term, d.definition_text, d.confidence,
               d.pattern_engine, doc.borrower
        FROM definitions d
        JOIN documents doc ON d.doc_id = doc.doc_id
        WHERE LOWER(d.term) = LOWER(?) AND {cohort_condition}
        ORDER BY d.confidence DESC
        LIMIT ?
        """,
        [term, limit],
    )

    return {
        "term": term,
        "total_variants": len(rows),
        "variants": [
            {
                "doc_id": str(r[0]),
                "term": str(r[1]),
                "definition_text": str(r[2]),
                "confidence": round(float(r[3]), 3) if r[3] else 0.0,
                "engine": str(r[4]),
                "borrower": str(r[5]) if r[5] else "",
            }
            for r in rows
        ],
    }


# ---------------------------------------------------------------------------
# Routes: Parsing Quality
# ---------------------------------------------------------------------------
@app.get("/api/quality/summary")
async def quality_summary():
    """Aggregate parsing quality metrics across the corpus."""
    corpus = _get_corpus()

    row = corpus.query(
        """
        SELECT
            COUNT(*) as total_docs,
            SUM(CASE WHEN section_count > 0 THEN 1 ELSE 0 END) as docs_with_sections,
            SUM(CASE WHEN clause_count > 0 THEN 1 ELSE 0 END) as docs_with_clauses,
            SUM(CASE WHEN definition_count > 0 THEN 1 ELSE 0 END) as docs_with_defs,
            SUM(CASE WHEN section_count = 0 THEN 1 ELSE 0 END) as no_sections,
            SUM(CASE WHEN definition_count = 0 AND word_count > 10000 THEN 1 ELSE 0 END) as no_defs_large,
            SUM(CASE WHEN clause_count = 0 AND section_count > 0 THEN 1 ELSE 0 END) as zero_clauses,
            SUM(CASE WHEN section_count > 0 OR definition_count > 0 OR clause_count > 0
                THEN 1 ELSE 0 END) as parse_success
        FROM documents
        """
    )[0]

    total = int(row[0]) if row[0] else 0
    with_sections = int(row[1]) if row[1] else 0
    with_clauses = int(row[2]) if row[2] else 0
    with_defs = int(row[3]) if row[3] else 0
    parsed_ok = int(row[7]) if row[7] else 0

    # Word count IQR for extreme_word_count detection
    wc_rows = corpus.query(
        "SELECT word_count FROM documents WHERE word_count IS NOT NULL"
    )
    wc_values = [float(r[0]) for r in wc_rows if r[0] is not None]
    extreme_wc = 0
    if len(wc_values) >= 4:
        q1 = _percentile(wc_values, 0.25)
        q3 = _percentile(wc_values, 0.75)
        iqr = q3 - q1
        if iqr > 0:
            lower = q1 - 1.5 * iqr
            upper = q3 + 1.5 * iqr
            extreme_wc = sum(1 for v in wc_values if v < lower or v > upper)

    # Parse rates by doc_type
    dt_rows = corpus.query(
        """
        SELECT doc_type,
               COUNT(*) as total,
               SUM(CASE WHEN section_count > 0 THEN 1 ELSE 0 END) as with_sections,
               SUM(CASE WHEN definition_count > 0 THEN 1 ELSE 0 END) as with_defs,
               SUM(CASE WHEN clause_count > 0 THEN 1 ELSE 0 END) as with_clauses
        FROM documents
        GROUP BY doc_type
        ORDER BY COUNT(*) DESC
        """
    )

    return {
        "total_docs": total,
        "docs_with_sections": with_sections,
        "docs_with_clauses": with_clauses,
        "docs_with_definitions": with_defs,
        "parse_success_rate": round(parsed_ok / total * 100, 1) if total > 0 else 0,
        "section_extraction_rate": round(with_sections / total * 100, 1) if total > 0 else 0,
        "clause_extraction_rate": round(with_clauses / total * 100, 1) if total > 0 else 0,
        "definition_extraction_rate": round(with_defs / total * 100, 1) if total > 0 else 0,
        "anomaly_counts": {
            "no_sections": int(row[4]) if row[4] else 0,
            "no_definitions": int(row[5]) if row[5] else 0,
            "extreme_word_count": extreme_wc,
            "zero_clauses": int(row[6]) if row[6] else 0,
        },
        "by_doc_type": [
            {
                "doc_type": str(r[0]),
                "total": int(r[1]),
                "section_rate": round(int(r[2]) / int(r[1]) * 100, 1) if int(r[1]) > 0 else 0,
                "definition_rate": round(int(r[3]) / int(r[1]) * 100, 1) if int(r[1]) > 0 else 0,
                "clause_rate": round(int(r[4]) / int(r[1]) * 100, 1) if int(r[1]) > 0 else 0,
            }
            for r in dt_rows
        ],
    }


_ANOMALY_TYPES = {"no_sections", "no_definitions", "extreme_word_count", "zero_clauses", "all"}


@app.get("/api/quality/anomalies")
async def quality_anomalies(
    anomaly_type: str = Query("all", description="Filter by anomaly type"),
    page: int = Query(0, ge=0),
    page_size: int = Query(50, ge=1, le=200),
):
    """Paginated list of documents with parsing anomalies."""
    corpus = _get_corpus()

    if anomaly_type not in _ANOMALY_TYPES:
        raise HTTPException(
            400,
            f"Invalid anomaly_type: {anomaly_type}. Must be one of: {', '.join(sorted(_ANOMALY_TYPES))}",
        )

    # Compute IQR fences only when needed for extreme_word_count
    wc_lower, wc_upper = 0.0, float("inf")
    if anomaly_type in ("all", "extreme_word_count"):
        wc_rows = corpus.query(
            "SELECT word_count FROM documents WHERE word_count IS NOT NULL"
        )
        wc_values = [float(r[0]) for r in wc_rows if r[0] is not None]
        if len(wc_values) >= 4:
            q1 = _percentile(wc_values, 0.25)
            q3 = _percentile(wc_values, 0.75)
            iqr = q3 - q1
            if iqr > 0:
                wc_lower = q1 - 1.5 * iqr
                wc_upper = q3 + 1.5 * iqr

    # Build CASE expression for anomaly classification
    # Each document can have multiple anomalies; we use UNION ALL to produce one
    # row per anomaly occurrence, then filter and paginate.
    anomaly_queries: list[str] = []
    params: list[Any] = []

    if anomaly_type in ("all", "no_sections"):
        anomaly_queries.append(
            "SELECT doc_id, borrower, 'no_sections' as anomaly_type, 'high' as severity, "
            "'No sections extracted' as detail, "
            "doc_type, market_segment, word_count, section_count, definition_count, clause_count, "
            "facility_size_mm "
            "FROM documents WHERE section_count = 0"
        )
    if anomaly_type in ("all", "no_definitions"):
        anomaly_queries.append(
            "SELECT doc_id, borrower, 'no_definitions' as anomaly_type, 'medium' as severity, "
            "'No definitions in large document' as detail, "
            "doc_type, market_segment, word_count, section_count, definition_count, clause_count, "
            "facility_size_mm "
            "FROM documents WHERE definition_count = 0 AND word_count > 10000"
        )
    if anomaly_type in ("all", "extreme_word_count") and wc_upper != float("inf"):
        anomaly_queries.append(
            "SELECT doc_id, borrower, 'extreme_word_count' as anomaly_type, 'low' as severity, "
            "'Word count outside IQR x 1.5 fences' as detail, "
            "doc_type, market_segment, word_count, section_count, definition_count, clause_count, "
            "facility_size_mm "
            "FROM documents WHERE word_count IS NOT NULL AND (word_count < ? OR word_count > ?)"
        )
        params.extend([wc_lower, wc_upper])
    if anomaly_type in ("all", "zero_clauses"):
        anomaly_queries.append(
            "SELECT doc_id, borrower, 'zero_clauses' as anomaly_type, 'medium' as severity, "
            "'Has sections but zero clauses parsed' as detail, "
            "doc_type, market_segment, word_count, section_count, definition_count, clause_count, "
            "facility_size_mm "
            "FROM documents WHERE clause_count = 0 AND section_count > 0"
        )

    if not anomaly_queries:
        return {"total": 0, "page": page, "page_size": page_size, "anomalies": []}

    union_sql = " UNION ALL ".join(anomaly_queries)

    # Count total
    count_row = corpus.query(
        f"SELECT COUNT(*) FROM ({union_sql})", params
    )
    total = int(count_row[0][0]) if count_row else 0

    # Fetch page
    offset = page * page_size
    rows = corpus.query(
        f"SELECT * FROM ({union_sql}) ORDER BY anomaly_type, doc_id LIMIT ? OFFSET ?",
        [*params, page_size, offset],
    )

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "anomalies": [
            {
                "doc_id": str(r[0]),
                "borrower": str(r[1]) if r[1] else "",
                "anomaly_type": str(r[2]),
                "severity": str(r[3]),
                "detail": str(r[4]),
                "doc_type": str(r[5]) if r[5] else "",
                "market_segment": str(r[6]) if r[6] else "",
                "word_count": int(r[7]) if r[7] is not None else 0,
                "section_count": int(r[8]) if r[8] is not None else 0,
                "definition_count": int(r[9]) if r[9] is not None else 0,
                "clause_count": int(r[10]) if r[10] is not None else 0,
                "facility_size_mm": float(r[11]) if r[11] is not None else None,
            }
            for r in rows
        ],
    }


# ---------------------------------------------------------------------------
# Routes: Edge Case Inspector
# ---------------------------------------------------------------------------
_EDGE_CASE_CATEGORIES = {
    "low_definitions", "missing_sections", "extreme_word_count",
    "zero_clauses", "extreme_facility", "all",
}


@app.get("/api/edge-cases")
async def edge_cases(
    category: str = Query("all", description="Edge case category to filter"),
    page: int = Query(0, ge=0),
    page_size: int = Query(50, ge=1, le=200),
    cohort_only: bool = Query(False),
):
    """Categorized edge case documents for inspection."""
    corpus = _get_corpus()

    if category not in _EDGE_CASE_CATEGORIES:
        raise HTTPException(
            400,
            f"Invalid category: {category}. Must be one of: {', '.join(sorted(_EDGE_CASE_CATEGORIES))}",
        )

    cohort_where = "WHERE cohort_included = true AND" if cohort_only else "WHERE"

    # --- Build ALL category queries (always, for global facet counts) ---
    all_queries: list[str] = []
    all_params: list[Any] = []

    # Block-1.1: enriched detail for missing_sections using word_count + doc_type
    all_queries.append(
        f"SELECT doc_id, borrower, 'missing_sections' as category, 'high' as severity, "
        f"CASE "
        f"  WHEN word_count < 500 THEN 'Short document (' || word_count || ' words) — likely amendment or supplement' "
        f"  WHEN doc_type NOT IN ('credit_agreement', 'other', '') "
        f"    THEN 'Non-credit-agreement document (doc_type: ' || doc_type || ')' "
        f"  WHEN word_count > 5000 "
        f"    THEN 'Parser gap — ' || word_count || '-word CA with non-standard heading format' "
        f"  ELSE 'No sections extracted from document' "
        f"END as detail, "
        f"doc_type, market_segment, word_count, section_count, definition_count, "
        f"clause_count, facility_size_mm "
        f"FROM documents {cohort_where} section_count = 0"
    )
    all_queries.append(
        f"SELECT doc_id, borrower, 'low_definitions' as category, 'medium' as severity, "
        f"'Fewer than 20 definitions in document with >10K words' as detail, "
        f"doc_type, market_segment, word_count, section_count, definition_count, "
        f"clause_count, facility_size_mm "
        f"FROM documents {cohort_where} definition_count < 20 AND word_count > 10000"
    )

    # IQR fences for extreme_word_count
    wc_sql = (
        "SELECT word_count FROM documents WHERE cohort_included = true AND word_count IS NOT NULL"
        if cohort_only else
        "SELECT word_count FROM documents WHERE word_count IS NOT NULL"
    )
    fences_rows = corpus.query(wc_sql)
    fences_vals = [float(r[0]) for r in fences_rows if r[0] is not None]
    wc_lo, wc_hi = 0.0, float("inf")
    if len(fences_vals) >= 4:
        q1 = _percentile(fences_vals, 0.25)
        q3 = _percentile(fences_vals, 0.75)
        iqr = q3 - q1
        if iqr > 0:
            wc_lo = q1 - 1.5 * iqr
            wc_hi = q3 + 1.5 * iqr

    if wc_hi != float("inf"):
        all_queries.append(
            f"SELECT doc_id, borrower, 'extreme_word_count' as category, 'low' as severity, "
            f"'Word count outside IQR x 1.5 range' as detail, "
            f"doc_type, market_segment, word_count, section_count, definition_count, "
            f"clause_count, facility_size_mm "
            f"FROM documents {cohort_where} word_count IS NOT NULL "
            f"AND (word_count < ? OR word_count > ?)"
        )
        all_params.extend([wc_lo, wc_hi])

    all_queries.append(
        f"SELECT doc_id, borrower, 'zero_clauses' as category, 'medium' as severity, "
        f"'Sections exist but no clauses parsed' as detail, "
        f"doc_type, market_segment, word_count, section_count, definition_count, "
        f"clause_count, facility_size_mm "
        f"FROM documents {cohort_where} clause_count = 0 AND section_count > 0"
    )
    all_queries.append(
        f"SELECT doc_id, borrower, 'extreme_facility' as category, 'low' as severity, "
        f"'Facility size outside typical range' as detail, "
        f"doc_type, market_segment, word_count, section_count, definition_count, "
        f"clause_count, facility_size_mm "
        f"FROM documents {cohort_where} facility_size_mm IS NOT NULL "
        f"AND (facility_size_mm > 10000 OR facility_size_mm < 1)"
    )

    all_union_sql = " UNION ALL ".join(all_queries)

    # Global category counts (always includes all categories for pill display)
    cat_rows = corpus.query(
        f"SELECT category, COUNT(*) FROM ({all_union_sql}) GROUP BY category ORDER BY COUNT(*) DESC",
        all_params,
    )

    # --- Build filtered query (for the paginated case list) ---
    if category == "all":
        filtered_sql = all_union_sql
        filtered_params = all_params
    else:
        filtered_sql = f"SELECT * FROM ({all_union_sql}) WHERE category = ?"
        filtered_params = [*all_params, category]

    count_row = corpus.query(f"SELECT COUNT(*) FROM ({filtered_sql})", filtered_params)
    total = int(count_row[0][0]) if count_row else 0

    offset = page * page_size
    rows = corpus.query(
        f"SELECT * FROM ({filtered_sql}) ORDER BY category, doc_id LIMIT ? OFFSET ?",
        [*filtered_params, page_size, offset],
    )

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "categories": [
            {"category": str(r[0]), "count": int(r[1])} for r in cat_rows
        ],
        "cases": [
            {
                "doc_id": str(r[0]),
                "borrower": str(r[1]) if r[1] else "",
                "category": str(r[2]),
                "severity": str(r[3]),
                "detail": str(r[4]),
                "doc_type": str(r[5]) if r[5] else "",
                "market_segment": str(r[6]) if r[6] else "",
                "word_count": int(r[7]) if r[7] is not None else 0,
                "section_count": int(r[8]) if r[8] is not None else 0,
                "definition_count": int(r[9]) if r[9] is not None else 0,
                "clause_count": int(r[10]) if r[10] is not None else 0,
                "facility_size_mm": float(r[11]) if r[11] is not None else None,
            }
            for r in rows
        ],
    }


# ---------------------------------------------------------------------------
# Routes: Section Frequency
# ---------------------------------------------------------------------------
@app.get("/api/stats/section-frequency")
async def section_frequency(
    cohort_only: bool = Query(True),
    min_presence: float = Query(0.0, ge=0.0, le=1.0, description="Min fraction of docs"),
    limit: int = Query(100, ge=1, le=500),
):
    """Section-number frequency across the corpus — which sections are most common."""
    corpus = _get_corpus()

    cohort_cond = (
        "s.doc_id IN (SELECT doc_id FROM documents WHERE cohort_included = true)"
        if cohort_only else "1=1"
    )

    # Count total docs for presence rate calculation
    doc_count_row = corpus.query(
        "SELECT COUNT(*) FROM documents"
        + (" WHERE cohort_included = true" if cohort_only else "")
    )
    total_docs = int(doc_count_row[0][0]) if doc_count_row else 1

    rows = corpus.query(
        f"""
        SELECT
            s.section_number,
            MODE(s.heading) as heading,
            COUNT(DISTINCT s.doc_id) as doc_count,
            ROUND(AVG(s.word_count), 0) as avg_word_count,
            ROUND(MEDIAN(s.word_count), 0) as median_word_count
        FROM sections s
        WHERE {cohort_cond}
        GROUP BY s.section_number
        HAVING COUNT(DISTINCT s.doc_id) >= ?
        ORDER BY doc_count DESC
        LIMIT ?
        """,
        [max(1, int(min_presence * total_docs)), limit],
    )

    return {
        "total_docs": total_docs,
        "sections": [
            {
                "section_number": str(r[0]),
                "heading": str(r[1]) if r[1] else "",
                "doc_count": int(r[2]),
                "presence_rate": round(int(r[2]) / total_docs, 4) if total_docs > 0 else 0,
                "avg_word_count": int(r[3]) if r[3] is not None else 0,
                "median_word_count": int(r[4]) if r[4] is not None else 0,
            }
            for r in rows
        ],
    }


# ===========================================================================
# Phase 6: Discovery Lab Endpoints
# ===========================================================================


# ---------------------------------------------------------------------------
# Request models for POST endpoints
# ---------------------------------------------------------------------------
class HeadingDiscoveryRequest(BaseModel):
    search_pattern: str | None = None
    article_min: int | None = None
    article_max: int | None = None
    min_frequency: int = Field(default=2, ge=1)
    limit: int = Field(default=200, ge=1, le=1000)
    cohort_only: bool = True


class PatternTestRequest(BaseModel):
    heading_patterns: list[str]
    keyword_patterns: list[str] = Field(default_factory=list)
    section_filter: str | None = None
    sample_size: int = Field(default=500, ge=0, le=50000)
    cohort_only: bool = True
    seed: int | None = None  # M7: Optional seed for reproducible random sampling


class DnaDiscoveryRequest(BaseModel):
    positive_heading_pattern: str
    top_k: int = Field(default=30, ge=1, le=200)
    min_section_rate: float = Field(default=0.20, ge=0.01, le=1.0)
    max_background_rate: float = Field(default=0.05, ge=0.001, le=0.5)
    ngram_min: int = Field(default=1, ge=1, le=4)
    ngram_max: int = Field(default=3, ge=1, le=5)
    cohort_only: bool = True


class CoverageRequest(BaseModel):
    heading_patterns: list[str]
    keyword_patterns: list[str] = Field(default_factory=list)
    group_by: str = "doc_type"
    sample_size: int = Field(default=0, ge=0, le=50000)
    cohort_only: bool = True
    seed: int | None = None  # M7: Optional seed for reproducible random sampling


class ClauseSearchRequest(BaseModel):
    section_number: str | None = None
    keywords: list[str] = Field(default_factory=list)
    heading_pattern: str | None = None
    min_depth: int = Field(default=1, ge=0, le=10)
    max_depth: int = Field(default=6, ge=1, le=10)
    limit: int = Field(default=200, ge=1, le=2000)
    cohort_only: bool = True


class JobSubmitRequest(BaseModel):
    job_type: str
    params: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Helpers: Lab
# ---------------------------------------------------------------------------
_VALID_PATTERN_GROUP_BY = {"doc_type", "market_segment", "template_family", "admin_agent"}


_MAX_REGEX_LENGTH = 500  # L1 RT4 FIX: limit pattern length to mitigate ReDoS


def _safe_regex(pattern: str) -> str:
    """Validate that a pattern is a legal regex. Raises HTTPException if not."""
    # L1 RT4 FIX: Reject excessively long patterns to reduce ReDoS surface
    if len(pattern) > _MAX_REGEX_LENGTH:
        raise HTTPException(
            status_code=400, detail=f"Regex pattern too long ({len(pattern)} chars, max {_MAX_REGEX_LENGTH})"
        )
    try:
        re.compile(pattern)
    except re.error as e:
        raise HTTPException(
            status_code=400, detail=f"Invalid regex pattern: {e}"
        ) from e
    return pattern


def _escape_like(value: str) -> str:
    """Escape SQL LIKE/ILIKE wildcards (% and _) so they match literally."""
    return value.replace("%", "\\%").replace("_", "\\_")


# M1 FIX: Module-level function (was defined inside dna_discover endpoint)
def _extract_ngrams(text: str, n_min: int, n_max: int) -> Counter[str]:
    """Extract n-grams from text, returning frequency counts."""
    words = re.findall(r"[a-z]+(?:'[a-z]+)?", text.lower())
    ngrams: Counter[str] = Counter()
    for n in range(n_min, n_max + 1):
        for i in range(len(words) - n + 1):
            gram = " ".join(words[i : i + n])
            if len(gram) >= 3:
                ngrams[gram] += 1
    return ngrams


def _heading_matches_any(heading: str, patterns: list[str]) -> bool:
    """Check if a heading matches any of the provided regex patterns (case-insensitive)."""
    h_lower = heading.lower()
    for pat in patterns:
        try:
            if re.search(pat, h_lower, re.IGNORECASE):
                return True
        except re.error:
            continue
    return False


def _text_keyword_score(text: str, keywords: list[str]) -> float:
    """Fraction of keywords found in text (case-insensitive)."""
    if not keywords:
        return 0.0
    t_lower = text.lower()
    found = sum(1 for kw in keywords if kw.lower() in t_lower)
    return found / len(keywords)


# ---------------------------------------------------------------------------
# Routes: Heading Discovery
# ---------------------------------------------------------------------------
@app.post("/api/lab/heading-discover")
async def heading_discover(req: HeadingDiscoveryRequest):
    """Discover unique section headings and their frequency across the corpus."""
    # M2 RT3 FIX: Validate article_min <= article_max
    if req.article_min is not None and req.article_max is not None and req.article_min > req.article_max:
        raise HTTPException(status_code=400, detail=f"article_min ({req.article_min}) must be <= article_max ({req.article_max})")

    corpus = _get_corpus()

    conditions: list[str] = []
    params: list[Any] = []

    if req.cohort_only:
        conditions.append(
            "s.doc_id IN (SELECT doc_id FROM documents WHERE cohort_included = true)"
        )
    if req.article_min is not None:
        conditions.append("s.article_num >= ?")
        params.append(req.article_min)
    if req.article_max is not None:
        conditions.append("s.article_num <= ?")
        params.append(req.article_max)
    if req.search_pattern:
        _safe_regex(req.search_pattern)
        conditions.append("s.heading ~* ?")
        params.append(req.search_pattern)

    where = _build_where(*conditions) if conditions else ""

    # Count total sections scanned
    count_row = corpus.query(
        f"SELECT COUNT(*) FROM sections s {where}", params
    )
    total_scanned = int(count_row[0][0]) if count_row else 0

    rows = corpus.query(
        f"""
        SELECT
            s.heading,
            COUNT(*) as freq,
            LIST(DISTINCT s.article_num) as article_nums,
            COUNT(DISTINCT s.doc_id) as doc_count,
            LIST(DISTINCT s.doc_id LIMIT 5) as example_docs
        FROM sections s
        {where}
        GROUP BY s.heading
        HAVING COUNT(*) >= ?
        ORDER BY freq DESC
        LIMIT ?
        """,
        [*params, req.min_frequency, req.limit],
    )

    return {
        "total_headings": len(rows),
        "total_sections_scanned": total_scanned,
        "headings": [
            {
                "heading": str(r[0]) if r[0] else "",
                "frequency": int(r[1]),
                "article_nums": list(r[2]) if r[2] else [],
                "doc_count": int(r[3]),
                "example_doc_ids": list(r[4]) if r[4] else [],
            }
            for r in rows
        ],
    }


# ---------------------------------------------------------------------------
# Routes: Pattern Testing
# ---------------------------------------------------------------------------
@app.post("/api/lab/pattern-test")
async def pattern_test(req: PatternTestRequest):
    """Test heading + keyword patterns against sections, report hit rate per document."""
    corpus = _get_corpus()

    if not req.heading_patterns:
        raise HTTPException(status_code=400, detail="At least one heading_pattern is required")

    # Validate all regex patterns upfront
    for pat in req.heading_patterns:
        _safe_regex(pat)
    for pat in req.keyword_patterns:
        _safe_regex(pat)

    # Get sample of documents
    cohort_cond = "WHERE cohort_included = true" if req.cohort_only else ""
    sample_clause = ""
    sample_params: list[Any] = []

    if req.sample_size > 0:
        # M7 FIX: Use seeded random sampling instead of deterministic ORDER BY doc_id
        # L1 RT2 FIX: Use parameterized CONCAT instead of f-string interpolation
        if req.seed is not None:
            sample_clause = "ORDER BY HASH(CONCAT(doc_id, ?)) LIMIT ?"
            sample_params = [str(req.seed), req.sample_size]
        else:
            sample_clause = "ORDER BY HASH(doc_id) LIMIT ?"
            sample_params = [req.sample_size]

    doc_rows = corpus.query(
        f"SELECT doc_id, borrower FROM documents {cohort_cond} {sample_clause}",
        sample_params,
    )

    if not doc_rows:
        return {
            "hit_rate": 0.0,
            "total_docs": 0,
            "hits": 0,
            "misses": 0,
            "matches": [],
            "miss_details": [],
            "by_article": [],
        }

    doc_ids = [str(r[0]) for r in doc_rows]
    doc_borrowers = {str(r[0]): str(r[1]) if r[1] else "" for r in doc_rows}

    # M3 FIX: Use subquery instead of large IN clause for scalability
    section_rows = corpus.query(
        f"""
        SELECT s.doc_id, s.section_number, s.heading, s.article_num
        FROM sections s
        INNER JOIN (
            SELECT doc_id FROM documents {cohort_cond} {sample_clause}
        ) d ON s.doc_id = d.doc_id
        ORDER BY s.doc_id, s.section_number
        """,
        sample_params,
    )

    # Group sections by doc_id
    doc_sections: dict[str, list[tuple[str, str, int | None]]] = {}
    for r in section_rows:
        did = str(r[0])
        if did not in doc_sections:
            doc_sections[did] = []
        # H2 FIX: Keep article_num as None when null, not 0
        doc_sections[did].append((str(r[1]), str(r[2]) if r[2] else "", int(r[3]) if r[3] is not None else None))

    # Test each document
    matches: list[dict[str, Any]] = []
    miss_details: list[dict[str, Any]] = []
    article_hits: dict[int, list[bool]] = {}

    for did in doc_ids:
        sections = doc_sections.get(did, [])
        best_score = 0.0
        best_section = ""
        best_heading = ""
        best_method = ""
        best_art_num: int | None = None

        # H2 RT2 FIX: Find best-scoring section (not first-passing)
        for sec_num, heading, art_num in sections:
            # Apply section filter if specified
            if req.section_filter and not sec_num.startswith(req.section_filter):
                continue

            score = 0.0
            method = ""

            # Check heading patterns
            if _heading_matches_any(heading, req.heading_patterns):
                score = 0.8
                method = "heading"

            # Check keyword patterns in heading text
            if req.keyword_patterns:
                kw_score = _text_keyword_score(heading, req.keyword_patterns)
                if kw_score > 0:
                    if score > 0:
                        score = min(1.0, score + kw_score * 0.2)
                        method = "heading+keyword"
                    else:
                        score = kw_score * 0.6
                        method = "keyword"

            if score > best_score:
                best_score = score
                best_section = sec_num
                best_heading = heading
                best_method = method
                best_art_num = art_num

        # M5 RT2 FIX: Single decision after scanning all sections
        if best_score >= 0.3:
            matches.append({
                "doc_id": did,
                "borrower": doc_borrowers.get(did, ""),
                "section_number": best_section,
                "heading": best_heading,
                "article_num": best_art_num,
                "match_method": best_method,
                "score": round(best_score, 3),
            })
            # Track article hits (skip null article numbers)
            if best_art_num is not None:
                if best_art_num not in article_hits:
                    article_hits[best_art_num] = []
                article_hits[best_art_num].append(True)
        else:
            miss_details.append({
                "doc_id": did,
                "borrower": doc_borrowers.get(did, ""),
                "best_section": best_section,
                "best_heading": best_heading,
                "best_score": round(best_score, 3),
            })
            # Track article misses for the best-matching article (skip null articles)
            if best_art_num is not None:
                if best_art_num not in article_hits:
                    article_hits[best_art_num] = []
                article_hits[best_art_num].append(False)

    total = len(doc_ids)
    hits = len(matches)

    return {
        "hit_rate": round(hits / total * 100, 1) if total > 0 else 0.0,
        "total_docs": total,
        "hits": hits,
        "misses": total - hits,
        "matches": matches[:500],
        "miss_details": miss_details[:200],
        "by_article": sorted(
            [
                {
                    "article_num": art,
                    "hit_rate": round(sum(v) / len(v) * 100, 1) if v else 0.0,
                    "n": len(v),
                }
                for art, v in article_hits.items()
            ],
            key=lambda x: x["n"],
            reverse=True,
        )[:20],
    }


# L2 RT2 FIX: Named constants for DNA scoring weights
_DNA_TFIDF_WEIGHT = 0.5       # Weight for TF-IDF component in combined score
_DNA_LOG_ODDS_WEIGHT = 0.5    # Weight for log-odds component in combined score
_DNA_LOG_ODDS_SCALE = 5.0     # Normalization divisor for log-odds (caps at 1.0)


# ---------------------------------------------------------------------------
# Routes: DNA Discovery
# ---------------------------------------------------------------------------
@app.post("/api/lab/dna-discover")
async def dna_discover(req: DnaDiscoveryRequest):
    """Discover discriminating n-gram phrases by comparing positive vs background sections."""
    corpus = _get_corpus()

    _safe_regex(req.positive_heading_pattern)

    cohort_cond = (
        "s.doc_id IN (SELECT doc_id FROM documents WHERE cohort_included = true)"
        if req.cohort_only else "1=1"
    )

    # Get positive sections (matching the heading pattern)
    pos_rows = corpus.query(
        f"""
        SELECT s.doc_id, s.section_number, s.heading, s.text
        FROM sections s
        WHERE {cohort_cond} AND s.heading ~* ?
        LIMIT 5000
        """,
        [req.positive_heading_pattern],
    )

    if not pos_rows:
        return {
            "positive_count": 0,
            "background_count": 0,
            "total_candidates": 0,
            "candidates": [],
        }

    pos_doc_ids = {str(r[0]) for r in pos_rows}

    # Get background sections (NOT matching the heading pattern, from different docs)
    bg_rows = corpus.query(
        f"""
        SELECT s.doc_id, s.section_number, s.heading, s.text
        FROM sections s
        WHERE {cohort_cond}
          AND s.heading !~* ?
          AND s.doc_id NOT IN (
              SELECT doc_id FROM sections WHERE heading ~* ?
          )
        ORDER BY RANDOM()
        LIMIT 5000
        """,
        [req.positive_heading_pattern, req.positive_heading_pattern],
    )

    if not bg_rows:
        return {
            "positive_count": len(pos_rows),
            "background_count": 0,
            "total_candidates": 0,
            "candidates": [],
        }

    # M2 FIX: Validate ngram range
    if req.ngram_min > req.ngram_max:
        raise HTTPException(
            status_code=400,
            detail=f"ngram_min ({req.ngram_min}) must be <= ngram_max ({req.ngram_max})",
        )

    # Count n-grams in positive and background corpora
    pos_section_count = len(pos_rows)
    bg_section_count = len(bg_rows)

    pos_sec_ngrams: Counter[str] = Counter()  # number of positive sections containing gram
    bg_sec_ngrams: Counter[str] = Counter()   # number of bg sections containing gram
    # C3 FIX: Track document-level presence separately from section-level
    pos_doc_gram_sets: dict[str, set[str]] = {}  # doc_id -> set of grams in that doc

    for r in pos_rows:
        text = str(r[3]) if r[3] else ""
        doc_id = str(r[0])
        grams = _extract_ngrams(text, req.ngram_min, req.ngram_max)
        pos_sec_ngrams.update(grams.keys())
        if doc_id not in pos_doc_gram_sets:
            pos_doc_gram_sets[doc_id] = set()
        pos_doc_gram_sets[doc_id].update(grams.keys())

    for r in bg_rows:
        text = str(r[3]) if r[3] else ""
        grams = _extract_ngrams(text, req.ngram_min, req.ngram_max)
        bg_sec_ngrams.update(grams.keys())

    # Build per-gram document count from doc-level sets
    pos_gram_doc_count: Counter[str] = Counter()
    for gram_set in pos_doc_gram_sets.values():
        pos_gram_doc_count.update(gram_set)

    # Score each n-gram: log-odds ratio + TF-IDF-inspired fusion
    candidates: list[dict[str, Any]] = []

    for gram in pos_sec_ngrams:
        sec_rate = pos_sec_ngrams[gram] / pos_section_count
        bg_rate = bg_sec_ngrams.get(gram, 0) / bg_section_count if bg_section_count > 0 else 0.0

        # Gate: must appear in enough positive sections
        if sec_rate < req.min_section_rate:
            continue
        # Gate: must not appear too often in background
        if bg_rate > req.max_background_rate:
            continue

        # Log-odds ratio (with Laplace smoothing)
        pos_freq = pos_sec_ngrams[gram] + 1
        bg_freq = bg_sec_ngrams.get(gram, 0) + 1
        pos_n = pos_section_count + 2
        bg_n = bg_section_count + 2
        log_odds = math.log((pos_freq / pos_n) / (bg_freq / bg_n))

        # TF-IDF-style score: section_rate * inverse_bg_rate
        idf = math.log(1 + bg_section_count / (bg_sec_ngrams.get(gram, 0) + 1))
        tfidf = sec_rate * idf

        # Combined score (weighted fusion)
        # L2 RT2 FIX: Named constants for scoring weights
        # M1 RT3 FIX: Use min(1.0, tfidf) instead of tfidf/idf which cancels IDF
        # M2 RT4 FIX: Clamp log_odds term to >= 0 to prevent negative combined scores
        #   (negative log_odds means gram is MORE common in background — not discriminating)
        combined = _DNA_TFIDF_WEIGHT * min(1.0, tfidf) + _DNA_LOG_ODDS_WEIGHT * max(0.0, min(1.0, log_odds / _DNA_LOG_ODDS_SCALE))

        candidates.append({
            "phrase": gram,
            "combined_score": round(combined, 4),
            "tfidf_score": round(tfidf, 4),
            "log_odds_ratio": round(log_odds, 4),
            "section_rate": round(sec_rate, 4),
            "background_rate": round(bg_rate, 4),
            # C3 FIX: Use actual document-level count, not section count
            "doc_count": pos_gram_doc_count.get(gram, 0),
        })

    # Sort by combined score and take top_k
    candidates.sort(key=lambda x: x["combined_score"], reverse=True)
    candidates = candidates[: req.top_k]

    return {
        "positive_count": pos_section_count,
        "background_count": bg_section_count,
        "total_candidates": len(candidates),
        "candidates": candidates,
    }


# ---------------------------------------------------------------------------
# Routes: Coverage Analysis
# ---------------------------------------------------------------------------
@app.post("/api/lab/coverage")
async def coverage_analysis(req: CoverageRequest):
    """Test heading patterns against the corpus grouped by a dimension."""
    corpus = _get_corpus()

    if not req.heading_patterns:
        raise HTTPException(status_code=400, detail="At least one heading_pattern is required")

    for pat in req.heading_patterns:
        _safe_regex(pat)
    for pat in req.keyword_patterns:
        _safe_regex(pat)

    group_col = req.group_by
    if group_col not in _VALID_PATTERN_GROUP_BY:
        raise HTTPException(
            status_code=400,
            detail=f"group_by must be one of: {', '.join(sorted(_VALID_PATTERN_GROUP_BY))}",
        )

    # Get documents with their group value
    cohort_cond = "WHERE cohort_included = true" if req.cohort_only else ""
    sample_clause = ""
    sample_params: list[Any] = []

    if req.sample_size > 0:
        # M7 FIX: Use seeded random sampling
        # L1 RT2 FIX: Use parameterized CONCAT instead of f-string interpolation
        if req.seed is not None:
            sample_clause = "ORDER BY HASH(CONCAT(doc_id, ?)) LIMIT ?"
            sample_params = [str(req.seed), req.sample_size]
        else:
            sample_clause = "ORDER BY HASH(doc_id) LIMIT ?"
            sample_params = [req.sample_size]

    doc_rows = corpus.query(
        f"SELECT doc_id, {group_col} FROM documents {cohort_cond} {sample_clause}",
        sample_params,
    )

    if not doc_rows:
        return {
            "overall_hit_rate": 0.0,
            "total_docs": 0,
            "total_hits": 0,
            "groups": [],
        }

    doc_ids = [str(r[0]) for r in doc_rows]
    doc_groups = {str(r[0]): str(r[1]) if r[1] else "unknown" for r in doc_rows}

    # M3 FIX: Use subquery instead of large IN clause for scalability
    section_rows = corpus.query(
        f"""
        SELECT s.doc_id, s.section_number, s.heading
        FROM sections s
        INNER JOIN (
            SELECT doc_id FROM documents {cohort_cond} {sample_clause}
        ) d ON s.doc_id = d.doc_id
        """,
        sample_params,
    )

    # Group sections by doc
    doc_sections: dict[str, list[tuple[str, str]]] = {}
    for r in section_rows:
        did = str(r[0])
        if did not in doc_sections:
            doc_sections[did] = []
        doc_sections[did].append((str(r[1]), str(r[2]) if r[2] else ""))

    # Test each document
    group_results: dict[str, list[bool]] = {}
    total_hits = 0

    for did in doc_ids:
        grp = doc_groups.get(did, "unknown")
        if grp not in group_results:
            group_results[grp] = []

        sections = doc_sections.get(did, [])
        hit = False
        for _sec_num, heading in sections:
            if _heading_matches_any(heading, req.heading_patterns):
                hit = True
                break
            # H4 FIX: Use >= 0.3 consistently (matches pattern_test threshold)
            if req.keyword_patterns and _text_keyword_score(heading, req.keyword_patterns) >= 0.3:
                hit = True
                break

        group_results[grp].append(hit)
        if hit:
            total_hits += 1

    total = len(doc_ids)

    groups = sorted(
        [
            {
                "group": grp,
                "hit_rate": round(sum(v) / len(v) * 100, 1) if v else 0.0,
                "hits": sum(v),
                "total": len(v),
            }
            for grp, v in group_results.items()
        ],
        key=lambda x: x["total"],
        reverse=True,
    )

    return {
        "overall_hit_rate": round(total_hits / total * 100, 1) if total > 0 else 0.0,
        "total_docs": total,
        "total_hits": total_hits,
        "groups": groups,
    }


# ---------------------------------------------------------------------------
# Routes: Clause Search
# ---------------------------------------------------------------------------
@app.post("/api/lab/clause-search")
async def clause_search(req: ClauseSearchRequest):
    """Search clauses by keywords, heading pattern, depth range."""
    # M3 RT3 FIX: Validate min_depth <= max_depth
    if req.min_depth > req.max_depth:
        raise HTTPException(status_code=400, detail=f"min_depth ({req.min_depth}) must be <= max_depth ({req.max_depth})")

    corpus = _get_corpus()

    # Verify clauses table exists
    try:
        table_check = corpus.query(
            "SELECT COUNT(*) FROM information_schema.tables WHERE table_name = 'clauses'"
        )
        if not table_check or int(table_check[0][0]) == 0:
            return {"total": 0, "matches": []}
    except Exception:
        return {"total": 0, "matches": []}

    conditions: list[str] = []
    params: list[Any] = []

    if req.cohort_only:
        conditions.append(
            "c.doc_id IN (SELECT doc_id FROM documents WHERE cohort_included = true)"
        )

    if req.section_number:
        conditions.append("c.section_number = ?")
        params.append(req.section_number)

    if req.min_depth > 0:
        conditions.append("c.depth >= ?")
        params.append(req.min_depth)

    if req.max_depth < 10:
        conditions.append("c.depth <= ?")
        params.append(req.max_depth)

    if req.heading_pattern:
        _safe_regex(req.heading_pattern)
        conditions.append(
            """c.section_number IN (
                SELECT section_number FROM sections
                WHERE doc_id = c.doc_id AND heading ~* ?
            )"""
        )
        params.append(req.heading_pattern)

    # Build keyword conditions (match in header_text or label)
    # C1 FIX: Escape ILIKE wildcards (% and _) in user-provided keywords
    if req.keywords:
        kw_conditions = []
        for kw in req.keywords:
            escaped = _escape_like(kw)
            kw_conditions.append("(c.header_text ILIKE ? ESCAPE '\\' OR c.label ILIKE ? ESCAPE '\\')")
            params.extend([f"%{escaped}%", f"%{escaped}%"])
        conditions.append(f"({' OR '.join(kw_conditions)})")

    where = _build_where(*conditions) if conditions else ""

    # Count total
    count_row = corpus.query(
        f"SELECT COUNT(*) FROM clauses c {where}", params
    )
    total = int(count_row[0][0]) if count_row else 0

    # Fetch matching clauses
    rows = corpus.query(
        f"""
        SELECT
            c.doc_id,
            d.borrower,
            c.section_number,
            s.heading,
            c.clause_path,
            c.label,
            c.depth,
            c.header_text,
            SUBSTRING(c.clause_text, 1, 500) as clause_text,
            c.word_count
        FROM clauses c
        LEFT JOIN documents d ON c.doc_id = d.doc_id
        LEFT JOIN sections s ON c.doc_id = s.doc_id AND c.section_number = s.section_number
        {where}
        ORDER BY c.doc_id, c.section_number, c.clause_path
        LIMIT ?
        """,
        [*params, req.limit],
    )

    return {
        "total": total,
        "matches": [
            {
                "doc_id": str(r[0]),
                "borrower": str(r[1]) if r[1] else "",
                "section_number": str(r[2]),
                "section_heading": str(r[3]) if r[3] else "",
                "clause_path": str(r[4]) if r[4] else "",
                "clause_label": str(r[5]) if r[5] else "",
                "depth": int(r[6]) if r[6] is not None else 0,
                "header_text": str(r[7]) if r[7] else "",
                "clause_text": str(r[8]) if r[8] else "",
                "word_count": int(r[9]) if r[9] is not None else 0,
            }
            for r in rows
        ],
    }


# ===========================================================================
# Phase 6: Jobs System
# ===========================================================================

# In-memory job store. In production this would use a database.
_jobs: dict[str, dict[str, Any]] = {}
_MAX_COMPLETED_JOBS = 200  # H1 FIX: cap completed jobs to prevent memory leak
_MAX_ACTIVE_JOBS = 50  # M1 RT4 FIX: cap pending/running jobs to prevent resource exhaustion


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _cleanup_old_jobs() -> None:
    """H1 FIX: Remove oldest completed/failed/cancelled jobs beyond the cap."""
    terminal = [
        (jid, j) for jid, j in _jobs.items()
        if j["status"] in ("completed", "failed", "cancelled")
    ]
    if len(terminal) <= _MAX_COMPLETED_JOBS:
        return
    # Sort by completed_at ascending (oldest first)
    terminal.sort(key=lambda x: x[1].get("completed_at") or "")
    to_remove = len(terminal) - _MAX_COMPLETED_JOBS
    for jid, _ in terminal[:to_remove]:
        del _jobs[jid]


_JOB_TYPE_MODELS: dict[str, type] = {
    "pattern_test": PatternTestRequest,
    "dna_discover": DnaDiscoveryRequest,
    "heading_discover": HeadingDiscoveryRequest,
    "coverage": CoverageRequest,
    "clause_search": ClauseSearchRequest,
}


@app.post("/api/jobs/submit")
async def submit_job(req: JobSubmitRequest):
    """Submit a new background job."""
    if req.job_type not in _JOB_TYPE_MODELS:
        raise HTTPException(
            status_code=400,
            detail=f"job_type must be one of: {', '.join(sorted(_JOB_TYPE_MODELS))}",
        )

    # M1 RT4 FIX: Reject if too many active jobs to prevent resource exhaustion
    active_count = sum(1 for j in _jobs.values() if j["status"] in ("pending", "running"))
    if active_count >= _MAX_ACTIVE_JOBS:
        raise HTTPException(status_code=429, detail="Job queue full — too many active jobs")

    # H4 RT2 FIX: Validate params eagerly so the user gets an immediate 400
    try:
        _JOB_TYPE_MODELS[req.job_type](**req.params)
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid params for {req.job_type}: {e}",
        ) from e

    job_id = str(uuid.uuid4())[:12]
    job: dict[str, Any] = {
        "job_id": job_id,
        "job_type": req.job_type,
        "status": "pending",
        "submitted_at": _now_iso(),
        "started_at": None,
        "completed_at": None,
        "progress": 0.0,
        "progress_message": "Queued",
        "params": req.params,
        "result_summary": None,
        "error": None,
    }
    _jobs[job_id] = job

    # Start job execution in background
    asyncio.create_task(_run_job(job_id))

    return {"job_id": job_id, "status": "pending"}


async def _run_job(job_id: str) -> None:
    """Execute a job asynchronously. Updates job state in _jobs dict."""
    job = _jobs.get(job_id)
    if not job:
        return

    # H1 RT3 FIX: Don't overwrite "cancelled" status set before task started
    if job["status"] == "cancelled":
        return

    job["status"] = "running"
    job["started_at"] = _now_iso()
    job["progress_message"] = "Starting..."

    try:
        jtype = job["job_type"]

        if jtype == "heading_discover":
            req = HeadingDiscoveryRequest(**job["params"])
            job["progress"] = 0.1
            job["progress_message"] = "Scanning sections..."
            result = await heading_discover(req)
            job["result_summary"] = {
                "total_headings": result["total_headings"],
                "total_scanned": result["total_sections_scanned"],
            }

        elif jtype == "pattern_test":
            req_pt = PatternTestRequest(**job["params"])
            job["progress"] = 0.1
            job["progress_message"] = f"Testing {req_pt.sample_size} documents..."
            result = await pattern_test(req_pt)
            job["result_summary"] = {
                "hit_rate": result["hit_rate"],
                "total_docs": result["total_docs"],
                "hits": result["hits"],
            }

        elif jtype == "dna_discover":
            req_dna = DnaDiscoveryRequest(**job["params"])
            job["progress"] = 0.1
            job["progress_message"] = "Discovering phrases..."
            result = await dna_discover(req_dna)
            job["result_summary"] = {
                "positive_count": result["positive_count"],
                "background_count": result["background_count"],
                "total_candidates": result["total_candidates"],
            }

        elif jtype == "coverage":
            req_cov = CoverageRequest(**job["params"])
            job["progress"] = 0.1
            job["progress_message"] = "Running coverage analysis..."
            result = await coverage_analysis(req_cov)
            job["result_summary"] = {
                "overall_hit_rate": result["overall_hit_rate"],
                "total_docs": result["total_docs"],
            }

        elif jtype == "clause_search":
            req_cls = ClauseSearchRequest(**job["params"])
            job["progress"] = 0.1
            job["progress_message"] = "Searching clauses..."
            result = await clause_search(req_cls)
            job["result_summary"] = {"total": result["total"]}

        else:
            raise ValueError(f"Unknown job type: {jtype}")

        # H1 RT2 FIX: Don't overwrite "cancelled" status set during an await
        if job["status"] != "cancelled":
            job["status"] = "completed"
            job["progress"] = 1.0
            job["progress_message"] = "Done"
            job["completed_at"] = _now_iso()

    except HTTPException as he:
        # H3 FIX: Unwrap HTTPException detail for background jobs
        # H1 RT2 FIX: Respect cancellation even on error
        if job["status"] != "cancelled":
            job["status"] = "failed"
            job["error"] = str(he.detail)
            job["completed_at"] = _now_iso()
            job["progress_message"] = f"Failed: {he.detail}"
    except Exception as e:
        if job["status"] != "cancelled":
            job["status"] = "failed"
            job["error"] = str(e)
            job["completed_at"] = _now_iso()
            job["progress_message"] = f"Failed: {e}"
    finally:
        # H1 FIX: Cleanup old jobs after each completion
        _cleanup_old_jobs()


@app.get("/api/jobs")
async def list_jobs(
    status: str | None = Query(None),
):
    """List all jobs, optionally filtered by status."""
    jobs = list(_jobs.values())

    if status:
        jobs = [j for j in jobs if j["status"] == status]

    # Sort by submitted_at descending
    jobs.sort(key=lambda j: j["submitted_at"], reverse=True)

    return {"total": len(jobs), "jobs": jobs}


@app.get("/api/jobs/{job_id}/status")
async def get_job_status(job_id: str):
    """Get the status of a specific job."""
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    return job


@app.post("/api/jobs/{job_id}/cancel")
async def cancel_job(job_id: str):
    """Cancel a pending or running job."""
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    if job["status"] in ("pending", "running"):
        job["status"] = "cancelled"
        job["completed_at"] = _now_iso()
        job["progress_message"] = "Cancelled by user"
        return {"cancelled": True}

    return {"cancelled": False}


@app.get("/api/jobs/{job_id}/stream")
async def job_stream(job_id: str, request: Request):
    """SSE stream for real-time job progress updates."""
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    # C2 FIX: Use module-level imports (orjson + StreamingResponse)
    # M1 RT2 FIX: Wrap in try/except so stream failures send an error event
    async def event_generator():
        try:
            while True:
                if await request.is_disconnected():
                    break

                j = _jobs.get(job_id)
                if not j:
                    yield f"event: error\ndata: {orjson.dumps({'error': 'Job not found'}).decode()}\n\n"
                    break

                data = orjson.dumps({
                    "status": j["status"],
                    "progress": j["progress"],
                    "message": j["progress_message"],
                }).decode()
                yield f"data: {data}\n\n"

                if j["status"] in ("completed", "failed", "cancelled"):
                    summary = orjson.dumps(j.get("result_summary") or {}).decode()
                    yield f"event: complete\ndata: {summary}\n\n"
                    break

                await asyncio.sleep(0.5)
        except Exception as exc:
            yield f"event: error\ndata: {orjson.dumps({'error': str(exc)}).decode()}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ===========================================================================
# Phase 7: Ontology Explorer
# ===========================================================================


@app.get("/api/ontology/stats")
async def ontology_stats():
    """Return pre-computed ontology statistics."""
    _get_ontology()
    return _ontology_stats


@app.get("/api/ontology/tree")
async def ontology_tree(
    domain: str | None = Query(None, description="Filter to single domain"),
    node_type: str | None = Query(None, alias="type", description="Filter node type"),
    level_max: int | None = Query(None, ge=0, le=5, description="Max depth level"),
    search: str | None = Query(None, min_length=2, description="Text filter on name/id"),
):
    """Return full ontology hierarchy with optional filters."""
    _get_ontology()

    def _prune(node: dict[str, Any]) -> dict[str, Any] | None:
        """Recursively prune tree based on filters. Returns None if branch should be excluded."""
        # Level filter
        if level_max is not None and node["level"] > level_max:
            return None

        # Domain filter
        if domain and node.get("domain_id", node["id"]) != domain and node["id"] != domain:
            if node["type"] != "domain":
                return None

        # Type filter: include ancestors of matching type
        # (domains and families are always shown when filtering for concepts/sub_components)

        # Prune children first
        pruned_children = []
        for child in node.get("children", []):
            pruned = _prune(child)
            if pruned is not None:
                pruned_children.append(pruned)

        # Search filter: keep node if it matches, or if any descendant matches
        if search:
            s_lower = search.lower()
            name_match = s_lower in node["name"].lower()
            id_match = s_lower in node["id"].lower()
            self_match = name_match or id_match
            if not self_match and not pruned_children:
                return None

        # Type filter (leaf-level): only exclude if no matching descendants
        if node_type and node["type"] != node_type and not pruned_children:
            return None

        result = {k: v for k, v in node.items() if k != "children"}
        result["children"] = pruned_children
        result["child_count"] = len(pruned_children)
        return result

    # Domain filter at root level
    roots = _ontology_tree
    if domain:
        roots = [r for r in roots if r["id"] == domain]
        if not roots:
            # Domain filter didn't match root - return empty
            return {"roots": [], "total_nodes": 0}

    # Apply pruning if any filter is active
    if domain or node_type or level_max is not None or search:
        pruned_roots = []
        for root in roots:
            pruned = _prune(root)
            if pruned is not None:
                pruned_roots.append(pruned)

        def _count(nodes: list[dict[str, Any]]) -> int:
            total = len(nodes)
            for n in nodes:
                total += _count(n.get("children", []))
            return total

        return {"roots": pruned_roots, "total_nodes": _count(pruned_roots)}

    # No filters — return full tree
    def _count_all(nodes: list[dict[str, Any]]) -> int:
        total = len(nodes)
        for n in nodes:
            total += _count_all(n.get("children", []))
        return total

    return {"roots": _ontology_tree, "total_nodes": _count_all(_ontology_tree)}


@app.get("/api/ontology/nodes/{node_id:path}")
async def ontology_node_detail(node_id: str):
    """Return full node detail with resolved edges."""
    _get_ontology()
    node = _ontology_nodes.get(node_id)
    if not node:
        raise HTTPException(status_code=404, detail=f"Node '{node_id}' not found")

    # Resolve edges with names
    edges = _ontology_edge_index.get(node_id, [])
    incoming: list[dict[str, Any]] = []
    outgoing: list[dict[str, Any]] = []
    for e in edges:
        resolved = dict(e)
        resolved["source_name"] = _ontology_nodes.get(e["source_id"], {}).get("name", e["source_id"])
        resolved["target_name"] = _ontology_nodes.get(e["target_id"], {}).get("name", e["target_id"])
        if e["source_id"] == node_id:
            outgoing.append(resolved)
        else:
            incoming.append(resolved)

    result = dict(node)
    result["incoming_edges"] = incoming
    result["outgoing_edges"] = outgoing
    result["notes"] = _ontology_notes.get(node_id, "")
    return result


@app.put("/api/ontology/nodes/{node_id:path}/notes")
async def ontology_node_update_notes(node_id: str, body: dict[str, Any] = Body(...)):
    """Save or clear user notes for an ontology node."""
    _get_ontology()
    if node_id not in _ontology_nodes:
        raise HTTPException(status_code=404, detail=f"Node '{node_id}' not found")

    notes_text = str(body.get("notes", "")).strip()
    async with _ontology_notes_lock:
        if notes_text:
            _ontology_notes[node_id] = notes_text
        else:
            _ontology_notes.pop(node_id, None)
        _save_ontology_notes()

    return {"node_id": node_id, "notes": notes_text}


@app.get("/api/ontology/edges")
async def ontology_edges(
    source_id: str | None = Query(None),
    target_id: str | None = Query(None),
    edge_type: str | None = Query(None),
    limit: int = Query(default=200, le=1000),
):
    """Query ontology edges with optional filters."""
    _get_ontology()
    results = _ontology_edges

    if source_id:
        results = [e for e in results if e["source_id"] == source_id]
    if target_id:
        results = [e for e in results if e["target_id"] == target_id]
    if edge_type:
        results = [e for e in results if e["edge_type"] == edge_type]

    # Resolve names
    resolved = []
    for e in results[:limit]:
        r = dict(e)
        r["source_name"] = _ontology_nodes.get(e["source_id"], {}).get("name", e["source_id"])
        r["target_name"] = _ontology_nodes.get(e["target_id"], {}).get("name", e["target_id"])
        resolved.append(r)

    return {"total": len(results), "edges": resolved}


@app.get("/api/ontology/search")
async def ontology_search(
    q: str = Query(min_length=2, description="Search query"),
    limit: int = Query(default=20, le=100),
):
    """Search ontology nodes by id, name, or definition."""
    _get_ontology()
    q_lower = q.lower()

    scored: list[tuple[int, dict[str, Any]]] = []
    for node in _ontology_nodes.values():
        name_lower = node["name"].lower()
        id_lower = node["id"].lower()
        definition = node.get("definition", "")
        def_lower = definition.lower() if definition else ""

        # Score: exact name > name contains > id contains > definition contains
        if name_lower == q_lower:
            score = 100
            match_field = "name"
        elif q_lower in name_lower:
            score = 80
            match_field = "name"
        elif q_lower in id_lower:
            score = 60
            match_field = "id"
        elif q_lower in def_lower:
            score = 40
            match_field = "definition"
        else:
            continue

        # Build snippet from definition
        snippet = ""
        if definition:
            idx = def_lower.find(q_lower)
            if idx >= 0:
                start = max(0, idx - 80)
                end = min(len(definition), idx + len(q) + 80)
                snippet = ("..." if start > 0 else "") + definition[start:end] + ("..." if end < len(definition) else "")
            else:
                snippet = definition[:160] + ("..." if len(definition) > 160 else "")

        scored.append((score, {
            "id": node["id"],
            "name": node["name"],
            "type": node["type"],
            "level": node["level"],
            "domain_id": node.get("domain_id", ""),
            "family_id": node.get("family_id"),
            "definition_snippet": snippet,
            "match_field": match_field,
            "corpus_prevalence": node.get("corpus_prevalence"),
        }))

    # Sort by score descending, then by name
    scored.sort(key=lambda x: (-x[0], x[1]["name"]))

    return {
        "query": q,
        "total": len(scored),
        "results": [s[1] for s in scored[:limit]],
    }


@app.get("/api/ontology/graph")
async def ontology_graph(
    center: str = Query(..., description="Center node ID"),
    depth: int = Query(default=2, ge=1, le=3),
    max_nodes: int = Query(default=80, le=200),
):
    """Return BFS neighborhood subgraph for force-directed visualization."""
    _get_ontology()
    if center not in _ontology_nodes:
        raise HTTPException(status_code=404, detail=f"Node '{center}' not found")

    # BFS from center following edges
    visited: set[str] = {center}
    queue: list[tuple[str, int]] = [(center, 0)]
    graph_edges: list[dict[str, str]] = []
    seen_edges: set[tuple[str, str, str]] = set()

    while queue and len(visited) < max_nodes:
        node_id, d = queue.pop(0)
        if d >= depth:
            continue

        for edge in _ontology_edge_index.get(node_id, []):
            src = edge["source_id"]
            tgt = edge["target_id"]
            edge_key = (src, tgt, edge["edge_type"])
            if edge_key in seen_edges:
                continue
            seen_edges.add(edge_key)

            # Determine the neighbor
            neighbor = tgt if src == node_id else src
            if neighbor not in _ontology_nodes:
                continue

            # Add edge
            graph_edges.append({
                "source": src,
                "target": tgt,
                "edge_type": edge["edge_type"],
                "description": edge.get("description", ""),
            })

            if neighbor not in visited and len(visited) < max_nodes:
                visited.add(neighbor)
                queue.append((neighbor, d + 1))

    # Build node list
    graph_nodes = []
    for nid in visited:
        n = _ontology_nodes[nid]
        graph_nodes.append({
            "id": n["id"],
            "name": n["name"],
            "type": n["type"],
            "level": n["level"],
            "domain_id": n.get("domain_id", ""),
        })

    return {
        "center_id": center,
        "depth": depth,
        "nodes": graph_nodes,
        "edges": graph_edges,
    }


# ---------------------------------------------------------------------------
# Routes: Credit Agreement Reader (Phase 8)
# ---------------------------------------------------------------------------


@app.get("/api/reader/{doc_id}/section/{section_number:path}")
async def reader_section_detail(doc_id: str, section_number: str):
    """Full section text + clause tree for the reader view."""
    corpus = _get_corpus()
    doc = corpus.get_doc(doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail=f"Document not found: {doc_id}")

    # Find section metadata (direct SQL for O(1) lookup)
    rows = corpus.query(
        "SELECT section_number, heading, article_num, word_count "
        "FROM sections WHERE doc_id = ? AND section_number = ?",
        [doc_id, section_number],
    )
    if not rows:
        raise HTTPException(
            status_code=404,
            detail=f"Section {section_number} not found in {doc_id}",
        )
    row = rows[0]

    # Get full text
    text = corpus.get_section_text(doc_id, section_number) or ""

    # Get clause tree
    clauses = corpus.get_clauses(doc_id, section_number)

    return {
        "section_number": str(row[0]),
        "heading": str(row[1]),
        "article_num": int(row[2]),
        "word_count": int(row[3]),
        "text": text,
        "clauses": [
            {
                "clause_id": c.clause_id,
                "label": c.label,
                "depth": c.depth,
                "level_type": c.level_type,
                "span_start": c.span_start,
                "span_end": c.span_end,
                "header_text": c.header_text,
                "parent_id": c.parent_id,
                "is_structural": c.is_structural,
                "parse_confidence": c.parse_confidence,
            }
            for c in clauses
        ],
    }


@app.get("/api/reader/{doc_id}/definitions")
async def reader_definitions(doc_id: str):
    """All defined terms for a document."""
    corpus = _get_corpus()
    doc = corpus.get_doc(doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail=f"Document not found: {doc_id}")

    defs = corpus.get_definitions(doc_id)

    return {
        "doc_id": doc_id,
        "definitions": [
            {
                "term": d.term,
                "definition_text": d.definition_text,
                "char_start": d.char_start,
                "char_end": d.char_end,
                "confidence": d.confidence,
            }
            for d in defs
        ],
    }


@app.get("/api/reader/{doc_id}/search")
async def reader_search(
    doc_id: str,
    q: str = Query(..., min_length=2, max_length=500),
    limit: int = Query(50, ge=1, le=200),
):
    """Search within a single document's section text."""
    corpus = _get_corpus()
    doc = corpus.get_doc(doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail=f"Document not found: {doc_id}")

    results = corpus.search_text(
        q,
        context_chars=150,
        max_results=limit,
        doc_ids=[doc_id],
        cohort_only=False,
    )

    return {
        "query": q,
        "total": len(results),
        "results": [
            {
                "section_number": r["section_number"],
                "heading": r["heading"],
                "char_offset": r["char_offset"],
                "matched_text": r["matched_text"],
                "context_before": r["context_before"],
                "context_after": r["context_after"],
            }
            for r in results
        ],
    }


# ---------------------------------------------------------------------------
# Routes: Strategy Manager (Phase 9)
# ---------------------------------------------------------------------------


def _strategy_summary(s: dict[str, Any]) -> dict[str, Any]:
    """Extract summary fields from a normalized strategy dict."""
    return {
        "concept_id": s.get("concept_id", ""),
        "concept_name": s.get("concept_name", ""),
        "family": s.get("family", ""),
        "validation_status": s.get("validation_status", "bootstrap"),
        "version": s.get("version", 1),
        "heading_pattern_count": len(s.get("heading_patterns", [])),
        "keyword_anchor_count": len(s.get("keyword_anchors", [])),
        "dna_phrase_count": s.get("dna_phrase_count", 0)
        or len(s.get("dna_tier1", [])) + len(s.get("dna_tier2", [])),
        "heading_hit_rate": s.get("heading_hit_rate", 0.0),
        "keyword_precision": s.get("keyword_precision", 0.0),
        "corpus_prevalence": s.get("corpus_prevalence", 0.0),
        "cohort_coverage": s.get("cohort_coverage", 0.0),
        "last_updated": s.get("last_updated", ""),
        "has_qc_issues": bool(s.get("dropped_headings"))
        or bool(s.get("false_positive_keywords")),
    }


def _find_latest_judge_report(concept_id: str) -> tuple[Path | None, int]:
    """Locate the latest versioned judge report for a concept."""
    best_path: Path | None = None
    best_version = -1
    pattern = re.compile(rf"^{re.escape(concept_id)}_v(\d+)\.judge\.json$")

    if not _workspace_root.exists():
        return None, -1

    for family_dir in _workspace_root.iterdir():
        if not family_dir.is_dir():
            continue
        strategies_dir = family_dir / "strategies"
        if not strategies_dir.exists():
            continue
        for fp in strategies_dir.glob("*.judge.json"):
            m = pattern.match(fp.name)
            if not m:
                continue
            version = int(m.group(1))
            if version > best_version:
                best_version = version
                best_path = fp
    return best_path, best_version


@app.get("/api/strategies")
async def list_strategies(
    family: str | None = Query(None),
    validation_status: str | None = Query(None),
    sort_by: str = Query("concept_name"),
    sort_dir: str = Query("asc"),
):
    """List all strategies with optional filters."""
    items = list(_strategies.values())

    # Apply filters
    if family:
        items = [s for s in items if s.get("family") == family]
    if validation_status:
        items = [s for s in items if s.get("validation_status") == validation_status]

    # Build summaries
    summaries = [_strategy_summary(s) for s in items]

    # Sort
    reverse = sort_dir == "desc"
    sort_key = sort_by if sort_by in ("concept_id", "concept_name", "family", "validation_status", "version", "heading_hit_rate", "keyword_precision", "corpus_prevalence", "cohort_coverage") else "concept_name"
    summaries.sort(key=lambda x: x.get(sort_key, ""), reverse=reverse)

    # Compute facet counts from the full (unfiltered) set
    all_items = list(_strategies.values())
    family_counts: dict[str, int] = {}
    status_counts: dict[str, int] = {}
    for s in all_items:
        f = s.get("family", "unknown")
        family_counts[f] = family_counts.get(f, 0) + 1
        st = s.get("validation_status", "bootstrap")
        status_counts[st] = status_counts.get(st, 0) + 1

    return {
        "total": len(summaries),
        "families": [{"family": f, "count": c} for f, c in sorted(family_counts.items())],
        "validation_statuses": [{"status": st, "count": c} for st, c in sorted(status_counts.items())],
        "strategies": summaries,
    }


@app.get("/api/strategies/stats")
async def strategy_stats():
    """Aggregate strategy statistics by family."""
    if not _strategies:
        return {
            "total_strategies": 0,
            "total_families": 0,
            "by_validation_status": [],
            "by_family": [],
            "overall_avg_heading_hit_rate": 0.0,
            "overall_avg_keyword_precision": 0.0,
            "overall_avg_corpus_prevalence": 0.0,
            "overall_avg_cohort_coverage": 0.0,
        }

    all_items = list(_strategies.values())
    n = len(all_items)

    # Status counts
    status_counts: dict[str, int] = {}
    for s in all_items:
        st = s.get("validation_status", "bootstrap")
        status_counts[st] = status_counts.get(st, 0) + 1

    # Per-family aggregates
    by_family: list[dict[str, Any]] = []
    for fam, cids in sorted(_strategy_families.items()):
        fam_items = [_strategies[cid] for cid in cids if cid in _strategies]
        fn = len(fam_items)
        if fn == 0:
            continue
        by_family.append({
            "family": fam,
            "strategy_count": fn,
            "avg_heading_hit_rate": sum(s.get("heading_hit_rate", 0.0) for s in fam_items) / fn,
            "avg_keyword_precision": sum(s.get("keyword_precision", 0.0) for s in fam_items) / fn,
            "avg_corpus_prevalence": sum(s.get("corpus_prevalence", 0.0) for s in fam_items) / fn,
            "avg_cohort_coverage": sum(s.get("cohort_coverage", 0.0) for s in fam_items) / fn,
            "total_dna_phrases": sum(
                s.get("dna_phrase_count", 0)
                or len(s.get("dna_tier1", [])) + len(s.get("dna_tier2", []))
                for s in fam_items
            ),
        })

    return {
        "total_strategies": n,
        "total_families": len(_strategy_families),
        "by_validation_status": [{"status": st, "count": c} for st, c in sorted(status_counts.items())],
        "by_family": by_family,
        "overall_avg_heading_hit_rate": sum(s.get("heading_hit_rate", 0.0) for s in all_items) / n,
        "overall_avg_keyword_precision": sum(s.get("keyword_precision", 0.0) for s in all_items) / n,
        "overall_avg_corpus_prevalence": sum(s.get("corpus_prevalence", 0.0) for s in all_items) / n,
        "overall_avg_cohort_coverage": sum(s.get("cohort_coverage", 0.0) for s in all_items) / n,
    }


@app.get("/api/strategies/{concept_id:path}")
async def get_strategy(concept_id: str):
    """Full strategy detail."""
    s = _strategies.get(concept_id)
    if s is None:
        raise HTTPException(status_code=404, detail=f"Strategy not found: {concept_id}")
    return s


@app.get("/api/strategies/{concept_id:path}/judge/latest")
async def get_latest_judge_report(concept_id: str):
    """Latest llm_judge output persisted by strategy_writer for a concept."""
    fp, version = _find_latest_judge_report(concept_id)
    if fp is None or not fp.exists():
        raise HTTPException(
            status_code=404,
            detail=f"No judge report found for strategy concept: {concept_id}",
        )
    try:
        payload = orjson.loads(fp.read_bytes())
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to parse judge report: {exc}",
        ) from exc

    if not isinstance(payload, dict):
        raise HTTPException(status_code=500, detail="Judge report payload is not an object.")

    return {
        "concept_id": concept_id,
        "version": version,
        "path": str(fp),
        "summary": {
            "precision_estimate": payload.get("precision_estimate", 0.0),
            "weighted_precision_estimate": payload.get("weighted_precision_estimate", 0.0),
            "n_sampled": payload.get("n_sampled", 0),
            "correct": payload.get("correct", 0),
            "partial": payload.get("partial", 0),
            "wrong": payload.get("wrong", 0),
            "backend_used": payload.get("backend_used", []),
            "generated_at": payload.get("generated_at", ""),
            "run_id": payload.get("run_id", ""),
        },
        "report": payload,
    }


# ---------------------------------------------------------------------------
# Routes: Review Operations (P2-05)
# ---------------------------------------------------------------------------


def _iter_workspace_evidence_files() -> list[Path]:
    files: list[Path] = []
    if not _workspace_root.exists():
        return files
    for family_dir in sorted(_workspace_root.iterdir()):
        if not family_dir.is_dir():
            continue
        evidence_dir = family_dir / "evidence"
        if not evidence_dir.exists():
            continue
        files.extend(sorted(evidence_dir.glob("*.jsonl")))
    return files


def _iter_workspace_strategy_files(concept_id: str) -> list[tuple[int, Path]]:
    out: list[tuple[int, Path]] = []
    pat = re.compile(rf"^{re.escape(concept_id)}_v(\d+)\.json$")
    if not _workspace_root.exists():
        return out
    for family_dir in sorted(_workspace_root.iterdir()):
        if not family_dir.is_dir():
            continue
        strategies_dir = family_dir / "strategies"
        if not strategies_dir.exists():
            continue
        for fp in strategies_dir.glob("*.json"):
            if fp.name.endswith(".raw.json") or fp.name.endswith(".resolved.json") or fp.name.endswith(".judge.json"):
                continue
            m = pat.match(fp.name)
            if not m:
                continue
            out.append((int(m.group(1)), fp))
    out.sort(key=lambda row: row[0])
    return out


def _iter_workspace_judge_files(concept_id: str) -> list[tuple[int, Path]]:
    out: list[tuple[int, Path]] = []
    pat = re.compile(rf"^{re.escape(concept_id)}_v(\d+)\.judge\.json$")
    if not _workspace_root.exists():
        return out
    for family_dir in sorted(_workspace_root.iterdir()):
        if not family_dir.is_dir():
            continue
        strategies_dir = family_dir / "strategies"
        if not strategies_dir.exists():
            continue
        for fp in strategies_dir.glob("*.judge.json"):
            m = pat.match(fp.name)
            if not m:
                continue
            out.append((int(m.group(1)), fp))
    out.sort(key=lambda row: row[0])
    return out


def _safe_load_json(path: Path) -> dict[str, Any]:
    try:
        payload = orjson.loads(path.read_bytes())
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


@app.get("/api/review/strategy-timeline/{concept_id:path}")
async def review_strategy_timeline(concept_id: str):
    files = _iter_workspace_strategy_files(concept_id)
    if not files:
        raise HTTPException(status_code=404, detail=f"No strategy versions found for concept: {concept_id}")

    versions: list[dict[str, Any]] = []
    previous: dict[str, Any] | None = None
    for version, fp in files:
        payload = _safe_load_json(fp)
        meta = payload.get("_meta", {}) if isinstance(payload.get("_meta"), dict) else {}
        headings = payload.get("heading_patterns", [])
        keywords = payload.get("keyword_anchors", [])
        dna1 = payload.get("dna_tier1", [])
        dna2 = payload.get("dna_tier2", [])
        judge_fp = fp.with_name(f"{concept_id}_v{version:03d}.judge.json")
        judge_payload = _safe_load_json(judge_fp) if judge_fp.exists() else {}

        row = {
            "version": version,
            "path": str(fp),
            "resolved_path": str(fp.with_name(f"{concept_id}_v{version:03d}.resolved.json")),
            "raw_path": str(fp.with_name(f"{concept_id}_v{version:03d}.raw.json")),
            "note": str(meta.get("note", "") or ""),
            "previous_version": meta.get("previous_version"),
            "heading_pattern_count": len(headings) if isinstance(headings, list) else 0,
            "keyword_anchor_count": len(keywords) if isinstance(keywords, list) else 0,
            "dna_phrase_count": (
                (len(dna1) if isinstance(dna1, list) else 0)
                + (len(dna2) if isinstance(dna2, list) else 0)
            ),
            "heading_hit_rate": payload.get("heading_hit_rate", 0.0),
            "keyword_precision": payload.get("keyword_precision", 0.0),
            "cohort_coverage": payload.get("cohort_coverage", 0.0),
            "judge": {
                "exists": bool(judge_payload),
                "path": str(judge_fp) if judge_fp.exists() else "",
                "precision_estimate": judge_payload.get("precision_estimate", 0.0),
                "weighted_precision_estimate": judge_payload.get("weighted_precision_estimate", 0.0),
                "n_sampled": judge_payload.get("n_sampled", 0),
            },
        }
        if previous is not None:
            row["delta"] = {
                "heading_pattern_count": row["heading_pattern_count"] - previous["heading_pattern_count"],
                "keyword_anchor_count": row["keyword_anchor_count"] - previous["keyword_anchor_count"],
                "dna_phrase_count": row["dna_phrase_count"] - previous["dna_phrase_count"],
                "heading_hit_rate": round(float(row["heading_hit_rate"]) - float(previous["heading_hit_rate"]), 4),
                "keyword_precision": round(float(row["keyword_precision"]) - float(previous["keyword_precision"]), 4),
                "cohort_coverage": round(float(row["cohort_coverage"]) - float(previous["cohort_coverage"]), 4),
            }
        else:
            row["delta"] = {}
        versions.append(row)
        previous = row

    return {
        "concept_id": concept_id,
        "total_versions": len(versions),
        "versions": versions,
    }


@app.get("/api/review/evidence")
async def review_evidence(
    concept_id: str | None = Query(None),
    template_family: str | None = Query(None),
    record_type: str | None = Query(None),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    files = _iter_workspace_evidence_files()
    rows: list[dict[str, Any]] = []
    matched = 0
    total_scanned = 0

    rt = record_type.upper().strip() if record_type else ""
    for fp in files:
        for line in fp.read_text().splitlines():
            if not line.strip():
                continue
            total_scanned += 1
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(payload, dict):
                continue

            cid = str(payload.get("ontology_node_id", payload.get("concept_id", "")) or "")
            tf = str(payload.get("template_family", "") or "")
            rtype = str(payload.get("record_type", "HIT") or "HIT").upper()

            if concept_id and cid != concept_id:
                continue
            if template_family and tf != template_family:
                continue
            if rt and rtype != rt:
                continue

            if matched < offset:
                matched += 1
                continue
            if len(rows) >= limit:
                matched += 1
                continue

            matched += 1
            rows.append(
                {
                    "concept_id": cid,
                    "record_type": rtype,
                    "doc_id": payload.get("doc_id", ""),
                    "template_family": tf,
                    "section_number": payload.get("section_number", ""),
                    "heading": payload.get("heading", ""),
                    "clause_path": payload.get("clause_path", ""),
                    "score": payload.get("score"),
                    "outlier_level": (
                        payload.get("outlier", {}).get("level", "none")
                        if isinstance(payload.get("outlier"), dict)
                        else "none"
                    ),
                    "source_tool": payload.get("source_tool", ""),
                    "created_at": payload.get("created_at", ""),
                    "path": str(fp),
                }
            )

    return {
        "filters": {
            "concept_id": concept_id or "",
            "template_family": template_family or "",
            "record_type": rt or "",
            "limit": limit,
            "offset": offset,
        },
        "files_scanned": len(files),
        "rows_scanned": total_scanned,
        "rows_matched": matched,
        "rows_returned": len(rows),
        "has_prev": offset > 0,
        "has_next": (offset + len(rows)) < matched,
        "rows": rows,
    }


@app.get("/api/review/coverage-heatmap")
async def review_coverage_heatmap(
    concept_id: str | None = Query(None),
    top_concepts: int = Query(50, ge=1, le=500),
):
    files = _iter_workspace_evidence_files()
    counts: dict[tuple[str, str], dict[str, int]] = {}
    concept_totals: Counter[str] = Counter()
    template_totals: Counter[str] = Counter()

    for fp in files:
        for line in fp.read_text().splitlines():
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(payload, dict):
                continue

            cid = str(payload.get("ontology_node_id", payload.get("concept_id", "")) or "")
            if not cid:
                continue
            if concept_id and cid != concept_id:
                continue

            tf = str(payload.get("template_family", "") or "unknown")
            rt = str(payload.get("record_type", "HIT") or "HIT").upper()
            key = (cid, tf)
            bucket = counts.setdefault(key, {"hits": 0, "total": 0})
            bucket["total"] += 1
            if rt == "HIT":
                bucket["hits"] += 1
            concept_totals[cid] += 1
            template_totals[tf] += 1

    concepts = [cid for cid, _n in concept_totals.most_common(top_concepts)]
    if concept_id:
        concepts = [concept_id]
    templates = [tf for tf, _n in template_totals.most_common()]

    cells: list[dict[str, Any]] = []
    for cid in concepts:
        for tf in templates:
            bucket = counts.get((cid, tf), {"hits": 0, "total": 0})
            total = bucket["total"]
            hits = bucket["hits"]
            cells.append(
                {
                    "concept_id": cid,
                    "template_family": tf,
                    "hits": hits,
                    "total": total,
                    "hit_rate": round(hits / total, 4) if total > 0 else 0.0,
                }
            )

    return {
        "concepts": concepts,
        "templates": templates,
        "cells": cells,
        "top_concepts": top_concepts,
    }


@app.get("/api/review/judge/{concept_id:path}/history")
async def review_judge_history(concept_id: str):
    files = _iter_workspace_judge_files(concept_id)
    if not files:
        raise HTTPException(status_code=404, detail=f"No judge history found for concept: {concept_id}")
    rows: list[dict[str, Any]] = []
    for version, fp in files:
        payload = _safe_load_json(fp)
        rows.append(
            {
                "version": version,
                "path": str(fp),
                "precision_estimate": payload.get("precision_estimate", 0.0),
                "weighted_precision_estimate": payload.get("weighted_precision_estimate", 0.0),
                "n_sampled": payload.get("n_sampled", 0),
                "correct": payload.get("correct", 0),
                "partial": payload.get("partial", 0),
                "wrong": payload.get("wrong", 0),
                "generated_at": payload.get("generated_at", ""),
                "run_id": payload.get("run_id", ""),
            }
        )
    return {"concept_id": concept_id, "history": rows}


@app.get("/api/review/agent-activity")
async def review_agent_activity(
    stale_minutes: int = Query(60, ge=1, le=24 * 60),
):
    if not _workspace_root.exists():
        return {"total": 0, "agents": []}

    now = datetime.now(timezone.utc)
    agents: list[dict[str, Any]] = []
    for family_dir in sorted(_workspace_root.iterdir()):
        if not family_dir.is_dir():
            continue
        checkpoint = family_dir / "checkpoint.json"
        payload = _safe_load_json(checkpoint) if checkpoint.exists() else {}
        status = str(payload.get("status", "missing") or "missing")
        last_update_raw = str(payload.get("last_update", "") or "")
        last_update_iso = last_update_raw
        stale = False
        if last_update_raw:
            try:
                dt = datetime.fromisoformat(last_update_raw.replace("Z", "+00:00"))
            except ValueError:
                dt = None
            if dt is not None:
                stale = (now - dt).total_seconds() > stale_minutes * 60
        agents.append(
            {
                "family": family_dir.name,
                "status": status,
                "iteration_count": payload.get("iteration_count", 0),
                "current_concept_id": payload.get("current_concept_id", ""),
                "last_strategy_version": payload.get("last_strategy_version", 0),
                "last_coverage_hit_rate": payload.get("last_coverage_hit_rate", 0.0),
                "last_session": payload.get("last_session", ""),
                "last_pane": payload.get("last_pane", ""),
                "last_start_at": payload.get("last_start_at", ""),
                "last_update": last_update_iso,
                "stale": stale,
                "checkpoint_path": str(checkpoint),
            }
        )

    return {
        "total": len(agents),
        "stale_minutes": stale_minutes,
        "stale_count": sum(1 for a in agents if a["stale"]),
        "agents": agents,
    }


# ---------------------------------------------------------------------------
# Routes: ML & Learning (Phase 11)
# ---------------------------------------------------------------------------


def _compute_review_priority(
    row: dict[str, Any], has_qc_issues: bool
) -> tuple[str, float, list[str]]:
    """Compute review priority level, numeric score, and reason tags."""
    outlier = row.get("outlier") or {}
    confidence = row.get("confidence_breakdown") or {}
    flags: list[str] = outlier.get("flags") or []

    # Weighted factors (0-1 each)
    outlier_score = float(outlier.get("score", 0))
    confidence_final = float(confidence.get("final", 0.5))
    confidence_gap = 1.0 - confidence_final
    single_channel = 1.0 if "single_channel_match" in flags else 0.0
    raw_score = float(row.get("score") or 0)
    low_score = 1.0 - min(1.0, raw_score)
    flag_density = min(1.0, len(flags) / 5.0) if flags else 0.0

    priority_score = (
        0.35 * outlier_score
        + 0.25 * confidence_gap
        + 0.20 * single_channel
        + 0.10 * low_score
        + 0.10 * flag_density
    )

    # Clamp
    priority_score = max(0.0, min(1.0, priority_score))

    # Reasons
    reasons: list[str] = []
    outlier_level = outlier.get("level", "none")
    if outlier_level in ("high", "medium"):
        reasons.append("high_outlier")
    if confidence_final < 0.5:
        reasons.append("low_confidence")
    if single_channel > 0:
        reasons.append("single_channel")
    if has_qc_issues:
        reasons.append("qc_flagged_strategy")

    # Threshold
    if priority_score >= 0.6:
        level = "high"
    elif priority_score >= 0.35:
        level = "medium"
    else:
        level = "low"

    return level, round(priority_score, 4), reasons


def _qualifies_for_review(row: dict[str, Any], has_qc_issues: bool) -> bool:
    """Check if a HIT evidence row belongs in the review queue."""
    if row.get("record_type") != "HIT":
        return False
    outlier = row.get("outlier") or {}
    confidence = row.get("confidence_breakdown") or {}
    flags: list[str] = outlier.get("flags") or []

    if outlier.get("level") in ("high", "medium"):
        return True
    if float(confidence.get("final", 1.0)) < 0.5:
        return True
    if "single_channel_match" in flags:
        return True
    if has_qc_issues:
        return True
    return False


@app.get("/api/ml/review-queue")
async def ml_review_queue(
    priority: str | None = Query(None),
    concept_id: str | None = Query(None),
    template_family: str | None = Query(None),
    limit: int = Query(200, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    """Prioritized queue of evidence items needing human review."""
    files = _iter_workspace_evidence_files()
    all_items: list[dict[str, Any]] = []
    concept_counts: dict[str, int] = {}
    template_counts: dict[str, int] = {}

    # Pre-compute which concepts have QC issues
    qc_concepts: set[str] = set()
    for cid, strat in _strategies.items():
        if strat.get("dropped_headings") or strat.get("false_positive_keywords"):
            qc_concepts.add(cid)

    for fp in files:
        try:
            for line in fp.read_text().splitlines():
                if not line.strip():
                    continue
                row = orjson.loads(line)
                cid = row.get("concept_id", "")
                has_qc = cid in qc_concepts

                if not _qualifies_for_review(row, has_qc):
                    continue

                level, score, reasons = _compute_review_priority(row, has_qc)

                outlier = row.get("outlier") or {}
                confidence = row.get("confidence_breakdown") or {}
                components = confidence.get("components") or {}

                item: dict[str, Any] = {
                    "priority": level,
                    "priority_score": score,
                    "concept_id": cid,
                    "doc_id": row.get("doc_id", ""),
                    "template_family": row.get("template_family", ""),
                    "section_number": row.get("section_number", ""),
                    "heading": row.get("heading", ""),
                    "score": row.get("score"),
                    "match_type": row.get("match_type", ""),
                    "confidence_final": float(confidence.get("final", 0)),
                    "confidence_components": {
                        "score": float(components.get("score", 0)),
                        "margin": float(components.get("margin", 0)),
                        "channels": float(components.get("channels", 0)),
                        "heading": float(components.get("heading", 0)),
                        "keyword": float(components.get("keyword", 0)),
                        "dna": float(components.get("dna", 0)),
                    },
                    "outlier_level": outlier.get("level", "none"),
                    "outlier_score": float(outlier.get("score", 0)),
                    "outlier_flags": outlier.get("flags") or [],
                    "risk_components": outlier.get("risk_components") or {},
                    "source_tool": row.get("source_tool", ""),
                    "strategy_version": row.get("strategy_version", 0),
                    "review_reasons": reasons,
                }
                all_items.append(item)

                # Facet counting (before priority filter)
                concept_counts[cid] = concept_counts.get(cid, 0) + 1
                tf = item["template_family"]
                template_counts[tf] = template_counts.get(tf, 0) + 1
        except Exception:
            continue

    # Sort by priority_score descending
    all_items.sort(key=lambda x: x["priority_score"], reverse=True)

    # KPIs from full unfiltered set
    kpis = {
        "total_queue": len(all_items),
        "high_priority": sum(1 for i in all_items if i["priority"] == "high"),
        "medium_priority": sum(1 for i in all_items if i["priority"] == "medium"),
        "low_priority": sum(1 for i in all_items if i["priority"] == "low"),
        "concepts_affected": len(concept_counts),
        "families_affected": len(template_counts),
    }

    # Apply filters
    filtered = all_items
    if priority:
        filtered = [i for i in filtered if i["priority"] == priority]
    if concept_id:
        filtered = [i for i in filtered if i["concept_id"] == concept_id]
    if template_family:
        filtered = [i for i in filtered if i["template_family"] == template_family]

    total_matched = len(filtered)
    page_items = filtered[offset : offset + limit]

    # Facets (top 50)
    facet_concepts = sorted(concept_counts.items(), key=lambda x: -x[1])[:50]
    facet_templates = sorted(template_counts.items(), key=lambda x: -x[1])[:50]

    return {
        "kpis": kpis,
        "filters": {
            "priority": priority or "",
            "concept_id": concept_id or "",
            "template_family": template_family or "",
            "limit": limit,
            "offset": offset,
        },
        "total_matched": total_matched,
        "has_prev": offset > 0,
        "has_next": offset + limit < total_matched,
        "items": page_items,
        "facets": {
            "concepts": [{"concept_id": c, "count": n} for c, n in facet_concepts],
            "templates": [{"template_family": t, "count": n} for t, n in facet_templates],
        },
    }


@app.get("/api/ml/heading-clusters")
async def ml_heading_clusters(
    concept_id: str = Query(...),
):
    """Group HIT evidence rows by heading text for a concept."""
    files = _iter_workspace_evidence_files()

    # Collect all HIT rows for this concept
    clusters: dict[str, dict[str, Any]] = {}  # normalized_heading -> cluster
    all_doc_ids: set[str] = set()
    total_hits = 0

    for fp in files:
        try:
            for line in fp.read_text().splitlines():
                if not line.strip():
                    continue
                row = orjson.loads(line)
                if row.get("concept_id") != concept_id:
                    continue
                if row.get("record_type") != "HIT":
                    continue

                total_hits += 1
                heading_raw = row.get("heading", "") or ""
                heading_norm = heading_raw.strip().lower()
                if not heading_norm:
                    heading_norm = "(no heading)"

                doc_id = row.get("doc_id", "")
                all_doc_ids.add(doc_id)
                score_val = float(row.get("score") or 0)
                match_type = row.get("match_type", "")
                tf = row.get("template_family", "")

                if heading_norm not in clusters:
                    clusters[heading_norm] = {
                        "heading_display": heading_raw.strip() or "(no heading)",
                        "heading_normalized": heading_norm,
                        "doc_ids": set(),
                        "template_families": set(),
                        "match_types": set(),
                        "scores": [],
                    }

                c = clusters[heading_norm]
                c["doc_ids"].add(doc_id)
                if tf:
                    c["template_families"].add(tf)
                if match_type:
                    c["match_types"].add(match_type)
                c["scores"].append(score_val)
        except Exception:
            continue

    # Cross-reference with strategy heading patterns
    strat = _strategies.get(concept_id, {})
    heading_patterns = strat.get("heading_patterns") or []

    def _matches_any_pattern(heading_norm: str) -> bool:
        for pat in heading_patterns:
            try:
                if re.search(pat, heading_norm, re.IGNORECASE):
                    return True
            except re.error:
                # Treat as literal match if regex invalid
                if pat.lower() in heading_norm:
                    return True
        return False

    # Build final cluster list
    result_clusters: list[dict[str, Any]] = []
    for _norm, c in clusters.items():
        scores = c["scores"]
        doc_ids_list = sorted(c["doc_ids"])
        in_strategy = _matches_any_pattern(c["heading_normalized"])
        result_clusters.append({
            "heading_display": c["heading_display"],
            "heading_normalized": c["heading_normalized"],
            "doc_count": len(c["doc_ids"]),
            "doc_ids": doc_ids_list[:20],
            "template_families": sorted(c["template_families"]),
            "avg_score": round(sum(scores) / len(scores), 4) if scores else 0,
            "min_score": round(min(scores), 4) if scores else 0,
            "max_score": round(max(scores), 4) if scores else 0,
            "match_types": sorted(c["match_types"]),
            "in_strategy": in_strategy,
            "is_orphan": len(c["doc_ids"]) == 1,
        })

    # Sort by doc_count descending
    result_clusters.sort(key=lambda x: -x["doc_count"])

    known = sum(1 for c in result_clusters if c["in_strategy"])
    unknown = sum(1 for c in result_clusters if not c["in_strategy"])
    orphans = sum(1 for c in result_clusters if c["is_orphan"])

    return {
        "concept_id": concept_id,
        "concept_name": strat.get("concept_name", strat.get("name", concept_id)),
        "strategy_heading_patterns": heading_patterns,
        "kpis": {
            "total_clusters": len(result_clusters),
            "known_headings": known,
            "unknown_headings": unknown,
            "orphan_headings": orphans,
            "total_hits": total_hits,
            "unique_docs": len(all_doc_ids),
        },
        "clusters": result_clusters,
    }


@app.get("/api/ml/concepts-with-evidence")
async def ml_concepts_with_evidence():
    """List concepts that have HIT evidence rows, with counts."""
    files = _iter_workspace_evidence_files()
    counts: dict[str, int] = {}

    for fp in files:
        try:
            for line in fp.read_text().splitlines():
                if not line.strip():
                    continue
                row = orjson.loads(line)
                if row.get("record_type") != "HIT":
                    continue
                cid = row.get("concept_id", "")
                if cid:
                    counts[cid] = counts.get(cid, 0) + 1
        except Exception:
            continue

    sorted_concepts = sorted(counts.items(), key=lambda x: -x[1])
    return {
        "concepts": [
            {"concept_id": cid, "hit_count": n} for cid, n in sorted_concepts
        ],
    }


# ---------------------------------------------------------------------------
# Routes: Feedback Backlog (Phase 9)
# ---------------------------------------------------------------------------


class FeedbackCreate(BaseModel):
    title: str = Field(..., min_length=3, max_length=200)
    type: str = Field(..., pattern=r"^(bug|improvement|question)$")
    priority: str = Field("medium", pattern=r"^(high|medium|low)$")
    related_concept_id: str | None = None
    description: str = Field("", max_length=2000)


class FeedbackUpdate(BaseModel):
    title: str | None = None
    type: str | None = Field(None, pattern=r"^(bug|improvement|question)$")
    priority: str | None = Field(None, pattern=r"^(high|medium|low)$")
    status: str | None = Field(None, pattern=r"^(open|in_progress|resolved)$")
    related_concept_id: str | None = None
    description: str | None = None


@app.get("/api/feedback")
async def list_feedback(
    status: str | None = Query(None),
    type: str | None = Query(None),
    priority: str | None = Query(None),
    concept_id: str | None = Query(None),
):
    """List feedback items with optional filters."""
    items = list(_feedback_items)

    if status:
        items = [i for i in items if i.get("status") == status]
    if type:
        items = [i for i in items if i.get("type") == type]
    if priority:
        items = [i for i in items if i.get("priority") == priority]
    if concept_id:
        items = [i for i in items if i.get("related_concept_id") == concept_id]

    # Status/type counts from full set
    status_counts: dict[str, int] = {}
    type_counts: dict[str, int] = {}
    for i in _feedback_items:
        st = i.get("status", "open")
        status_counts[st] = status_counts.get(st, 0) + 1
        tp = i.get("type", "bug")
        type_counts[tp] = type_counts.get(tp, 0) + 1

    return {
        "total": len(items),
        "items": items,
        "status_counts": [{"status": st, "count": c} for st, c in sorted(status_counts.items())],
        "type_counts": [{"type": tp, "count": c} for tp, c in sorted(type_counts.items())],
    }


@app.post("/api/feedback")
async def create_feedback(body: FeedbackCreate):
    """Create a new feedback item."""
    async with _feedback_lock:
        item: dict[str, Any] = {
            "id": str(uuid.uuid4()),
            "title": body.title,
            "type": body.type,
            "priority": body.priority,
            "status": "open",
            "related_concept_id": body.related_concept_id,
            "description": body.description,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": None,
        }
        _feedback_items.insert(0, item)
        _save_feedback()
    return item


@app.patch("/api/feedback/{feedback_id}")
async def update_feedback(feedback_id: str, body: FeedbackUpdate):
    """Update an existing feedback item."""
    async with _feedback_lock:
        for item in _feedback_items:
            if item.get("id") == feedback_id:
                updates = body.model_dump(exclude_unset=True)
                for key, val in updates.items():
                    item[key] = val
                item["updated_at"] = datetime.now(timezone.utc).isoformat()
                _save_feedback()
                return item
    raise HTTPException(status_code=404, detail=f"Feedback item not found: {feedback_id}")


@app.delete("/api/feedback/{feedback_id}")
async def delete_feedback(feedback_id: str):
    """Delete a feedback item."""
    async with _feedback_lock:
        for idx, item in enumerate(_feedback_items):
            if item.get("id") == feedback_id:
                _feedback_items.pop(idx)
                _save_feedback()
                return {"deleted": True}
    raise HTTPException(status_code=404, detail=f"Feedback item not found: {feedback_id}")
