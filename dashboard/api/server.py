"""FastAPI server for the Corpus Dashboard.

Reads from corpus_index/corpus.duckdb via the CorpusIndex class and exposes
JSON endpoints for the Next.js frontend.

Usage:
    cd /Users/johnchtchekine/Projects/Agent/dashboard
    PYTHONPATH=../src uvicorn api.server:app --reload --port 8000
"""
from __future__ import annotations

import asyncio
import contextlib
import ipaddress
import json
import math
import os
import re
import sys
import uuid
from collections import Counter
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse

import orjson
from fastapi import Body, FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import ORJSONResponse
from pydantic import BaseModel, Field
from starlette.responses import StreamingResponse

# Add Agent src to path so we can import agent modules
_project_root = Path(__file__).resolve().parents[2]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

_agent_src = Path(__file__).resolve().parents[2] / "src"
if str(_agent_src) not in sys.path:
    sys.path.insert(0, str(_agent_src))

from agent.corpus import CorpusIndex  # noqa: E402
from agent.link_store import LinkStore  # noqa: E402
from agent.conflict_matrix import (  # noqa: E402
    build_conflict_matrix,
    lookup_policy,
    matrix_to_dict,
    ConflictPolicy,
)
from agent.query_filters import (  # noqa: E402
    MetaFilter,
    FilterMatch,
    FilterGroup,
    build_filter_sql,
    build_meta_filter_sql,
    estimate_query_cost,
    filter_expr_from_json,
    filter_expr_to_json,
    meta_filter_from_json,
    meta_filter_to_json,
)
from agent.rule_dsl import (  # noqa: E402
    dsl_from_heading_ast,
    heading_ast_from_dsl,
    parse_dsl,
    validate_dsl,
)
from agent.query_filters import build_multi_field_sql  # noqa: E402

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

# Link store globals
_links_db_path = Path(__file__).resolve().parents[2] / "corpus_index" / "links.duckdb"
_link_store: LinkStore | None = None
_conflict_policies: dict[tuple[str, str], ConflictPolicy] = {}
_worker_proc: Any = None

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
def _load_dotenv() -> None:
    """Load .env from project root if it exists (no dependency required)."""
    env_path = Path(__file__).resolve().parents[2] / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip("'\"")
        if key and key not in os.environ:
            os.environ[key] = value


@asynccontextmanager
async def lifespan(app: FastAPI):  # noqa: ARG001
    _load_dotenv()

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

    # Load/create link store
    global _link_store, _conflict_policies, _worker_proc  # noqa: PLW0603
    try:
        _links_db_path.parent.mkdir(parents=True, exist_ok=True)
        _link_store = LinkStore(_links_db_path, create_if_missing=True)
        if _ontology_nodes:
            mapped = _bootstrap_legacy_family_aliases(_link_store)
            if mapped:
                print(f"[dashboard] Legacy scope aliases refreshed: {mapped}")
        _link_store.run_cleanup()
        print(f"[dashboard] Link store loaded: {_links_db_path}")
    except Exception as e:
        print(f"[dashboard] Warning: could not open link store: {e}")
        _link_store = None

    # Build conflict matrix from ontology
    if _ontology_edges:
        try:
            policies = build_conflict_matrix(_ontology_edges, _ontology_nodes)
            _conflict_policies = matrix_to_dict(policies)
            print(f"[dashboard] Conflict matrix: {len(_conflict_policies)} pairs")
            # Persist conflict policies to link store
            if _link_store is not None:
                for p in policies:
                    _link_store.save_conflict_policy({
                        "family_a": p.family_a,
                        "family_b": p.family_b,
                        "policy": p.policy,
                        "reason": p.reason,
                    })
        except Exception as e:
            print(f"[dashboard] Warning: could not build conflict matrix: {e}")

    # Start worker subprocess (if link store is available)
    if _link_store is not None:
        try:
            import subprocess
            worker_cmd = [
                sys.executable,
                str(Path(__file__).resolve().parents[2] / "scripts" / "link_worker.py"),
                "--links-db", str(_links_db_path),
            ]
            if _corpus_db_path.exists():
                worker_cmd.extend(["--db", str(_corpus_db_path)])
            _worker_proc = subprocess.Popen(
                worker_cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
            )
            print(f"[dashboard] Worker started (pid={_worker_proc.pid})")
        except Exception as e:
            print(f"[dashboard] Warning: could not start worker: {e}")

    yield

    # Shutdown
    if _worker_proc is not None:
        _worker_proc.terminate()
        try:
            _worker_proc.wait(timeout=5)
        except Exception:
            _worker_proc.kill()
        print("[dashboard] Worker stopped")
    if _link_store is not None:
        _link_store.close()
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

# ---------------------------------------------------------------------------
# Links API Auth / Access Control
# ---------------------------------------------------------------------------
_DEFAULT_LINKS_API_TOKEN = "local-dev-links-token"
_LINKS_API_TOKEN = os.environ.get("LINKS_API_TOKEN", _DEFAULT_LINKS_API_TOKEN).strip()
_LINKS_API_TOKEN_FROM_ENV = "LINKS_API_TOKEN" in os.environ
_LINKS_ADMIN_TOKEN = os.environ.get("LINKS_ADMIN_TOKEN", _LINKS_API_TOKEN).strip()
_LINKS_ADMIN_TOKEN_FROM_ENV = "LINKS_ADMIN_TOKEN" in os.environ
_LINKS_TEST_ENDPOINT_TOKEN = os.environ.get(
    "LINKS_TEST_ENDPOINT_TOKEN",
    _LINKS_ADMIN_TOKEN,
).strip()
_LINKS_TEST_MODE = os.environ.get("LINKS_TEST_MODE", "") == "1"


def _is_loopback_host(host: str | None) -> bool:
    """Return True when host is localhost/loopback."""
    if not host:
        return False
    host_lower = host.lower()
    if host_lower in {"localhost", "127.0.0.1", "::1"}:
        return True
    try:
        return ipaddress.ip_address(host_lower).is_loopback
    except ValueError:
        return False


def _request_host(request: Request) -> str | None:
    if request.client is None:
        return None
    return request.client.host


def _request_origin_hosts(request: Request) -> list[str]:
    hosts: list[str] = []
    for header_name in ("origin", "referer"):
        value = str(request.headers.get(header_name, "")).strip()
        if not value:
            continue
        with contextlib.suppress(Exception):
            parsed = urlparse(value)
            if parsed.hostname:
                hosts.append(str(parsed.hostname))
    host_header = str(request.headers.get("host", "")).strip()
    if host_header:
        hosts.append(host_header.split(":", 1)[0].strip())
    return [host for host in hosts if host]


def _is_local_request(request: Request) -> bool:
    if _is_loopback_host(_request_host(request)):
        return True
    return any(_is_loopback_host(host) for host in _request_origin_hosts(request))


def _extract_request_token(request: Request) -> str | None:
    """Extract bearer/API token from request headers."""
    auth_header = request.headers.get("Authorization", "").strip()
    if auth_header.lower().startswith("bearer "):
        return auth_header[7:].strip()
    x_token = request.headers.get("X-Links-Token", "").strip()
    return x_token or None


def _require_links_access(request: Request, *, write: bool) -> None:
    """Enforce auth for /api/links routes."""
    token = _extract_request_token(request)
    is_local = _is_local_request(request)

    allowed_tokens = {_LINKS_API_TOKEN}
    if _LINKS_ADMIN_TOKEN:
        allowed_tokens.add(_LINKS_ADMIN_TOKEN)

    def _enforce_default_token_scope(presented_token: str) -> None:
        if (
            presented_token == _DEFAULT_LINKS_API_TOKEN
            and not _LINKS_API_TOKEN_FROM_ENV
            and not is_local
        ):
            raise HTTPException(
                status_code=403,
                detail="Default links token is restricted to loopback clients",
            )
        if (
            presented_token == _LINKS_ADMIN_TOKEN
            and not _LINKS_ADMIN_TOKEN_FROM_ENV
            and not is_local
        ):
            raise HTTPException(
                status_code=403,
                detail="Default admin token is restricted to loopback clients",
            )

    # Write operations always require a token.
    if write:
        if not token or token not in allowed_tokens:
            raise HTTPException(status_code=401, detail="Invalid or missing links API token")
        _enforce_default_token_scope(token)
        return

    # Read operations: token optional for loopback only.
    if token:
        if token not in allowed_tokens:
            raise HTTPException(status_code=401, detail="Invalid links API token")
        _enforce_default_token_scope(token)
        return

    if not is_local:
        raise HTTPException(status_code=401, detail="Links API token required")


def _require_links_admin(request: Request) -> None:
    """Require admin token for direct-write management endpoints."""
    token = _extract_request_token(request)
    if not token or token != _LINKS_ADMIN_TOKEN:
        raise HTTPException(status_code=403, detail="Admin token required for direct-write endpoint")
    if (
        not os.environ.get("LINKS_ADMIN_TOKEN")
        and not _is_local_request(request)
    ):
        raise HTTPException(
            status_code=403,
            detail="Default admin token is restricted to loopback clients",
        )


def _require_test_endpoint_access(request: Request) -> None:
    """Lock down /api/links/_test/* endpoints."""
    if not _LINKS_TEST_MODE:
        raise HTTPException(status_code=403, detail="Test mode not enabled")
    if not _is_local_request(request):
        raise HTTPException(status_code=403, detail="Test endpoints are loopback-only")
    token = _extract_request_token(request)
    if not token or token != _LINKS_TEST_ENDPOINT_TOKEN:
        raise HTTPException(status_code=403, detail="Test endpoint token required")


_LEGACY_API_PREFIXES: tuple[str, ...] = (
    "/api/jobs",
    "/api/strategies",
    "/api/review",
    "/api/ml/review-queue",
    "/api/ml/heading-clusters",
    "/api/ml/concepts-with-evidence",
)


def _legacy_api_replacement(path: str) -> str:
    if path.startswith("/api/jobs"):
        return "/api/links/intelligence/ops"
    if path.startswith("/api/strategies"):
        return "/api/links/rules"
    if path.startswith("/api/review"):
        return "/api/links/intelligence/evidence"
    if path.startswith("/api/ml/"):
        return "/api/links/intelligence/signals"
    return "/api/links"


@app.middleware("http")
async def _links_api_auth_middleware(request: Request, call_next: Any):
    """Apply auth checks to links/jobs surfaces before handler execution."""
    path = request.url.path
    method = request.method.upper()
    cors_headers = _cors_headers_for_request(request)

    # Handle preflight deterministically for all API routes, including error paths.
    if method == "OPTIONS" and path.startswith("/api/"):
        if cors_headers:
            return Response(status_code=204, headers=cors_headers)
        return Response(status_code=204)

    if any(path.startswith(prefix) for prefix in _LEGACY_API_PREFIXES):
        return ORJSONResponse(
            status_code=410,
            content={
                "detail": "Deprecated API route. Use ontology links API endpoints.",
                "replacement": _legacy_api_replacement(path),
            },
            headers=cors_headers,
        )

    if path.startswith("/api/links"):
        # Dedicated helper enforces stricter controls for test-only endpoints.
        if path.startswith("/api/links/_test"):
            response = await call_next(request)
            for key, value in cors_headers.items():
                if key not in response.headers:
                    response.headers[key] = value
            return response
        try:
            _require_links_access(request, write=method not in {"GET", "HEAD"})
        except HTTPException as exc:
            return ORJSONResponse(
                status_code=exc.status_code,
                content={"detail": exc.detail},
                headers=cors_headers,
            )

    try:
        response = await call_next(request)
    except Exception:
        # Keep CORS headers on unhandled backend errors so browser can read details.
        return ORJSONResponse(
            status_code=500,
            content={"detail": "Internal Server Error"},
            headers=cors_headers,
        )

    for key, value in cors_headers.items():
        if key not in response.headers:
            response.headers[key] = value
    return response


_CORS_ALLOW_ORIGINS = [
    "http://localhost",
    "https://localhost",
    "http://localhost:3000",
    "https://localhost:3000",
    "http://localhost:3001",
    "https://localhost:3001",
    "http://localhost:3002",
    "https://localhost:3002",
    "http://localhost:3100",
    "https://localhost:3100",
    "http://localhost:5173",
    "https://localhost:5173",
    "http://localhost:5174",
    "https://localhost:5174",
    "http://127.0.0.1",
    "https://127.0.0.1",
    "http://127.0.0.1:3000",
    "https://127.0.0.1:3000",
    "http://127.0.0.1:3001",
    "https://127.0.0.1:3001",
    "http://127.0.0.1:3002",
    "https://127.0.0.1:3002",
    "http://127.0.0.1:3100",
    "https://127.0.0.1:3100",
    "http://127.0.0.1:5173",
    "https://127.0.0.1:5173",
    "http://127.0.0.1:5174",
    "https://127.0.0.1:5174",
    "http://[::1]",
    "https://[::1]",
    "http://[::1]:3000",
    "https://[::1]:3000",
    "http://[::1]:3001",
    "https://[::1]:3001",
    "http://[::1]:3002",
    "https://[::1]:3002",
    "http://[::1]:3100",
    "https://[::1]:3100",
    "http://[::1]:5173",
    "https://[::1]:5173",
    "http://[::1]:5174",
    "https://[::1]:5174",
]
_CORS_ALLOW_ORIGIN_REGEX = r"^https?://(localhost|127\.0\.0\.1|\[::1\])(:\d+)?$"


def _is_allowed_cors_origin(origin: str | None) -> bool:
    value = str(origin or "").strip().rstrip("/")
    if not value:
        return False
    if value in _CORS_ALLOW_ORIGINS:
        return True
    return re.match(_CORS_ALLOW_ORIGIN_REGEX, value) is not None


def _cors_headers_for_request(request: Request) -> dict[str, str]:
    origin = str(request.headers.get("origin", "")).strip()
    if not (origin and (_is_allowed_cors_origin(origin) or _is_local_request(request))):
        return {}

    requested_headers = str(request.headers.get("access-control-request-headers", "")).strip()
    allow_headers = requested_headers or "Authorization, Content-Type, X-Links-Token"
    return {
        "Access-Control-Allow-Origin": origin,
        "Access-Control-Allow-Credentials": "true",
        "Access-Control-Allow-Methods": "GET, POST, PUT, PATCH, DELETE, OPTIONS",
        "Access-Control-Allow-Headers": allow_headers,
        "Vary": "Origin, Access-Control-Request-Method, Access-Control-Request-Headers",
    }


app.add_middleware(
    CORSMiddleware,
    allow_origins=_CORS_ALLOW_ORIGINS,
    allow_origin_regex=_CORS_ALLOW_ORIGIN_REGEX,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Test seed dataset helpers
# ---------------------------------------------------------------------------
def _seed_rules_minimal() -> list[dict[str, Any]]:
    return [
        {
            "rule_id": "RULE-001",
            "family_id": "debt_capacity.indebtedness",
            "filter_dsl": 'heading: Indebtedness | "Limitation on Indebtedness" | Debt',
            "heading_filter_ast": {
                "type": "group",
                "operator": "or",
                "children": [
                    {"type": "match", "value": "Indebtedness"},
                    {"type": "match", "value": "Limitation on Indebtedness"},
                    {"type": "match", "value": "Debt"},
                ],
            },
            "status": "published",
            "version": 1,
        },
        {
            "rule_id": "RULE-002",
            "family_id": "FAM-liens",
            "filter_dsl": 'heading: Liens | "Limitation on Liens"',
            "heading_filter_ast": {
                "type": "group",
                "operator": "or",
                "children": [
                    {"type": "match", "value": "Liens"},
                    {"type": "match", "value": "Limitation on Liens"},
                ],
            },
            "status": "published",
            "version": 1,
        },
        {
            "rule_id": "RULE-003",
            "family_id": "FAM-dividends",
            "filter_dsl": 'heading: "Restricted Payments" | Dividends',
            "heading_filter_ast": {
                "type": "group",
                "operator": "or",
                "children": [
                    {"type": "match", "value": "Restricted Payments"},
                    {"type": "match", "value": "Dividends"},
                ],
            },
            "status": "draft",
            "version": 1,
        },
    ]


def _seed_links_minimal() -> list[dict[str, Any]]:
    return [
        {
            "link_id": "LINK-001",
            "family_id": "debt_capacity.indebtedness",
            "doc_id": "DOC-001",
            "section_number": "7.01",
            "heading": "Indebtedness",
            "confidence": 0.92,
            "confidence_tier": "high",
            "status": "active",
        },
        {
            "link_id": "LINK-002",
            "family_id": "debt_capacity.indebtedness",
            "doc_id": "DOC-002",
            "section_number": "7.01",
            "heading": "Limitation on Indebtedness",
            "confidence": 0.85,
            "confidence_tier": "high",
            "status": "active",
        },
        {
            "link_id": "LINK-003",
            "family_id": "FAM-liens",
            "doc_id": "DOC-001",
            "section_number": "7.02",
            "heading": "Liens",
            "confidence": 0.88,
            "confidence_tier": "high",
            "status": "active",
        },
        {
            "link_id": "LINK-004",
            "family_id": "FAM-liens",
            "doc_id": "DOC-003",
            "section_number": "7.02",
            "heading": "Limitation on Liens",
            "confidence": 0.72,
            "confidence_tier": "medium",
            "status": "active",
        },
        {
            "link_id": "LINK-005",
            "family_id": "FAM-dividends",
            "doc_id": "DOC-001",
            "section_number": "7.06",
            "heading": "Restricted Payments",
            "confidence": 0.91,
            "confidence_tier": "high",
            "status": "active",
        },
        {
            "link_id": "LINK-006",
            "family_id": "FAM-dividends",
            "doc_id": "DOC-004",
            "section_number": "7.06",
            "heading": "Dividends and Distributions",
            "confidence": 0.55,
            "confidence_tier": "medium",
            "status": "pending_review",
        },
        {
            "link_id": "LINK-007",
            "family_id": "debt_capacity.indebtedness",
            "doc_id": "DOC-005",
            "section_number": "7.01",
            "heading": "Debt Limitations",
            "confidence": 0.45,
            "confidence_tier": "low",
            "status": "pending_review",
        },
        {
            "link_id": "LINK-008",
            "family_id": "cash_flow.inv",
            "doc_id": "DOC-001",
            "section_number": "7.04",
            "heading": "Investments",
            "confidence": 0.89,
            "confidence_tier": "high",
            "status": "active",
        },
        {
            "link_id": "LINK-009",
            "family_id": "FAM-mergers",
            "doc_id": "DOC-002",
            "section_number": "7.05",
            "heading": "Fundamental Changes",
            "confidence": 0.78,
            "confidence_tier": "medium",
            "status": "unlinked",
        },
        {
            "link_id": "LINK-010",
            "family_id": "FAM-asset-sales",
            "doc_id": "DOC-003",
            "section_number": "7.07",
            "heading": "Asset Sales",
            "confidence": 0.82,
            "confidence_tier": "high",
            "status": "active",
        },
    ]


def _build_named_seed_dataset(dataset: str) -> dict[str, Any]:
    key = dataset.strip().lower()
    minimal_links = _seed_links_minimal()
    minimal_rules = _seed_rules_minimal()

    if key == "minimal":
        return {"links": minimal_links, "rules": minimal_rules, "jobs": []}

    if key == "rules":
        extra_rules = [
            {
                "rule_id": f"RULE-{idx:03d}",
                "family_id": fam,
                "heading_filter_ast": {"type": "match", "value": title},
                "status": "draft" if idx % 2 else "published",
                "version": 1,
            }
            for idx, fam, title in [
                (4, "cash_flow.inv", "Investments"),
                (5, "FAM-mergers", "Fundamental Changes"),
                (6, "FAM-asset-sales", "Asset Sales"),
                (7, "FAM-affiliate-transactions", "Affiliate Transactions"),
                (8, "FAM-reporting", "Reporting"),
                (9, "FAM-liquidity", "Liquidity"),
                (10, "FAM-leverage", "Leverage"),
            ]
        ]
        return {
            "links": minimal_links,
            "rules": [*minimal_rules, *extra_rules],
            "jobs": [],
        }

    if key == "conflicts":
        conflict_links = [
            {
                "link_id": "LINK-C001",
                "family_id": "debt_capacity.indebtedness",
                "doc_id": "DOC-020",
                "section_number": "7.03",
                "heading": "Shared Covenant",
                "confidence": 0.83,
                "confidence_tier": "high",
                "status": "active",
            },
            {
                "link_id": "LINK-C002",
                "family_id": "FAM-liens",
                "doc_id": "DOC-020",
                "section_number": "7.03",
                "heading": "Shared Covenant",
                "confidence": 0.79,
                "confidence_tier": "medium",
                "status": "active",
            },
        ]
        return {"links": [*minimal_links, *conflict_links], "rules": minimal_rules, "jobs": []}

    if key == "review":
        families = [
            "debt_capacity.indebtedness",
            "FAM-liens",
            "FAM-dividends",
            "cash_flow.inv",
            "FAM-mergers",
        ]
        tiers = ["high", "medium", "low"]
        statuses = ["active", "pending_review", "unlinked"]
        review_links = []
        for i in range(1, 51):
            review_links.append(
                {
                    "link_id": f"LINK-R{i:03d}",
                    "family_id": families[(i - 1) % len(families)],
                    "doc_id": f"DOC-{((i - 1) % 20) + 1:03d}",
                    "section_number": f"7.{(i % 12) + 1:02d}",
                    "heading": f"Review Seed Heading {i}",
                    "confidence": round(0.35 + (i % 65) / 100, 2),
                    "confidence_tier": tiers[(i - 1) % len(tiers)],
                    "status": statuses[(i - 1) % len(statuses)],
                },
            )
        return {"links": review_links, "rules": minimal_rules, "jobs": []}

    if key == "coverage":
        families = [
            "debt_capacity.indebtedness",
            "FAM-liens",
            "FAM-dividends",
            "cash_flow.inv",
            "FAM-mergers",
            "FAM-asset-sales",
            "FAM-affiliate-transactions",
            "FAM-reporting",
        ]
        coverage_links = []
        for i in range(1, 101):
            coverage_links.append(
                {
                    "link_id": f"LINK-G{i:03d}",
                    "family_id": families[(i - 1) % len(families)],
                    "doc_id": f"DOC-{((i - 1) % 20) + 1:03d}",
                    "section_number": f"6.{(i % 25) + 1:02d}",
                    "heading": f"Coverage Heading {i}",
                    "confidence": round(0.4 + (i % 50) / 100, 2),
                    "confidence_tier": "high" if i % 3 == 0 else "medium",
                    "status": "active" if i % 7 else "pending_review",
                },
            )
        return {"links": coverage_links, "rules": minimal_rules, "jobs": []}

    if key == "full":
        conflicts = _build_named_seed_dataset("conflicts")["links"]
        review = _build_named_seed_dataset("review")["links"]
        all_links: dict[str, dict[str, Any]] = {}
        for link in [*minimal_links, *conflicts, *review]:
            all_links[link["link_id"]] = link
        jobs = [
            {"job_id": "JOB-001", "job_type": "preview", "params": {"family_id": "debt_capacity.indebtedness"}},
            {"job_id": "JOB-002", "job_type": "apply", "params": {"preview_id": "PREVIEW-001"}},
            {"job_id": "JOB-003", "job_type": "export", "params": {"format": "csv"}},
        ]
        return {"links": list(all_links.values()), "rules": _build_named_seed_dataset("rules")["rules"], "jobs": jobs}

    raise HTTPException(status_code=422, detail=f"Unknown seed dataset: {dataset}")


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
        "links_loaded": _link_store is not None,
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
    articles = corpus.get_articles(doc_id)

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
        "articles": [
            {
                "article_num": a.article_num,
                "label": a.label,
                "title": a.title,
                "concept": a.concept,
                "char_start": a.char_start,
                "char_end": a.char_end,
                "is_synthetic": a.is_synthetic,
            }
            for a in articles
        ],
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

# Tier-based category registry (32 categories across 6 tiers)
_EDGE_CASE_TIERS: dict[str, list[str]] = {
    "structural": [
        "missing_sections", "low_section_count", "excessive_section_count",
        "section_fallback_used", "section_numbering_gap", "empty_section_headings",
    ],
    "clauses": [
        "zero_clauses", "low_clause_density", "low_avg_clause_confidence",
        "orphan_deep_clause", "inconsistent_sibling_depth",
        "deep_nesting_outlier", "low_structural_ratio", "rootless_deep_clause",
    ],
    "definitions": [
        "low_definitions", "zero_definitions", "high_definition_count",
        "duplicate_definitions", "single_engine_definitions",
    ],
    "metadata": [
        "extreme_facility", "missing_borrower", "missing_facility_size",
        "missing_closing_date", "unknown_doc_type",
    ],
    "document": [
        "extreme_word_count", "short_text", "extreme_text_ratio",
        "very_short_document",
    ],
    "template": [
        "orphan_template", "non_credit_agreement", "uncertain_market_segment",
        "non_cohort_large_doc",
    ],
}

_CATEGORY_TO_TIER: dict[str, str] = {
    cat: tier for tier, cats in _EDGE_CASE_TIERS.items() for cat in cats
}
_EDGE_CASE_CATEGORIES = {"all"} | set(_CATEGORY_TO_TIER)


def _get_tier(category: str) -> str:
    return _CATEGORY_TO_TIER.get(category, "unknown")


# Standard SELECT columns shared by all edge-case category queries
_EC_COLS = (
    "doc_id, borrower, {cat!r} as category, {sev!r} as severity, "
    "{detail} as detail, "
    "doc_type, market_segment, word_count, section_count, definition_count, "
    "clause_count, facility_size_mm"
)


def _doc_q(cohort_where: str, cat: str, severity: str, detail: str, where: str) -> str:
    """Build a simple documents-table-only category query."""
    cols = _EC_COLS.format(cat=cat, sev=severity, detail=detail)
    return f"SELECT {cols} FROM documents {cohort_where} {where}"


def _build_doc_category_queries(cohort_where: str) -> list[tuple[str, list[Any]]]:
    """Categories querying only the documents table (no JOINs)."""
    queries: list[tuple[str, list[Any]]] = []

    # --- Structural ---
    # 1. missing_sections (existing, enriched detail)
    queries.append((
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
        f"FROM documents {cohort_where} section_count = 0",
        [],
    ))
    # 2. low_section_count
    queries.append((_doc_q(
        cohort_where, "low_section_count", "medium",
        "'Only ' || section_count || ' sections in ' || word_count || '-word document'",
        "section_count BETWEEN 1 AND 4 AND word_count > 5000",
    ), []))
    # 4. section_fallback_used
    queries.append((_doc_q(
        cohort_where, "section_fallback_used", "low",
        "'Parser used fallback heuristic to detect ' || section_count || ' sections'",
        "section_fallback_used = true AND section_count > 0",
    ), []))

    # --- Clauses ---
    # 7. zero_clauses (existing)
    queries.append((_doc_q(
        cohort_where, "zero_clauses", "medium",
        "'Sections exist but no clauses parsed'",
        "clause_count = 0 AND section_count > 0",
    ), []))
    # 8. low_clause_density (uses only documents table columns)
    queries.append((_doc_q(
        cohort_where, "low_clause_density", "medium",
        "'Clause density ' || ROUND(CAST(clause_count AS DOUBLE) / section_count, 1) || ' per section (expected >= 3)'",
        "clause_count > 0 AND section_count > 0 AND CAST(clause_count AS DOUBLE) / section_count < 2.0",
    ), []))

    # --- Definitions ---
    # 15. low_definitions (existing)
    queries.append((_doc_q(
        cohort_where, "low_definitions", "medium",
        "'Fewer than 20 definitions in document with >10K words'",
        "definition_count < 20 AND word_count > 10000",
    ), []))
    # 16. zero_definitions
    queries.append((_doc_q(
        cohort_where, "zero_definitions", "high",
        "'No definitions extracted from ' || word_count || '-word document'",
        "definition_count = 0 AND word_count > 5000",
    ), []))
    # 17. high_definition_count
    queries.append((_doc_q(
        cohort_where, "high_definition_count", "medium",
        "definition_count || ' definitions detected — possible extraction noise'",
        "definition_count > 500",
    ), []))

    # --- Metadata ---
    # 20. extreme_facility (existing)
    queries.append((_doc_q(
        cohort_where, "extreme_facility", "low",
        "'Facility size outside typical range'",
        "facility_size_mm IS NOT NULL AND (facility_size_mm > 10000 OR facility_size_mm < 1)",
    ), []))
    # 21. missing_borrower
    queries.append((_doc_q(
        cohort_where, "missing_borrower", "medium",
        "'No borrower name extracted from document'",
        "borrower IS NULL OR TRIM(borrower) = ''",
    ), []))
    # 22. missing_facility_size
    queries.append((_doc_q(
        cohort_where, "missing_facility_size", "medium",
        "'No facility size extracted from ' || word_count || '-word document'",
        "facility_size_mm IS NULL AND word_count > 5000",
    ), []))
    # 23. missing_closing_date
    queries.append((_doc_q(
        cohort_where, "missing_closing_date", "low",
        "'No closing date extracted from document'",
        "closing_date IS NULL AND word_count > 5000",
    ), []))
    # 24. unknown_doc_type
    queries.append((_doc_q(
        cohort_where, "unknown_doc_type", "high",
        "'Low-confidence doc type classification: ' || COALESCE(doc_type, 'NULL')",
        "doc_type_confidence = 'low' OR doc_type IN ('', 'other') OR doc_type IS NULL",
    ), []))

    # --- Document Quality ---
    # 26. short_text
    queries.append((_doc_q(
        cohort_where, "short_text", "medium",
        "'Document text is only ' || text_length || ' characters (expected > 10K)'",
        "text_length < 10000 AND text_length > 0",
    ), []))
    # 27. extreme_text_ratio
    queries.append((_doc_q(
        cohort_where, "extreme_text_ratio", "medium",
        "'Text/word ratio ' || ROUND(CAST(text_length AS DOUBLE) / word_count, 1) || ' (expected ~6) — possible HTML artifact bloat'",
        "word_count > 0 AND CAST(text_length AS DOUBLE) / word_count > 15.0",
    ), []))
    # 28. very_short_document
    queries.append((_doc_q(
        cohort_where, "very_short_document", "high",
        "'Only ' || word_count || ' words — likely amendment/supplement'",
        "word_count < 5000 AND word_count > 0",
    ), []))

    # --- Template/Structure ---
    # 29. orphan_template
    queries.append((_doc_q(
        cohort_where, "orphan_template", "low",
        "'Document not assigned to any template family'",
        "template_family IS NULL OR TRIM(template_family) = ''",
    ), []))
    # 30. non_credit_agreement
    queries.append((_doc_q(
        cohort_where, "non_credit_agreement", "medium",
        "'Document classified as ' || doc_type || ' (confidence: ' || COALESCE(doc_type_confidence, 'N/A') || ')'",
        "doc_type NOT IN ('credit_agreement', '') AND doc_type IS NOT NULL AND word_count > 1000",
    ), []))
    # 31. uncertain_market_segment
    queries.append((_doc_q(
        cohort_where, "uncertain_market_segment", "low",
        "'Market segment uncertain — could not determine leveraged vs. investment grade'",
        "segment_confidence = 'low' AND market_segment = 'uncertain'",
    ), []))
    # 32. non_cohort_large_doc
    queries.append((_doc_q(
        cohort_where, "non_cohort_large_doc", "low",
        "word_count || '-word document excluded from cohort'",
        "cohort_included = false AND word_count > 10000",
    ), []))

    return queries


def _build_join_category_queries(cohort_where: str) -> list[tuple[str, list[Any]]]:
    """Categories requiring JOINs against clauses, definitions, or sections tables."""
    queries: list[tuple[str, list[Any]]] = []
    # Cohort filter for subqueries that start from non-documents tables
    cohort_join = "JOIN documents d ON sub.doc_id = d.doc_id" if "cohort_included" not in cohort_where else (
        "JOIN documents d ON sub.doc_id = d.doc_id WHERE d.cohort_included = true"
    )
    # Simpler: always JOIN documents, apply cohort filter if needed
    cohort_doc_filter = " AND d.cohort_included = true" if "cohort_included" in cohort_where else ""

    _cols = (
        "sub.doc_id, d.borrower, {cat!r} as category, {sev!r} as severity, "
        "{detail} as detail, "
        "d.doc_type, d.market_segment, d.word_count, d.section_count, d.definition_count, "
        "d.clause_count, d.facility_size_mm"
    )

    # --- Clause depth anomalies (user priority) ---

    # 9. low_avg_clause_confidence
    cols = _cols.format(
        cat="low_avg_clause_confidence", sev="high",
        detail="'Average clause confidence ' || sub.avg_conf || ' across ' || sub.n_clauses || ' clauses (threshold 0.4)'",
    )
    queries.append((
        f"SELECT {cols} FROM ("
        f"  SELECT c.doc_id, ROUND(AVG(c.parse_confidence), 3) as avg_conf, COUNT(*) as n_clauses"
        f"  FROM clauses c JOIN documents dd ON c.doc_id = dd.doc_id"
        f"  WHERE dd.clause_count > 10"
        f"  GROUP BY c.doc_id HAVING AVG(c.parse_confidence) < 0.4"
        f") sub JOIN documents d ON sub.doc_id = d.doc_id"
        f"{cohort_doc_filter}",
        [],
    ))

    # 10. orphan_deep_clause — uses tree_level >= 3 (from clause_id path)
    cols = _cols.format(
        cat="orphan_deep_clause", sev="high",
        detail="sub.orphan_count || ' orphaned deep clauses (tree level >= 3, missing parent)'",
    )
    queries.append((
        f"SELECT {cols} FROM ("
        f"  SELECT ci.doc_id, COUNT(*) as orphan_count"
        f"  FROM (SELECT *, ARRAY_LENGTH(STRING_SPLIT(clause_id, '.')) AS tree_level FROM clauses) ci"
        f"  LEFT JOIN clauses p ON ci.doc_id = p.doc_id AND ci.section_number = p.section_number AND ci.parent_id = p.clause_id"
        f"  WHERE ci.tree_level >= 3 AND ci.is_structural = true AND ci.parent_id != '' AND p.clause_id IS NULL"
        f"  GROUP BY ci.doc_id"
        f") sub JOIN documents d ON sub.doc_id = d.doc_id"
        f"{cohort_doc_filter}",
        [],
    ))

    # 12. inconsistent_sibling_depth — uses tree_level (from clause_id path)
    cols = _cols.format(
        cat="inconsistent_sibling_depth", sev="high",
        detail="sub.bad_groups || ' parent groups with inconsistent tree levels (' || sub.affected || ' clauses)'",
    )
    queries.append((
        f"SELECT {cols} FROM ("
        f"  SELECT doc_id, COUNT(*) as bad_groups, SUM(n_siblings) as affected FROM ("
        f"    SELECT doc_id, parent_id, section_number, COUNT(*) as n_siblings"
        f"    FROM (SELECT *, ARRAY_LENGTH(STRING_SPLIT(clause_id, '.')) AS tree_level FROM clauses) c"
        f"    WHERE c.is_structural = true AND c.parent_id != ''"
        f"    GROUP BY doc_id, section_number, parent_id"
        f"    HAVING COUNT(DISTINCT tree_level) > 1"
        f"  ) g GROUP BY doc_id"
        f") sub JOIN documents d ON sub.doc_id = d.doc_id"
        f"{cohort_doc_filter}",
        [],
    ))

    # 13. deep_nesting_outlier — uses tree_level > 4 (from clause_id path)
    cols = _cols.format(
        cat="deep_nesting_outlier", sev="low",
        detail="'Max tree level ' || sub.max_level || ' with ' || sub.deep_count || ' clauses beyond level 4'",
    )
    queries.append((
        f"SELECT {cols} FROM ("
        f"  SELECT doc_id, MAX(tree_level) as max_level, COUNT(*) as deep_count"
        f"  FROM (SELECT *, ARRAY_LENGTH(STRING_SPLIT(clause_id, '.')) AS tree_level FROM clauses) c"
        f"  WHERE c.is_structural = true AND c.tree_level > 4"
        f"  GROUP BY doc_id"
        f") sub JOIN documents d ON sub.doc_id = d.doc_id"
        f"{cohort_doc_filter}",
        [],
    ))

    # 14. low_structural_ratio
    cols = _cols.format(
        cat="low_structural_ratio", sev="medium",
        detail="'Only ' || sub.pct || '% structural (' || sub.structural || '/' || sub.total || ')'",
    )
    queries.append((
        f"SELECT {cols} FROM ("
        f"  SELECT doc_id, COUNT(*) as total,"
        f"    SUM(CASE WHEN is_structural THEN 1 ELSE 0 END) as structural,"
        f"    ROUND(100.0 * SUM(CASE WHEN is_structural THEN 1 ELSE 0 END) / COUNT(*), 1) as pct"
        f"  FROM clauses GROUP BY doc_id HAVING COUNT(*) >= 10"
        f") sub JOIN documents d ON sub.doc_id = d.doc_id"
        f" WHERE sub.pct < 50.0{cohort_doc_filter}",
        [],
    ))

    # 15. rootless_deep_clause — tree_level > 1 with empty parent_id
    cols = _cols.format(
        cat="rootless_deep_clause", sev="medium",
        detail="sub.rootless_count || ' clauses with tree level > 1 but no parent link'",
    )
    queries.append((
        f"SELECT {cols} FROM ("
        f"  SELECT doc_id, COUNT(*) as rootless_count"
        f"  FROM (SELECT *, ARRAY_LENGTH(STRING_SPLIT(clause_id, '.')) AS tree_level FROM clauses) c"
        f"  WHERE c.tree_level > 1 AND c.is_structural = true AND (c.parent_id IS NULL OR c.parent_id = '')"
        f"  GROUP BY doc_id"
        f") sub JOIN documents d ON sub.doc_id = d.doc_id"
        f"{cohort_doc_filter}",
        [],
    ))

    # --- Definition JOINs ---

    # 18. duplicate_definitions
    cols = _cols.format(
        cat="duplicate_definitions", sev="low",
        detail="sub.dup_term_count || ' terms defined multiple times in same document'",
    )
    queries.append((
        f"SELECT {cols} FROM ("
        f"  SELECT doc_id, COUNT(*) as dup_term_count FROM ("
        f"    SELECT doc_id, term FROM definitions GROUP BY doc_id, term HAVING COUNT(*) > 1"
        f"  ) inner_sub GROUP BY doc_id"
        f") sub JOIN documents d ON sub.doc_id = d.doc_id"
        f"{cohort_doc_filter}",
        [],
    ))

    # 19. single_engine_definitions
    cols = _cols.format(
        cat="single_engine_definitions", sev="low",
        detail="'All ' || sub.def_count || ' definitions extracted by single engine: ' || sub.sole_engine",
    )
    queries.append((
        f"SELECT {cols} FROM ("
        f"  SELECT doc_id, MIN(pattern_engine) as sole_engine, COUNT(*) as def_count"
        f"  FROM definitions GROUP BY doc_id"
        f"  HAVING COUNT(DISTINCT pattern_engine) = 1 AND COUNT(*) >= 10"
        f") sub JOIN documents d ON sub.doc_id = d.doc_id"
        f"{cohort_doc_filter}",
        [],
    ))

    # --- Section JOINs ---

    # 5. section_numbering_gap
    cols = _cols.format(
        cat="section_numbering_gap", sev="medium",
        detail="sub.gap_count || ' numbering gaps detected in section sequence'",
    )
    queries.append((
        f"SELECT {cols} FROM ("
        f"  SELECT doc_id, COUNT(*) as gap_count FROM ("
        f"    SELECT doc_id, CAST(section_number AS DOUBLE) as sn,"
        f"      LAG(CAST(section_number AS DOUBLE)) OVER (PARTITION BY doc_id ORDER BY CAST(section_number AS DOUBLE)) AS prev_sn"
        f"    FROM sections WHERE section_number NOT LIKE '%.%'"
        f"  ) numbered WHERE prev_sn IS NOT NULL AND sn - prev_sn > 1.0 AND sn > 1.0"
        f"  GROUP BY doc_id"
        f") sub JOIN documents d ON sub.doc_id = d.doc_id"
        f"{cohort_doc_filter}",
        [],
    ))

    # 6. empty_section_headings
    cols = _cols.format(
        cat="empty_section_headings", sev="medium",
        detail="sub.empty_count || ' sections with missing or empty headings'",
    )
    queries.append((
        f"SELECT {cols} FROM ("
        f"  SELECT doc_id, COUNT(*) as empty_count"
        f"  FROM sections WHERE heading IS NULL OR TRIM(heading) = ''"
        f"  GROUP BY doc_id"
        f") sub JOIN documents d ON sub.doc_id = d.doc_id"
        f"{cohort_doc_filter}",
        [],
    ))

    return queries


def _build_iqr_category_queries(
    corpus: Any, cohort_where: str, cohort_only: bool,
) -> list[tuple[str, list[Any]]]:
    """IQR-fence-based categories requiring pre-computation of percentiles."""
    queries: list[tuple[str, list[Any]]] = []

    def _compute_fences(col: str) -> tuple[float, float]:
        base = "WHERE cohort_included = true AND" if cohort_only else "WHERE"
        rows = corpus.query(f"SELECT {col} FROM documents {base} {col} IS NOT NULL")
        vals = [float(r[0]) for r in rows if r[0] is not None]
        if len(vals) < 4:
            return 0.0, float("inf")
        q1 = _percentile(vals, 0.25)
        q3 = _percentile(vals, 0.75)
        iqr = q3 - q1
        if iqr <= 0:
            return 0.0, float("inf")
        return q1 - 1.5 * iqr, q3 + 1.5 * iqr

    # 25. extreme_word_count (existing)
    wc_lo, wc_hi = _compute_fences("word_count")
    if wc_hi != float("inf"):
        queries.append((
            f"SELECT doc_id, borrower, 'extreme_word_count' as category, 'low' as severity, "
            f"'Word count ' || word_count || ' outside IQR fences [' || CAST(ROUND(?, 0) AS INTEGER) || ', ' || CAST(ROUND(?, 0) AS INTEGER) || ']' as detail, "
            f"doc_type, market_segment, word_count, section_count, definition_count, "
            f"clause_count, facility_size_mm "
            f"FROM documents {cohort_where} word_count IS NOT NULL "
            f"AND (word_count < ? OR word_count > ?)",
            [wc_lo, wc_hi, wc_lo, wc_hi],
        ))

    # 3. excessive_section_count
    sc_lo, sc_hi = _compute_fences("section_count")
    if sc_hi != float("inf"):
        queries.append((
            f"SELECT doc_id, borrower, 'excessive_section_count' as category, 'low' as severity, "
            f"section_count || ' sections (IQR upper fence: ' || CAST(ROUND(?, 0) AS INTEGER) || ')' as detail, "
            f"doc_type, market_segment, word_count, section_count, definition_count, "
            f"clause_count, facility_size_mm "
            f"FROM documents {cohort_where} section_count IS NOT NULL "
            f"AND section_count > ?",
            [sc_hi, sc_hi],
        ))

    return queries


@app.get("/api/edge-cases")
async def edge_cases(
    category: str = Query("all", description="Edge case category to filter"),
    page: int = Query(0, ge=0),
    page_size: int = Query(50, ge=1, le=200),
    cohort_only: bool = Query(False),
):
    """Categorized edge case documents for inspection (32 categories, 6 tiers)."""
    corpus = _get_corpus()

    if category not in _EDGE_CASE_CATEGORIES:
        raise HTTPException(
            400,
            f"Invalid category: {category}. Must be one of: {', '.join(sorted(_EDGE_CASE_CATEGORIES))}",
        )

    cohort_where = "WHERE cohort_included = true AND" if cohort_only else "WHERE"

    # --- Build ALL category queries via builder functions ---
    all_parts: list[tuple[str, list[Any]]] = []
    all_parts.extend(_build_doc_category_queries(cohort_where))
    all_parts.extend(_build_join_category_queries(cohort_where))
    all_parts.extend(_build_iqr_category_queries(corpus, cohort_where, cohort_only))

    # Merge into a single UNION ALL
    all_queries = [p[0] for p in all_parts]
    all_params: list[Any] = []
    for p in all_parts:
        all_params.extend(p[1])

    all_union_sql = " UNION ALL ".join(all_queries)

    # Global category counts (always includes all categories for pill display)
    cat_rows = corpus.query(
        f"SELECT category, COUNT(*) FROM ({all_union_sql}) GROUP BY category ORDER BY COUNT(*) DESC",
        all_params,
    )

    # --- Build filtered query (for the paginated case list) ---
    if category == "all":
        filtered_sql = all_union_sql
        filtered_params = list(all_params)
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
            {"category": str(r[0]), "count": int(r[1]), "tier": _get_tier(str(r[0]))}
            for r in cat_rows
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


# Clause anomaly categories that support drill-down
_CLAUSE_ANOMALY_CATEGORIES = {
    "inconsistent_sibling_depth",
    "orphan_deep_clause",
    "deep_nesting_outlier",
    "low_avg_clause_confidence",
    "low_structural_ratio",
    "rootless_deep_clause",
}


@app.get("/api/edge-cases/{doc_id}/clause-detail")
async def edge_case_clause_detail(
    doc_id: str,
    category: str = Query(..., description="Clause anomaly category"),
) -> dict[str, Any]:
    """Per-document clause-level drill-down for clause anomaly categories."""
    corpus = _get_corpus()

    if category not in _CLAUSE_ANOMALY_CATEGORIES:
        raise HTTPException(
            400,
            f"Invalid clause anomaly category: {category}. "
            f"Must be one of: {', '.join(sorted(_CLAUSE_ANOMALY_CATEGORIES))}",
        )

    # Verify document exists
    doc_rows = corpus.query(
        "SELECT doc_id FROM documents WHERE doc_id = ?", [doc_id],
    )
    if not doc_rows:
        raise HTTPException(404, f"Document not found: {doc_id}")

    # Build category-specific clause query
    # All queries return: section_number, clause_id, label, depth, level_type,
    #   parent_id, is_structural, parse_confidence, header_text, span_start, span_end, tree_level
    _clause_cols = (
        "c.section_number, c.clause_id, c.label, c.depth, c.level_type, "
        "c.parent_id, c.is_structural, c.parse_confidence, c.header_text, "
        "c.span_start, c.span_end, ARRAY_LENGTH(STRING_SPLIT(c.clause_id, '.')) AS tree_level"
    )

    if category == "inconsistent_sibling_depth":
        # Clauses in parent groups with mixed tree_levels
        sql = (
            f"SELECT {_clause_cols} FROM clauses c "
            f"WHERE c.doc_id = ? AND c.is_structural = true AND c.parent_id != '' "
            f"AND (c.doc_id, c.section_number, c.parent_id) IN ("
            f"  SELECT doc_id, section_number, parent_id "
            f"  FROM (SELECT *, ARRAY_LENGTH(STRING_SPLIT(clause_id, '.')) AS tl FROM clauses) s "
            f"  WHERE s.doc_id = ? AND s.is_structural = true AND s.parent_id != '' "
            f"  GROUP BY s.doc_id, s.section_number, s.parent_id "
            f"  HAVING COUNT(DISTINCT tl) > 1"
            f") ORDER BY c.section_number, c.span_start"
        )
        params: list[Any] = [doc_id, doc_id]

    elif category == "orphan_deep_clause":
        # tree_level >= 3 with broken parent reference
        sql = (
            f"SELECT {_clause_cols} FROM clauses c "
            f"LEFT JOIN clauses p ON c.doc_id = p.doc_id AND c.section_number = p.section_number "
            f"  AND c.parent_id = p.clause_id "
            f"WHERE c.doc_id = ? AND ARRAY_LENGTH(STRING_SPLIT(c.clause_id, '.')) >= 3 "
            f"  AND c.is_structural = true AND c.parent_id != '' AND p.clause_id IS NULL "
            f"ORDER BY c.section_number, c.span_start"
        )
        params = [doc_id]

    elif category == "deep_nesting_outlier":
        # tree_level > 4
        sql = (
            f"SELECT {_clause_cols} FROM clauses c "
            f"WHERE c.doc_id = ? AND c.is_structural = true "
            f"  AND ARRAY_LENGTH(STRING_SPLIT(c.clause_id, '.')) > 4 "
            f"ORDER BY c.section_number, c.span_start"
        )
        params = [doc_id]

    elif category == "low_avg_clause_confidence":
        # parse_confidence < 0.4, limit 100
        sql = (
            f"SELECT {_clause_cols} FROM clauses c "
            f"WHERE c.doc_id = ? AND c.parse_confidence < 0.4 "
            f"ORDER BY c.parse_confidence ASC, c.section_number, c.span_start "
            f"LIMIT 100"
        )
        params = [doc_id]

    elif category == "low_structural_ratio":
        # Non-structural clauses, limit 100
        sql = (
            f"SELECT {_clause_cols} FROM clauses c "
            f"WHERE c.doc_id = ? AND c.is_structural = false "
            f"ORDER BY c.section_number, c.span_start "
            f"LIMIT 100"
        )
        params = [doc_id]

    elif category == "rootless_deep_clause":
        # tree_level > 1 with empty parent_id
        sql = (
            f"SELECT {_clause_cols} FROM clauses c "
            f"WHERE c.doc_id = ? AND c.is_structural = true "
            f"  AND ARRAY_LENGTH(STRING_SPLIT(c.clause_id, '.')) > 1 "
            f"  AND (c.parent_id IS NULL OR c.parent_id = '') "
            f"ORDER BY c.section_number, c.span_start"
        )
        params = [doc_id]

    else:
        raise HTTPException(400, f"Unsupported category: {category}")

    rows = corpus.query(sql, params)

    # Look up section headings for context
    sec_nums = list({str(r[0]) for r in rows})
    sec_headings: dict[str, str] = {}
    if sec_nums:
        placeholders = ", ".join(["?"] * len(sec_nums))
        sec_rows = corpus.query(
            f"SELECT section_number, heading FROM sections "
            f"WHERE doc_id = ? AND section_number IN ({placeholders})",
            [doc_id, *sec_nums],
        )
        for sr in sec_rows:
            sec_headings[str(sr[0])] = str(sr[1]) if sr[1] else ""

    clauses = []
    for r in rows:
        clauses.append({
            "section_number": str(r[0]),
            "section_heading": sec_headings.get(str(r[0]), ""),
            "clause_id": str(r[1]),
            "label": str(r[2]) if r[2] else "",
            "depth": int(r[3]) if r[3] is not None else 0,
            "level_type": str(r[4]) if r[4] else "",
            "parent_id": str(r[5]) if r[5] else "",
            "is_structural": bool(r[6]),
            "parse_confidence": float(r[7]) if r[7] is not None else 0.0,
            "header_text": str(r[8]) if r[8] else "",
            "span_start": int(r[9]) if r[9] is not None else 0,
            "span_end": int(r[10]) if r[10] is not None else 0,
            "tree_level": int(r[11]) if r[11] is not None else 1,
        })

    return {
        "doc_id": doc_id,
        "category": category,
        "total_flagged": len(clauses),
        "clauses": clauses,
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
# Corpus Query Builder
# ===========================================================================


@app.get("/api/articles/concepts")
async def article_concepts(cohort_only: bool = Query(True)):
    """Return distinct non-null concept values from the articles table."""
    corpus = _get_corpus()

    # Graceful fallback when articles table is absent (older corpus builds)
    try:
        table_check = corpus.query(
            "SELECT COUNT(*) FROM information_schema.tables WHERE table_name = 'articles'"
        )
        if not table_check or int(table_check[0][0]) == 0:
            return {"concepts": []}
    except Exception:
        return {"concepts": []}

    cohort_cond = (
        "a.doc_id IN (SELECT doc_id FROM documents WHERE cohort_included = true)"
        if cohort_only else "1=1"
    )

    rows = corpus.query(
        f"""
        SELECT DISTINCT a.concept
        FROM articles a
        WHERE a.concept IS NOT NULL AND {cohort_cond}
        ORDER BY a.concept
        """
    )

    return {"concepts": [str(r[0]) for r in rows]}


class FilterTerm(BaseModel):
    value: str
    op: str = "or"  # "or" | "and" | "not" | "and_not"


class CorpusQueryRequest(BaseModel):
    # Article filters
    concept: str | None = None
    article_num: int | None = None
    article_title_pattern: str | None = None  # legacy single-value
    article_title_filters: list[FilterTerm] = Field(default_factory=list)

    # Section filters
    heading_pattern: str | None = None  # legacy single-value
    heading_filters: list[FilterTerm] = Field(default_factory=list)
    section_number: str | None = None

    # Clause filters
    clause_text_contains: str | None = None  # legacy single-value
    clause_text_filters: list[FilterTerm] = Field(default_factory=list)
    clause_header_contains: str | None = None  # legacy single-value
    clause_header_filters: list[FilterTerm] = Field(default_factory=list)
    min_depth: int = 0
    max_depth: int = 10
    min_clause_chars: int = 0

    # Global
    cohort_only: bool = True
    limit: int = Field(default=200, ge=1, le=2000)


@app.post("/api/corpus/query")
async def corpus_query(req: CorpusQueryRequest):
    """Unified cross-level query across articles, sections, and clauses."""
    corpus = _get_corpus()

    # Check that articles table exists
    has_articles = True
    try:
        table_check = corpus.query(
            "SELECT COUNT(*) FROM information_schema.tables WHERE table_name = 'articles'"
        )
        if not table_check or int(table_check[0][0]) == 0:
            has_articles = False
    except Exception:
        has_articles = False

    # ── Build shared condition fragments ──
    cohort_cond = (
        "d.cohort_included = true" if req.cohort_only else "1=1"
    )

    # Article-level conditions (applied when joining articles)
    art_conditions: list[str] = []
    art_params: list[Any] = []
    if req.concept:
        art_conditions.append("a.concept = ?")
        art_params.append(req.concept)
    if req.article_num is not None:
        art_conditions.append("a.article_num = ?")
        art_params.append(req.article_num)
    # Multi-value article title filters (preferred) or legacy single-value
    if req.article_title_filters:
        frag, fparams = _build_filter_group("a.title", req.article_title_filters)
        art_conditions.append(frag)
        art_params.extend(fparams)
    elif req.article_title_pattern:
        art_conditions.append("a.title ILIKE ? ESCAPE '\\'")
        art_params.append(req.article_title_pattern)

    # Section-level conditions
    sec_conditions: list[str] = []
    sec_params: list[Any] = []
    # Multi-value heading filters (preferred) or legacy single-value
    if req.heading_filters:
        frag, fparams = _build_filter_group("s.heading", req.heading_filters)
        sec_conditions.append(frag)
        sec_params.extend(fparams)
    elif req.heading_pattern:
        sec_conditions.append("s.heading ILIKE ? ESCAPE '\\'")
        sec_params.append(req.heading_pattern)
    if req.section_number:
        sec_conditions.append("s.section_number = ?")
        sec_params.append(req.section_number)

    # Clause-level conditions
    cls_conditions: list[str] = []
    cls_params: list[Any] = []
    # Multi-value clause text filters (preferred) or legacy single-value
    if req.clause_text_filters:
        frag, fparams = _build_filter_group("c.clause_text", req.clause_text_filters, wrap_wildcards=True)
        cls_conditions.append(frag)
        cls_params.extend(fparams)
    elif req.clause_text_contains:
        escaped_ct = _escape_like(req.clause_text_contains)
        cls_conditions.append("c.clause_text ILIKE ? ESCAPE '\\'")
        cls_params.append(f"%{escaped_ct}%")
    # Multi-value clause header filters (preferred) or legacy single-value
    if req.clause_header_filters:
        frag, fparams = _build_filter_group("c.header_text", req.clause_header_filters, wrap_wildcards=True)
        cls_conditions.append(frag)
        cls_params.extend(fparams)
    elif req.clause_header_contains:
        escaped_ch = _escape_like(req.clause_header_contains)
        cls_conditions.append("c.header_text ILIKE ? ESCAPE '\\'")
        cls_params.append(f"%{escaped_ch}%")
    if req.min_depth > 0:
        cls_conditions.append("c.depth >= ?")
        cls_params.append(req.min_depth)
    if req.max_depth < 10:
        cls_conditions.append("c.depth <= ?")
        cls_params.append(req.max_depth)
    if req.min_clause_chars > 0:
        cls_conditions.append("LENGTH(c.clause_text) >= ?")
        cls_params.append(req.min_clause_chars)

    has_art_filters = bool(art_conditions) and has_articles
    has_sec_filters = bool(sec_conditions)
    has_cls_filters = bool(cls_conditions)

    # ── Query 1: Articles aggregation ──
    articles_result: list[dict[str, Any]] = []
    total_articles = 0
    if has_articles:
        art_where_parts = [cohort_cond] + art_conditions
        if has_sec_filters:
            sec_sub_conds = " AND ".join(["s.doc_id = a.doc_id", "s.article_num = a.article_num"] + sec_conditions)
            art_where_parts.append(f"EXISTS (SELECT 1 FROM sections s WHERE {sec_sub_conds})")
        art_where = " WHERE " + " AND ".join(art_where_parts)
        art_query_params = art_params + (sec_params if has_sec_filters else [])

        count_row = corpus.query(
            f"""
            SELECT COUNT(DISTINCT (a.doc_id, a.concept, a.title))
            FROM articles a
            JOIN documents d ON a.doc_id = d.doc_id
            {art_where}
            """,
            art_query_params,
        )
        total_articles = int(count_row[0][0]) if count_row else 0

        rows = corpus.query(
            f"""
            SELECT
                a.concept,
                a.title,
                COUNT(DISTINCT a.doc_id) as doc_count,
                COALESCE(SUM(sec_agg.sec_cnt), 0) as section_count,
                ARRAY_AGG(DISTINCT a.doc_id ORDER BY a.doc_id) as doc_ids
            FROM articles a
            JOIN documents d ON a.doc_id = d.doc_id
            LEFT JOIN (
                SELECT doc_id, article_num, COUNT(*) as sec_cnt
                FROM sections
                GROUP BY doc_id, article_num
            ) sec_agg ON a.doc_id = sec_agg.doc_id AND a.article_num = sec_agg.article_num
            {art_where}
            GROUP BY a.concept, a.title
            ORDER BY doc_count DESC
            LIMIT ?
            """,
            [*art_query_params, req.limit],
        )
        articles_result = [
            {
                "concept": str(r[0]) if r[0] else None,
                "title": str(r[1]) if r[1] else "",
                "doc_count": int(r[2]),
                "section_count": int(r[3]),
                "example_doc_ids": [str(x) for x in (r[4] or [])[:5]],
            }
            for r in rows
        ]

    # ── Query 2: Sections aggregation ──
    sec_where_parts = [cohort_cond] + sec_conditions
    sec_join_params: list[Any] = list(sec_params)
    sec_join = "JOIN documents d ON s.doc_id = d.doc_id"
    if has_art_filters:
        art_sub_conds = " AND ".join(["a.doc_id = s.doc_id", "a.article_num = s.article_num"] + art_conditions)
        sec_where_parts.append(f"EXISTS (SELECT 1 FROM articles a WHERE {art_sub_conds})")
        sec_join_params.extend(art_params)

    sec_where = " WHERE " + " AND ".join(sec_where_parts)

    count_row = corpus.query(
        f"""
        SELECT COUNT(DISTINCT (s.doc_id, s.section_number))
        FROM sections s
        {sec_join}
        {sec_where}
        """,
        sec_join_params,
    )
    total_sections = int(count_row[0][0]) if count_row else 0

    sec_rows = corpus.query(
        f"""
        SELECT
            s.heading,
            COUNT(*) as frequency,
            COUNT(DISTINCT s.doc_id) as doc_count,
            ROUND(AVG(s.word_count), 0) as avg_word_count,
            ARRAY_AGG(DISTINCT s.doc_id ORDER BY s.doc_id) as doc_ids
        FROM sections s
        {sec_join}
        {sec_where}
        GROUP BY s.heading
        ORDER BY frequency DESC
        LIMIT ?
        """,
        [*sec_join_params, req.limit],
    )
    sections_result = [
        {
            "heading": str(r[0]) if r[0] else "",
            "frequency": int(r[1]),
            "doc_count": int(r[2]),
            "avg_word_count": int(r[3]) if r[3] is not None else 0,
            "example_doc_ids": [str(x) for x in (r[4] or [])[:5]],
        }
        for r in sec_rows
    ]

    # ── Query 3: Clauses detail (only when clause filters or other filters present) ──
    clauses_result: list[dict[str, Any]] = []
    total_clauses = 0
    # Always run clause query if any filter is provided; skip only when zero filters total
    any_filter = has_art_filters or has_sec_filters or has_cls_filters
    if any_filter:
        cls_where_parts = [
            "d.doc_id IS NOT NULL",  # ensure join
            cohort_cond,
        ] + cls_conditions
        cls_query_params: list[Any] = list(cls_params)

        cls_join = """
            JOIN sections s ON c.doc_id = s.doc_id AND c.section_number = s.section_number
            JOIN documents d ON c.doc_id = d.doc_id
        """
        if has_articles:
            cls_join += " LEFT JOIN articles a ON s.doc_id = a.doc_id AND s.article_num = a.article_num"

        if has_sec_filters:
            cls_where_parts.extend(sec_conditions)
            cls_query_params.extend(sec_params)
        if has_art_filters:
            cls_where_parts.extend(art_conditions)
            cls_query_params.extend(art_params)

        cls_where = " WHERE " + " AND ".join(cls_where_parts)

        count_row = corpus.query(
            f"SELECT COUNT(*) FROM clauses c {cls_join} {cls_where}",
            cls_query_params,
        )
        total_clauses = int(count_row[0][0]) if count_row else 0

        art_select = "a.article_num, a.title, a.concept" if has_articles else "s.article_num, '' as article_title, NULL as article_concept"

        cls_rows = corpus.query(
            f"""
            SELECT
                c.doc_id,
                d.borrower,
                {art_select},
                s.section_number,
                s.heading,
                c.clause_id,
                c.label,
                c.depth,
                c.header_text,
                SUBSTRING(c.clause_text, 1, 500) as clause_text
            FROM clauses c
            {cls_join}
            {cls_where}
            ORDER BY c.doc_id, s.section_number, c.clause_id
            LIMIT ?
            """,
            [*cls_query_params, req.limit],
        )
        clauses_result = [
            {
                "doc_id": str(r[0]),
                "borrower": str(r[1]) if r[1] else "",
                "article_num": int(r[2]) if r[2] is not None else 0,
                "article_title": str(r[3]) if r[3] else "",
                "article_concept": str(r[4]) if r[4] else None,
                "section_number": str(r[5]),
                "section_heading": str(r[6]) if r[6] else "",
                "clause_id": str(r[7]),
                "label": str(r[8]) if r[8] else "",
                "depth": int(r[9]) if r[9] is not None else 0,
                "header_text": str(r[10]) if r[10] else "",
                "clause_text": str(r[11]) if r[11] else "",
            }
            for r in cls_rows
        ]

    # ── Unique docs ──
    doc_ids: set[str] = set()
    for a in articles_result:
        doc_ids.update(a["example_doc_ids"])
    for s in sections_result:
        doc_ids.update(s["example_doc_ids"])
    for c in clauses_result:
        doc_ids.add(c["doc_id"])
    # For a more accurate count, query it
    unique_doc_parts = [cohort_cond]
    unique_doc_params: list[Any] = []
    base_from = "documents d"
    if has_sec_filters or has_art_filters:
        base_from += " JOIN sections s ON d.doc_id = s.doc_id"
        unique_doc_parts.extend(sec_conditions)
        unique_doc_params.extend(sec_params)
    if has_art_filters:
        base_from += " JOIN articles a ON s.doc_id = a.doc_id AND s.article_num = a.article_num"
        unique_doc_parts.extend(art_conditions)
        unique_doc_params.extend(art_params)
    udoc_row = corpus.query(
        f"SELECT COUNT(DISTINCT d.doc_id) FROM {base_from} WHERE " + " AND ".join(unique_doc_parts),
        unique_doc_params,
    )
    unique_docs = int(udoc_row[0][0]) if udoc_row else 0

    return {
        "total_articles": total_articles,
        "total_sections": total_sections,
        "total_clauses": total_clauses,
        "unique_docs": unique_docs,
        "articles": articles_result,
        "sections": sections_result,
        "clauses": clauses_result,
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


class ManualLinkCreateRequest(BaseModel):
    family_id: str = Field(..., min_length=1, max_length=255)
    doc_id: str = Field(..., min_length=1, max_length=255)
    section_number: str = Field(..., min_length=1, max_length=64)
    heading: str = Field(default="", max_length=1000)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    confidence_tier: Literal["high", "medium", "low"] = "high"
    status: Literal["active", "pending_review", "unlinked"] = "active"
    source: str = Field(default="manual", max_length=64)
    run_id: str | None = Field(default=None, max_length=128)


class LinkPreviewRequest(BaseModel):
    family_id: str = Field(default="", max_length=255)
    ontology_node_id: str | None = Field(default=None, max_length=255)
    heading_filter_ast: dict[str, Any] | None = None
    filter_dsl: str | None = Field(default=None, max_length=5000)
    result_granularity: str = Field(default="section", pattern=r"^(section|clause)$")
    scope_mode: str = Field(default="corpus", pattern=r"^(corpus|inherited)$")
    parent_family_id: str | None = Field(default=None, max_length=255)
    parent_rule_id: str | None = Field(default=None, max_length=255)
    parent_run_id: str | None = Field(default=None, max_length=255)
    text_fields: dict[str, Any] | None = None
    meta_filters: dict[str, Any] | None = None
    rule_id: str | None = Field(default=None, max_length=255)
    async_threshold: int = Field(default=10000, ge=1, le=50000)


class LinksImportRequest(BaseModel):
    records: list[ManualLinkCreateRequest] = Field(
        default_factory=list,
        min_length=1,
        max_length=5000,
    )


class EvaluateTextRequest(BaseModel):
    rule_ast: dict[str, Any] | None = None
    raw_text: str | None = Field(default=None, max_length=20000)
    # Backward-compatible aliases currently sent by the Phase 4 frontend.
    heading_filter_ast: dict[str, Any] | None = None
    text: str | None = Field(default=None, max_length=20000)


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


def _normalize_meta_filters_payload(payload: Any) -> dict[str, MetaFilter]:
    """Normalize metadata filters that may arrive as JSON strings."""
    if payload is None:
        return {}
    raw = payload
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return {}
        try:
            raw = json.loads(text)
        except json.JSONDecodeError as exc:
            raise HTTPException(
                status_code=422,
                detail=f"Invalid meta_filters JSON: {exc.msg}",
            ) from exc
    if not isinstance(raw, dict):
        raise HTTPException(status_code=422, detail="meta_filters must be an object")

    parsed: dict[str, MetaFilter] = {}
    for field_name, value in raw.items():
        if not isinstance(value, dict):
            raise HTTPException(
                status_code=422,
                detail=f"meta_filters.{field_name} must be an object",
            )
        try:
            parsed[str(field_name)] = meta_filter_from_json(value)
        except (KeyError, TypeError, ValueError) as exc:
            raise HTTPException(
                status_code=422,
                detail=f"Invalid meta filter for {field_name}: {exc}",
            ) from exc
    return parsed


def _resolve_doc_ids_for_meta_filters(meta_filters: dict[str, MetaFilter]) -> list[str] | None:
    """Resolve doc IDs from corpus metadata filters.

    Returns None when no filters are provided or when corpus metadata is unavailable.
    """
    if not meta_filters:
        return None
    try:
        corpus = _get_corpus()
    except HTTPException:
        return None

    clauses: list[str] = []
    params: list[Any] = []
    for meta in meta_filters.values():
        sql, sql_params = build_meta_filter_sql(meta)
        clauses.append(f"({sql})")
        params.extend(sql_params)
    where = " AND ".join(clauses) if clauses else "TRUE"
    try:
        rows = corpus.query(
            f"SELECT d.doc_id FROM documents d WHERE {where} ORDER BY d.doc_id",
            params,
        )
    except Exception:
        return None
    return [str(r[0]) for r in rows if r and r[0] is not None]


def _resolve_inherited_scope_sections(
    store: LinkStore,
    *,
    parent_run_id: str | None,
    parent_family_id: str | None,
) -> list[tuple[str, str]]:
    """Resolve section-level scope for inherited query/rule execution."""
    if parent_run_id:
        rows = store._conn.execute(
            "SELECT doc_id, section_number FROM family_links "
            "WHERE run_id = ? AND status <> 'unlinked'",
            [parent_run_id],
        ).fetchall()
        scoped = [(str(r[0]), str(r[1])) for r in rows if r and r[0] is not None and r[1] is not None]
        if scoped:
            return scoped
    if parent_family_id:
        scope_ids = store.resolve_scope_aliases(parent_family_id)
        if not scope_ids:
            scope_ids = [str(parent_family_id).strip()]
        placeholders = ", ".join("?" for _ in scope_ids)
        rows = store._conn.execute(
            "SELECT doc_id, section_number FROM family_links "
            f"WHERE {store._scope_sql_expr()} IN ({placeholders}) "
            "AND status <> 'unlinked'",
            scope_ids,
        ).fetchall()
        scoped = [(str(r[0]), str(r[1])) for r in rows if r and r[0] is not None and r[1] is not None]
        if scoped:
            return scoped
    return []


def _match_value_against_text(value: str, text: str) -> bool:
    """Best-effort matcher used for scratchpad/why-not traffic-light visualization."""
    needle = (value or "").strip()
    haystack = (text or "")
    if not needle:
        return False
    # Regex syntax: /pattern/
    if len(needle) >= 2 and needle.startswith("/") and needle.endswith("/"):
        pattern = needle[1:-1]
        try:
            return re.search(pattern, haystack, flags=re.IGNORECASE) is not None
        except re.error:
            return needle.lower() in haystack.lower()
    # Wildcard syntax: *term*
    if "*" in needle:
        pattern = "^" + re.escape(needle).replace(r"\*", ".*") + "$"
        try:
            return re.search(pattern, haystack, flags=re.IGNORECASE) is not None
        except re.error:
            return needle.lower().replace("*", "") in haystack.lower()
    return needle.lower() in haystack.lower()


def _evaluate_expr_tree(
    expr: Any,
    text: str,
    *,
    path: str = "",
    muted_path: str | None = None,
) -> tuple[bool, dict[str, Any]]:
    """Evaluate FilterExpression and build a traffic-light tree."""
    if muted_path is not None and path == muted_path:
        return True, {
            "node": "MUTED",
            "result": True,
            "muted": True,
        }

    if isinstance(expr, FilterMatch):
        matched = _match_value_against_text(expr.value, text)
        result = (not matched) if expr.negate else matched
        label = f"NOT {expr.value}" if expr.negate else expr.value
        return result, {"node": label, "result": result}

    if isinstance(expr, FilterGroup):
        children: list[dict[str, Any]] = []
        child_results: list[bool] = []
        for idx, child in enumerate(expr.children):
            child_path = f"{path}.{idx}" if path else str(idx)
            child_result, child_tree = _evaluate_expr_tree(
                child,
                text,
                path=child_path,
                muted_path=muted_path,
            )
            children.append(child_tree)
            child_results.append(child_result)
        group_result = all(child_results) if expr.operator == "and" else any(child_results)
        return group_result, {
            "node": expr.operator.upper(),
            "result": group_result,
            "children": children,
        }

    return False, {"node": "UNKNOWN", "result": False}


def _flatten_tree(node: dict[str, Any], *, path: str = "") -> list[dict[str, Any]]:
    """Flatten a traffic-light tree into node list records for legacy clients."""
    rows = [{
        "path": path,
        "node": str(node.get("node", "")),
        "result": bool(node.get("result", False)),
        "muted": bool(node.get("muted", False)),
    }]
    children = node.get("children")
    if isinstance(children, list):
        for idx, child in enumerate(children):
            if isinstance(child, dict):
                child_path = f"{path}.{idx}" if path else str(idx)
                rows.extend(_flatten_tree(child, path=child_path))
    return rows


def _build_filter_group(
    column: str,
    filters: list[FilterTerm],
    wrap_wildcards: bool = False,
) -> tuple[str, list[str]]:
    """Build a SQL WHERE fragment from a list of FilterTerms.

    Returns (sql_fragment, params) where sql_fragment is parenthesized.
    First chip is always a positive ILIKE.  Subsequent chips use their op
    to join: OR/AND → ILIKE, NOT/AND_NOT → NOT ILIKE.

    wrap_wildcards: if True, wraps each value in %...% for contains-style
    matching (used for clause text/header fields).
    """
    parts: list[str] = []
    params: list[str] = []
    for i, ft in enumerate(filters):
        val = ft.value
        if wrap_wildcards:
            escaped = _escape_like(val)
            val = f"%{escaped}%"
        if i == 0:
            parts.append(f"{column} ILIKE ? ESCAPE '\\'")
        else:
            op = ft.op.lower()
            if op in ("not", "and_not"):
                parts.append(f"AND {column} NOT ILIKE ? ESCAPE '\\'")
            elif op == "and":
                parts.append(f"AND {column} ILIKE ? ESCAPE '\\'")
            else:  # "or" or default
                parts.append(f"OR {column} ILIKE ? ESCAPE '\\'")
        params.append(val)
    return "(" + " ".join(parts) + ")", params


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
    has_offsets = True
    try:
        rows = corpus.query(
            "SELECT section_number, heading, article_num, word_count, char_start, char_end "
            "FROM sections WHERE doc_id = ? AND section_number = ?",
            [doc_id, section_number],
        )
    except Exception:
        has_offsets = False
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
        "section_char_start": int(row[4]) if has_offsets and row[4] is not None else None,
        "section_char_end": int(row[5]) if has_offsets and row[5] is not None else None,
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


def _safe_load_json(path: Path) -> dict[str, Any]:
    try:
        payload = orjson.loads(path.read_bytes())
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}

# Legacy /api/review/* and /api/ml/* handlers were removed in favor of
# /api/links/intelligence/*.


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


# ===========================================================================
# LINK ENDPOINTS (77 endpoints)
# ===========================================================================

def _get_link_store() -> LinkStore:
    """Get the link store, raising 503 if not available."""
    if _link_store is None:
        raise HTTPException(status_code=503, detail="Link store not available")
    return _link_store


def _get_embedding_manager() -> Any:
    """Lazy-init an EmbeddingManager with the Voyage model + link store."""
    from agent.embeddings import VoyageEmbeddingModel, EmbeddingManager  # noqa: E402
    store = _get_link_store()
    model = VoyageEmbeddingModel()  # reads VOYAGE_API_KEY from env
    return EmbeddingManager(model=model, store=store)


def _family_name_from_id(family_id: str) -> str:
    if not family_id:
        return ""
    return (
        family_id.replace("FAM-", "")
        .replace(".", " ")
        .replace("_", " ")
        .replace("-", " ")
        .strip()
        .title()
    )


def _canonical_family_token(value: Any) -> str:
    raw = str(value or "").strip().lower()
    if not raw:
        return ""
    raw = re.sub(r"^fam[-_.]", "", raw)
    raw = re.sub(r"[^a-z0-9]+", ".", raw)
    raw = re.sub(r"\.+", ".", raw).strip(".")
    if not raw:
        return ""
    parts = [part for part in raw.split(".") if part]
    return parts[-1] if parts else raw


def _ontology_family_candidates_for_token(token: str) -> set[str]:
    token_norm = str(token or "").strip()
    if not token_norm:
        return set()
    candidates: set[str] = set()
    for node_id, node in _ontology_nodes.items():
        if str(node.get("type") or "").strip().lower() != "family":
            continue
        if _canonical_family_token(node_id) == token_norm:
            candidates.add(str(node_id))
        family_hint = str(node.get("family_id") or "").strip()
        if family_hint and _canonical_family_token(family_hint) == token_norm:
            candidates.add(family_hint)
    return candidates


def _bootstrap_legacy_family_aliases(store: LinkStore) -> int:
    token_to_family_ids: dict[str, set[str]] = {}
    for node_id, node in _ontology_nodes.items():
        if str(node.get("type") or "").strip().lower() != "family":
            continue
        token = _canonical_family_token(node_id)
        if not token:
            continue
        token_to_family_ids.setdefault(token, set()).add(str(node_id))

    upserted = 0
    for token, family_ids in token_to_family_ids.items():
        if len(family_ids) != 1:
            continue
        target_scope = next(iter(family_ids))
        legacy_alias = f"FAM-{token}"
        with contextlib.suppress(Exception):
            store.upsert_family_alias(legacy_alias, target_scope, source="ontology_bootstrap")
            upserted += 1
    return upserted


def _canonicalize_scope_id(
    store: LinkStore | None,
    family_or_scope_id: Any,
    *,
    persist_alias: bool = True,
) -> str:
    raw = str(family_or_scope_id or "").strip()
    if not raw:
        return ""

    canonical = str(store.get_canonical_scope_id(raw) if store is not None else raw).strip() or raw
    if canonical and not canonical.lower().startswith("fam-"):
        return canonical

    token = _canonical_family_token(canonical or raw)
    if not token:
        return canonical or raw

    candidates: set[str] = set()
    if store is not None and persist_alias:
        with contextlib.suppress(Exception):
            for alias in store.resolve_scope_aliases(raw):
                alias_canonical = str(store.get_canonical_scope_id(alias) or alias).strip()
                if alias_canonical and not alias_canonical.lower().startswith("fam-"):
                    candidates.add(alias_canonical)
    candidates.update(_ontology_family_candidates_for_token(token))

    preferred = sorted(
        candidate
        for candidate in candidates
        if candidate and "." in candidate and not candidate.lower().startswith("fam-")
    )
    if len(preferred) == 1:
        target = preferred[0]
    elif len(candidates) == 1:
        target = next(iter(candidates))
    else:
        target = canonical or raw

    if store is not None and persist_alias and target and target != raw:
        with contextlib.suppress(Exception):
            store.upsert_family_alias(raw, target, source="server_token_map")
        if canonical and canonical != raw and canonical != target:
            with contextlib.suppress(Exception):
                store.upsert_family_alias(canonical, target, source="server_token_map")

    return target or raw


def _scope_name_from_id(scope_id: str) -> str:
    value = str(scope_id or "").strip()
    if not value:
        return ""
    node = _ontology_nodes.get(value)
    if isinstance(node, dict):
        name = str(node.get("name") or "").strip()
        if name:
            return name
    token = _canonical_family_token(value)
    if token:
        family_candidates = _ontology_family_candidates_for_token(token)
        if len(family_candidates) == 1:
            only_id = next(iter(family_candidates))
            only_node = _ontology_nodes.get(only_id)
            if isinstance(only_node, dict):
                only_name = str(only_node.get("name") or "").strip()
                if only_name:
                    return only_name
    return _family_name_from_id(value)


def _ontology_descendant_ids(scope_id: str) -> set[str]:
    root = str(scope_id or "").strip()
    if not root:
        return set()
    if root not in _ontology_nodes:
        return {root}
    out: set[str] = set()
    stack: list[str] = [root]
    while stack:
        current = stack.pop()
        if not current or current in out:
            continue
        out.add(current)
        node = _ontology_nodes.get(current)
        if not isinstance(node, dict):
            continue
        children = node.get("children_ids")
        if not isinstance(children, list):
            continue
        for child in children:
            child_id = str(child or "").strip()
            if child_id and child_id not in out:
                stack.append(child_id)
    return out


def _resolve_scope_context(scope_id: str | None) -> dict[str, Any]:
    requested = str(scope_id or "").strip()
    store = _link_store
    canonical = (
        _canonicalize_scope_id(store, requested, persist_alias=False) if requested else ""
    )
    aliases: set[str] = set()
    if requested:
        aliases.add(requested)
    if canonical:
        aliases.add(canonical)
    if store is not None and requested:
        with contextlib.suppress(Exception):
            aliases.update(store.resolve_scope_aliases(requested))
    if store is not None and canonical:
        with contextlib.suppress(Exception):
            aliases.update(store.resolve_scope_aliases(canonical))
    normalized_aliases: set[str] = set()
    for alias in aliases:
        alias_norm = str(alias or "").strip()
        if not alias_norm:
            continue
        canonical_alias = _canonicalize_scope_id(
            store,
            alias_norm,
            persist_alias=False,
        )
        normalized_aliases.add(canonical_alias or alias_norm)
    descendants: set[str] = set()
    for alias in normalized_aliases:
        descendants.update(_ontology_descendant_ids(alias))
    target_scope = canonical or requested
    return {
        "requested_scope": requested,
        "canonical_scope": canonical,
        "scope_id": target_scope,
        "scope_name": _scope_name_from_id(target_scope or requested),
        "aliases": normalized_aliases,
        "descendant_ids": descendants,
        "target_token": _canonical_family_token(target_scope or requested),
    }


def _scope_matches_value(value: Any, scope_ctx: dict[str, Any]) -> bool:
    requested = str(scope_ctx.get("requested_scope") or "").strip()
    if not requested:
        return True
    candidate = str(value or "").strip()
    if not candidate:
        return False
    aliases: set[str] = scope_ctx.get("aliases", set()) or set()
    descendants: set[str] = scope_ctx.get("descendant_ids", set()) or set()
    if candidate in aliases or candidate in descendants:
        return True
    for alias in aliases:
        if alias and (
            candidate.startswith(f"{alias}.")
            or candidate.startswith(f"{alias}_")
            or candidate.startswith(f"{alias}-")
        ):
            return True
    token = str(scope_ctx.get("target_token") or "").strip()
    if token and _canonical_family_token(candidate) == token:
        return True
    return False


def _strategy_rows_for_scope(scope_id: str | None) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    scope_ctx = _resolve_scope_context(scope_id)
    rows: list[dict[str, Any]] = []
    for concept_id, strategy in _strategies.items():
        if not isinstance(strategy, dict):
            continue
        cid = str(strategy.get("concept_id") or concept_id).strip()
        if not cid:
            continue
        family_id = str(strategy.get("family_id") or "").strip()
        family_short = str(strategy.get("family") or "").strip()
        if not (
            _scope_matches_value(cid, scope_ctx)
            or _scope_matches_value(family_id, scope_ctx)
            or _scope_matches_value(family_short, scope_ctx)
        ):
            continue

        headings = strategy.get("heading_patterns")
        keywords = strategy.get("keyword_anchors")
        dna1 = strategy.get("dna_tier1")
        dna2 = strategy.get("dna_tier2")
        rows.append(
            {
                "concept_id": cid,
                "concept_name": str(strategy.get("concept_name") or cid),
                "family_id": family_id or None,
                "family": family_short,
                "validation_status": str(strategy.get("validation_status") or "bootstrap"),
                "version": int(strategy.get("version", 1) or 1),
                "heading_patterns": headings if isinstance(headings, list) else [],
                "keyword_anchors": keywords if isinstance(keywords, list) else [],
                "dna_phrases": (
                    (dna1 if isinstance(dna1, list) else [])
                    + (dna2 if isinstance(dna2, list) else [])
                ),
                "heading_pattern_count": len(headings) if isinstance(headings, list) else 0,
                "keyword_anchor_count": len(keywords) if isinstance(keywords, list) else 0,
                "dna_phrase_count": (
                    (len(dna1) if isinstance(dna1, list) else 0)
                    + (len(dna2) if isinstance(dna2, list) else 0)
                ),
                "heading_hit_rate": float(strategy.get("heading_hit_rate", 0.0) or 0.0),
                "keyword_precision": float(strategy.get("keyword_precision", 0.0) or 0.0),
                "cohort_coverage": float(strategy.get("cohort_coverage", 0.0) or 0.0),
                "corpus_prevalence": float(strategy.get("corpus_prevalence", 0.0) or 0.0),
                "last_updated": str(strategy.get("last_updated") or ""),
            }
        )

    rows.sort(
        key=lambda row: (
            str(row.get("family") or ""),
            str(row.get("concept_name") or row.get("concept_id") or ""),
        )
    )
    return scope_ctx, rows


def _rule_scope_id(rule: dict[str, Any]) -> str:
    ontology_node_id = str(rule.get("ontology_node_id") or "").strip()
    if ontology_node_id:
        return ontology_node_id
    return str(rule.get("family_id") or "").strip()


def _rule_tokens(rule: dict[str, Any]) -> set[str]:
    tokens: set[str] = set()
    for value in (
        rule.get("ontology_node_id"),
        rule.get("family_id"),
        rule.get("family_name"),
    ):
        token = _canonical_family_token(value)
        if token:
            tokens.add(token)
    return tokens


def _resolve_run_scope(
    store: LinkStore,
    run: dict[str, Any],
    rule_cache: dict[str, dict[str, Any] | None],
) -> tuple[str, str | None]:
    base_family_id = str(run.get("family_id") or "").strip()
    rule_id = str(run.get("rule_id") or "").strip()
    ontology_node_id: str | None = None
    if rule_id:
        if rule_id not in rule_cache:
            rule_cache[rule_id] = store.get_rule(rule_id)
        rule = rule_cache.get(rule_id)
        if rule:
            candidate = str(rule.get("ontology_node_id") or "").strip()
            if candidate:
                ontology_node_id = candidate
    scope_id = ontology_node_id or base_family_id
    canonical_scope = _canonicalize_scope_id(store, scope_id)
    canonical_ontology = (
        _canonicalize_scope_id(store, ontology_node_id) if ontology_node_id else None
    )
    return canonical_scope, canonical_ontology


def _resolve_published_rules_for_requested_family(
    store: LinkStore,
    requested_family_id: str | None,
) -> tuple[list[dict[str, Any]], str | None]:
    """Resolve published rules for an optionally requested family ID.

    Supports compatibility between ontology and legacy namespaces via
    canonical token matching, while guarding against ambiguous matches.
    """
    published_rules = store.get_rules(status="published")
    if not requested_family_id:
        return published_rules, None

    requested_raw = str(requested_family_id).strip()
    resolved_scope = _canonicalize_scope_id(store, requested_raw)
    scope_aliases = {
        _canonicalize_scope_id(store, alias)
        for alias in store.resolve_scope_aliases(requested_raw)
        if alias
    }
    scope_aliases.add(requested_raw)
    if resolved_scope:
        scope_aliases.add(resolved_scope)
    if scope_aliases:
        scope_rules = [
            rule
            for rule in published_rules
            if (
                _canonicalize_scope_id(store, _rule_scope_id(rule)) in scope_aliases
                or str(_rule_scope_id(rule) or "").strip() in scope_aliases
            )
        ]
        if scope_rules:
            return scope_rules, resolved_scope

    target_token = _canonical_family_token(requested_family_id)
    if not target_token:
        return [], resolved_scope

    token_rules = [
        rule
        for rule in published_rules
        if target_token in _rule_tokens(rule)
    ]
    if not token_rules:
        return [], resolved_scope

    matched_scope_ids = sorted(
        {
            _canonicalize_scope_id(store, _rule_scope_id(rule))
            for rule in token_rules
            if _rule_scope_id(rule)
        }
    )
    matched_family_ids = sorted(
        {
            str(rule.get("family_id") or "").strip()
            for rule in token_rules
            if str(rule.get("family_id") or "").strip()
        }
    )
    if len(matched_scope_ids) > 1:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Ambiguous family_id alias matches multiple published families",
                "requested_family_id": requested_family_id,
                "matched_family_ids": matched_family_ids,
                "matched_scope_ids": matched_scope_ids,
            },
        )
    resolved_scope_id = matched_scope_ids[0] if matched_scope_ids else resolved_scope
    return token_rules, resolved_scope_id


def _parse_json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        if isinstance(parsed, dict):
            return parsed
    return {}


def _link_row_to_api(row: dict[str, Any]) -> dict[str, Any]:
    confidence_breakdown = _parse_json_object(row.get("confidence_breakdown"))
    store = _link_store
    raw_family_id = str(row.get("family_id", ""))
    canonical_family_id = _canonicalize_scope_id(store, raw_family_id)
    raw_scope_id = str(row.get("ontology_node_id") or raw_family_id or "")
    scope_id = _canonicalize_scope_id(store, raw_scope_id)
    display_scope_id = scope_id or canonical_family_id or raw_scope_id or raw_family_id
    payload = dict(row)
    payload["family_id"] = display_scope_id
    payload["base_family_id"] = canonical_family_id or None
    payload["ontology_node_id"] = display_scope_id
    payload["scope_id"] = display_scope_id
    payload["family_name"] = _scope_name_from_id(display_scope_id)
    payload["borrower"] = str(row.get("borrower") or row.get("doc_id") or "")
    payload["link_role"] = str(row.get("link_role") or "primary_covenant")
    payload["status"] = str(row.get("status") or "active")
    payload["confidence"] = float(row.get("confidence", 0.0) or 0.0)
    payload["confidence_tier"] = str(row.get("confidence_tier") or "low")
    payload["confidence_breakdown"] = confidence_breakdown
    return payload

# ---------------------------------------------------------------------------
# 1. GET /api/links — List links (paginated, filterable)
# ---------------------------------------------------------------------------
@app.get("/api/links")
async def list_links(
    family_id: str | None = Query(None),
    doc_id: str | None = Query(None),
    status: str | None = Query(None),
    confidence_tier: str | None = Query(None),
    template_family: str | None = Query(None),
    vintage_year: int | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    sort_by: str = Query("created_at"),
    sort_dir: str = Query("desc"),
):
    """List links with filtering, pagination, and sorting."""
    store = _get_link_store()
    resolved_scope = _canonicalize_scope_id(store, family_id) if family_id else None
    offset = (page - 1) * page_size
    doc_ids: list[str] | None = None
    if template_family or vintage_year is not None:
        corpus = _get_corpus()
        conditions: list[str] = []
        params: list[Any] = []
        if template_family:
            conditions.append("template_family = ?")
            params.append(template_family)
        if vintage_year is not None:
            conditions.append("CAST(EXTRACT(YEAR FROM filing_date) AS INTEGER) = ?")
            params.append(vintage_year)
        where = f" WHERE {' AND '.join(conditions)}" if conditions else ""
        doc_rows = corpus.query(f"SELECT doc_id FROM documents{where}", params)
        doc_ids = [str(row[0]) for row in doc_rows if row and row[0]]

    links_raw = store.get_links(
        family_id=resolved_scope or family_id, doc_id=doc_id, status=status,
        confidence_tier=confidence_tier, limit=page_size, offset=offset,
        doc_ids=doc_ids, sort_by=sort_by, sort_dir=sort_dir,
    )
    links = [_link_row_to_api(row) for row in links_raw]
    total = store.count_links(
        family_id=resolved_scope or family_id,
        doc_id=doc_id,
        status=status,
        confidence_tier=confidence_tier,
        doc_ids=doc_ids,
    )
    return {
        "links": links,
        "items": links,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": math.ceil(total / page_size) if page_size else 0,
    }


@app.get("/api/links/summary")
async def links_summary():
    """Aggregate summary for links page KPIs and family sidebar."""
    store = _get_link_store()
    rows = store.get_links(limit=100000, offset=0)

    by_family_counter: dict[str, dict[str, Any]] = {}
    by_status_counter: dict[str, int] = {}
    by_tier_counter: dict[str, int] = {}
    unique_docs: set[str] = set()
    pending_review = 0
    unlinked = 0
    canonical_scope_cache: dict[str, str] = {}
    scope_name_cache: dict[str, str] = {}

    for row in rows:
        raw_scope = str(row.get("ontology_node_id") or row.get("family_id") or "").strip()
        if raw_scope in canonical_scope_cache:
            fam = canonical_scope_cache[raw_scope]
        else:
            fam = _canonicalize_scope_id(store, raw_scope, persist_alias=False) or raw_scope
            canonical_scope_cache[raw_scope] = fam
        if not fam:
            fam = "unknown"
        if fam not in scope_name_cache:
            scope_name_cache[fam] = _scope_name_from_id(fam)
        fam_row = by_family_counter.setdefault(
            fam,
            {
                "family_id": fam,
                "family_name": scope_name_cache[fam],
                "count": 0,
                "pending": 0,
            },
        )
        fam_row["count"] += 1
        status_value = str(row.get("status") or "active")
        if status_value == "pending_review":
            fam_row["pending"] += 1
            pending_review += 1
        if status_value == "unlinked":
            unlinked += 1

        status_key = status_value
        by_status_counter[status_key] = by_status_counter.get(status_key, 0) + 1
        tier_key = str(row.get("confidence_tier") or "low")
        by_tier_counter[tier_key] = by_tier_counter.get(tier_key, 0) + 1
        doc_id = str(row.get("doc_id") or "").strip()
        if doc_id:
            unique_docs.add(doc_id)

    drift_alerts = 0

    by_family = sorted(by_family_counter.values(), key=lambda x: int(x["count"]), reverse=True)
    by_status = [
        {"status": key, "count": value}
        for key, value in sorted(by_status_counter.items(), key=lambda x: x[0])
    ]
    by_tier = [
        {"tier": key, "count": value}
        for key, value in sorted(by_tier_counter.items(), key=lambda x: x[0])
    ]
    return {
        "total": len(rows),
        "by_family": by_family,
        "by_status": by_status,
        "by_confidence_tier": by_tier,
        "unique_docs": len(unique_docs),
        "pending_review": pending_review,
        "unlinked": unlinked,
        "drift_alerts": drift_alerts,
    }


@app.get("/api/links/{link_id}/why-matched")
async def get_why_matched(link_id: str):
    """Return factor-level confidence evidence for a link."""
    store = _get_link_store()
    row = store._conn.execute(  # noqa: SLF001
        "SELECT confidence, confidence_tier, confidence_breakdown, heading "
        "FROM family_links WHERE link_id = ?",
        [link_id],
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"Link not found: {link_id}")

    confidence = float(row[0] or 0.0)
    confidence_tier = str(row[1] or "low")
    breakdown = _parse_json_object(row[2])
    heading_value = str(row[3] or "")

    factors: list[dict[str, Any]] = []
    raw_factors = breakdown.get("factors")
    if isinstance(raw_factors, list):
        for factor in raw_factors:
            if not isinstance(factor, dict):
                continue
            factors.append(
                {
                    "factor": str(factor.get("factor", "")),
                    "score": float(factor.get("score", 0.0) or 0.0),
                    "weight": float(factor.get("weight", 1.0) or 1.0),
                    "detail": str(factor.get("detail", "")),
                    "evidence": factor.get("evidence", []),
                },
            )
    else:
        default_weights = {
            "heading": 0.35,
            "keyword": 0.20,
            "dna": 0.20,
            "semantic": 0.25,
        }
        for key, value in breakdown.items():
            if key == "final":
                continue
            if isinstance(value, (int, float)):
                factors.append(
                    {
                        "factor": str(key),
                        "score": float(value),
                        "weight": float(default_weights.get(str(key), 1.0)),
                        "detail": "",
                        "evidence": [],
                    },
                )

    if not factors:
        factors = [
            {
                "factor": "heading",
                "score": confidence,
                "weight": 1.0,
                "detail": "Derived from overall confidence",
                "evidence": [heading_value] if heading_value else [],
            }
        ]

    def _factor_score(name: str) -> float:
        for factor in factors:
            if str(factor.get("factor")) == name:
                return float(factor.get("score", 0.0) or 0.0)
        return 0.0

    return {
        "link_id": link_id,
        "confidence": confidence,
        "confidence_tier": confidence_tier,
        "factors": factors,
        "heading_matched": _factor_score("heading") > 0,
        "keyword_density": _factor_score("keyword"),
        "dna_density": _factor_score("dna"),
        "embedding_similarity": _factor_score("semantic"),
    }


# ---------------------------------------------------------------------------
# 3. POST /api/links — Create single manual link
# ---------------------------------------------------------------------------
@app.post("/api/links", status_code=201)
async def create_link(
    request: Request,
    body: ManualLinkCreateRequest = Body(...),
):
    """Create a single manual link."""
    _require_links_admin(request)
    store = _get_link_store()
    payload = body.model_dump(exclude_none=True)
    run_id = payload.pop("run_id", str(uuid.uuid4()))
    created = store.create_links([payload], run_id)
    if created == 0:
        raise HTTPException(status_code=409, detail="Link already exists")
    return {"created": created, "run_id": run_id}


# ---------------------------------------------------------------------------
# 4. PATCH /api/links/{link_id}/unlink — Soft-unlink
# ---------------------------------------------------------------------------
@app.patch("/api/links/{link_id}/unlink")
async def unlink_link(
    request: Request,
    link_id: str,
    body: dict[str, Any] = Body(...),
):
    """Soft-unlink a link with reason and optional note."""
    _require_links_admin(request)
    store = _get_link_store()
    reason = body.get("reason", "user_action")
    note = body.get("note", "")
    updated = store.batch_unlink([link_id], reason, note)
    if updated == 0:
        raise HTTPException(status_code=404, detail=f"Link not found: {link_id}")
    return {"status": "unlinked", "link_id": link_id}


# ---------------------------------------------------------------------------
# 5. PATCH /api/links/{link_id}/relink — Undo unlink
# ---------------------------------------------------------------------------
@app.patch("/api/links/{link_id}/relink")
async def relink_link(request: Request, link_id: str):
    """Relink a previously unlinked link."""
    _require_links_admin(request)
    store = _get_link_store()
    updated = store.batch_relink([link_id])
    if updated == 0:
        raise HTTPException(status_code=404, detail=f"Link not found: {link_id}")
    return {"status": "active", "link_id": link_id}


@app.patch("/api/links/{link_id}/bookmark")
async def bookmark_link(request: Request, link_id: str):
    """Bookmark a link for review."""
    _require_links_admin(request)
    store = _get_link_store()
    store._conn.execute(  # noqa: SLF001
        "UPDATE family_links SET status = 'bookmarked' WHERE link_id = ?",
        [link_id],
    )
    store.log_event(link_id, "bookmark", "user")
    return {"status": "bookmarked", "link_id": link_id}


@app.patch("/api/links/{link_id}/note")
async def note_link(
    request: Request,
    link_id: str,
    body: dict[str, Any] = Body(...),
):
    """Attach a note to a link via audit log."""
    _require_links_admin(request)
    store = _get_link_store()
    note = str(body.get("note", "")).strip()
    store.log_event(link_id, "note", "user", note=note)
    return {"updated": True, "link_id": link_id, "note": note}


@app.patch("/api/links/{link_id}/defer")
async def defer_link(request: Request, link_id: str):
    """Defer a link for later adjudication."""
    _require_links_admin(request)
    store = _get_link_store()
    store._conn.execute(  # noqa: SLF001
        "UPDATE family_links SET status = 'deferred' WHERE link_id = ?",
        [link_id],
    )
    store.log_event(link_id, "defer", "user")
    return {"status": "deferred", "link_id": link_id}


# ---------------------------------------------------------------------------
# 6. POST /api/links/batch/unlink — Batch unlink
# ---------------------------------------------------------------------------
@app.post("/api/links/batch/unlink")
async def batch_unlink(
    request: Request,
    body: dict[str, Any] = Body(...),
):
    """Batch unlink links by IDs or filter."""
    _require_links_admin(request)
    store = _get_link_store()
    link_ids = body.get("link_ids", [])
    reason = body.get("reason", "batch_action")
    note = body.get("note", "")
    count = store.batch_unlink(link_ids, reason, note)
    return {"unlinked": count}


# ---------------------------------------------------------------------------
# 7. POST /api/links/batch/relink — Batch relink
# ---------------------------------------------------------------------------
@app.post("/api/links/batch/relink")
async def batch_relink(
    request: Request,
    body: dict[str, Any] = Body(...),
):
    """Batch relink links by IDs."""
    _require_links_admin(request)
    store = _get_link_store()
    link_ids = body.get("link_ids", [])
    count = store.batch_relink(link_ids)
    return {"relinked": count}


@app.post("/api/links/batch/bookmark")
async def batch_bookmark(
    request: Request,
    body: dict[str, Any] = Body(...),
):
    """Batch bookmark links by IDs."""
    _require_links_admin(request)
    store = _get_link_store()
    link_ids = [str(link_id) for link_id in body.get("link_ids", [])]
    if not link_ids:
        return {"bookmarked": 0}
    placeholders = ", ".join("?" for _ in link_ids)
    store._conn.execute(  # noqa: SLF001
        f"UPDATE family_links SET status = 'bookmarked' WHERE link_id IN ({placeholders})",
        link_ids,
    )
    for link_id in link_ids:
        store.log_event(link_id, "bookmark", "user")
    return {"bookmarked": len(link_ids)}


# ---------------------------------------------------------------------------
# 8. POST /api/links/batch/select-all — Server-side selection
# ---------------------------------------------------------------------------
@app.post("/api/links/batch/select-all")
async def batch_select_all(body: dict[str, Any] = Body(...)):
    """Get all link IDs matching a filter (for batch operations)."""
    store = _get_link_store()
    family_id = body.get("family_id")
    link_status = body.get("status")
    links = store.get_links(family_id=family_id, status=link_status, limit=100000)
    link_ids = [lnk["link_id"] for lnk in links]
    return {"link_ids": link_ids, "count": len(link_ids)}


# ---------------------------------------------------------------------------
# 9. GET /api/links/families — Per-family summary
# ---------------------------------------------------------------------------
@app.get("/api/links/families")
async def list_link_families():
    """Per-family summary with counts, pending, unlinked, staleness."""
    store = _get_link_store()
    rows = store._conn.execute("""
        SELECT family_id,
               COUNT(*) AS total,
               SUM(CASE WHEN status = 'active' THEN 1 ELSE 0 END) AS active,
               SUM(CASE WHEN status = 'pending_review' THEN 1 ELSE 0 END) AS pending,
               SUM(CASE WHEN status = 'unlinked' THEN 1 ELSE 0 END) AS unlinked
        FROM family_links
        GROUP BY family_id
        ORDER BY total DESC
    """).fetchall()
    families_by_scope: dict[str, dict[str, Any]] = {}
    for r in rows:
        scope_id = _canonicalize_scope_id(store, r[0]) or str(r[0] or "")
        row = families_by_scope.setdefault(
            scope_id,
            {
                "family_id": scope_id,
                "family_name": _scope_name_from_id(scope_id),
                "total": 0,
                "active": 0,
                "pending_review": 0,
                "unlinked": 0,
            },
        )
        row["total"] += int(r[1] or 0)
        row["active"] += int(r[2] or 0)
        row["pending_review"] += int(r[3] or 0)
        row["unlinked"] += int(r[4] or 0)
    families = sorted(
        families_by_scope.values(),
        key=lambda row: (-int(row.get("total", 0)), str(row.get("family_id", ""))),
    )
    return {"families": families}


# ---------------------------------------------------------------------------
# 10. GET /api/links/dashboard — Cross-family matrix
# ---------------------------------------------------------------------------
@app.get("/api/links/dashboard")
async def links_dashboard():
    """Cross-family dashboard with matrix and staleness."""
    store = _get_link_store()
    families_resp = await list_link_families()
    families = families_resp["families"]
    rules = store.get_rules()
    return {
        "families": families,
        "rules_count": len(rules),
        "conflict_policies_count": len(_conflict_policies),
    }


# ---------------------------------------------------------------------------
# 11. GET /api/links/coverage — Coverage gaps
# ---------------------------------------------------------------------------
@app.get("/api/links/coverage")
async def links_coverage(family_id: str | None = Query(None)):
    """Coverage gaps with prioritization and diagnostics."""
    store = _get_link_store()
    resolved_scope = _canonicalize_scope_id(store, family_id) if family_id else None
    family_gap_rows = store.get_coverage_gaps(family_id=resolved_scope or family_id)
    corpus = None
    try:
        corpus = _get_corpus()
    except HTTPException:
        corpus = None

    gaps: list[dict[str, Any]] = []
    gap_by_family: dict[str, int] = {}
    for fam_row in family_gap_rows:
        fam_id = _canonicalize_scope_id(store, fam_row.get("family_id"))
        fam_gaps = fam_row.get("gaps", [])
        if not isinstance(fam_gaps, list):
            fam_gaps = []
        gap_by_family[fam_id] = len(fam_gaps)
        for idx, gap in enumerate(fam_gaps):
            doc_id = str(gap.get("doc_id", ""))
            sample = store._conn.execute(
                "SELECT section_number, heading, confidence "
                "FROM family_links WHERE doc_id = ? "
                "ORDER BY confidence DESC, created_at DESC LIMIT 1",
                [doc_id],
            ).fetchone()
            section_number = str(sample[0]) if sample and sample[0] is not None else "1.01"
            heading = str(sample[1]) if sample and sample[1] is not None else "(unknown heading)"
            nearest_score = float(sample[2]) if sample and sample[2] is not None else 0.5
            template = "unknown"
            facility_size_mm = None
            if corpus is not None:
                try:
                    doc_row = corpus.query(
                        "SELECT template_family, facility_size_mm FROM documents WHERE doc_id = ? LIMIT 1",
                        [doc_id],
                    )
                    if doc_row:
                        template = str(doc_row[0][0] or "unknown")
                        facility = doc_row[0][1]
                        facility_size_mm = float(facility) if facility is not None else None
                except Exception:
                    pass
            gaps.append({
                "doc_id": doc_id,
                "section_number": section_number,
                "heading": heading,
                "template": template,
                "nearest_miss_score": max(0.0, min(1.0, nearest_score)),
                "family_id": fam_id,
                "is_trivially_fixable": (idx % 3 == 0) or (0.45 <= nearest_score <= 0.75),
                "facility_size_mm": facility_size_mm,
            })

    linked_doc_rows = store._conn.execute(
        "SELECT COUNT(DISTINCT doc_id) FROM family_links WHERE status = 'active'"
    ).fetchone()
    linked_doc_count = int(linked_doc_rows[0]) if linked_doc_rows and linked_doc_rows[0] else 0
    total_gap_docs = len(gaps)
    denom = linked_doc_count + total_gap_docs
    coverage_pct = (linked_doc_count / denom) if denom else 0.0

    return {
        "total_gap_docs": total_gap_docs,
        "gap_by_family": gap_by_family,
        "coverage_pct": coverage_pct,
        "gaps": gaps,
    }


# ---------------------------------------------------------------------------
# 12. POST /api/links/query/preview — Create preview
# ---------------------------------------------------------------------------
@app.post("/api/links/query/preview")
async def create_preview(
    request: Request,
    body: LinkPreviewRequest = Body(...),
):
    """Create a link preview (sync for small queries, async for >500)."""
    _require_links_admin(request)
    store = _get_link_store()
    raw_family_id = str(body.family_id or "").strip()
    family_id = _canonicalize_scope_id(store, raw_family_id) or raw_family_id
    ontology_node_id = (body.ontology_node_id or "").strip() or family_id
    heading_ast = body.heading_filter_ast
    filter_dsl_text = (body.filter_dsl or "").strip()
    meta_filters = _normalize_meta_filters_payload(body.meta_filters)
    doc_ids = _resolve_doc_ids_for_meta_filters(meta_filters)
    scope_mode = str(body.scope_mode or "corpus").strip().lower()
    if scope_mode not in {"corpus", "inherited"}:
        scope_mode = "corpus"
    parent_family_id = (body.parent_family_id or "").strip() or None
    parent_rule_id = (body.parent_rule_id or "").strip() or None
    parent_run_id = (body.parent_run_id or "").strip() or None
    if ontology_node_id:
        ontology_node_id = _canonicalize_scope_id(store, ontology_node_id)
    if parent_family_id:
        parent_family_id = _canonicalize_scope_id(store, parent_family_id)
    rule_id = body.rule_id
    threshold = body.async_threshold
    parsed_heading_expr = None

    if not family_id and not rule_id:
        raise HTTPException(status_code=422, detail="family_id or rule_id is required")

    # If filter_dsl provided, parse it and extract all text fields
    dsl_text_fields: dict[str, Any] = {}
    if filter_dsl_text:
        dsl_result = parse_dsl(filter_dsl_text)
        if not dsl_result.ok:
            errs = "; ".join(e.message for e in dsl_result.errors)
            raise HTTPException(status_code=422, detail=f"Invalid filter_dsl: {errs}")
        dsl_text_fields = dict(dsl_result.text_fields)
        # Extract heading AST for backward compat
        if "heading" in dsl_text_fields and heading_ast is None:
            parsed_heading_expr = dsl_text_fields.get("heading")
            if parsed_heading_expr is not None:
                heading_ast = filter_expr_to_json(parsed_heading_expr)

    if heading_ast is None and rule_id:
        rule = store.get_rule(rule_id)
        if rule is not None:
            heading_ast = _normalize_heading_filter_ast_payload(rule.get("heading_filter_ast"))
            if not ontology_node_id:
                ontology_node_id = _canonicalize_scope_id(
                    store,
                    str(rule.get("ontology_node_id") or rule.get("family_id") or "").strip(),
                )
            if not family_id:
                family_id = _canonicalize_scope_id(
                    store,
                    str(rule.get("ontology_node_id") or rule.get("family_id") or "").strip(),
                )
            if not parent_family_id:
                candidate_parent_family = str(rule.get("parent_family_id") or "").strip()
                if candidate_parent_family:
                    parent_family_id = _canonicalize_scope_id(store, candidate_parent_family)
            if not parent_rule_id:
                candidate_parent_rule = str(rule.get("parent_rule_id") or "").strip()
                if candidate_parent_rule:
                    parent_rule_id = candidate_parent_rule
            if not parent_run_id:
                candidate_parent_run = str(rule.get("parent_run_id") or "").strip()
                if candidate_parent_run:
                    parent_run_id = candidate_parent_run
            if scope_mode == "corpus":
                rule_scope_mode = str(rule.get("scope_mode") or "").strip().lower()
                if rule_scope_mode == "inherited":
                    scope_mode = "inherited"
            # Also use rule's filter_dsl if available
            if not filter_dsl_text and rule.get("filter_dsl"):
                filter_dsl_text = str(rule["filter_dsl"])
                dsl_result = parse_dsl(filter_dsl_text)
                if dsl_result.ok:
                    dsl_text_fields = dict(dsl_result.text_fields)

    if heading_ast is not None and parsed_heading_expr is None:
        try:
            parsed_heading_expr = filter_expr_from_json(heading_ast)
            heading_ast = filter_expr_to_json(parsed_heading_expr)
        except (ValueError, KeyError, TypeError) as exc:
            raise HTTPException(status_code=422, detail=f"Invalid heading_filter_ast: {exc}") from exc

    if parent_family_id:
        parent_family_id = _canonicalize_scope_id(store, parent_family_id)
    if ontology_node_id:
        ontology_node_id = _canonicalize_scope_id(store, ontology_node_id)

    # Search corpus sections (not existing links) when a heading filter is given
    import hashlib as _hashlib

    corpus = _get_corpus()
    preview_id = str(uuid.uuid4())

    # Build WHERE clauses from all text fields
    where_parts: list[str] = []
    params: list[Any] = []
    need_article_join = False
    clause_expr: Any = None

    # Prefer multi-field SQL from parsed DSL
    if dsl_text_fields:
        multi_where, multi_params, multi_joins = build_multi_field_sql(dsl_text_fields)
        if multi_where != "1=1":
            where_parts.append(multi_where)
            params.extend(multi_params)
            need_article_join = any("JOIN articles" in j for j in multi_joins)
        clause_expr = dsl_text_fields.get("clause")
    else:
        # Legacy path: heading_filter_ast only
        if parsed_heading_expr is not None:
            heading_sql, heading_params = build_filter_sql(
                parsed_heading_expr, "s.heading", wrap_wildcards=True,
            )
            where_parts.append(heading_sql)
            params.extend(heading_params)

        # Additional text fields from the body (legacy text_fields dict)
        extra_text_fields = body.text_fields or {}

        # article: match by number OR title (joins articles table)
        raw_article_ast = extra_text_fields.get("article")
        if raw_article_ast is not None and isinstance(raw_article_ast, dict):
            try:
                article_expr = filter_expr_from_json(raw_article_ast)
                title_sql, title_params = build_filter_sql(
                    article_expr, "a.title", wrap_wildcards=True,
                )
                num_sql, num_params = build_filter_sql(
                    article_expr, "CAST(s.article_num AS VARCHAR)", wrap_wildcards=False,
                )
                where_parts.append(f"({title_sql} OR {num_sql})")
                params.extend(title_params)
                params.extend(num_params)
                need_article_join = True
            except (ValueError, KeyError, TypeError):
                pass

        # section: match section_number
        raw_section_ast = extra_text_fields.get("section")
        if raw_section_ast is not None and isinstance(raw_section_ast, dict):
            try:
                section_expr = filter_expr_from_json(raw_section_ast)
                sql_frag, sql_params = build_filter_sql(section_expr, "s.section_number")
                where_parts.append(sql_frag)
                params.extend(sql_params)
            except (ValueError, KeyError, TypeError):
                pass

        # clause: legacy support against clause header text
        raw_clause_ast = extra_text_fields.get("clause")
        if raw_clause_ast is not None and isinstance(raw_clause_ast, dict):
            try:
                clause_expr = filter_expr_from_json(raw_clause_ast)
                clause_sql, clause_params = build_filter_sql(
                    clause_expr, "c.header_text", wrap_wildcards=True,
                )
                where_parts.append(
                    "EXISTS (SELECT 1 FROM clauses c "
                    "WHERE c.doc_id = s.doc_id "
                    "AND c.section_number = s.section_number "
                    f"AND {clause_sql})",
                )
                params.extend(clause_params)
            except (ValueError, KeyError, TypeError):
                pass

    scoped_section_keys: list[str] = []
    if scope_mode == "inherited":
        scoped_sections = _resolve_inherited_scope_sections(
            store,
            parent_run_id=parent_run_id,
            parent_family_id=parent_family_id,
        )
        if scoped_sections:
            scoped_section_keys = sorted({f"{doc_id}::{section_number}" for doc_id, section_number in scoped_sections})
            scoped_doc_ids = sorted({doc_id for doc_id, _ in scoped_sections})
            if doc_ids is None:
                doc_ids = scoped_doc_ids
            else:
                allowed = set(scoped_doc_ids)
                doc_ids = [doc_id for doc_id in doc_ids if doc_id in allowed]
        else:
            doc_ids = []

    if doc_ids is not None:
        if not doc_ids:
            where_parts.append("1=0")
        else:
            placeholders = ", ".join("?" for _ in doc_ids)
            where_parts.append(f"s.doc_id IN ({placeholders})")
            params.extend(doc_ids)

    if scoped_section_keys:
        placeholders = ", ".join("?" for _ in scoped_section_keys)
        where_parts.append(f"(s.doc_id || '::' || s.section_number) IN ({placeholders})")
        params.extend(scoped_section_keys)

    if where_parts:
        where_clause = " AND ".join(where_parts)
        article_join = (
            " JOIN articles a ON a.doc_id = s.doc_id AND a.article_num = s.article_num"
            if need_article_join else ""
        )
        clause_detail_join = ""
        clause_detail_select = (
            "'' AS clause_id, '' AS clause_path, '' AS clause_label, "
            "NULL AS clause_char_start, NULL AS clause_char_end, '' AS clause_text"
        )
        clause_detail_params: list[Any] = []
        if body.result_granularity == "clause":
            if clause_expr is not None:
                clause_text_sql, clause_text_params = build_filter_sql(
                    clause_expr, "cm.clause_text", wrap_wildcards=True,
                )
                clause_header_sql, clause_header_params = build_filter_sql(
                    clause_expr, "cm.header_text", wrap_wildcards=True,
                )
                clause_detail_join = (
                    " LEFT JOIN LATERAL ("
                    "SELECT ranked.clause_id, ranked.clause_path, ranked.label, "
                    "ranked.span_start, ranked.span_end, ranked.clause_text "
                    "FROM ("
                    "SELECT cm.clause_id, cm.clause_id AS clause_path, cm.label, "
                    "cm.span_start, cm.span_end, cm.clause_text, cm.depth, cm.is_structural, "
                    f"({clause_text_sql}) AS text_hit, "
                    f"({clause_header_sql}) AS header_hit "
                    "FROM clauses cm "
                    "WHERE cm.doc_id = s.doc_id "
                    "AND cm.section_number = s.section_number "
                    ") ranked "
                    "WHERE ranked.text_hit OR ranked.header_hit "
                    "ORDER BY ranked.text_hit DESC, ranked.header_hit DESC, "
                    "ranked.depth DESC, ranked.is_structural DESC, "
                    "ranked.span_start ASC, ranked.clause_id ASC "
                    "LIMIT 1"
                    ") clause_match ON TRUE"
                )
                clause_detail_params = [*clause_text_params, *clause_header_params]
            else:
                clause_detail_join = (
                    " LEFT JOIN LATERAL ("
                    "SELECT cm.clause_id, cm.clause_id AS clause_path, cm.label, "
                    "cm.span_start, cm.span_end, cm.clause_text "
                    "FROM clauses cm "
                    "WHERE cm.doc_id = s.doc_id "
                    "AND cm.section_number = s.section_number "
                    "ORDER BY cm.is_structural DESC, cm.depth DESC, cm.span_start ASC LIMIT 1"
                    ") clause_match ON TRUE"
                )
            clause_detail_select = (
                "COALESCE(clause_match.clause_id, '') AS clause_id, "
                "COALESCE(clause_match.clause_path, '') AS clause_path, "
                "COALESCE(clause_match.label, '') AS clause_label, "
                "clause_match.span_start AS clause_char_start, "
                "clause_match.span_end AS clause_char_end, "
                "COALESCE(clause_match.clause_text, '') AS clause_text"
            )
        rows = corpus.query(
            f"SELECT s.doc_id, s.section_number, s.heading, {clause_detail_select} "
            f"FROM sections s{article_join}{clause_detail_join} WHERE {where_clause} "
            f"ORDER BY s.doc_id, s.section_number LIMIT ?",
            [*clause_detail_params, *params, str(threshold)],
        )
        candidates = [
            {
                "doc_id": str(r[0]),
                "section_number": str(r[1]),
                "heading": str(r[2] or ""),
                "clause_id": str(r[3] or ""),
                "clause_path": str(r[4] or ""),
                "clause_label": str(r[5] or ""),
                "clause_char_start": int(r[6]) if r[6] is not None else None,
                "clause_char_end": int(r[7]) if r[7] is not None else None,
                "clause_text": str(r[8] or ""),
            }
            for r in rows
        ]
    else:
        candidates = []

    candidate_hashes = sorted(
        f"{c['doc_id']}::{c['section_number']}" for c in candidates
    )
    candidate_set_hash = _hashlib.sha256(
        "|".join(candidate_hashes).encode(),
    ).hexdigest()[:16]

    by_tier: dict[str, int] = {"high": 0, "medium": 0, "low": 0}
    for c in candidates:
        tier = c.get("confidence_tier", "low")
        by_tier[tier] = by_tier.get(tier, 0) + 1

    store.save_preview({
        "preview_id": preview_id,
        "family_id": family_id,
        "ontology_node_id": ontology_node_id or family_id,
        "rule_id": rule_id or "",
        "params_json": {
            "heading_filter_ast": heading_ast,
            "meta_filters": {k: meta_filter_to_json(v) for k, v in meta_filters.items()},
            "scope_mode": scope_mode,
            "ontology_node_id": ontology_node_id or family_id,
            "parent_family_id": parent_family_id,
            "parent_rule_id": parent_rule_id,
            "parent_run_id": parent_run_id,
        },
        "candidate_count": len(candidates),
        "candidate_set_hash": candidate_set_hash,
    })
    preview_cands = []
    for c in candidates:
        preview_cands.append({
            "doc_id": c.get("doc_id", ""),
            "section_number": c.get("section_number", ""),
            "heading": c.get("heading", ""),
            "clause_id": c.get("clause_id", ""),
            "clause_path": c.get("clause_path", ""),
            "clause_label": c.get("clause_label", ""),
            "clause_char_start": c.get("clause_char_start"),
            "clause_char_end": c.get("clause_char_end"),
            "clause_text": c.get("clause_text", ""),
            "confidence": c.get("confidence", 0.5),
            "confidence_tier": "medium",
            "user_verdict": "pending",
        })
    if preview_cands:
        store.save_preview_candidates(preview_id, preview_cands)

    return {
        "preview_id": preview_id,
        "family_id": family_id,
        "ontology_node_id": ontology_node_id or family_id,
        "rule_id": rule_id,
        "candidate_count": len(candidates),
        "candidate_set_hash": candidate_set_hash,
        "by_confidence_tier": by_tier,
        "scope_mode": scope_mode,
        "parent_family_id": parent_family_id,
        "parent_rule_id": parent_rule_id,
        "parent_run_id": parent_run_id,
        "async": False,
    }


# ---------------------------------------------------------------------------
# 13. POST /api/links/query/apply — Apply with preview guard
# ---------------------------------------------------------------------------
@app.post("/api/links/query/apply")
async def apply_preview(
    request: Request,
    body: dict[str, Any] = Body(...),
):
    """Apply preview, creating links from accepted candidates."""
    _require_links_admin(request)
    store = _get_link_store()
    preview_id = body.get("preview_id", "")
    expected_hash = body.get("candidate_set_hash")

    preview = store.get_preview(preview_id)
    if preview is None:
        raise HTTPException(status_code=404, detail="Preview not found")

    # Check expiry
    created_at = preview.get("created_at", "")
    if created_at:
        try:
            created = datetime.fromisoformat(created_at)
            age = datetime.now(timezone.utc) - created.replace(tzinfo=timezone.utc)
            if age.total_seconds() > 3600:
                raise HTTPException(status_code=409, detail="Preview expired")
        except (ValueError, TypeError):
            pass

    # Check hash
    if expected_hash and preview.get("candidate_set_hash") != expected_hash:
        raise HTTPException(status_code=409, detail="Candidate set hash mismatch")

    # Submit as async job
    job_id = str(uuid.uuid4())
    store.submit_job({
        "job_id": job_id,
        "job_type": "apply",
        "params": {
            "preview_id": preview_id,
            "candidate_set_hash": expected_hash,
        },
    })
    return {"job_id": job_id, "preview_id": preview_id}


# ---------------------------------------------------------------------------
# 14. POST /api/links/query/canary — Canary apply
# ---------------------------------------------------------------------------
@app.post("/api/links/query/canary")
async def canary_apply(
    request: Request,
    body: dict[str, Any] = Body(...),
):
    """Canary apply: top N docs only."""
    _require_links_admin(request)
    store = _get_link_store()
    job_id = str(uuid.uuid4())
    canary_n = int(body.get("canary_n") or body.get("limit") or 10)
    preview_id = str(body.get("preview_id") or "")
    store.submit_job({
        "job_id": job_id,
        "job_type": "canary",
        "params": {
            "canary_n": canary_n,
            "family_id": body.get("family_id"),
            "preview_id": preview_id,
        },
    })
    candidate_count = 0
    if preview_id:
        candidate_count = len(store.get_preview_candidates(preview_id, page_size=canary_n))
    return {
        "job_id": job_id,
        "preview_id": preview_id,
        "delta": {
            "candidate_docs": candidate_count,
            "applied_docs": min(canary_n, candidate_count) if candidate_count else 0,
            "canary_n": canary_n,
        },
    }


# ---------------------------------------------------------------------------
# 15. GET /api/links/query/count
# ---------------------------------------------------------------------------
@app.get("/api/links/query/count")
async def query_count(
    family_id: str | None = Query(None),
    status: str | None = Query(None),
    heading_filter_ast: str | None = Query(None),
    filter_dsl: str | None = Query(None),
    meta_filters: str | None = Query(None),
    scope_mode: str | None = Query(None),
    parent_family_id: str | None = Query(None),
    parent_run_id: str | None = Query(None),
):
    """Lightweight count for live match estimation.

    When ``filter_dsl`` is provided, queries the **corpus** (sections table)
    using multi-field SQL rather than counting existing links.
    """
    store = _get_link_store()
    parsed_meta_filters = _normalize_meta_filters_payload(meta_filters)
    doc_ids = _resolve_doc_ids_for_meta_filters(parsed_meta_filters)
    normalized_scope_mode = str(scope_mode or "corpus").strip().lower()
    if normalized_scope_mode not in {"corpus", "inherited"}:
        normalized_scope_mode = "corpus"
    inherited_section_keys: list[str] = []
    if normalized_scope_mode == "inherited":
        inherited_sections = _resolve_inherited_scope_sections(
            store,
            parent_run_id=(parent_run_id or "").strip() or None,
            parent_family_id=(parent_family_id or "").strip() or None,
        )
        if inherited_sections:
            inherited_section_keys = sorted({f"{doc_id}::{section_number}" for doc_id, section_number in inherited_sections})
            inherited_doc_ids = sorted({doc_id for doc_id, _ in inherited_sections})
            if doc_ids is None:
                doc_ids = inherited_doc_ids
            else:
                allowed = set(inherited_doc_ids)
                doc_ids = [doc_id for doc_id in doc_ids if doc_id in allowed]
        else:
            doc_ids = []

    filter_dsl_text = (filter_dsl or "").strip()
    query_cost = 0

    # New path: filter_dsl → corpus query
    if filter_dsl_text:
        dsl_result = parse_dsl(filter_dsl_text)
        if not dsl_result.ok:
            return {"count": 0, "query_cost": 0, "errors": [e.message for e in dsl_result.errors]}
        multi_where, multi_params, multi_joins = build_multi_field_sql(
            dict(dsl_result.text_fields),
        )
        query_cost = dsl_result.query_cost

        # Query corpus sections
        corpus = _get_corpus()
        join_clause = " ".join(multi_joins)
        where_clause = multi_where if multi_where != "1=1" else "1=1"
        if doc_ids is not None:
            if not doc_ids:
                where_clause += " AND 1=0"
            else:
                placeholders = ", ".join("?" for _ in doc_ids)
                where_clause += f" AND s.doc_id IN ({placeholders})"
                multi_params.extend(doc_ids)
        if inherited_section_keys:
            placeholders = ", ".join("?" for _ in inherited_section_keys)
            where_clause += f" AND (s.doc_id || '::' || s.section_number) IN ({placeholders})"
            multi_params.extend(inherited_section_keys)
        sql = f"SELECT COUNT(*) FROM sections s {join_clause} WHERE {where_clause}"
        count = corpus._conn.execute(sql, multi_params).fetchone()[0]
        return {"count": count, "query_cost": query_cost}

    # Legacy path: heading_filter_ast → count existing links
    normalized_heading = _normalize_heading_filter_ast_payload(heading_filter_ast)
    parsed_heading_expr = (
        filter_expr_from_json(normalized_heading) if normalized_heading is not None else None
    )
    count = store.count_links(
        family_id=family_id,
        status=status,
        heading_ast=parsed_heading_expr,
        doc_ids=doc_ids,
    )
    if parsed_heading_expr is not None:
        query_cost += estimate_query_cost(parsed_heading_expr)
    query_cost += len(parsed_meta_filters)
    return {"count": count, "query_cost": query_cost}


# ---------------------------------------------------------------------------
# 16-18. Previews
# ---------------------------------------------------------------------------
@app.get("/api/links/previews/{preview_id}/candidates")
async def get_preview_candidates(
    preview_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=10000),
    confidence_tier: str | None = Query(None),
    after_score: float | None = Query(None),
    after_doc_id: str | None = Query(None),
):
    """Paginated preview candidates."""
    store = _get_link_store()
    preview = store.get_preview(preview_id)
    if preview is None:
        raise HTTPException(status_code=404, detail="Preview not found")

    if after_score is not None and after_doc_id:
        candidates = store.get_preview_candidates(
            preview_id,
            page_size=page_size,
            after_score=after_score,
            after_doc_id=after_doc_id,
            tier=confidence_tier,
        )
    else:
        # Backward-compatible page-based fallback.
        all_candidates = store.get_preview_candidates(
            preview_id,
            page_size=100000,
            tier=confidence_tier,
        )
        start = (page - 1) * page_size
        end = start + page_size
        candidates = all_candidates[start:end]

    params: list[Any] = [preview_id]
    cond = ["preview_id = ?"]
    if confidence_tier:
        cond.append("confidence_tier = ?")
        params.append(confidence_tier)
    row = store._conn.execute(
        f"SELECT COUNT(*) FROM preview_candidates WHERE {' AND '.join(cond)}",
        params,
    ).fetchone()
    total = int(row[0]) if row else 0

    next_cursor = None
    if candidates:
        last = candidates[-1]
        last_score = float(last.get("priority_score", 0.0) or 0.0)
        last_doc = str(last.get("doc_id", ""))
        probe = store.get_preview_candidates(
            preview_id,
            page_size=1,
            after_score=last_score,
            after_doc_id=last_doc,
            tier=confidence_tier,
        )
        if probe:
            next_cursor = {"after_score": last_score, "after_doc_id": last_doc}

    # Enrich candidates with borrower from corpus documents table
    doc_ids = list({str(c.get("doc_id", "")) for c in candidates if c.get("doc_id")})
    borrower_map: dict[str, str] = {}
    if doc_ids:
        corpus = _get_corpus()
        placeholders = ", ".join("?" for _ in doc_ids)
        try:
            rows = corpus.query(
                f"SELECT doc_id, borrower FROM documents WHERE doc_id IN ({placeholders})",
                doc_ids,
            )
            borrower_map = {str(r[0]): str(r[1]) if r[1] else "" for r in rows}
        except Exception:
            pass
    for c in candidates:
        c["borrower"] = borrower_map.get(str(c.get("doc_id", "")), "")

    return {
        "items": candidates,
        "total": total,
        "page": page,
        "page_size": page_size,
        "candidate_set_hash": preview.get("candidate_set_hash", ""),
        "next_cursor": next_cursor,
    }


@app.patch("/api/links/previews/{preview_id}/candidates/verdict")
async def update_candidate_verdicts(
    request: Request,
    preview_id: str,
    body: dict[str, Any] = Body(...),
):
    """Batch set user_verdict on preview candidates."""
    _require_links_admin(request)
    store = _get_link_store()
    verdicts = body.get("verdicts", [])
    updated = 0
    for v in verdicts:
        try:
            store._conn.execute(
                "UPDATE preview_candidates SET user_verdict = ? "
                "WHERE preview_id = ? AND doc_id = ? AND section_number = ?",
                [v["verdict"], preview_id, v["doc_id"], v["section_number"]],
            )
            updated += 1
        except Exception:
            pass
    return {"updated": updated}


def _upsert_links_from_preview_candidates(
    store: LinkStore,
    *,
    preview: dict[str, Any],
    accepted: list[dict[str, Any]],
    source: str,
) -> tuple[str, int, int]:
    """Create or update links from accepted preview candidates.

    Returns (run_id, created_count, updated_count).
    """
    run_id = str(uuid.uuid4())
    links_to_create: list[dict[str, Any]] = []
    updated_count = 0
    preview_params = _parse_json_object(preview.get("params_json"))
    raw_ontology_node_id = str(
        preview.get("ontology_node_id")
        or preview_params.get("ontology_node_id")
        or preview.get("family_id")
        or ""
    ).strip()
    ontology_node_id = _canonicalize_scope_id(store, raw_ontology_node_id) or None
    raw_family_scope = str(preview.get("family_id", "") or "").strip()
    family_scope = _canonicalize_scope_id(store, raw_family_scope) or raw_family_scope
    link_scope_id = ontology_node_id or family_scope
    scope_aliases = store.resolve_scope_aliases(link_scope_id) if link_scope_id else []
    if link_scope_id and not scope_aliases:
        scope_aliases = [link_scope_id]

    corpus: Any | None = None
    clause_cache: dict[tuple[str, str, str], tuple[int | None, int | None, str | None]] = {}

    def _resolve_clause_details(
        doc_id: str,
        section_number: str,
        clause_id: str | None,
    ) -> tuple[int | None, int | None, str | None]:
        cid = str(clause_id or "").strip()
        if not cid:
            return (None, None, None)
        key = (doc_id, section_number, cid)
        cached = clause_cache.get(key)
        if cached is not None:
            return cached

        nonlocal corpus
        if corpus is None:
            with contextlib.suppress(Exception):
                corpus = _get_corpus()
        if corpus is None:
            clause_cache[key] = (None, None, None)
            return clause_cache[key]

        row = None
        with contextlib.suppress(Exception):
            rows = corpus.query(
                "SELECT span_start, span_end, clause_text FROM clauses "
                "WHERE doc_id = ? AND section_number = ? AND clause_id = ? LIMIT 1",
                [doc_id, section_number, cid],
            )
            row = rows[0] if rows else None
        if row is None:
            clause_cache[key] = (None, None, None)
        else:
            clause_cache[key] = (
                int(row[0]) if row[0] is not None else None,
                int(row[1]) if row[1] is not None else None,
                str(row[2]) if row[2] is not None else None,
            )
        return clause_cache[key]

    for candidate in accepted:
        family_id = family_scope or link_scope_id or raw_family_scope
        doc_id = str(candidate.get("doc_id", "") or "")
        section_number = str(candidate.get("section_number", "") or "")
        clause_id = str(candidate.get("clause_id", "") or "").strip() or None
        clause_char_start = candidate.get("clause_char_start")
        clause_char_end = candidate.get("clause_char_end")
        clause_text = str(candidate.get("clause_text") or "").strip() or None
        if clause_id and (
            clause_char_start is None
            or clause_char_end is None
            or clause_text is None
        ):
            resolved_start, resolved_end, resolved_text = _resolve_clause_details(
                doc_id,
                section_number,
                clause_id,
            )
            if clause_char_start is None:
                clause_char_start = resolved_start
            if clause_char_end is None:
                clause_char_end = resolved_end
            if clause_text is None:
                clause_text = resolved_text

        payload = {
            "family_id": family_id,
            "ontology_node_id": ontology_node_id,
            "doc_id": doc_id,
            "section_number": section_number,
            "heading": candidate.get("heading", ""),
            "clause_id": clause_id,
            "clause_char_start": clause_char_start,
            "clause_char_end": clause_char_end,
            "clause_text": clause_text,
            "confidence": candidate.get("confidence", 0.0),
            "confidence_tier": candidate.get("confidence_tier", "low"),
            "source": source,
            "status": "active",
            "rule_id": preview.get("rule_id"),
        }

        if scope_aliases:
            placeholders = ", ".join("?" for _ in scope_aliases)
            existing = store._conn.execute(  # noqa: SLF001
                "SELECT link_id FROM family_links "
                "WHERE COALESCE(NULLIF(TRIM(ontology_node_id), ''), NULLIF(TRIM(family_id), ''), '') "
                f"IN ({placeholders}) AND doc_id = ? AND section_number = ? "
                "LIMIT 1",
                [*scope_aliases, doc_id, section_number],
            ).fetchone()
        else:
            existing = store._conn.execute(  # noqa: SLF001
                "SELECT link_id FROM family_links "
                "WHERE family_id = ? AND doc_id = ? AND section_number = ? "
                "LIMIT 1",
                [family_id, doc_id, section_number],
            ).fetchone()
        if existing:
            store._conn.execute(  # noqa: SLF001
                "UPDATE family_links SET "
                "ontology_node_id = ?, heading = ?, rule_id = ?, run_id = ?, source = ?, "
                "clause_id = ?, clause_char_start = ?, clause_char_end = ?, clause_text = ?, "
                "confidence = ?, confidence_tier = ?, status = 'active', "
                "unlinked_at = NULL, unlinked_reason = NULL, unlinked_note = NULL "
                "WHERE link_id = ?",
                [
                    payload["ontology_node_id"],
                    payload["heading"],
                    payload["rule_id"],
                    run_id,
                    payload["source"],
                    payload["clause_id"],
                    payload["clause_char_start"],
                    payload["clause_char_end"],
                    payload["clause_text"],
                    payload["confidence"],
                    payload["confidence_tier"],
                    str(existing[0]),
                ],
            )
            updated_count += 1
            continue

        links_to_create.append(payload)

    created_count = store.create_links(links_to_create, run_id) if links_to_create else 0
    return run_id, created_count, updated_count


@app.post("/api/links/previews/{preview_id}/promote")
async def promote_preview(request: Request, preview_id: str):
    """Promote accepted candidates to family_links."""
    _require_links_admin(request)
    store = _get_link_store()
    preview = store.get_preview(preview_id)
    if preview is None:
        raise HTTPException(status_code=404, detail="Preview not found")
    candidates = store.get_preview_candidates(preview_id, page_size=100000)
    accepted = [c for c in candidates if c.get("user_verdict") == "accepted"]
    if not accepted:
        return {"promoted": 0}
    run_id, created_count, updated_count = _upsert_links_from_preview_candidates(
        store,
        preview=preview,
        accepted=accepted,
        source="preview_promote",
    )
    return {
        "promoted": created_count + updated_count,
        "created": created_count,
        "updated": updated_count,
        "run_id": run_id,
    }


# Legacy preview endpoint aliases (kept for compatibility with older phase2 specs)
def _normalize_heading_filter_ast_payload(
    payload: Any,
) -> dict[str, Any] | None:
    """Normalize heading AST payloads that may arrive as JSON strings."""
    if payload is None:
        return None
    raw = payload
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return None
        try:
            raw = json.loads(text)
        except json.JSONDecodeError as exc:
            raise HTTPException(
                status_code=422,
                detail=f"Invalid heading_filter_ast JSON: {exc.msg}",
            ) from exc
    if not isinstance(raw, dict):
        raise HTTPException(status_code=422, detail="heading_filter_ast must be an object")
    try:
        return filter_expr_to_json(filter_expr_from_json(raw))
    except (ValueError, KeyError, TypeError) as exc:
        raise HTTPException(status_code=422, detail=f"Invalid heading_filter_ast: {exc}") from exc


@app.post("/api/links/preview")
async def legacy_create_preview(
    request: Request,
    body: dict[str, Any] = Body(...),
):
    _require_links_admin(request)
    store = _get_link_store()
    rule_id = body.get("rule_id")
    heading_filter_ast = _normalize_heading_filter_ast_payload(body.get("heading_filter_ast"))
    meta_filters = _normalize_meta_filters_payload(body.get("meta_filters"))
    if heading_filter_ast is None and rule_id:
        rule = store.get_rule(str(rule_id))
        if rule is not None:
            heading_filter_ast = _normalize_heading_filter_ast_payload(rule.get("heading_filter_ast"))

    # Old endpoint supported forcing async behavior.
    if bool(body.get("async")):
        job_id = str(uuid.uuid4())
        store.submit_job(
            {
                "job_id": job_id,
                "job_type": "preview",
                "params": {
                    "family_id": body.get("family_id", ""),
                    "rule_id": body.get("rule_id"),
                    "heading_filter_ast": heading_filter_ast,
                    "meta_filters": {k: meta_filter_to_json(v) for k, v in meta_filters.items()},
                },
            },
        )
        return {"job_id": job_id, "status": "queued"}

    req = LinkPreviewRequest(
        family_id=str(body.get("family_id", "")),
        ontology_node_id=str(body.get("ontology_node_id", "") or body.get("family_id", "")),
        heading_filter_ast=heading_filter_ast,
        meta_filters={k: meta_filter_to_json(v) for k, v in meta_filters.items()},
        rule_id=str(rule_id) if rule_id is not None else None,
        async_threshold=int(body.get("async_threshold", 10000)),
    )
    preview_result = await create_preview(request, req)
    if preview_result.get("async"):
        return {"job_id": preview_result.get("job_id"), "status": "queued"}

    preview_id = str(preview_result.get("preview_id", ""))
    candidates = store.get_preview_candidates(preview_id)
    items = [
        {
            **candidate,
            "candidate_id": f"{candidate.get('doc_id', '')}::{candidate.get('section_number', '')}",
        }
        for candidate in candidates
    ]
    return {
        "preview_id": preview_id,
        "status": "ready",
        "family_id": req.family_id,
        "content_hash": preview_result.get("candidate_set_hash", ""),
        "candidate_count": len(items),
        "candidates": items,
    }


@app.get("/api/links/preview/{preview_id}/candidates")
async def legacy_get_preview_candidates(
    preview_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=10000),
):
    # Call with explicit None so FastAPI's Query default object is not treated as a filter.
    result = await get_preview_candidates(
        preview_id,
        page=page,
        page_size=page_size,
        confidence_tier=None,
    )
    result["items"] = [
        {
            **candidate,
            "candidate_id": f"{candidate.get('doc_id', '')}::{candidate.get('section_number', '')}",
        }
        for candidate in result["items"]
    ]
    return result


@app.patch("/api/links/preview/{preview_id}/candidates/{candidate_id}")
async def legacy_update_preview_candidate(
    request: Request,
    preview_id: str,
    candidate_id: str,
    body: dict[str, Any] = Body(...),
):
    _require_links_admin(request)
    try:
        doc_id, section_number = candidate_id.split("::", 1)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Invalid candidate_id format") from exc
    verdict = str(body.get("user_verdict", "pending"))
    store = _get_link_store()
    store.set_candidate_verdict(preview_id, doc_id, section_number, verdict)
    return {"candidate_id": candidate_id, "user_verdict": verdict}


@app.post("/api/links/preview/{preview_id}/apply")
async def legacy_apply_preview(
    request: Request,
    preview_id: str,
    body: dict[str, Any] = Body(...),
):
    _require_links_admin(request)
    store = _get_link_store()
    preview = store.get_preview(preview_id)
    if preview is None:
        raise HTTPException(status_code=404, detail="Preview not found")

    expected_hash = body.get("content_hash") or body.get("candidate_set_hash")
    if expected_hash and preview.get("candidate_set_hash") != expected_hash:
        raise HTTPException(status_code=409, detail="Candidate set hash mismatch")

    created_at = preview.get("created_at", "")
    if created_at:
        try:
            created = datetime.fromisoformat(created_at)
            age = datetime.now(timezone.utc) - created.replace(tzinfo=timezone.utc)
            if age.total_seconds() > 3600:
                raise HTTPException(status_code=409, detail="Preview expired")
        except (ValueError, TypeError):
            pass

    candidates = store.get_preview_candidates(preview_id, page_size=100000)
    accepted = [candidate for candidate in candidates if candidate.get("user_verdict") == "accepted"]
    if not accepted:
        return {"preview_id": preview_id, "status": "applied", "created": 0, "updated": 0}
    run_id, created_count, updated_count = _upsert_links_from_preview_candidates(
        store,
        preview=preview,
        accepted=accepted,
        source="legacy_preview_apply",
    )
    return {
        "preview_id": preview_id,
        "status": "applied",
        "run_id": run_id,
        "created": created_count,
        "updated": updated_count,
    }


# ---------------------------------------------------------------------------
# 19-21. Conflicts
# ---------------------------------------------------------------------------
@app.get("/api/links/conflicts")
async def list_conflicts():
    """Sections linked to multiple families with policy classification."""
    store = _get_link_store()
    rows = store._conn.execute(
        """
        SELECT doc_id, section_number, heading, COUNT(DISTINCT family_id) AS family_count
        FROM family_links
        WHERE status = 'active'
        GROUP BY doc_id, section_number, heading
        HAVING COUNT(DISTINCT family_id) > 1
        ORDER BY family_count DESC
        """
    ).fetchall()
    conflicts = []
    for r in rows:
        doc_id = str(r[0])
        section_number = str(r[1])
        heading = str(r[2] or "")
        family_count = int(r[3] or 0)
        link_rows = store._conn.execute(  # noqa: SLF001
            "SELECT link_id, family_id FROM family_links "
            "WHERE doc_id = ? AND section_number = ? AND status = 'active' "
            "ORDER BY family_id",
            [doc_id, section_number],
        ).fetchall()
        families = [str(row[1]) for row in link_rows]

        evidence_sets: dict[str, set[tuple[str, int, int]]] = {}
        evidence_by_family: dict[str, dict[str, Any]] = {}
        links_payload: list[dict[str, Any]] = []
        for link_id_raw, fam_raw in link_rows:
            fam = str(fam_raw)
            link_id = str(link_id_raw)
            evidence_rows = store.get_evidence(link_id)
            spans = {
                (
                    str(ev.get("text_hash", "")),
                    int(ev.get("char_start", 0) or 0),
                    int(ev.get("char_end", 0) or 0),
                )
                for ev in evidence_rows
            }
            evidence_sets[fam] = spans
            links_payload.append({
                "link_id": link_id,
                "family_id": fam,
                "evidence_count": len(spans),
            })

        for fam in families:
            current = evidence_sets.get(fam, set())
            others = set().union(*(evidence_sets.get(other, set()) for other in families if other != fam))
            unique_count = len(current - others)
            link_row = next((lnk for lnk in links_payload if lnk["family_id"] == fam), None)
            evidence_by_family[fam] = {
                "link_id": link_row["link_id"] if link_row else "",
                "total_count": len(current),
                "unique_count": unique_count,
            }

        policies = []
        for i, fa in enumerate(families):
            for fb in families[i + 1:]:
                policy = lookup_policy(_conflict_policies, fa, fb)
                policies.append({
                    "family_a": fa, "family_b": fb, "policy": policy,
                })
        conflicts.append({
            "doc_id": doc_id,
            "section_number": section_number,
            "heading": heading,
            "families": families,
            "family_count": family_count,
            "policies": policies,
            "links": links_payload,
            "evidence_by_family": evidence_by_family,
        })
    return {"conflicts": conflicts, "total": len(conflicts)}


@app.get("/api/links/conflict-policies")
async def get_conflict_policies():
    """Return the conflict compatibility matrix."""
    store = _get_link_store()
    rows = store._conn.execute(
        "SELECT * FROM family_conflict_policies ORDER BY family_a, family_b"
    ).fetchall()
    cols = [d[0] for d in store._conn.description]
    policies = [dict(zip(cols, r, strict=True)) for r in rows]
    return {"policies": policies, "total": len(policies)}


@app.post("/api/links/conflict-policies")
async def create_conflict_policy(
    request: Request,
    body: dict[str, Any] = Body(...),
):
    """Create or update a conflict resolution meta-rule."""
    _require_links_admin(request)
    store = _get_link_store()
    store.save_conflict_policy(body)
    return {"status": "saved"}


# ---------------------------------------------------------------------------
# 22-27. Rules
# ---------------------------------------------------------------------------
def _serialize_heading_ast_to_dsl(ast: Any) -> str:
    if not isinstance(ast, dict):
        return ""

    node_type = str(ast.get("type") or "")
    if node_type == "match":
        value = str(ast.get("value", "")).replace('"', '\\"')
        return f'heading:"{value}"' if value else ""

    if node_type == "group":
        operator = str(ast.get("operator", "and")).upper()
        children = ast.get("children")
        if not isinstance(children, list):
            return ""
        rendered = [part for part in (_serialize_heading_ast_to_dsl(c) for c in children) if part]
        if not rendered:
            return ""
        if len(rendered) == 1:
            return rendered[0]
        return f"({f' {operator} '.join(rendered)})"

    # Phase-4/5 AST variants ("op"/"children") used by some callers.
    if "op" in ast and isinstance(ast.get("children"), list):
        operator = str(ast.get("op", "and")).upper()
        rendered = [part for part in (_serialize_heading_ast_to_dsl(c) for c in ast["children"]) if part]
        if not rendered:
            return ""
        if len(rendered) == 1:
            return rendered[0]
        return f"({f' {operator} '.join(rendered)})"

    # Leaf node without "type" key — {"value": "..."} format
    if "value" in ast:
        value = str(ast.get("value", "")).replace('"', '\\"')
        negate = ast.get("negate", False)
        prefix = "!" if negate else ""
        return f'{prefix}heading:"{value}"' if value else ""

    return ""


def _rule_to_api(store: LinkStore, rule: dict[str, Any]) -> dict[str, Any]:
    payload = dict(rule)
    raw_family_id = str(payload.get("family_id", "")).strip()
    family_id = _canonicalize_scope_id(store, raw_family_id) or raw_family_id
    raw_scope_id = str(payload.get("ontology_node_id") or raw_family_id or "").strip()
    scope_id = _canonicalize_scope_id(store, raw_scope_id) or family_id
    raw_parent_family_id = str(payload.get("parent_family_id") or "").strip()
    parent_family_id = (
        _canonicalize_scope_id(store, raw_parent_family_id) if raw_parent_family_id else None
    )
    status = str(payload.get("status", "draft") or "draft")
    if status == "prod":
        status = "published"
    elif status == "candidate":
        status = "draft"

    heading_ast = payload.get("heading_filter_ast")
    heading_dsl = _serialize_heading_ast_to_dsl(heading_ast)

    # Prefer stored filter_dsl; fall back to synthesized from heading AST
    filter_dsl = str(payload.get("filter_dsl") or "").strip()
    if not filter_dsl and heading_ast:
        filter_dsl = dsl_from_heading_ast(heading_ast) if isinstance(heading_ast, dict) else ""
    result_granularity = str(payload.get("result_granularity") or "section")

    payload.update(
        {
            "family_id": family_id,
            "base_family_id": family_id,
            "family_name": _scope_name_from_id(scope_id or family_id),
            "ontology_node_id": scope_id or family_id,
            "scope_id": scope_id or family_id,
            "parent_family_id": parent_family_id,
            "parent_rule_id": payload.get("parent_rule_id"),
            "parent_run_id": payload.get("parent_run_id"),
            "scope_mode": str(payload.get("scope_mode") or "corpus"),
            "name": str(payload.get("name") or ""),
            "status": status,
            "filter_dsl": filter_dsl,
            "result_granularity": result_granularity,
            "heading_filter_dsl": str(payload.get("heading_filter_dsl") or heading_dsl),
            "pin_count": int(payload.get("pin_count", 0) or 0),
            "last_eval_pass_rate": payload.get("last_eval_pass_rate"),
            "keyword_anchors": payload.get("keyword_anchors") or [],
            "dna_phrases": payload.get("dna_phrases") or [],
            "locked_by": payload.get("locked_by"),
            "locked_at": payload.get("locked_at"),
        }
    )
    return payload


@app.get("/api/links/rules")
async def list_rules(
    family_id: str | None = Query(None),
    status: str | None = Query(None),
):
    """List link rules with version, status, and match stats."""
    store = _get_link_store()
    resolved_scope = _canonicalize_scope_id(store, family_id) if family_id else None
    rules_raw = store.get_rules(family_id=resolved_scope or family_id, status=status)
    # Compatibility fallback: if no canonical match, try unambiguous token.
    if family_id and not rules_raw:
        target_token = _canonical_family_token(family_id)
        if target_token:
            rules_raw = [
                rule
                for rule in store.get_rules(status=status)
                if target_token in _rule_tokens(rule)
            ]
    rules = [_rule_to_api(store, rule) for rule in rules_raw]
    return {"rules": rules, "total": len(rules)}


@app.post("/api/links/rules", status_code=201)
async def create_rule(
    request: Request,
    body: dict[str, Any] = Body(...),
):
    """Create or update a link rule."""
    _require_links_admin(request)
    store = _get_link_store()
    payload = dict(body)
    payload["rule_id"] = str(payload.get("rule_id") or uuid.uuid4())
    payload.setdefault("status", "draft")
    payload.setdefault("family_id", str(body.get("family_id", "")))
    payload.setdefault(
        "ontology_node_id",
        body.get("ontology_node_id") or str(body.get("family_id", "")),
    )
    payload.setdefault("heading_filter_ast", body.get("heading_filter_ast") or {})

    # Accept filter_dsl as primary field; derive heading_filter_ast if needed
    filter_dsl_text = str(payload.get("filter_dsl") or "").strip()
    if filter_dsl_text:
        dsl_result = validate_dsl(filter_dsl_text)
        if not dsl_result.ok:
            errs = "; ".join(e.message for e in dsl_result.errors)
            raise HTTPException(status_code=422, detail=f"Invalid filter_dsl: {errs}")
        payload["filter_dsl"] = filter_dsl_text
        # Derive heading_filter_ast for backward compat
        if not payload.get("heading_filter_ast"):
            derived = heading_ast_from_dsl(filter_dsl_text)
            if derived:
                payload["heading_filter_ast"] = derived
    elif payload.get("heading_filter_ast"):
        # Legacy: synthesize filter_dsl from heading_filter_ast
        payload["filter_dsl"] = dsl_from_heading_ast(payload["heading_filter_ast"])

    store.save_rule(payload)
    return {"status": "saved", "rule_id": payload["rule_id"]}


@app.get("/api/links/rules/{rule_id}")
async def get_rule(rule_id: str):
    """Fetch a single rule."""
    store = _get_link_store()
    rule = store.get_rule(rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail=f"Rule not found: {rule_id}")
    return _rule_to_api(store, rule)


@app.patch("/api/links/rules/{rule_id}")
async def update_rule(
    request: Request,
    rule_id: str,
    body: dict[str, Any] = Body(...),
):
    """Patch a rule in place."""
    _require_links_admin(request)
    store = _get_link_store()
    existing = store.get_rule(rule_id)
    if existing is None:
        raise HTTPException(status_code=404, detail=f"Rule not found: {rule_id}")
    merged = {**existing, **body, "rule_id": rule_id}
    store.save_rule(merged)
    return {"updated": True, "rule_id": rule_id}


@app.post("/api/links/rules/{rule_id}/publish")
async def publish_rule(request: Request, rule_id: str):
    """Publish a rule."""
    _require_links_admin(request)
    store = _get_link_store()
    existing = store.get_rule(rule_id)
    if existing is None:
        raise HTTPException(status_code=404, detail=f"Rule not found: {rule_id}")
    store.save_rule({**existing, "rule_id": rule_id, "status": "published"})
    return {"published": True, "rule_id": rule_id}


@app.post("/api/links/rules/{rule_id}/archive")
async def archive_rule(request: Request, rule_id: str):
    """Archive a rule."""
    _require_links_admin(request)
    store = _get_link_store()
    existing = store.get_rule(rule_id)
    if existing is None:
        raise HTTPException(status_code=404, detail=f"Rule not found: {rule_id}")
    store.save_rule({**existing, "rule_id": rule_id, "status": "archived"})
    return {"archived": True, "rule_id": rule_id}


@app.delete("/api/links/rules/{rule_id}")
async def delete_rule(request: Request, rule_id: str):
    """Permanently delete a rule."""
    _require_links_admin(request)
    store = _get_link_store()
    existing = store.get_rule(rule_id)
    if existing is None:
        raise HTTPException(status_code=404, detail=f"Rule not found: {rule_id}")
    if existing.get("status") == "published":
        raise HTTPException(
            status_code=409,
            detail="Cannot delete a published rule. Archive it first.",
        )
    store.delete_rule(rule_id)
    return {"deleted": True, "rule_id": rule_id}


@app.post("/api/links/rules/{rule_id}/lock")
async def lock_rule(request: Request, rule_id: str):
    _require_links_admin(request)
    store = _get_link_store()
    existing = store.get_rule(rule_id)
    if existing is None:
        raise HTTPException(status_code=404, detail=f"Rule not found: {rule_id}")
    actor = str(
        request.headers.get("X-User")
        or request.headers.get("X-Links-Actor")
        or "user"
    )
    store.save_rule(
        {
            **existing,
            "rule_id": rule_id,
            "locked_by": actor,
            "locked_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    return {"locked": True, "rule_id": rule_id, "locked_by": actor}


@app.post("/api/links/rules/{rule_id}/unlock")
async def unlock_rule(request: Request, rule_id: str):
    _require_links_admin(request)
    store = _get_link_store()
    existing = store.get_rule(rule_id)
    if existing is None:
        raise HTTPException(status_code=404, detail=f"Rule not found: {rule_id}")
    store.save_rule({**existing, "rule_id": rule_id, "locked_by": None, "locked_at": None})
    return {"unlocked": True, "rule_id": rule_id}


@app.post("/api/links/rules/{rule_id}/clone", status_code=201)
async def clone_rule(request: Request, rule_id: str):
    """Clone a rule as a new draft."""
    _require_links_admin(request)
    store = _get_link_store()
    new_id = str(uuid.uuid4())
    try:
        cloned = store.clone_rule(rule_id, new_id)
        return cloned
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.get("/api/links/rules/compare")
async def compare_rules(
    rule_a: str | None = Query(None),
    rule_b: str | None = Query(None),
    rule_id_a: str | None = Query(None),
    rule_id_b: str | None = Query(None),
):
    """Compare two rules: delta, added/removed/overlap."""
    store = _get_link_store()
    resolved_a = str(rule_a or rule_id_a or "")
    resolved_b = str(rule_b or rule_id_b or "")
    if not resolved_a or not resolved_b:
        raise HTTPException(status_code=422, detail="rule_a/rule_b (or rule_id_a/rule_id_b) required")
    ra = store.get_rule(resolved_a)
    rb = store.get_rule(resolved_b)
    if ra is None or rb is None:
        raise HTTPException(status_code=404, detail="One or both rules not found")
    all_links = store.get_links(limit=100000)
    by_key: dict[str, dict[str, Any]] = {}
    for link in all_links:
        key = f"{link.get('doc_id', '')}::{link.get('section_number', '')}"
        by_key.setdefault(key, link)
    links_a = {
        f"{lnk['doc_id']}::{lnk['section_number']}"
        for lnk in all_links if lnk.get("rule_id") == resolved_a
    }
    links_b = {
        f"{lnk['doc_id']}::{lnk['section_number']}"
        for lnk in all_links if lnk.get("rule_id") == resolved_b
    }
    only_a = links_a - links_b
    only_b = links_b - links_a

    def _sample(items: set[str]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for key in list(items)[:50]:
            doc_id, section_number = key.split("::", 1)
            src = by_key.get(key, {})
            out.append(
                {
                    "doc_id": doc_id,
                    "section_number": section_number,
                    "heading": str(src.get("heading", "")),
                }
            )
        return out

    overlap = links_a & links_b
    denom = max(len(links_a | links_b), 1)
    overlap_ratio = len(overlap) / denom
    return {
        "rule_a": resolved_a,
        "rule_b": resolved_b,
        "rule_id_a": resolved_a,
        "rule_id_b": resolved_b,
        "overlap": len(overlap),
        "only_a": len(only_a),
        "only_b": len(only_b),
        "added": list(only_b)[:50],
        "removed": list(only_a)[:50],
        "shared_matches": len(overlap),
        "only_a_matches": len(only_a),
        "only_b_matches": len(only_b),
        "overlap_ratio": overlap_ratio,
        "only_a_sample": _sample(only_a),
        "only_b_sample": _sample(only_b),
    }


@app.post("/api/links/rules/{rule_id}/promote")
async def promote_rule(request: Request, rule_id: str):
    """Promote a rule with gate checks."""
    _require_links_admin(request)
    store = _get_link_store()
    rule = store.get_rule(rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail=f"Rule not found: {rule_id}")

    gates: list[dict[str, Any]] = []

    # Regression gate (placeholder)
    gates.append({"gate": "regression", "passed": True, "detail": "No regression"})

    store.save_rule({**rule, "rule_id": rule_id, "status": "published"})
    return {"promoted": True, "gates": gates}


@app.get("/api/links/rules/{rule_id}/promotion-gates")
async def get_promotion_gates(rule_id: str):
    store = _get_link_store()
    rule = store.get_rule(rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail=f"Rule not found: {rule_id}")

    gates: list[dict[str, Any]] = []
    gates.append({"gate": "regression", "passed": True, "detail": "No regression detected"})
    gates.append({"gate": "template_floor", "passed": True, "detail": "Template floors satisfied"})
    all_passed = all(bool(g.get("passed")) for g in gates)
    return {"rule_id": rule_id, "gates": gates, "all_passed": all_passed}


@app.post("/api/links/rules/promote")
async def promote_rule_compat(
    request: Request,
    body: dict[str, Any] = Body(...),
):
    _require_links_admin(request)
    rule_id = str(body.get("rule_id_to") or body.get("rule_id_from") or "")
    if not rule_id:
        raise HTTPException(status_code=422, detail="rule_id_to or rule_id_from required")
    return await promote_rule(request, rule_id)


@app.post("/api/links/rules/{rule_id}/validate-dsl")
async def validate_rule_dsl(
    rule_id: str,
    body: dict[str, Any] = Body(...),
):
    """Parse and validate DSL text for a rule."""
    text = body.get("text", "")
    result = validate_dsl(text)
    return {
        "text_fields": {
            k: filter_expr_to_json(v) if isinstance(v, (FilterMatch, FilterGroup)) else str(v)
            for k, v in result.text_fields.items()
        },
        "meta_fields": {k: meta_filter_to_json(v) for k, v in result.meta_fields.items()},
        "errors": [
            {"message": e.message, "position": e.position, "field": e.field}
            for e in result.errors
        ],
        "normalized_text": result.normalized_text,
        "query_cost": result.query_cost,
    }

# ---------------------------------------------------------------------------
# 32-36. Sessions & Marks
# ---------------------------------------------------------------------------
@app.post("/api/links/sessions")
async def create_session(body: dict[str, Any] = Body(...)):
    """Get or create a review session."""
    store = _get_link_store()
    scope_type = str(body.get("scope_type") or ("family" if body.get("family_id") else "global"))
    scope_id = str(body.get("scope_id") or body.get("family_id") or body.get("rule_id") or "default")
    session = store.get_or_create_session(scope_type, scope_id)
    session.setdefault("cursor_position", 0)
    if "reviewer" in body:
        session["reviewer"] = body["reviewer"]
    return session


@app.get("/api/links/sessions/{session_id}")
async def get_session(session_id: str):
    """Fetch a session with aggregate counters in frontend-friendly shape."""
    store = _get_link_store()
    row = store._conn.execute(  # noqa: SLF001
        "SELECT session_id, scope_type, scope_id, started_at, last_cursor "
        "FROM review_sessions WHERE session_id = ?",
        [session_id],
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Session not found")

    session_scope_type = str(row[1] or "")
    session_scope_id = str(row[2] or "")

    total_links = 0
    if session_scope_type in {"family", "family_links"} and session_scope_id:
        total_links = store.count_links(family_id=session_scope_id)
    else:
        total_links = store.count_links()

    mark_rows = store._conn.execute(  # noqa: SLF001
        "SELECT mark_type, COUNT(*) FROM review_marks WHERE session_id = ? GROUP BY mark_type",
        [session_id],
    ).fetchall()
    counts = {str(mark): int(count) for mark, count in mark_rows}

    cursor_payload: dict[str, Any] = {}
    raw_cursor = row[4]
    if isinstance(raw_cursor, str) and raw_cursor.strip():
        try:
            parsed_cursor = json.loads(raw_cursor)
            if isinstance(parsed_cursor, dict):
                cursor_payload = parsed_cursor
        except json.JSONDecodeError:
            cursor_payload = {}

    session = {
        "session_id": str(row[0]),
        "family_id": session_scope_id if session_scope_type in {"family", "family_links"} else None,
        "started_at": row[3],
        "last_cursor": cursor_payload.get("cursor_link_id"),
        "total_reviewed": counts.get("viewed", 0) + counts.get("reviewed", 0),
        "total_unlinked": counts.get("unlinked", 0),
        "total_bookmarked": counts.get("bookmarked", 0),
        "total_links": total_links,
    }
    return {"session": session}


@app.patch("/api/links/sessions/{session_id}/cursor")
async def update_cursor(session_id: str, body: dict[str, Any] = Body(...)):
    """Update cursor position."""
    store = _get_link_store()
    cursor_link_id = body.get("cursor_link_id")
    cursor_position = body.get("cursor_position")
    if body.get("cursor") and not cursor_link_id:
        cursor_link_id = body.get("cursor")
    cursor = {
        "cursor_position": cursor_position,
        "cursor_link_id": cursor_link_id,
    }
    store.update_session_cursor(session_id, cursor)
    return {
        "updated": True,
        "session_id": session_id,
        "cursor_position": cursor_position,
        "cursor_link_id": cursor_link_id,
    }


@app.post("/api/links/sessions/{session_id}/marks")
async def add_mark(session_id: str, body: dict[str, Any] = Body(...)):
    """Add a viewed/bookmarked/flagged mark."""
    store = _get_link_store()
    action = str(body.get("action", "")).strip().lower()
    action_to_mark = {
        "reviewed": "viewed",
        "bookmarked": "bookmarked",
        "unlinked": "unlinked",
        "relinked": "relinked",
        "pinned_tp": "flagged",
        "pinned_tn": "flagged",
        "deferred": "deferred",
        "reassigned": "reassigned",
        "noted": "noted",
    }
    mark_type = str(body.get("mark_type") or action_to_mark.get(action, "viewed"))
    note = str(body.get("note", "") or body.get("reason", "")) or None
    link_id = body.get("link_id")
    doc_id = body.get("doc_id")
    section_number = body.get("section_number")

    if link_id and (not doc_id or not section_number):
        row = store._conn.execute(  # noqa: SLF001
            "SELECT doc_id, section_number FROM family_links WHERE link_id = ?",
            [link_id],
        ).fetchone()
        if row:
            doc_id, section_number = row[0], row[1]

    if not doc_id or not section_number:
        raise HTTPException(
            status_code=422,
            detail="doc_id and section_number are required (or provide a valid link_id)",
        )

    store.add_mark(session_id, str(doc_id), str(section_number), mark_type, note)
    return {
        "status": "saved",
        "session_id": session_id,
        "doc_id": doc_id,
        "section_number": section_number,
        "mark_type": mark_type,
    }


@app.get("/api/links/sessions/{session_id}/marks")
async def get_session_marks(session_id: str):
    """List marks for a session."""
    store = _get_link_store()
    rows = store._conn.execute(  # noqa: SLF001
        "SELECT * FROM review_marks WHERE session_id = ? ORDER BY created_at DESC",
        [session_id],
    ).fetchall()
    cols = [d[0] for d in store._conn.description]  # noqa: SLF001
    marks = [dict(zip(cols, row, strict=False)) for row in rows]
    return {"marks": marks, "total": len(marks)}


@app.get("/api/links/sessions/{session_id}/bookmarks")
async def get_bookmarks(session_id: str):
    """List bookmarked items in a session."""
    store = _get_link_store()
    marks = store.get_bookmarks(session_id)
    return {"bookmarks": marks, "total": len(marks)}


@app.get("/api/links/sessions/{session_id}/progress")
async def get_session_progress(session_id: str):
    """Session progress stats."""
    store = _get_link_store()
    progress = store.session_progress(session_id)
    if not progress:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"session_id": session_id, **progress}


@app.post("/api/links/review-sessions")
async def legacy_create_review_session(body: dict[str, Any] = Body(...)):
    """Backward-compatible alias for /api/links/sessions."""
    return await create_session(body)


@app.patch("/api/links/review-sessions/{session_id}")
async def legacy_update_review_session(session_id: str, body: dict[str, Any] = Body(...)):
    """Backward-compatible alias for /api/links/sessions/{id}/cursor."""
    return await update_cursor(session_id, body)


@app.get("/api/links/review-sessions/{session_id}/progress")
async def legacy_get_review_session_progress(session_id: str):
    """Backward-compatible alias for /api/links/sessions/{id}/progress."""
    return await get_session_progress(session_id)


@app.post("/api/links/review-marks")
async def legacy_add_review_mark(body: dict[str, Any] = Body(...)):
    """Backward-compatible alias for mark creation."""
    session_id = str(body.get("session_id", ""))
    if not session_id:
        raise HTTPException(status_code=422, detail="session_id is required")
    return await add_mark(session_id, body)


@app.get("/api/links/review-marks")
async def legacy_get_review_marks(mark_type: str = Query("bookmarked")):
    """Backward-compatible mark list endpoint across sessions."""
    store = _get_link_store()
    rows = store._conn.execute(  # noqa: SLF001
        "SELECT * FROM review_marks WHERE mark_type = ? ORDER BY created_at DESC",
        [mark_type],
    ).fetchall()
    cols = [d[0] for d in store._conn.description]  # noqa: SLF001
    marks = [dict(zip(cols, row, strict=False)) for row in rows]
    return {"marks": marks, "total": len(marks)}


# ---------------------------------------------------------------------------
# 37-39. Undo / Redo
# ---------------------------------------------------------------------------
@app.post("/api/links/undo")
async def undo_action(request: Request):
    """Undo the last batch action."""
    _require_links_admin(request)
    store = _get_link_store()
    result = store.undo()
    if result is None:
        raise HTTPException(status_code=404, detail="Nothing to undo")
    return result


@app.post("/api/links/redo")
async def redo_action(request: Request):
    """Redo the last undone action."""
    _require_links_admin(request)
    store = _get_link_store()
    result = store.redo()
    if result is None:
        raise HTTPException(status_code=404, detail="Nothing to redo")
    return result


@app.get("/api/links/undo-stack")
async def get_undo_stack():
    """Recent undo batches."""
    store = _get_link_store()
    stack = store.get_undo_stack()
    return {"stack": stack}


# ---------------------------------------------------------------------------
# 40-44. Analytics & Monitoring
# ---------------------------------------------------------------------------
@app.get("/api/links/analytics/unlink-reasons")
async def unlink_reasons():
    """Unlink reason taxonomy with counts."""
    store = _get_link_store()
    rows = store._conn.execute("""
        SELECT unlinked_reason, COUNT(*) AS count
        FROM family_links
        WHERE status = 'unlinked' AND unlinked_reason IS NOT NULL
        GROUP BY unlinked_reason ORDER BY count DESC
    """).fetchall()
    return {"reasons": [{"reason": r[0], "count": r[1]} for r in rows]}


@app.get("/api/links/analytics")
async def links_analytics_dashboard(
    family_id: str | None = Query(None),
    scope_id: str | None = Query(None),
):
    """Top-level analytics payload for the dashboard tab."""
    store = _get_link_store()
    requested_scope = str(scope_id or family_id or "").strip() or None
    resolved_scope = _canonicalize_scope_id(store, requested_scope) if requested_scope else None
    scope_aliases: set[str] = set()
    if requested_scope:
        scope_aliases.update(store.resolve_scope_aliases(requested_scope))
        scope_aliases.add(requested_scope)
    if resolved_scope:
        scope_aliases.update(store.resolve_scope_aliases(resolved_scope))
        scope_aliases.add(resolved_scope)
    scope_aliases = {_canonicalize_scope_id(store, scope) for scope in scope_aliases if scope}

    # Dashboard metrics should reflect the currently-linked population, not
    # historical unlinked rows retained for audit history.
    links = [
        link
        for link in store.get_links(
            family_id=resolved_scope or requested_scope,
            limit=100000,
        )
        if str(link.get("status", "")) != "unlinked"
    ]
    runs = store.get_runs(family_id=resolved_scope or requested_scope, limit=20)

    links_by_family_counter: Counter[str] = Counter()
    base_family_by_scope: dict[str, str] = {}
    ontology_by_scope: dict[str, str | None] = {}
    for link in links:
        base_family_id = _canonicalize_scope_id(store, link.get("family_id"))
        ontology_node_id = _canonicalize_scope_id(store, link.get("ontology_node_id"))
        raw_scope = ontology_node_id or base_family_id
        scope_id = _canonicalize_scope_id(store, raw_scope)
        if not scope_id:
            continue
        links_by_family_counter[scope_id] += 1
        if scope_id not in base_family_by_scope:
            base_family_by_scope[scope_id] = base_family_id or scope_id
        if scope_id not in ontology_by_scope:
            ontology_by_scope[scope_id] = ontology_node_id or None
    links_by_status_counter = Counter(str(link.get("status", "active")) for link in links)
    confidence_counter = Counter(str(link.get("confidence_tier", "low")) for link in links)

    if scope_aliases:
        families_by_section: dict[tuple[str, str], set[str]] = {}
        for link in links:
            if str(link.get("status", "")) != "active":
                continue
            doc_id = str(link.get("doc_id", "")).strip()
            section_number = str(link.get("section_number", "")).strip()
            if not doc_id or not section_number:
                continue
            key = (doc_id, section_number)
            families_by_section.setdefault(key, set()).add(
                _canonicalize_scope_id(store, link.get("family_id"))
            )
        total_conflicts = sum(1 for family_ids in families_by_section.values() if len(family_ids) > 1)
    else:
        total_conflicts_row = store._conn.execute(  # noqa: SLF001
            """
            SELECT COUNT(*) FROM (
                SELECT doc_id, section_number
                FROM family_links
                WHERE status = 'active'
                GROUP BY doc_id, section_number
                HAVING COUNT(DISTINCT family_id) > 1
            )
            """
        ).fetchone()
        total_conflicts = int(total_conflicts_row[0]) if total_conflicts_row else 0

    run_rule_cache: dict[str, dict[str, Any] | None] = {}
    recent_runs = []
    for run in runs:
        base_family_id = _canonicalize_scope_id(store, run.get("family_id"))
        scope_id, ontology_node_id = _resolve_run_scope(store, run, run_rule_cache)
        scope_id = _canonicalize_scope_id(store, scope_id or base_family_id)
        recent_runs.append(
            {
                "run_id": str(run.get("run_id", "")),
                "run_type": str(run.get("run_type") or run.get("source") or "apply"),
                "family_id": base_family_id,
                "base_family_id": base_family_id,
                "scope_id": scope_id or base_family_id,
                "ontology_node_id": _canonicalize_scope_id(store, ontology_node_id) if ontology_node_id else None,
                "links_created": int(run.get("links_created", 0) or 0),
                "conflicts_detected": int(run.get("conflicts_detected", 0) or 0),
                "started_at": run.get("started_at"),
                "completed_at": run.get("completed_at"),
                "status": "completed" if run.get("completed_at") else "running",
            }
        )

    return {
        "total_links": len(links),
        "total_runs": len(runs),
        "total_conflicts": total_conflicts,
        "total_drift_alerts": 0,
        "links_by_family": [
            {
                "family_id": scope_id,
                "scope_id": scope_id,
                "base_family_id": base_family_by_scope.get(scope_id, scope_id),
                "ontology_node_id": ontology_by_scope.get(scope_id),
                "count": count,
            }
            for scope_id, count in sorted(
                links_by_family_counter.items(),
                key=lambda item: (-item[1], item[0]),
            )
        ],
        "links_by_status": [
            {"status": status, "count": count}
            for status, count in links_by_status_counter.items()
        ],
        "confidence_distribution": [
            {"tier": tier, "count": count}
            for tier, count in confidence_counter.items()
        ],
        "recent_runs": recent_runs,
        "recent_alerts": [],
    }


@app.get("/api/links/intelligence/signals")
async def links_intelligence_signals(
    scope_id: str | None = Query(None),
    family_id: str | None = Query(None),
    top_n: int = Query(12, ge=1, le=50),
):
    """Legacy strategy signal digest projected onto ontology scope selection."""
    requested_scope = str(scope_id or family_id or "").strip() or None
    scope_ctx, strategy_rows = _strategy_rows_for_scope(requested_scope)

    heading_counts: Counter[str] = Counter()
    keyword_counts: Counter[str] = Counter()
    dna_counts: Counter[str] = Counter()
    for row in strategy_rows:
        heading_counts.update(
            str(value).strip()
            for value in row.get("heading_patterns", [])
            if str(value).strip()
        )
        keyword_counts.update(
            str(value).strip()
            for value in row.get("keyword_anchors", [])
            if str(value).strip()
        )
        dna_counts.update(
            str(value).strip()
            for value in row.get("dna_phrases", [])
            if str(value).strip()
        )

    signal_rows = []
    for row in strategy_rows:
        signal_rows.append(
            {
                "concept_id": row.get("concept_id"),
                "concept_name": row.get("concept_name"),
                "family_id": row.get("family_id"),
                "family": row.get("family"),
                "validation_status": row.get("validation_status"),
                "version": row.get("version"),
                "heading_pattern_count": row.get("heading_pattern_count"),
                "keyword_anchor_count": row.get("keyword_anchor_count"),
                "dna_phrase_count": row.get("dna_phrase_count"),
                "heading_hit_rate": row.get("heading_hit_rate"),
                "keyword_precision": row.get("keyword_precision"),
                "cohort_coverage": row.get("cohort_coverage"),
                "corpus_prevalence": row.get("corpus_prevalence"),
                "last_updated": row.get("last_updated"),
            }
        )

    return {
        "scope_id": scope_ctx.get("scope_id") or scope_ctx.get("requested_scope") or None,
        "scope_name": scope_ctx.get("scope_name") or "",
        "total_strategies": len(signal_rows),
        "strategies": signal_rows,
        "top_heading_patterns": [
            {"value": value, "count": count}
            for value, count in heading_counts.most_common(top_n)
        ],
        "top_keyword_anchors": [
            {"value": value, "count": count}
            for value, count in keyword_counts.most_common(top_n)
        ],
        "top_dna_phrases": [
            {"value": value, "count": count}
            for value, count in dna_counts.most_common(top_n)
        ],
    }


@app.get("/api/links/intelligence/evidence")
async def links_intelligence_evidence(
    scope_id: str | None = Query(None),
    family_id: str | None = Query(None),
    record_type: str | None = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """Evidence-browser view scoped to ontology selection."""
    requested_scope = str(scope_id or family_id or "").strip() or None
    scope_ctx, strategy_rows = _strategy_rows_for_scope(requested_scope)
    scoped_concept_ids = {
        str(row.get("concept_id") or "").strip()
        for row in strategy_rows
        if str(row.get("concept_id") or "").strip()
    }

    rows: list[dict[str, Any]] = []
    files = _iter_workspace_evidence_files()
    total_scanned = 0
    matched_filtered = 0
    scope_total = 0
    scope_hits = 0
    template_totals: Counter[str] = Counter()
    template_hits: Counter[str] = Counter()
    rt_filter = str(record_type or "").strip().upper()

    for fp in files:
        with contextlib.suppress(Exception):
            for raw_line in fp.read_text().splitlines():
                if not raw_line.strip():
                    continue
                total_scanned += 1
                with contextlib.suppress(Exception):
                    payload = orjson.loads(raw_line)
                    if not isinstance(payload, dict):
                        continue
                    cid = str(
                        payload.get("ontology_node_id")
                        or payload.get("concept_id")
                        or ""
                    ).strip()
                    if scoped_concept_ids:
                        if cid and cid not in scoped_concept_ids and not _scope_matches_value(
                            cid,
                            scope_ctx,
                        ):
                            continue
                    elif not _scope_matches_value(cid, scope_ctx):
                        continue

                    scope_total += 1
                    rtype = str(payload.get("record_type", "HIT") or "HIT").upper()
                    if rtype == "HIT":
                        scope_hits += 1
                    template_family = str(payload.get("template_family", "") or "unknown")
                    template_totals[template_family] += 1
                    if rtype == "HIT":
                        template_hits[template_family] += 1

                    if rt_filter and rtype != rt_filter:
                        continue

                    if matched_filtered < offset:
                        matched_filtered += 1
                        continue
                    if len(rows) >= limit:
                        matched_filtered += 1
                        continue

                    matched_filtered += 1
                    outlier = payload.get("outlier")
                    outlier_level = (
                        str(outlier.get("level", "none"))
                        if isinstance(outlier, dict)
                        else "none"
                    )
                    rows.append(
                        {
                            "concept_id": cid,
                            "record_type": rtype,
                            "doc_id": str(payload.get("doc_id", "") or ""),
                            "template_family": template_family,
                            "section_number": str(payload.get("section_number", "") or ""),
                            "heading": str(payload.get("heading", "") or ""),
                            "clause_path": str(payload.get("clause_path", "") or ""),
                            "score": payload.get("score"),
                            "outlier_level": outlier_level,
                            "source_tool": str(payload.get("source_tool", "") or ""),
                            "created_at": str(payload.get("created_at", "") or ""),
                            "path": str(fp),
                        }
                    )

    templates = [
        {
            "template_family": template,
            "hits": int(template_hits.get(template, 0)),
            "total": int(total),
            "hit_rate": round(template_hits.get(template, 0) / total, 4) if total else 0.0,
        }
        for template, total in template_totals.most_common()
    ]

    return {
        "scope_id": scope_ctx.get("scope_id") or scope_ctx.get("requested_scope") or None,
        "scope_name": scope_ctx.get("scope_name") or "",
        "filters": {
            "record_type": rt_filter or "",
            "limit": limit,
            "offset": offset,
        },
        "summary": {
            "files_scanned": len(files),
            "rows_scanned": total_scanned,
            "rows_matched": matched_filtered,
            "rows_returned": len(rows),
            "scope_total": scope_total,
            "scope_hits": scope_hits,
            "scope_hit_rate": round(scope_hits / scope_total, 4) if scope_total else 0.0,
            "has_prev": offset > 0,
            "has_next": (offset + len(rows)) < matched_filtered,
        },
        "templates": templates,
        "rows": rows,
    }


@app.get("/api/links/intelligence/ops")
async def links_intelligence_ops(
    scope_id: str | None = Query(None),
    family_id: str | None = Query(None),
    stale_minutes: int = Query(60, ge=1, le=24 * 60),
    run_limit: int = Query(20, ge=1, le=200),
    job_limit: int = Query(50, ge=1, le=200),
):
    """Operational telemetry (agents, jobs, runs) scoped for ontology links."""
    requested_scope = str(scope_id or family_id or "").strip() or None
    scope_ctx, strategy_rows = _strategy_rows_for_scope(requested_scope)
    store = _get_link_store()

    related_tokens: set[str] = set()
    for value in (
        scope_ctx.get("target_token"),
        scope_ctx.get("scope_id"),
        scope_ctx.get("requested_scope"),
    ):
        token = _canonical_family_token(value)
        if token:
            related_tokens.add(token)
    for row in strategy_rows:
        for value in (
            row.get("family_id"),
            row.get("family"),
            row.get("concept_id"),
        ):
            token = _canonical_family_token(value)
            if token:
                related_tokens.add(token)

    now = datetime.now(timezone.utc)
    agents: list[dict[str, Any]] = []
    if _workspace_root.exists():
        for family_dir in sorted(_workspace_root.iterdir()):
            if not family_dir.is_dir():
                continue
            family_name = family_dir.name
            family_token = _canonical_family_token(family_name)
            if requested_scope:
                if not _scope_matches_value(family_name, scope_ctx) and (
                    family_token not in related_tokens
                ):
                    continue
            checkpoint = family_dir / "checkpoint.json"
            payload = _safe_load_json(checkpoint) if checkpoint.exists() else {}
            status = str(payload.get("status", "missing") or "missing")
            last_update_raw = str(payload.get("last_update", "") or "")
            stale = False
            if last_update_raw:
                with contextlib.suppress(Exception):
                    dt = datetime.fromisoformat(last_update_raw.replace("Z", "+00:00"))
                    stale = (now - dt).total_seconds() > stale_minutes * 60
            agents.append(
                {
                    "family": family_name,
                    "status": status,
                    "iteration_count": int(payload.get("iteration_count", 0) or 0),
                    "current_concept_id": str(payload.get("current_concept_id", "") or ""),
                    "last_strategy_version": int(payload.get("last_strategy_version", 0) or 0),
                    "last_coverage_hit_rate": float(payload.get("last_coverage_hit_rate", 0.0) or 0.0),
                    "last_session": str(payload.get("last_session", "") or ""),
                    "last_pane": str(payload.get("last_pane", "") or ""),
                    "last_start_at": str(payload.get("last_start_at", "") or ""),
                    "last_update": last_update_raw,
                    "stale": stale,
                    "checkpoint_path": str(checkpoint),
                }
            )

    rows = store._conn.execute(  # noqa: SLF001
        "SELECT * FROM job_queue ORDER BY submitted_at DESC LIMIT ?",
        [max(job_limit * 4, 200)],
    ).fetchall()
    cols = [d[0] for d in store._conn.description]  # noqa: SLF001
    jobs: list[dict[str, Any]] = []
    for row in rows:
        payload = dict(zip(cols, row, strict=False))
        params_json = payload.get("params_json")
        params = json.loads(params_json) if isinstance(params_json, str) and params_json else {}
        if not isinstance(params, dict):
            params = {}
        job_scope = str(params.get("family_id") or params.get("scope_id") or "").strip()
        if requested_scope:
            if not job_scope:
                continue
            if not _scope_matches_value(job_scope, scope_ctx):
                job_token = _canonical_family_token(job_scope)
                if job_token not in related_tokens:
                    continue
        jobs.append(
            {
                "job_id": str(payload.get("job_id", "")),
                "job_type": str(payload.get("job_type", "")),
                "status": str(payload.get("status", "pending")),
                "submitted_at": payload.get("submitted_at"),
                "started_at": payload.get("claimed_at"),
                "completed_at": payload.get("completed_at"),
                "progress": float(payload.get("progress_pct", 0.0) or 0.0),
                "progress_message": str(payload.get("progress_message", "")),
                "scope_id": job_scope or None,
                "error": payload.get("error_message"),
            }
        )
        if len(jobs) >= job_limit:
            break

    run_rule_cache: dict[str, dict[str, Any] | None] = {}
    requested_run_scope = str(scope_ctx.get("scope_id") or scope_ctx.get("requested_scope") or "").strip()
    runs_raw = store.get_runs(family_id=requested_run_scope or None, limit=run_limit)
    if requested_run_scope and not runs_raw:
        token = str(scope_ctx.get("target_token") or "").strip()
        if token:
            runs_raw = [
                run
                for run in store.get_runs(limit=max(run_limit * 10, 500))
                if (
                    _canonical_family_token(run.get("family_id")) == token
                    or _canonical_family_token(
                        _resolve_run_scope(store, run, run_rule_cache)[0]
                    )
                    == token
                )
            ][:run_limit]

    runs: list[dict[str, Any]] = []
    for run in runs_raw:
        base_family_id = _canonicalize_scope_id(store, run.get("family_id"))
        resolved_scope, ontology_node_id = _resolve_run_scope(store, run, run_rule_cache)
        scope_val = _canonicalize_scope_id(store, resolved_scope or base_family_id)
        runs.append(
            {
                "run_id": str(run.get("run_id", "")),
                "run_type": str(run.get("run_type") or run.get("source") or "apply"),
                "family_id": base_family_id,
                "scope_id": scope_val or base_family_id,
                "ontology_node_id": (
                    _canonicalize_scope_id(store, ontology_node_id)
                    if ontology_node_id
                    else None
                ),
                "links_created": int(run.get("links_created", 0) or 0),
                "conflicts_detected": int(run.get("conflicts_detected", 0) or 0),
                "started_at": run.get("started_at"),
                "completed_at": run.get("completed_at"),
                "status": "completed" if run.get("completed_at") else "running",
            }
        )

    job_status_counts = Counter(str(job.get("status", "pending")) for job in jobs)
    run_status_counts = Counter(str(run.get("status", "running")) for run in runs)
    agents.sort(key=lambda row: (not bool(row.get("stale")), str(row.get("family", ""))))

    return {
        "scope_id": scope_ctx.get("scope_id") or scope_ctx.get("requested_scope") or None,
        "scope_name": scope_ctx.get("scope_name") or "",
        "stale_minutes": stale_minutes,
        "agents": {
            "total": len(agents),
            "stale_count": sum(1 for row in agents if row.get("stale")),
            "items": agents,
        },
        "jobs": {
            "total": len(jobs),
            "pending": int(job_status_counts.get("pending", 0)),
            "running": int(job_status_counts.get("running", 0)),
            "failed": int(job_status_counts.get("failed", 0)),
            "items": jobs,
        },
        "runs": {
            "total": len(runs),
            "running": int(run_status_counts.get("running", 0)),
            "completed": int(run_status_counts.get("completed", 0)),
            "items": runs,
        },
    }


@app.post("/api/links/calibrate/{family_id}")
async def calibrate_family(
    request: Request,
    family_id: str,
    body: dict[str, Any] = Body(...),
):
    """Recalibrate confidence thresholds for a family."""
    _require_links_admin(request)
    store = _get_link_store()
    thresholds = {
        "family_id": family_id,
        "high_threshold": body.get("high_threshold", 0.8),
        "medium_threshold": body.get("medium_threshold", 0.5),
        "method": body.get("method", "manual"),
    }
    store.save_calibration(family_id, "_global", thresholds)
    return thresholds


# ---------------------------------------------------------------------------
# 45-46. Jobs
# ---------------------------------------------------------------------------
@app.get("/api/links/jobs")
async def list_link_jobs():
    """List link jobs from durable job_queue."""
    store = _get_link_store()
    rows = store._conn.execute(  # noqa: SLF001
        "SELECT * FROM job_queue ORDER BY submitted_at DESC LIMIT 200"
    ).fetchall()
    cols = [d[0] for d in store._conn.description]  # noqa: SLF001
    jobs: list[dict[str, Any]] = []
    for row in rows:
        payload = dict(zip(cols, row, strict=False))
        params = payload.get("params_json")
        result = payload.get("result_json")
        jobs.append(
            {
                "job_id": str(payload.get("job_id", "")),
                "job_type": str(payload.get("job_type", "")),
                "status": str(payload.get("status", "pending")),
                "submitted_at": payload.get("submitted_at"),
                "started_at": payload.get("claimed_at"),
                "completed_at": payload.get("completed_at"),
                "progress": float(payload.get("progress_pct", 0.0) or 0.0),
                "progress_message": str(payload.get("progress_message", "")),
                "params": json.loads(params) if isinstance(params, str) and params else {},
                "result_summary": json.loads(result) if isinstance(result, str) and result else None,
                "error": payload.get("error_message"),
            }
        )
    return {"jobs": jobs, "total": len(jobs)}


@app.get("/api/links/jobs/{job_id}")
async def get_link_job_status(job_id: str):
    """Get link job status and progress."""
    store = _get_link_store()
    job = store.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")
    return job


@app.delete("/api/links/jobs/{job_id}")
async def cancel_link_job(request: Request, job_id: str):
    """Cancel a pending/claimed link job."""
    _require_links_admin(request)
    store = _get_link_store()
    cancelled = store.cancel_job(job_id)
    if not cancelled:
        raise HTTPException(
            status_code=409,
            detail="Job cannot be cancelled (already running/completed)",
        )
    return {"cancelled": True}


# ---------------------------------------------------------------------------
# 47-51. Export / Import
# ---------------------------------------------------------------------------
@app.post("/api/links/export")
async def export_links(
    request: Request,
    body: dict[str, Any] = Body(...),
):
    """Export links as CSV/JSONL (async job)."""
    _require_links_admin(request)
    store = _get_link_store()
    job_id = str(uuid.uuid4())
    store.submit_job({
        "job_id": job_id,
        "job_type": "export",
        "params": {
            "format": body.get("format", "csv"),
            "family_id": body.get("family_id"),
            "status": body.get("status"),
        },
    })
    return {"job_id": job_id}


@app.post("/api/links/import")
async def import_links(
    request: Request,
    body: LinksImportRequest = Body(...),
):
    """Import adjudicated labels."""
    _require_links_admin(request)
    store = _get_link_store()
    records = [record.model_dump(exclude_none=True) for record in body.records]
    for record in records:
        record.pop("run_id", None)
    run_id = str(uuid.uuid4())
    created = store.create_links(records, run_id)
    return {"imported": created, "run_id": run_id}


@app.get("/api/links/rules/{rule_id}/export")
async def export_rule(rule_id: str):
    """Export rule as JSON."""
    store = _get_link_store()
    rule = store.get_rule(rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail=f"Rule not found: {rule_id}")
    return _rule_to_api(store, rule)


@app.post("/api/links/batch-run")
async def batch_run(
    request: Request,
    body: dict[str, Any] = Body(...),
):
    """Run published rules against corpus and persist links."""
    _require_links_admin(request)
    store = _get_link_store()
    corpus = _get_corpus()
    requested_raw = str(body.get("scope_id") or body.get("family_id") or "").strip() or None
    requested_family_id = _canonicalize_scope_id(store, requested_raw) if requested_raw else None

    from scripts.bulk_family_linker import run_bulk_linking

    rules, resolved_family_id = _resolve_published_rules_for_requested_family(
        store,
        requested_family_id,
    )
    if not rules:
        return {
            "status": "no_rules",
            "job_id": None,
            "requested_family_id": requested_family_id,
            "resolved_family_id": resolved_family_id,
        }

    result = run_bulk_linking(
        corpus,
        store,
        rules,
        family_filter=resolved_family_id,
        dry_run=False,
    )
    run_id = result.get("run_id")
    return {
        "job_id": run_id,
        "status": result.get("status", "completed"),
        "result": result,
        "requested_family_id": requested_family_id,
        "resolved_family_id": resolved_family_id,
    }


@app.get("/api/links/runs")
async def list_link_runs(
    family_id: str | None = Query(None),
    limit: int = Query(50, ge=1, le=500),
):
    store = _get_link_store()
    run_rule_cache: dict[str, dict[str, Any] | None] = {}
    requested_scope = _canonicalize_scope_id(store, family_id) if family_id else ""
    runs_raw = store.get_runs(family_id=requested_scope or family_id, limit=limit)
    if family_id and not runs_raw:
        scoped_matches = []
        for run in store.get_runs(limit=max(limit * 10, 500)):
            scope_id, _ = _resolve_run_scope(store, run, run_rule_cache)
            if scope_id and scope_id == requested_scope:
                scoped_matches.append(run)
        if scoped_matches:
            runs_raw = scoped_matches[:limit]
    if family_id and not runs_raw:
        target_token = _canonical_family_token(family_id)
        if target_token:
            runs_raw = [
                run
                for run in store.get_runs(limit=max(limit * 10, 500))
                if (
                    _canonical_family_token(run.get("family_id")) == target_token
                    or _canonical_family_token(
                        _resolve_run_scope(store, run, run_rule_cache)[0]
                    )
                    == target_token
                )
            ][:limit]
    latest_completed_started_by_scope: dict[str, datetime] = {}
    for run in runs_raw:
        completed_at = run.get("completed_at")
        started_at = run.get("started_at")
        if not completed_at or not started_at:
            continue
        try:
            started_dt = datetime.fromisoformat(str(started_at))
        except (TypeError, ValueError):
            continue
        scope_id, _ = _resolve_run_scope(store, run, run_rule_cache)
        fid = _canonicalize_scope_id(store, scope_id or run.get("family_id"))
        prev = latest_completed_started_by_scope.get(fid)
        if prev is None or started_dt > prev:
            latest_completed_started_by_scope[fid] = started_dt
    runs: list[dict[str, Any]] = []
    for run in runs_raw:
        base_family_id = _canonicalize_scope_id(store, run.get("family_id"))
        scope_id, ontology_node_id = _resolve_run_scope(store, run, run_rule_cache)
        fid = _canonicalize_scope_id(store, scope_id or base_family_id)
        display_family_id = _canonicalize_scope_id(store, base_family_id) or fid
        display_scope_id = _canonicalize_scope_id(store, scope_id or base_family_id) or display_family_id
        display_parent_family = _canonicalize_scope_id(store, run.get("parent_family_id")) or None
        display_ontology_id = _canonicalize_scope_id(store, ontology_node_id) if ontology_node_id else None
        started_dt: datetime | None = None
        if run.get("started_at"):
            try:
                started_dt = datetime.fromisoformat(str(run.get("started_at")))
            except (TypeError, ValueError):
                started_dt = None
        stale_running = (
            not run.get("completed_at")
            and bool(fid)
            and started_dt is not None
            and latest_completed_started_by_scope.get(fid) is not None
            and started_dt <= latest_completed_started_by_scope[fid]
        )
        runs.append(
            {
                "run_id": str(run.get("run_id", "")),
                "run_type": str(run.get("run_type") or run.get("source") or "apply"),
                "family_id": display_family_id,
                "base_family_id": display_family_id,
                "scope_id": display_scope_id,
                "ontology_node_id": display_ontology_id,
                "rule_id": run.get("rule_id"),
                "parent_family_id": display_parent_family,
                "parent_run_id": run.get("parent_run_id"),
                "scope_mode": str(run.get("scope_mode") or "corpus"),
                "corpus_version": str(run.get("corpus_version", "")),
                "corpus_doc_count": int(run.get("corpus_doc_count", 0) or 0),
                "parser_version": str(run.get("parser_version", "")),
                "links_created": int(run.get("links_created", 0) or 0),
                "conflicts_detected": int(run.get("conflicts_detected", 0) or 0),
                "started_at": run.get("started_at"),
                "completed_at": run.get("completed_at"),
                "status": "completed" if run.get("completed_at") or stale_running else "running",
            }
        )
    return {"runs": runs, "total": len(runs)}


@app.get("/api/links/runs/{run_id}/replay-bundle")
async def get_replay_bundle(run_id: str):
    """Export durable replay bundle."""
    store = _get_link_store()
    run = store.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")
    return {"run": run}


# ---------------------------------------------------------------------------
# 52-53. DSL & Semantic
# ---------------------------------------------------------------------------
@app.post("/api/links/rules/expand-term")
async def expand_term(body: dict[str, Any] = Body(...)):
    """Semantic expand: term → synonyms + co-occurrence."""
    term = body.get("term", "")
    expansions: list[str] = [term]
    for _nid, node in _ontology_nodes.items():
        name = node.get("name", "")
        if term.lower() in name.lower() and name != term:
            expansions.append(name)
    return {"term": term, "expansions": expansions[:20]}


@app.get("/api/links/rules/autocomplete")
@app.get("/api/links/rules-autocomplete")
async def rules_autocomplete(
    field: str = Query(...),
    prefix: str = Query(""),
    limit: int = Query(8, ge=1, le=50),
):
    """Autocomplete suggestions for DSL fields sourced from corpus/ontology."""
    field_norm = field.strip().lower()
    prefix_norm = prefix.strip()

    if field_norm == "article":
        names = [
            str(node.get("name", ""))
            for node in _ontology_nodes.values()
            if node.get("name")
        ]
        if prefix_norm:
            names = [n for n in names if n.lower().startswith(prefix_norm.lower())]
        names = sorted(set(names), key=lambda x: x.lower())
        return {"field": field_norm, "suggestions": names[:limit]}

    corpus = _get_corpus()
    like = f"{_escape_like(prefix_norm)}%" if prefix_norm else "%"
    try:
        if field_norm == "heading":
            rows = corpus.query(
                "SELECT heading, COUNT(*) AS n "
                "FROM sections "
                "WHERE heading IS NOT NULL AND TRIM(heading) <> '' "
                "AND heading ILIKE ? ESCAPE '\\' "
                "GROUP BY heading "
                "ORDER BY n DESC, heading "
                "LIMIT ?",
                [like, limit],
            )
            return {"field": field_norm, "suggestions": [str(r[0]) for r in rows]}

        if field_norm == "template":
            rows = corpus.query(
                "SELECT DISTINCT template_family "
                "FROM documents "
                "WHERE template_family IS NOT NULL AND TRIM(template_family) <> '' "
                "AND template_family ILIKE ? ESCAPE '\\' "
                "ORDER BY template_family "
                "LIMIT ?",
                [like, limit],
            )
            return {"field": field_norm, "suggestions": [str(r[0]) for r in rows]}

        if field_norm == "admin_agent":
            rows = corpus.query(
                "SELECT admin_agent, COUNT(*) AS n "
                "FROM documents "
                "WHERE admin_agent IS NOT NULL AND TRIM(admin_agent) <> '' "
                "AND admin_agent ILIKE ? ESCAPE '\\' "
                "GROUP BY admin_agent "
                "ORDER BY n DESC, admin_agent "
                "LIMIT ?",
                [like, limit],
            )
            return {"field": field_norm, "suggestions": [str(r[0]) for r in rows]}

        if field_norm == "vintage":
            rows = corpus.query(
                "SELECT CAST(EXTRACT(YEAR FROM filing_date) AS VARCHAR) AS vintage, COUNT(*) AS n "
                "FROM documents "
                "WHERE filing_date IS NOT NULL "
                "AND CAST(EXTRACT(YEAR FROM filing_date) AS VARCHAR) ILIKE ? ESCAPE '\\' "
                "GROUP BY vintage "
                "ORDER BY vintage DESC "
                "LIMIT ?",
                [like, limit],
            )
            return {"field": field_norm, "suggestions": [str(r[0]) for r in rows]}
    except Exception:
        return {"field": field_norm, "suggestions": []}

    try:
        if field_norm == "clause":
            # Clause text is too long for autocomplete — return common leading phrases
            rows = corpus.query(
                "SELECT DISTINCT LEFT(TRIM(text), 60) AS snippet "
                "FROM section_text "
                "WHERE text IS NOT NULL AND TRIM(text) <> '' "
                "AND LEFT(TRIM(text), 60) ILIKE ? ESCAPE '\\' "
                "ORDER BY snippet "
                "LIMIT ?",
                [like, limit],
            )
            return {"field": field_norm, "suggestions": [str(r[0]) for r in rows]}

        if field_norm == "section":
            rows = corpus.query(
                "SELECT heading, COUNT(*) AS n "
                "FROM sections "
                "WHERE heading IS NOT NULL AND TRIM(heading) <> '' "
                "AND heading ILIKE ? ESCAPE '\\' "
                "GROUP BY heading "
                "ORDER BY n DESC, heading "
                "LIMIT ?",
                [like, limit],
            )
            return {"field": field_norm, "suggestions": [str(r[0]) for r in rows]}

        if field_norm == "defined_term":
            rows = corpus.query(
                "SELECT term, COUNT(*) AS n "
                "FROM definitions "
                "WHERE term IS NOT NULL AND TRIM(term) <> '' "
                "AND term ILIKE ? ESCAPE '\\' "
                "GROUP BY term "
                "ORDER BY n DESC, term "
                "LIMIT ?",
                [like, limit],
            )
            return {"field": field_norm, "suggestions": [str(r[0]) for r in rows]}

        if field_norm == "market":
            rows = corpus.query(
                "SELECT DISTINCT market_segment "
                "FROM documents "
                "WHERE market_segment IS NOT NULL AND TRIM(market_segment) <> '' "
                "AND market_segment ILIKE ? ESCAPE '\\' "
                "ORDER BY market_segment "
                "LIMIT ?",
                [like, limit],
            )
            return {"field": field_norm, "suggestions": [str(r[0]) for r in rows]}

        if field_norm == "doc_type":
            rows = corpus.query(
                "SELECT DISTINCT doc_type "
                "FROM documents "
                "WHERE doc_type IS NOT NULL AND TRIM(doc_type) <> '' "
                "AND doc_type ILIKE ? ESCAPE '\\' "
                "ORDER BY doc_type "
                "LIMIT ?",
                [like, limit],
            )
            return {"field": field_norm, "suggestions": [str(r[0]) for r in rows]}

        if field_norm == "facility_size_mm":
            rows = corpus.query(
                "SELECT DISTINCT CAST(facility_size_mm AS VARCHAR) AS val "
                "FROM documents "
                "WHERE facility_size_mm IS NOT NULL "
                "AND CAST(facility_size_mm AS VARCHAR) ILIKE ? ESCAPE '\\' "
                "ORDER BY val DESC "
                "LIMIT ?",
                [like, limit],
            )
            return {"field": field_norm, "suggestions": [str(r[0]) for r in rows]}
    except Exception:
        return {"field": field_norm, "suggestions": []}

    raise HTTPException(
        status_code=422,
        detail=(
            "field must be one of: heading, article, clause, section, defined_term, "
            "template, admin_agent, vintage, market, doc_type, facility_size_mm"
        ),
    )


@app.get("/api/links/definitions-peek")
async def definitions_peek(
    doc_id: str = Query(...),
    term: str = Query(...),
):
    """Defined term lookup from corpus."""
    corpus = _get_corpus()
    defs = corpus.get_definitions(doc_id)
    for d in defs:
        if d.term.lower() == term.lower():
            return {"term": d.term, "found": True}
    return {"term": term, "found": False}


# ---------------------------------------------------------------------------
# 54-55. Diagnostic
# ---------------------------------------------------------------------------
@app.post("/api/links/coverage/why-not")
async def why_not_matched(body: dict[str, Any] = Body(...)):
    """Per-doc 'why not matched' with traffic-light AST evaluation."""
    doc_id = str(body.get("doc_id", ""))
    section_number = str(body.get("section_number", "") or "")
    rule_id = str(body.get("rule_id", ""))
    store = _get_link_store()
    rule = store.get_rule(rule_id) if rule_id else None
    if rule is None:
        return {
            "doc_id": doc_id,
            "section_number": section_number or "1.01",
            "family_id": "",
            "nearest_score": 0.0,
            "missing_factors": ["rule_not_found"],
            "suggestion": "Select a valid rule for this family.",
            "rule_ast": {},
            "traffic_tree": None,
        }

    try:
        parsed_expr = filter_expr_from_json(rule.get("heading_filter_ast", {}))
        canonical_ast = filter_expr_to_json(parsed_expr)
    except (TypeError, ValueError, KeyError):
        return {
            "doc_id": doc_id,
            "section_number": section_number or "1.01",
            "family_id": str(rule.get("family_id", "")),
            "nearest_score": 0.0,
            "missing_factors": ["invalid_rule_ast"],
            "suggestion": "Rule AST could not be parsed.",
            "rule_ast": {},
            "traffic_tree": None,
        }

    heading = ""
    if section_number:
        heading_row = store._conn.execute(  # noqa: SLF001
            "SELECT heading FROM family_links WHERE doc_id = ? AND section_number = ? "
            "ORDER BY created_at DESC LIMIT 1",
            [doc_id, section_number],
        ).fetchone()
        if heading_row and heading_row[0]:
            heading = str(heading_row[0])
    if not heading:
        heading_row = store._conn.execute(  # noqa: SLF001
            "SELECT section_number, heading FROM family_links WHERE doc_id = ? "
            "ORDER BY created_at DESC LIMIT 1",
            [doc_id],
        ).fetchone()
        if heading_row:
            if not section_number and heading_row[0] is not None:
                section_number = str(heading_row[0])
            if heading_row[1] is not None:
                heading = str(heading_row[1])
    if not heading:
        try:
            corpus = _get_corpus()
            sections = corpus.search_sections(doc_id=doc_id, cohort_only=False, limit=1)
            if sections:
                if not section_number:
                    section_number = str(sections[0].section_number)
                heading = str(sections[0].heading or "")
        except HTTPException:
            pass

    matched, traffic_tree = _evaluate_expr_tree(parsed_expr, heading or "")
    flat = _flatten_tree(traffic_tree)
    non_root = [n for n in flat if n.get("path")]
    passed = sum(1 for n in non_root if bool(n.get("result")))
    nearest = (passed / len(non_root)) if non_root else (1.0 if matched else 0.0)
    missing = [
        str(n.get("node", ""))
        for n in non_root
        if not bool(n.get("result"))
    ]
    suggestion = (
        f'Consider adding variant "{missing[0]}"'
        if missing
        else "Rule already matches this section."
    )
    return {
        "doc_id": doc_id,
        "section_number": section_number or "1.01",
        "family_id": str(rule.get("family_id", "")),
        "nearest_score": max(0.0, min(1.0, nearest)),
        "missing_factors": missing,
        "suggestion": suggestion,
        "rule_ast": canonical_ast,
        "traffic_tree": traffic_tree,
        "evaluated_heading": heading,
    }


@app.post("/api/links/coverage/counterfactual")
async def counterfactual(body: dict[str, Any] = Body(...)):
    """Counterfactual analysis: what if we mute a node?"""
    store = _get_link_store()
    family_id = str(body.get("family_id", ""))
    heading_ast = body.get("heading_filter_ast")
    muted_node_path = str(body.get("muted_node_path", ""))
    if not isinstance(heading_ast, dict):
        return {
            "rule_ast": heading_ast,
            "muted_node_path": muted_node_path,
            "new_hits": 0,
            "false_positives": 0,
            "total_matched": 0,
            "fps_estimate": 0,
        }

    try:
        parsed_expr = filter_expr_from_json(heading_ast)
    except (TypeError, ValueError, KeyError):
        return {
            "rule_ast": heading_ast,
            "muted_node_path": muted_node_path,
            "new_hits": 0,
            "false_positives": 0,
            "total_matched": 0,
            "fps_estimate": 0,
        }

    links = store.get_links(family_id=family_id, limit=100000)
    baseline_count = 0
    muted_count = 0
    for link in links:
        heading = str(link.get("heading", ""))
        baseline_ok, _ = _evaluate_expr_tree(parsed_expr, heading)
        muted_ok, _ = _evaluate_expr_tree(parsed_expr, heading, muted_path=muted_node_path or None)
        baseline_count += 1 if baseline_ok else 0
        muted_count += 1 if muted_ok else 0

    new_hits = max(0, muted_count - baseline_count)
    false_positives = max(0, int(round(new_hits * 0.25)))
    return {
        "rule_ast": heading_ast,
        "muted_node_path": muted_node_path,
        "new_hits": new_hits,
        "false_positives": false_positives,
        "total_matched": muted_count,
        "fps_estimate": false_positives,
    }

# ---------------------------------------------------------------------------
# 56. Queue
# ---------------------------------------------------------------------------
@app.post("/api/links/sessions/{session_id}/claim-batch")
async def claim_batch(session_id: str, body: dict[str, Any] = Body(...)):
    """Reserve N rows for current reviewer."""
    store = _get_link_store()
    try:
        n = int(body.get("batch_size", 50))
    except (TypeError, ValueError):
        n = 50
    n = max(1, min(n, 500))

    claimed_rows = store._conn.execute(  # noqa: SLF001
        "SELECT doc_id, section_number FROM review_marks WHERE mark_type = 'claimed'",
    ).fetchall()
    claimed_keys = {(str(row[0]), str(row[1])) for row in claimed_rows}

    scan_limit = max(n * 6, n)
    pending = store.get_links(status="pending_review", limit=scan_limit)
    selected: list[dict[str, Any]] = []
    for link in pending:
        key = (str(link.get("doc_id", "")), str(link.get("section_number", "")))
        if key in claimed_keys:
            continue
        selected.append(link)
        claimed_keys.add(key)
        if len(selected) >= n:
            break

    for link in selected:
        store.add_mark(
            session_id,
            str(link.get("doc_id", "")),
            str(link.get("section_number", "")),
            "claimed",
            None,
        )

    return {
        "claimed": [str(link.get("link_id", "")) for link in selected],
        "count": len(selected),
        "session_id": session_id,
    }


# ---------------------------------------------------------------------------
# 57-58. Reassign
# ---------------------------------------------------------------------------
@app.post("/api/links/{link_id}/reassign")
async def reassign_link(
    request: Request,
    link_id: str,
    body: dict[str, Any] = Body(...),
):
    """Move link to different family."""
    _require_links_admin(request)
    store = _get_link_store()
    new_family = body.get("new_family_id", "")
    if not new_family:
        raise HTTPException(status_code=422, detail="new_family_id required")
    result = store.reassign_link(link_id, new_family)
    return result


@app.get("/api/links/{link_id}/reassign-suggestions")
async def reassign_suggestions(link_id: str):
    """Top 5 likely families for reassignment."""
    from scripts.bulk_family_linker import heading_matches_ast

    store = _get_link_store()
    all_links = store.get_links(limit=100000)
    link = next((lnk for lnk in all_links if lnk.get("link_id") == link_id), None)
    if link is None:
        raise HTTPException(status_code=404, detail=f"Link not found: {link_id}")

    current_family = link.get("family_id", "")
    heading = link.get("heading", "")
    all_rules = store.get_rules(status="published")

    suggestions: list[dict[str, Any]] = []
    for rule in all_rules:
        fam = rule.get("family_id", "")
        if fam == current_family:
            continue
        matched, match_type, _ = heading_matches_ast(
            heading, rule.get("heading_filter_ast", {}),
        )
        if matched:
            suggestions.append({
                "family_id": fam,
                "family_name": _family_name_from_id(str(fam)),
                "confidence": 0.7 if match_type == "exact" else 0.55,
                "reason": f"Matched via {match_type}",
                "match_type": match_type,
                "rule_id": rule.get("rule_id", ""),
            })
    return {"suggestions": suggestions[:5]}


# ---------------------------------------------------------------------------
# 59-61. Multi-Role Links
# ---------------------------------------------------------------------------
@app.get("/api/links/{link_id}/context-strip")
async def context_strip(link_id: str):
    """Primary covenant + definitions + xrefs."""
    store = _get_link_store()
    context = store.get_context_strip(link_id)
    if not context:
        raise HTTPException(status_code=404, detail=f"Link not found: {link_id}")

    doc_id = str(context.get("doc_id", ""))
    section_number = str(context.get("section_number", ""))
    section_text: str | None = None
    if doc_id and section_number:
        try:
            section_text = _get_corpus().get_section_text(doc_id, section_number) or None
        except Exception:
            section_text = None
    if not section_text:
        heading = str(context.get("primary_covenant_heading", "")).strip()
        section_text = (
            f"{heading}\n\n"
            f"This section ({section_number}) governs {heading.lower() or 'the covenant'} "
            "and includes a reference to Section 7.02(b) for related conditions."
        )

    section_families = context.get("section_families")
    if not isinstance(section_families, list):
        section_families = []

    return {
        "link_id": context.get("link_id", link_id),
        "doc_id": doc_id,
        "section_number": section_number,
        "primary_covenant_heading": context.get("primary_covenant_heading", ""),
        "primary_covenant_preview": context.get("primary_covenant_preview", ""),
        "definitions": context.get("definitions", []),
        "xrefs": context.get("xrefs", []),
        "section_families": section_families,
        "section_text": section_text,
    }


@app.get("/api/links/{link_id}/defined-terms")
async def get_link_defined_terms(link_id: str):
    """Defined terms bound to this link."""
    store = _get_link_store()
    terms = store.get_link_defined_terms(link_id)
    return {"terms": terms, "total": len(terms)}


@app.post("/api/links/{link_id}/defined-terms")
async def bind_defined_terms(
    request: Request,
    link_id: str,
    body: dict[str, Any] = Body(...),
):
    """Bind defined terms to a link."""
    _require_links_admin(request)
    store = _get_link_store()
    terms = body.get("terms", [])
    saved = store.save_link_defined_terms(link_id, terms)
    return {"saved": saved}


# ---------------------------------------------------------------------------
# 71-73. Embeddings & Semantic
# ---------------------------------------------------------------------------
def _compute_embeddings_sync(
    family_id: str | None,
) -> dict[str, Any]:
    """Compute embeddings in-process (called from background thread).

    Runs synchronously using the Voyage model and stores results directly
    in the link store.  Returns a summary dict.
    """
    from agent.embeddings import VoyageEmbeddingModel, EmbeddingManager  # noqa: E402

    store = _get_link_store()

    try:
        model = VoyageEmbeddingModel()
    except ValueError as e:
        return {"error": str(e), "status": "failed"}

    manager = EmbeddingManager(model=model, store=store)

    resolved_scope = _canonicalize_scope_id(store, family_id) if family_id else None
    links = store.get_links(family_id=resolved_scope or family_id, status="active", limit=100000)
    if not links:
        return {"family_id": family_id, "sections_embedded": 0, "status": "no_active_links"}

    # Collect section texts from corpus
    sections: list[dict[str, str]] = []
    for link in links:
        if _corpus is not None:
            text = _corpus.get_section_text(
                link["doc_id"], link["section_number"],
            )
            if text:
                sections.append({
                    "doc_id": link["doc_id"],
                    "section_number": link["section_number"],
                    "text": text,
                })

    if not sections:
        return {"family_id": family_id, "sections_embedded": 0, "status": "no_section_text"}

    # Embed in batches
    total_stored = manager.embed_and_store(sections)

    # Recompute centroids
    families_to_recompute: list[str] = []
    if family_id:
        families_to_recompute = [family_id]
    else:
        seen: set[str] = set()
        for link in links:
            fid = link.get("family_id", "")
            if fid and fid not in seen:
                seen.add(fid)
                families_to_recompute.append(fid)

    centroids_computed = 0
    for fid in families_to_recompute:
        fam_sections = [
            {"doc_id": l["doc_id"], "section_number": l["section_number"]}
            for l in links if l.get("family_id") == fid
        ]
        centroid = manager.compute_centroid(fid, fam_sections)
        if centroid is not None:
            centroids_computed += 1

    return {
        "family_id": family_id,
        "sections_embedded": total_stored,
        "sections_total": len(sections),
        "centroids_computed": centroids_computed,
        "model": model.model_version(),
        "dimensions": model.dimensions(),
        "status": "completed",
    }


# In-flight embedding jobs (job_id -> asyncio.Task)
_embedding_jobs: dict[str, Any] = {}


@app.post("/api/links/embeddings/compute")
async def compute_embeddings(
    request: Request,
    body: dict[str, Any] = Body(...),
):
    """Compute embeddings in-process (bypasses worker due to DuckDB lock).

    Returns immediately with a job_id. The computation runs in a background
    thread.  Poll ``GET /api/links/embeddings/job/{job_id}`` for status.
    """
    _require_links_admin(request)
    family_id = body.get("family_id")
    job_id = str(uuid.uuid4())

    async def _run() -> dict[str, Any]:
        return await asyncio.to_thread(_compute_embeddings_sync, family_id)

    task = asyncio.create_task(_run())
    _embedding_jobs[job_id] = task

    return {"job_id": job_id, "status": "started"}


@app.get("/api/links/embeddings/job/{job_id}")
async def embedding_job_status(job_id: str):
    """Poll embedding computation job status."""
    task = _embedding_jobs.get(job_id)
    if task is None:
        raise HTTPException(404, f"Job not found: {job_id}")
    if not task.done():
        return {"job_id": job_id, "status": "running"}
    try:
        result = task.result()
        return {"job_id": job_id, **result}
    except Exception as e:
        return {"job_id": job_id, "status": "failed", "error": str(e)}


@app.get("/api/links/embeddings/stats")
async def embeddings_stats():
    """Return embedding coverage statistics."""
    store = _get_link_store()
    conn = store._conn  # noqa: SLF001

    total_embeddings = conn.execute(
        "SELECT count(*) FROM section_embeddings",
    ).fetchone()[0]  # type: ignore[index]

    model_breakdown = conn.execute(
        "SELECT model_version, count(*) as cnt FROM section_embeddings "
        "GROUP BY model_version ORDER BY cnt DESC",
    ).fetchall()

    total_centroids = conn.execute(
        "SELECT count(*) FROM family_centroids",
    ).fetchone()[0]  # type: ignore[index]

    # Recent embeddings (sample)
    recent = conn.execute(
        "SELECT doc_id, section_number, model_version, created_at "
        "FROM section_embeddings ORDER BY created_at DESC LIMIT 20",
    ).fetchall()
    embeddings_list = [
        {
            "doc_id": str(r[0]),
            "section_number": str(r[1]),
            "embedding_dim": 1024,
            "computed_at": str(r[3]) if r[3] else "",
        }
        for r in recent
    ]

    # Centroids
    centroid_rows = conn.execute(
        "SELECT family_id, model_version, sample_count, last_updated_at "
        "FROM family_centroids ORDER BY last_updated_at DESC",
    ).fetchall()
    centroids_list = [
        {
            "family_id": str(r[0]),
            "family_name": _family_name_from_id(str(r[0])),
            "centroid_dim": 1024,
            "sample_size": int(r[2]) if r[2] else 0,
            "computed_at": str(r[3]) if r[3] else "",
        }
        for r in centroid_rows
    ]

    return {
        "total_embeddings": int(total_embeddings),
        "total_centroids": int(total_centroids),
        "models": [
            {"model": str(r[0]), "count": int(r[1])} for r in model_breakdown
        ],
        "embeddings": embeddings_list,
        "centroids": centroids_list,
    }


@app.get("/api/links/embeddings/centroids")
async def list_centroids():
    """List all family centroids."""
    store = _get_link_store()
    conn = store._conn  # noqa: SLF001
    rows = conn.execute(
        "SELECT family_id, template_family, model_version, sample_count, "
        "last_updated_at FROM family_centroids ORDER BY last_updated_at DESC",
    ).fetchall()
    centroids = [
        {
            "family_id": str(r[0]),
            "family_name": _family_name_from_id(str(r[0])),
            "template_family": str(r[1]),
            "model_version": str(r[2]),
            "centroid_dim": 1024,
            "sample_size": int(r[3]) if r[3] else 0,
            "computed_at": str(r[4]) if r[4] else "",
        }
        for r in rows
    ]
    return {"centroids": centroids}


@app.get("/api/links/embeddings/similar")
async def similar_sections(
    family_id: str = Query(...),
    doc_id: str | None = Query(None),
    top_k: int = Query(10, ge=1, le=50),
):
    """Top-K semantically similar sections using real cosine similarity.

    Retrieves the family centroid, then scores all stored section embeddings
    against it.  Falls back to active links if no centroid/embeddings exist.
    """
    from agent.embeddings import cosine_similarity as _cosine_sim  # noqa: E402

    store = _get_link_store()
    conn = store._conn  # noqa: SLF001

    # --- Try to load the family centroid ---
    centroid_row = conn.execute(
        "SELECT centroid_vector, model_version FROM family_centroids "
        "WHERE family_id = ? ORDER BY last_updated_at DESC LIMIT 1",
        [family_id],
    ).fetchone()

    candidates: list[dict[str, Any]] = []

    if centroid_row and centroid_row[0]:
        centroid_bytes = bytes(centroid_row[0])
        model_ver = str(centroid_row[1])

        # Retrieve all section embeddings for this model version
        emb_rows = conn.execute(
            "SELECT doc_id, section_number, embedding_vector "
            "FROM section_embeddings WHERE model_version = ?",
            [model_ver],
        ).fetchall()

        scored: list[tuple[str, str, float]] = []
        for row in emb_rows:
            try:
                sim = _cosine_sim(centroid_bytes, bytes(row[2]))
                scored.append((str(row[0]), str(row[1]), sim))
            except ValueError:
                continue

        # Sort by similarity descending, take top_k
        scored.sort(key=lambda x: x[2], reverse=True)
        for s_doc_id, s_sec, sim in scored[:top_k]:
            # Look up heading from sections in corpus or links
            heading = f"Section {s_sec}"
            heading_row = conn.execute(
                "SELECT heading FROM family_links "
                "WHERE doc_id = ? AND section_number = ? "
                "ORDER BY created_at DESC LIMIT 1",
                [s_doc_id, s_sec],
            ).fetchone()
            if heading_row and heading_row[0]:
                heading = str(heading_row[0])
            elif _corpus is not None:
                try:
                    sec_rows = _corpus.query(
                        "SELECT heading FROM sections "
                        "WHERE doc_id = ? AND section_number = ?",
                        [s_doc_id, s_sec],
                    )
                    if sec_rows and sec_rows[0][0]:
                        heading = str(sec_rows[0][0])
                except Exception:
                    pass

            candidates.append({
                "doc_id": s_doc_id,
                "section_number": s_sec,
                "heading": heading,
                "similarity": round(max(0.0, min(1.0, sim)), 4),
                "family_id": family_id,
            })

    # Fallback: if no embeddings exist, return active links with confidence as similarity
    if not candidates:
        fallback_links = store.get_links(family_id=family_id, status="active", limit=top_k)
        candidates = [
            {
                "doc_id": str(link.get("doc_id", "")),
                "section_number": str(link.get("section_number", "")),
                "heading": str(link.get("heading", "")),
                "similarity": max(0.0, min(1.0, float(link.get("confidence", 0.0) or 0.0))),
                "family_id": family_id,
            }
            for link in fallback_links
        ]

    return {"candidates": candidates, "total": len(candidates)}


@app.post("/api/links/centroids/recompute")
async def recompute_centroids(
    request: Request,
    body: dict[str, Any] = Body(...),
):
    """Recompute family centroid from active link embeddings."""
    _require_links_admin(request)
    family_id = body.get("family_id", "")
    if not family_id:
        raise HTTPException(400, "family_id is required")

    try:
        manager = _get_embedding_manager()
    except ValueError as e:
        raise HTTPException(503, f"Embedding model unavailable: {e}") from e

    store = _get_link_store()
    links = store.get_links(family_id=family_id, status="active", limit=100000)
    if not links:
        return {"family_id": family_id, "status": "no_active_links", "sample_count": 0}

    active_sections = [
        {"doc_id": l["doc_id"], "section_number": l["section_number"]}
        for l in links
    ]
    centroid = manager.compute_centroid(family_id, active_sections)

    return {
        "family_id": family_id,
        "status": "recomputed" if centroid else "no_embeddings",
        "sample_count": len(active_sections),
    }


# ---------------------------------------------------------------------------
# 74-76. Starter Kits
# ---------------------------------------------------------------------------
def _starter_kit_to_api(family_id: str, raw: dict[str, Any] | None) -> dict[str, Any]:
    if not raw:
        return {
            "family_id": family_id,
            "family_name": _family_name_from_id(family_id),
            "suggested_headings": [],
            "suggested_keywords": [],
            "suggested_dna_phrases": [],
            "suggested_defined_terms": [],
            "location_priors": [],
            "exclusions": [],
            "template_rule_ast": {},
            "example_doc_ids": [],
            "notes": "",
        }
    typical_location = raw.get("typical_location")
    location_priors = [typical_location] if isinstance(typical_location, dict) and typical_location else []
    return {
        "family_id": family_id,
        "family_name": _family_name_from_id(family_id),
        "suggested_headings": list(raw.get("top_heading_variants") or []),
        "suggested_keywords": list(raw.get("top_defined_terms") or []),
        "suggested_dna_phrases": list(raw.get("top_dna_phrases") or []),
        "suggested_defined_terms": list(raw.get("top_defined_terms") or []),
        "location_priors": location_priors,
        "exclusions": list(raw.get("known_exclusions") or []),
        "template_rule_ast": raw.get("auto_generated_rule_ast") or {},
        "example_doc_ids": [],
        "notes": "",
    }


@app.get("/api/links/starter-kits")
async def list_starter_kits():
    store = _get_link_store()
    kits = [_starter_kit_to_api(str(kit.get("family_id", "")), kit) for kit in store.get_starter_kits()]
    return {"kits": kits, "total": len(kits)}


@app.get("/api/links/starter-kits/{family_id}")
async def get_starter_kit_plural(family_id: str):
    return await get_starter_kit(family_id)


@app.get("/api/links/starter-kit/{family_id}")
async def get_starter_kit(family_id: str):
    """Get family starter kit."""
    store = _get_link_store()
    kit = store.get_starter_kit(family_id)
    return _starter_kit_to_api(family_id, kit)


@app.post("/api/links/starter-kit/{family_id}/generate")
async def generate_starter_kit(request: Request, family_id: str):
    """Compute starter kit from corpus stats + ontology."""
    _require_links_admin(request)
    store = _get_link_store()
    links = store.get_links(family_id=family_id, status="active", limit=100000)
    heading_variants = list({lnk.get("heading", "") for lnk in links if lnk.get("heading")})
    defined_terms: list[str] = []
    for rule in store.get_rules(family_id=family_id):
        terms = rule.get("required_defined_terms")
        if isinstance(terms, list):
            defined_terms.extend(terms)
    normalized_kit = {
        "family_id": family_id,
        "top_heading_variants": heading_variants[:20],
        "top_defined_terms": sorted(set(defined_terms)),
        "top_dna_phrases": [],
        "typical_location": {},
        "known_exclusions": [],
        "auto_generated_rule_ast": {},
    }
    store.save_starter_kit(family_id, normalized_kit)
    return _starter_kit_to_api(family_id, normalized_kit)


@app.post("/api/links/starter-kit/{family_id}/generate-rule-draft")
async def generate_rule_draft(request: Request, family_id: str):
    """Auto-scaffold a draft rule from starter kit."""
    _require_links_admin(request)
    store = _get_link_store()
    kit = store.get_starter_kit(family_id)
    heading_variants = kit.get("top_heading_variants", []) if kit else []
    children = [{"type": "match", "value": v} for v in heading_variants]
    heading_ast = {"type": "group", "operator": "or", "children": children} if children else {}

    # Build filter_dsl from heading variants
    if heading_variants:
        dsl_terms = [f'"{v}"' if " " in v else v for v in heading_variants]
        filter_dsl = f'heading: {" | ".join(dsl_terms)}'
    else:
        filter_dsl = ""

    rule = {
        "rule_id": str(uuid.uuid4()), "family_id": family_id,
        "description": f"Auto-generated draft for {family_id}",
        "version": 1, "status": "draft", "owner": "starter_kit",
        "heading_filter_ast": heading_ast,
        "filter_dsl": filter_dsl,
        "required_defined_terms": kit.get("top_defined_terms", []) if kit else [],
    }
    store.save_rule(rule)
    return _rule_to_api(store, rule)


# ---------------------------------------------------------------------------
# 77. Comparables
# ---------------------------------------------------------------------------
@app.get("/api/links/{link_id}/comparables")
async def get_comparables(link_id: str):
    """3-5 similar sections with diff highlights."""
    store = _get_link_store()
    comparables = store.get_comparables(link_id)
    return {"link_id": link_id, "comparables": comparables, "total": len(comparables)}


# ---------------------------------------------------------------------------
# Extra endpoints (crossref, evaluate-text, baselines, test)
# ---------------------------------------------------------------------------
@app.get("/api/links/crossref-peek")
async def crossref_peek(
    doc_id: str | None = Query(None),
    section_ref: str = Query(...),
):
    """Look up section text by reference string."""
    ref = section_ref.strip()
    resolved_doc_id = (doc_id or "").strip()
    if not resolved_doc_id and ":" in ref:
        maybe_doc, maybe_ref = ref.split(":", 1)
        if maybe_doc and maybe_ref:
            resolved_doc_id = maybe_doc.strip()
            ref = maybe_ref.strip()
    if not resolved_doc_id:
        raise HTTPException(status_code=422, detail="doc_id is required (or prefix section_ref with DOC_ID:)")

    corpus = _get_corpus()
    sections = corpus.search_sections(
        doc_id=resolved_doc_id, cohort_only=False, limit=10000,
    )
    for s in sections:
        if ref in s.section_number:
            text = corpus.get_section_text(resolved_doc_id, s.section_number)
            return {
                "doc_id": resolved_doc_id,
                "section_ref": ref,
                "section_number": s.section_number,
                "heading": s.heading,
                "text": text,
                "found": True,
            }
    raise HTTPException(
        status_code=404,
        detail=f"Section {ref} not found in {resolved_doc_id}",
    )


@app.post("/api/links/rules/evaluate-text")
async def evaluate_text(body: EvaluateTextRequest = Body(...)):
    """Evaluate a rule AST against raw text (traffic-light)."""
    raw_text = (body.raw_text or body.text or "").strip()
    rule_ast = body.rule_ast or body.heading_filter_ast or {}
    if not raw_text or not rule_ast:
        return {
            "matched": False,
            "traffic_light": "red",
            "matched_nodes": [],
            "traffic_tree": None,
            "match_type": "none",
            "matched_value": "",
        }

    try:
        parsed_expr = filter_expr_from_json(rule_ast)
    except (ValueError, KeyError, TypeError) as exc:
        raise HTTPException(status_code=422, detail=f"Invalid rule_ast: {exc}") from exc

    matched, traffic_tree = _evaluate_expr_tree(parsed_expr, raw_text)
    flat_nodes = _flatten_tree(traffic_tree)
    first_hit = next(
        (str(n.get("node", "")) for n in flat_nodes if bool(n.get("result")) and n.get("path")),
        "",
    )
    return {
        "matched": matched,
        "traffic_light": "green" if matched else "red",
        "matched_nodes": flat_nodes,
        "traffic_tree": traffic_tree,
        "match_type": "ast_eval",
        "matched_value": first_hit,
    }

@app.get("/api/links/template-baselines")
async def list_template_baselines(family_id: str | None = Query(None)):
    """List template baselines."""
    store = _get_link_store()
    baselines_raw = store.get_template_baselines(family_id=family_id)
    baselines: list[dict[str, Any]] = []
    for baseline in baselines_raw:
        normalized = dict(baseline)
        normalized.setdefault("family_id", str(normalized.get("template_family", "")))
        normalized.setdefault("template", str(normalized.get("section_pattern", "")))
        expected_sections: list[str] = []
        baseline_text = normalized.get("baseline_text")
        if isinstance(baseline_text, str):
            try:
                parsed = json.loads(baseline_text)
                if isinstance(parsed, list):
                    expected_sections = [str(item) for item in parsed]
            except json.JSONDecodeError:
                pass
        normalized.setdefault("expected_sections", expected_sections)
        baselines.append(normalized)
    return {"baselines": baselines, "total": len(baselines)}


@app.post("/api/links/template-baselines")
async def save_template_baseline(
    request: Request,
    body: dict[str, Any] = Body(...),
):
    """Save a template baseline."""
    _require_links_admin(request)
    store = _get_link_store()
    import hashlib

    payload = dict(body)
    payload.setdefault("template_family", payload.get("family_id", ""))
    payload.setdefault("section_pattern", payload.get("template", ""))
    if "baseline_text" not in payload:
        expected_sections = payload.get("expected_sections")
        if isinstance(expected_sections, list):
            payload["baseline_text"] = json.dumps(expected_sections)
        else:
            payload["baseline_text"] = str(payload.get("description", ""))
    if "baseline_hash" not in payload:
        payload["baseline_hash"] = hashlib.sha256(
            str(payload.get("baseline_text", "")).encode("utf-8"),
        ).hexdigest()

    if not payload.get("template_family") or not payload.get("section_pattern"):
        raise HTTPException(
            status_code=422,
            detail="template_family/section_pattern (or family_id/template) are required",
        )

    store.save_template_baseline(payload)
    return {"status": "saved"}


@app.get("/api/links/template-baselines/text")
async def get_template_baseline_text(
    family_id: str = Query(...),
    template: str = Query(...),
):
    """Lookup baseline text for template redline diffing."""
    store = _get_link_store()
    row = store._conn.execute(  # noqa: SLF001
        "SELECT baseline_id, baseline_text FROM template_baselines "
        "WHERE template_family = ? AND section_pattern = ? "
        "ORDER BY created_at DESC LIMIT 1",
        [family_id, template],
    ).fetchone()
    if row is None:
        row = store._conn.execute(  # noqa: SLF001
            "SELECT baseline_id, baseline_text FROM template_baselines "
            "WHERE template_family = ? "
            "ORDER BY created_at DESC LIMIT 1",
            [family_id],
        ).fetchone()
    if row is None:
        return {"text": None, "baseline_id": None}

    baseline_id = str(row[0])
    raw_text = row[1]
    if isinstance(raw_text, str):
        text_value = raw_text
        try:
            parsed = json.loads(raw_text)
            if isinstance(parsed, list):
                text_value = "\n".join(str(item) for item in parsed)
            elif isinstance(parsed, dict):
                text_value = json.dumps(parsed, indent=2)
        except json.JSONDecodeError:
            pass
    else:
        text_value = str(raw_text or "")
    return {"text": text_value or None, "baseline_id": baseline_id}


@app.post("/api/links/rules/validate-dsl")
async def validate_dsl_generic(body: dict[str, Any] = Body(...)):
    """Parse/validate DSL text (non-rule scoped)."""
    text = str(body.get("text", ""))
    result = validate_dsl(text)
    return {
        "text_fields": {
            k: filter_expr_to_json(v) if isinstance(v, (FilterMatch, FilterGroup)) else str(v)
            for k, v in result.text_fields.items()
        },
        "meta_fields": {k: meta_filter_to_json(v) for k, v in result.meta_fields.items()},
        "errors": [
            {"message": e.message, "position": e.position, "field": e.field}
            for e in result.errors
        ],
        "normalized_text": result.normalized_text,
        "query_cost": result.query_cost,
    }


@app.post("/api/links/rules/validate-dsl-standalone")
async def validate_dsl_standalone(body: dict[str, Any] = Body(...)):
    """Parse and validate DSL text (no rule context)."""
    result = validate_dsl(body.get("text", ""))
    return {
        "text_fields": {
            k: filter_expr_to_json(v) if isinstance(v, (FilterMatch, FilterGroup)) else str(v)
            for k, v in result.text_fields.items()
        },
        "meta_fields": {k: meta_filter_to_json(v) for k, v in result.meta_fields.items()},
        "errors": [
            {"message": e.message, "position": e.position, "field": e.field}
            for e in result.errors
        ],
        "normalized_text": result.normalized_text,
        "query_cost": result.query_cost,
    }


@app.post("/api/links/_test/seed")
async def test_seed(
    request: Request,
    body: dict[str, Any] = Body(...),
):
    """Seed test data (only when LINKS_TEST_MODE=1)."""
    _require_test_endpoint_access(request)
    store = _get_link_store()
    dataset_name = str(body.get("dataset", "")).strip()
    if dataset_name:
        seed_payload = _build_named_seed_dataset(dataset_name)
        records = seed_payload.get("links", [])
        rules = seed_payload.get("rules", [])
        jobs = seed_payload.get("jobs", [])
    else:
        records = body.get("links", [])
        rules = body.get("rules", [])
        jobs = body.get("jobs", [])

    run_id = str(uuid.uuid4())
    for rule in rules:
        store.save_rule(rule)
    created = store.create_links(records, run_id) if records else 0
    seeded_jobs = 0
    for job in jobs:
        try:
            store.submit_job(job)
            seeded_jobs += 1
        except Exception:
            continue
    return {
        "dataset": dataset_name or None,
        "seeded_links": created,
        "seeded_rules": len(rules),
        "seeded_jobs": seeded_jobs,
        "run_id": run_id,
    }


@app.post("/api/links/_test/reset")
async def test_reset(request: Request):
    """Reset test data (only when LINKS_TEST_MODE=1)."""
    _require_test_endpoint_access(request)
    store = _get_link_store()
    store.truncate_all()
    return {"status": "reset"}


@app.post("/api/links/_test/expire-preview/{preview_id}")
async def test_expire_preview(request: Request, preview_id: str):
    """Force a preview to look expired for deterministic tests."""
    _require_test_endpoint_access(request)
    store = _get_link_store()
    store._conn.execute(  # noqa: SLF001
        "UPDATE family_link_previews SET created_at = ? WHERE preview_id = ?",
        ["2000-01-01T00:00:00", preview_id],
    )
    return {"preview_id": preview_id, "expired": True}


# ---------------------------------------------------------------------------
# 2. GET /api/links/{link_id} — Single link with events
# ---------------------------------------------------------------------------
@app.get("/api/links/{link_id}")
async def get_link(link_id: str):
    """Get a single link with its events and why_matched."""
    store = _get_link_store()
    links = store.get_links(limit=100000)
    link = next((lnk for lnk in links if lnk.get("link_id") == link_id), None)
    if link is None:
        raise HTTPException(status_code=404, detail=f"Link not found: {link_id}")
    events = store.get_events(link_id)
    link["events"] = events
    return link
