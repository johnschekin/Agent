"""DuckDB read/write store for the family linking system.

Manages ``corpus_index/links.duckdb`` — a separate writable DuckDB database
(the main corpus DB remains read-only). Contains 28+ tables covering:

* Family link rules, links, events, evidence, runs, previews, candidates
* Calibrations, job queue, action log (undo/redo), pins, pin evaluations
* Review sessions, review marks, drift baselines/checks/alerts
* Macros, template baselines, link defined terms
* Child-node linking (rules, links, previews, candidates, evidence)
* Embeddings (section embeddings, family centroids)
* Starter kits, conflict policies

Write discipline: the worker subprocess is the sole heavy writer.
The API server only writes to ``job_queue`` and lightweight session tables.
"""
from __future__ import annotations

import contextlib
import importlib
import json
import re
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from agent.query_filters import (
    FilterExpression,
    build_filter_sql,
    filter_expr_from_json,
    filter_expr_to_json,
)
from agent.rule_dsl import (
    dsl_from_heading_ast,
    heading_ast_from_dsl,
)

# Dynamic DuckDB import for pyright compatibility
_duckdb_mod = importlib.import_module("duckdb")

# orjson with stdlib fallback
_orjson: Any
try:
    import orjson  # type: ignore[import-untyped]
    _orjson = orjson
except ImportError:
    _orjson = None


def _json_dumps(obj: Any) -> str:
    if _orjson is not None:
        return _orjson.dumps(obj).decode("utf-8")
    return json.dumps(obj)


def _json_loads(s: str) -> Any:
    if _orjson is not None:
        return _orjson.loads(s)
    return json.loads(s)


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _to_dict(cols: list[str], row: tuple[Any, ...]) -> dict[str, Any]:
    """Zip column names with a row tuple into a dict (strict length check)."""
    return dict(zip(cols, row, strict=True))


def _opt_json(d: dict[str, Any], key: str) -> str | None:
    """Return JSON-encoded value for *key* if present, else None."""
    val = d.get(key)
    return _json_dumps(val) if val else None


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


SCHEMA_VERSION = "1.1.0"


# ---------------------------------------------------------------------------
# Schema DDL
# ---------------------------------------------------------------------------

_SCHEMA_DDL = """
-- Schema version tracking
CREATE TABLE IF NOT EXISTS _schema_version (
    table_name VARCHAR PRIMARY KEY,
    version VARCHAR NOT NULL
);

-- ─── FAMILY LINK RULES ────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS family_link_rules (
    rule_id VARCHAR PRIMARY KEY,
    family_id VARCHAR NOT NULL,
    ontology_node_id VARCHAR,
    parent_family_id VARCHAR,
    parent_rule_id VARCHAR,
    parent_run_id VARCHAR,
    scope_mode VARCHAR NOT NULL DEFAULT 'corpus',
    name VARCHAR NOT NULL DEFAULT '',
    description VARCHAR NOT NULL DEFAULT '',
    version INTEGER NOT NULL DEFAULT 1,
    status VARCHAR NOT NULL DEFAULT 'draft',
    owner VARCHAR NOT NULL DEFAULT '',
    locked_by VARCHAR,
    locked_at TIMESTAMP,
    article_concepts VARCHAR NOT NULL,
    heading_filter_ast VARCHAR NOT NULL,
    filter_dsl VARCHAR NOT NULL DEFAULT '',
    result_granularity VARCHAR NOT NULL DEFAULT 'section',
    clause_text_filter_ast VARCHAR,
    clause_header_filter_ast VARCHAR,
    required_defined_terms VARCHAR,
    excluded_cue_phrases VARCHAR,
    template_overrides VARCHAR,
    created_at TIMESTAMP DEFAULT current_timestamp,
    updated_at TIMESTAMP DEFAULT current_timestamp
);

-- ─── FAMILY SCOPE ALIASES ────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS family_scope_aliases (
    legacy_family_id VARCHAR PRIMARY KEY,
    canonical_ontology_node_id VARCHAR NOT NULL,
    source VARCHAR NOT NULL DEFAULT 'inferred',
    created_at TIMESTAMP DEFAULT current_timestamp,
    updated_at TIMESTAMP DEFAULT current_timestamp
);
CREATE INDEX IF NOT EXISTS idx_family_scope_aliases_canonical
    ON family_scope_aliases(canonical_ontology_node_id);

-- ─── FAMILY LINKS ─────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS family_links (
    link_id VARCHAR PRIMARY KEY,
    family_id VARCHAR NOT NULL,
    ontology_node_id VARCHAR,
    doc_id VARCHAR NOT NULL,
    section_number VARCHAR NOT NULL,
    heading VARCHAR NOT NULL DEFAULT '',
    article_num INTEGER NOT NULL DEFAULT 0,
    article_concept VARCHAR NOT NULL DEFAULT '',
    rule_id VARCHAR,
    rule_version INTEGER,
    rule_hash VARCHAR,
    run_id VARCHAR NOT NULL,
    source VARCHAR NOT NULL DEFAULT 'bulk_linker',
    section_char_start INTEGER,
    section_char_end INTEGER,
    section_text_hash VARCHAR,
    clause_id VARCHAR,
    clause_char_start INTEGER,
    clause_char_end INTEGER,
    clause_text VARCHAR,
    link_role VARCHAR NOT NULL DEFAULT 'primary_covenant',
    confidence DOUBLE NOT NULL DEFAULT 1.0,
    confidence_tier VARCHAR NOT NULL DEFAULT 'high',
    confidence_breakdown VARCHAR,
    status VARCHAR NOT NULL DEFAULT 'active',
    unlinked_at TIMESTAMP,
    unlinked_reason VARCHAR,
    unlinked_note VARCHAR,
    corpus_version VARCHAR,
    parser_version VARCHAR,
    created_at TIMESTAMP DEFAULT current_timestamp,
    UNIQUE (family_id, doc_id, section_number)
);
CREATE INDEX IF NOT EXISTS idx_links_family ON family_links(family_id);
CREATE INDEX IF NOT EXISTS idx_links_doc ON family_links(doc_id);
CREATE INDEX IF NOT EXISTS idx_links_status ON family_links(status);
CREATE INDEX IF NOT EXISTS idx_links_tier ON family_links(confidence_tier);
CREATE INDEX IF NOT EXISTS idx_links_run ON family_links(run_id);
CREATE INDEX IF NOT EXISTS idx_links_char ON family_links(doc_id, section_char_start);

-- ─── FAMILY LINK EVENTS ──────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS family_link_events (
    event_id VARCHAR PRIMARY KEY,
    link_id VARCHAR NOT NULL,
    event_type VARCHAR NOT NULL,
    actor VARCHAR NOT NULL DEFAULT '',
    reason VARCHAR,
    note VARCHAR,
    metadata VARCHAR,
    created_at TIMESTAMP DEFAULT current_timestamp
);
CREATE INDEX IF NOT EXISTS idx_events_link ON family_link_events(link_id);
CREATE INDEX IF NOT EXISTS idx_events_type ON family_link_events(event_type);

-- ─── LINK EVIDENCE ───────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS link_evidence (
    evidence_id VARCHAR PRIMARY KEY,
    link_id VARCHAR NOT NULL,
    evidence_type VARCHAR NOT NULL,
    char_start INTEGER NOT NULL,
    char_end INTEGER NOT NULL,
    text_hash VARCHAR NOT NULL,
    matched_pattern VARCHAR,
    reason_code VARCHAR NOT NULL,
    score DOUBLE NOT NULL DEFAULT 1.0,
    metadata VARCHAR
);
CREATE INDEX IF NOT EXISTS idx_evidence_link ON link_evidence(link_id);
CREATE INDEX IF NOT EXISTS idx_evidence_type ON link_evidence(evidence_type);
CREATE INDEX IF NOT EXISTS idx_evidence_char ON link_evidence(link_id, char_start);

-- ─── LINK DEFINED TERMS ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS link_defined_terms (
    id VARCHAR PRIMARY KEY,
    link_id VARCHAR NOT NULL,
    term VARCHAR NOT NULL,
    definition_section_path VARCHAR NOT NULL,
    definition_char_start INTEGER NOT NULL,
    definition_char_end INTEGER NOT NULL,
    confidence DOUBLE NOT NULL DEFAULT 1.0,
    extraction_engine VARCHAR NOT NULL DEFAULT 'definitions',
    created_at TIMESTAMP DEFAULT current_timestamp,
    UNIQUE (link_id, term)
);
CREATE INDEX IF NOT EXISTS idx_ldt_link ON link_defined_terms(link_id);
CREATE INDEX IF NOT EXISTS idx_ldt_term ON link_defined_terms(term);

-- ─── FAMILY LINK RUNS ────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS family_link_runs (
    run_id VARCHAR PRIMARY KEY,
    run_type VARCHAR NOT NULL,
    family_id VARCHAR,
    rule_id VARCHAR,
    parent_family_id VARCHAR,
    parent_run_id VARCHAR,
    scope_mode VARCHAR NOT NULL DEFAULT 'corpus',
    rule_version INTEGER,
    corpus_version VARCHAR NOT NULL,
    corpus_doc_count INTEGER NOT NULL,
    parser_version VARCHAR NOT NULL,
    links_created INTEGER NOT NULL DEFAULT 0,
    links_skipped_existing INTEGER NOT NULL DEFAULT 0,
    links_skipped_low_confidence INTEGER NOT NULL DEFAULT 0,
    conflicts_detected INTEGER NOT NULL DEFAULT 0,
    outlier_count INTEGER NOT NULL DEFAULT 0,
    preview_summary VARCHAR,
    started_at TIMESTAMP DEFAULT current_timestamp,
    completed_at TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_runs_family ON family_link_runs(family_id);

-- ─── FAMILY LINK PREVIEWS ────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS family_link_previews (
    preview_id VARCHAR PRIMARY KEY,
    family_id VARCHAR NOT NULL,
    ontology_node_id VARCHAR,
    rule_id VARCHAR,
    rule_hash VARCHAR NOT NULL,
    corpus_version VARCHAR NOT NULL,
    parser_version VARCHAR NOT NULL,
    candidate_set_hash VARCHAR NOT NULL,
    candidate_count INTEGER NOT NULL DEFAULT 0,
    new_link_count INTEGER NOT NULL DEFAULT 0,
    already_linked_count INTEGER NOT NULL DEFAULT 0,
    conflict_count INTEGER NOT NULL DEFAULT 0,
    by_confidence_tier VARCHAR NOT NULL DEFAULT '{}',
    avg_confidence DOUBLE DEFAULT 0.0,
    params_json VARCHAR,
    expires_at TIMESTAMP NOT NULL,
    applied_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT current_timestamp
);

-- ─── PREVIEW CANDIDATES ──────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS preview_candidates (
    preview_id VARCHAR NOT NULL,
    doc_id VARCHAR NOT NULL,
    section_number VARCHAR NOT NULL,
    heading VARCHAR,
    article_num INTEGER,
    article_concept VARCHAR,
    template_family VARCHAR,
    confidence DOUBLE NOT NULL DEFAULT 0.0,
    confidence_tier VARCHAR NOT NULL DEFAULT 'high',
    confidence_breakdown VARCHAR,
    why_matched VARCHAR,
    priority_score DOUBLE NOT NULL DEFAULT 0.0,
    uncertainty_score DOUBLE NOT NULL DEFAULT 0.0,
    impact_score DOUBLE NOT NULL DEFAULT 0.0,
    drift_score DOUBLE NOT NULL DEFAULT 0.0,
    flags VARCHAR,
    conflict_families VARCHAR,
    clause_id VARCHAR,
    clause_path VARCHAR,
    clause_label VARCHAR,
    clause_char_start INTEGER,
    clause_char_end INTEGER,
    clause_text VARCHAR,
    user_verdict VARCHAR,
    verdict_at TIMESTAMP,
    PRIMARY KEY (preview_id, doc_id, section_number)
);
CREATE INDEX IF NOT EXISTS idx_pc_priority
    ON preview_candidates(preview_id, priority_score DESC, doc_id);
CREATE INDEX IF NOT EXISTS idx_pc_confidence
    ON preview_candidates(preview_id, confidence DESC, doc_id);
CREATE INDEX IF NOT EXISTS idx_pc_uncertainty
    ON preview_candidates(preview_id, uncertainty_score DESC);
CREATE INDEX IF NOT EXISTS idx_pc_verdict ON preview_candidates(preview_id, user_verdict);
CREATE INDEX IF NOT EXISTS idx_pc_tier ON preview_candidates(preview_id, confidence_tier);

-- ─── FAMILY LINK CALIBRATIONS ────────────────────────────────────────
CREATE TABLE IF NOT EXISTS family_link_calibrations (
    family_id VARCHAR NOT NULL,
    template_family VARCHAR NOT NULL DEFAULT '_global',
    high_threshold DOUBLE NOT NULL DEFAULT 0.8,
    medium_threshold DOUBLE NOT NULL DEFAULT 0.5,
    target_precision DOUBLE NOT NULL DEFAULT 0.9,
    sample_size INTEGER NOT NULL DEFAULT 0,
    expected_review_load INTEGER NOT NULL DEFAULT 0,
    queue_weights VARCHAR,
    last_calibrated_at TIMESTAMP,
    PRIMARY KEY (family_id, template_family)
);

-- ─── JOB QUEUE ───────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS job_queue (
    job_id VARCHAR PRIMARY KEY,
    job_type VARCHAR NOT NULL,
    status VARCHAR NOT NULL DEFAULT 'pending',
    idempotency_key VARCHAR UNIQUE,
    params_json VARCHAR NOT NULL,
    result_json VARCHAR,
    error_message VARCHAR,
    progress_pct DOUBLE NOT NULL DEFAULT 0.0,
    progress_message VARCHAR DEFAULT 'Queued',
    worker_pid INTEGER,
    submitted_at TIMESTAMP DEFAULT current_timestamp,
    claimed_at TIMESTAMP,
    completed_at TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON job_queue(status);

-- ─── ACTION LOG + UNDO STATE ─────────────────────────────────────────
CREATE SEQUENCE IF NOT EXISTS action_seq START 1;

CREATE TABLE IF NOT EXISTS action_log (
    action_id BIGINT PRIMARY KEY DEFAULT nextval('action_seq'),
    batch_id VARCHAR NOT NULL,
    batch_label VARCHAR NOT NULL,
    entity_type VARCHAR NOT NULL,
    entity_id VARCHAR NOT NULL,
    operation VARCHAR NOT NULL,
    forward_patch VARCHAR NOT NULL,
    reverse_patch VARCHAR NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT current_timestamp,
    created_by VARCHAR DEFAULT 'user'
);

CREATE TABLE IF NOT EXISTS undo_state (
    id INTEGER PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    current_position BIGINT NOT NULL DEFAULT 0
);

-- ─── RULE PINS + PIN EVALUATIONS ─────────────────────────────────────
CREATE TABLE IF NOT EXISTS rule_pins (
    pin_id VARCHAR PRIMARY KEY,
    rule_id VARCHAR NOT NULL,
    doc_id VARCHAR NOT NULL,
    section_number VARCHAR NOT NULL,
    expected VARCHAR NOT NULL,
    note VARCHAR,
    created_at TIMESTAMP DEFAULT current_timestamp,
    UNIQUE (rule_id, doc_id, section_number)
);
CREATE INDEX IF NOT EXISTS idx_pins_rule ON rule_pins(rule_id);

CREATE TABLE IF NOT EXISTS pin_evaluations (
    eval_id VARCHAR PRIMARY KEY,
    rule_id VARCHAR NOT NULL,
    rule_version INTEGER NOT NULL,
    evaluated_at TIMESTAMP DEFAULT current_timestamp,
    total_pins INTEGER NOT NULL,
    passed INTEGER NOT NULL,
    failed INTEGER NOT NULL,
    results_json VARCHAR NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_pin_evals ON pin_evaluations(rule_id, evaluated_at DESC);

-- ─── FAMILY CONFLICT POLICIES ────────────────────────────────────────
CREATE TABLE IF NOT EXISTS family_conflict_policies (
    family_a VARCHAR NOT NULL,
    family_b VARCHAR NOT NULL,
    policy VARCHAR NOT NULL,
    reason VARCHAR NOT NULL,
    edge_types VARCHAR NOT NULL,
    ontology_version VARCHAR NOT NULL,
    PRIMARY KEY (family_a, family_b)
);
CREATE INDEX IF NOT EXISTS idx_fcp_policy ON family_conflict_policies(policy);

-- ─── REVIEW SESSIONS + REVIEW MARKS ─────────────────────────────────
CREATE TABLE IF NOT EXISTS review_sessions (
    session_id VARCHAR PRIMARY KEY,
    scope_type VARCHAR NOT NULL,
    scope_id VARCHAR NOT NULL,
    started_at TIMESTAMP DEFAULT current_timestamp,
    last_active_at TIMESTAMP DEFAULT current_timestamp,
    last_cursor VARCHAR,
    rows_viewed INTEGER DEFAULT 0,
    rows_acted_on INTEGER DEFAULT 0,
    rows_bookmarked INTEGER DEFAULT 0,
    status VARCHAR DEFAULT 'active'
);
CREATE INDEX IF NOT EXISTS idx_sessions_scope ON review_sessions(scope_type, scope_id);

CREATE TABLE IF NOT EXISTS review_marks (
    session_id VARCHAR NOT NULL,
    doc_id VARCHAR NOT NULL,
    section_number VARCHAR NOT NULL,
    mark_type VARCHAR NOT NULL,
    note VARCHAR,
    created_at TIMESTAMP DEFAULT current_timestamp,
    PRIMARY KEY (session_id, doc_id, section_number, mark_type)
);
CREATE INDEX IF NOT EXISTS idx_marks_type ON review_marks(session_id, mark_type);

-- ─── RULE BASELINES + DRIFT CHECKS + DRIFT ALERTS ──────────────────
CREATE TABLE IF NOT EXISTS rule_baselines (
    baseline_id VARCHAR PRIMARY KEY,
    rule_id VARCHAR NOT NULL,
    rule_version INTEGER NOT NULL,
    promoted_at TIMESTAMP NOT NULL,
    total_docs INTEGER NOT NULL,
    total_hits INTEGER NOT NULL,
    overall_hit_rate DOUBLE NOT NULL,
    profile_json VARCHAR NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_baselines_rule ON rule_baselines(rule_id, promoted_at DESC);

CREATE TABLE IF NOT EXISTS drift_checks (
    check_id VARCHAR PRIMARY KEY,
    rule_id VARCHAR NOT NULL,
    baseline_id VARCHAR NOT NULL,
    checked_at TIMESTAMP DEFAULT current_timestamp,
    overall_hit_rate DOUBLE NOT NULL,
    chi2_statistic DOUBLE NOT NULL,
    p_value DOUBLE NOT NULL,
    max_cell_delta DOUBLE NOT NULL,
    drift_detected BOOLEAN NOT NULL,
    current_profile_json VARCHAR NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_drift_rule ON drift_checks(rule_id, checked_at DESC);

CREATE TABLE IF NOT EXISTS drift_alerts (
    alert_id VARCHAR PRIMARY KEY,
    rule_id VARCHAR NOT NULL,
    check_id VARCHAR NOT NULL,
    severity VARCHAR NOT NULL,
    message VARCHAR NOT NULL,
    cells_affected VARCHAR NOT NULL,
    acknowledged BOOLEAN DEFAULT FALSE,
    acknowledged_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT current_timestamp
);
CREATE INDEX IF NOT EXISTS idx_drift_alerts_open ON drift_alerts(acknowledged, severity);

-- ─── FAMILY LINK MACROS ──────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS family_link_macros (
    macro_id VARCHAR PRIMARY KEY,
    family_id VARCHAR NOT NULL DEFAULT '_global',
    name VARCHAR NOT NULL,
    description VARCHAR NOT NULL DEFAULT '',
    ast_json VARCHAR NOT NULL,
    created_by VARCHAR NOT NULL DEFAULT '',
    created_at TIMESTAMP DEFAULT current_timestamp,
    updated_at TIMESTAMP DEFAULT current_timestamp,
    UNIQUE (family_id, name)
);
CREATE INDEX IF NOT EXISTS idx_macros_family ON family_link_macros(family_id);

-- ─── TEMPLATE BASELINES ──────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS template_baselines (
    baseline_id VARCHAR PRIMARY KEY,
    template_family VARCHAR NOT NULL,
    section_pattern VARCHAR NOT NULL,
    baseline_text VARCHAR NOT NULL,
    baseline_hash VARCHAR NOT NULL,
    source VARCHAR NOT NULL DEFAULT '',
    created_at TIMESTAMP DEFAULT current_timestamp,
    UNIQUE (template_family, section_pattern)
);
CREATE INDEX IF NOT EXISTS idx_tbl_template ON template_baselines(template_family);

-- ─── EMBEDDINGS ──────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS section_embeddings (
    doc_id VARCHAR NOT NULL,
    section_number VARCHAR NOT NULL,
    embedding_vector BLOB NOT NULL,
    model_version VARCHAR NOT NULL,
    text_hash VARCHAR NOT NULL,
    created_at TIMESTAMP DEFAULT current_timestamp,
    PRIMARY KEY (doc_id, section_number, model_version)
);
CREATE INDEX IF NOT EXISTS idx_se_hash ON section_embeddings(text_hash);

CREATE TABLE IF NOT EXISTS family_centroids (
    family_id VARCHAR NOT NULL,
    template_family VARCHAR NOT NULL DEFAULT '_global',
    centroid_vector BLOB NOT NULL,
    model_version VARCHAR NOT NULL,
    sample_count INTEGER NOT NULL,
    last_updated_at TIMESTAMP DEFAULT current_timestamp,
    PRIMARY KEY (family_id, template_family, model_version)
);

-- ─── FAMILY STARTER KITS ────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS family_starter_kits (
    family_id VARCHAR PRIMARY KEY,
    typical_location VARCHAR NOT NULL DEFAULT '{}',
    top_heading_variants VARCHAR NOT NULL DEFAULT '[]',
    top_defined_terms VARCHAR NOT NULL DEFAULT '[]',
    top_dna_phrases VARCHAR NOT NULL DEFAULT '[]',
    known_exclusions VARCHAR NOT NULL DEFAULT '[]',
    auto_generated_rule_ast VARCHAR,
    last_computed_at TIMESTAMP DEFAULT current_timestamp
);
"""


# ---------------------------------------------------------------------------
# LinkStore class
# ---------------------------------------------------------------------------

class LinkStore:
    """Read/write interface to ``corpus_index/links.duckdb``."""

    def __init__(
        self,
        db_path: Path | str,
        *,
        create_if_missing: bool = False,
    ) -> None:
        self._db_path = Path(db_path)
        if not self._db_path.exists() and not create_if_missing:
            raise FileNotFoundError(f"Links database not found: {self._db_path}")

        self._conn: Any = _duckdb_mod.connect(str(self._db_path))

        # Always run schema setup/migrations so older DB files receive
        # additive columns (for example `family_link_rules.name`).
        self._create_schema()
        self._ensure_undo_state()

    def _create_schema(self) -> None:
        """Create all tables if they don't exist."""
        for stmt in _SCHEMA_DDL.split(";"):
            stmt = stmt.strip()
            if stmt:
                with contextlib.suppress(Exception):
                    self._conn.execute(stmt)

        # Migrations for existing databases
        self._add_column_if_missing(
            "family_link_rules",
            "filter_dsl",
            "ALTER TABLE family_link_rules ADD COLUMN filter_dsl VARCHAR DEFAULT ''",
            default="",
        )
        self._add_column_if_missing(
            "family_link_rules",
            "result_granularity",
            "ALTER TABLE family_link_rules ADD COLUMN result_granularity VARCHAR DEFAULT 'section'",
            default="section",
        )
        self._add_column_if_missing(
            "family_link_rules",
            "locked_by",
            "ALTER TABLE family_link_rules ADD COLUMN locked_by VARCHAR",
        )
        self._add_column_if_missing(
            "family_link_rules",
            "locked_at",
            "ALTER TABLE family_link_rules ADD COLUMN locked_at TIMESTAMP",
        )
        self._add_column_if_missing(
            "preview_candidates",
            "clause_id",
            "ALTER TABLE preview_candidates ADD COLUMN clause_id VARCHAR",
        )
        self._add_column_if_missing(
            "preview_candidates",
            "clause_path",
            "ALTER TABLE preview_candidates ADD COLUMN clause_path VARCHAR",
        )
        self._add_column_if_missing(
            "preview_candidates",
            "clause_label",
            "ALTER TABLE preview_candidates ADD COLUMN clause_label VARCHAR",
        )
        self._add_column_if_missing(
            "preview_candidates",
            "clause_char_start",
            "ALTER TABLE preview_candidates ADD COLUMN clause_char_start INTEGER",
        )
        self._add_column_if_missing(
            "preview_candidates",
            "clause_char_end",
            "ALTER TABLE preview_candidates ADD COLUMN clause_char_end INTEGER",
        )
        self._add_column_if_missing(
            "preview_candidates",
            "clause_text",
            "ALTER TABLE preview_candidates ADD COLUMN clause_text VARCHAR",
        )
        self._add_column_if_missing(
            "family_link_rules",
            "name",
            "ALTER TABLE family_link_rules ADD COLUMN name VARCHAR DEFAULT ''",
            default="",
        )
        self._add_column_if_missing(
            "family_link_rules",
            "ontology_node_id",
            "ALTER TABLE family_link_rules ADD COLUMN ontology_node_id VARCHAR",
        )
        self._add_column_if_missing(
            "family_link_rules",
            "parent_family_id",
            "ALTER TABLE family_link_rules ADD COLUMN parent_family_id VARCHAR",
        )
        self._add_column_if_missing(
            "family_link_rules",
            "parent_rule_id",
            "ALTER TABLE family_link_rules ADD COLUMN parent_rule_id VARCHAR",
        )
        self._add_column_if_missing(
            "family_link_rules",
            "parent_run_id",
            "ALTER TABLE family_link_rules ADD COLUMN parent_run_id VARCHAR",
        )
        self._add_column_if_missing(
            "family_link_rules",
            "scope_mode",
            "ALTER TABLE family_link_rules ADD COLUMN scope_mode VARCHAR DEFAULT 'corpus'",
            default="corpus",
        )
        self._add_column_if_missing(
            "family_link_runs",
            "parent_family_id",
            "ALTER TABLE family_link_runs ADD COLUMN parent_family_id VARCHAR",
        )
        self._add_column_if_missing(
            "family_link_runs",
            "parent_run_id",
            "ALTER TABLE family_link_runs ADD COLUMN parent_run_id VARCHAR",
        )
        self._add_column_if_missing(
            "family_link_runs",
            "scope_mode",
            "ALTER TABLE family_link_runs ADD COLUMN scope_mode VARCHAR DEFAULT 'corpus'",
            default="corpus",
        )
        self._add_column_if_missing(
            "family_link_previews",
            "ontology_node_id",
            "ALTER TABLE family_link_previews ADD COLUMN ontology_node_id VARCHAR",
        )
        self._add_column_if_missing(
            "family_links",
            "ontology_node_id",
            "ALTER TABLE family_links ADD COLUMN ontology_node_id VARCHAR",
        )
        self._add_column_if_missing(
            "family_links",
            "clause_text",
            "ALTER TABLE family_links ADD COLUMN clause_text VARCHAR",
        )

        # Backfill additive fields for older databases.
        with contextlib.suppress(Exception):
            self._conn.execute(
                "UPDATE family_link_rules SET ontology_node_id = family_id "
                "WHERE ontology_node_id IS NULL OR TRIM(ontology_node_id) = ''",
            )
        with contextlib.suppress(Exception):
            self._conn.execute(
                "UPDATE family_link_previews SET ontology_node_id = family_id "
                "WHERE ontology_node_id IS NULL OR TRIM(ontology_node_id) = ''",
            )
        with contextlib.suppress(Exception):
            self._conn.execute(
                "UPDATE family_links SET ontology_node_id = family_id "
                "WHERE ontology_node_id IS NULL OR TRIM(ontology_node_id) = ''",
            )
        with contextlib.suppress(Exception):
            self._refresh_family_scope_aliases()

        # Set schema version
        self._conn.execute(
            "INSERT OR REPLACE INTO _schema_version (table_name, version) VALUES (?, ?)",
            ["links", SCHEMA_VERSION],
        )

    def _column_exists(self, table_name: str, column_name: str) -> bool:
        """Check DuckDB metadata to avoid re-running ALTER statements."""
        row = self._conn.execute(
            """
            SELECT 1
            FROM information_schema.columns
            WHERE table_schema = 'main'
              AND table_name = ?
              AND column_name = ?
            """,
            [table_name, column_name],
        ).fetchone()
        return row is not None

    def _add_column_if_missing(
        self,
        table_name: str,
        column_name: str,
        ddl: str,
        *,
        default: Any | None = None,
    ) -> None:
        """Run ALTER TABLE only when the column is absent, then populate defaults."""
        if self._column_exists(table_name, column_name):
            return
        self._conn.execute(ddl)
        if default is not None:
            self._conn.execute(
                f"UPDATE \"{table_name}\" SET \"{column_name}\" = ? "
                f"WHERE \"{column_name}\" IS NULL",
                [default],
            )

    @staticmethod
    def _scope_sql_expr(
        *,
        ontology_column: str = "ontology_node_id",
        family_column: str = "family_id",
    ) -> str:
        return (
            f"COALESCE(NULLIF(TRIM({ontology_column}), ''), "
            f"NULLIF(TRIM({family_column}), ''), '')"
        )

    def upsert_family_alias(
        self,
        legacy_family_id: str,
        canonical_ontology_node_id: str,
        *,
        source: str = "inferred",
    ) -> None:
        legacy = str(legacy_family_id or "").strip()
        canonical = str(canonical_ontology_node_id or "").strip()
        if not legacy or not canonical:
            return
        source_norm = str(source or "inferred").strip() or "inferred"
        now = _now()
        existing = self._conn.execute(
            "SELECT created_at FROM family_scope_aliases WHERE legacy_family_id = ?",
            [legacy],
        ).fetchone()
        created_at = existing[0] if existing and existing[0] is not None else now
        self._conn.execute(
            """
            INSERT OR REPLACE INTO family_scope_aliases
            (legacy_family_id, canonical_ontology_node_id, source, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            [legacy, canonical, source_norm, created_at, now],
        )

    def get_canonical_scope_id(self, family_or_scope_id: str | None) -> str | None:
        raw = str(family_or_scope_id or "").strip()
        if not raw:
            return None
        row = self._conn.execute(
            "SELECT canonical_ontology_node_id "
            "FROM family_scope_aliases WHERE legacy_family_id = ?",
            [raw],
        ).fetchone()
        if row and row[0] is not None and str(row[0]).strip():
            return str(row[0]).strip()
        return raw

    def resolve_scope_aliases(self, family_or_scope_id: str | None) -> list[str]:
        raw = str(family_or_scope_id or "").strip()
        if not raw:
            return []

        resolved: set[str] = set()
        queue: list[str] = [raw]
        canonical = self.get_canonical_scope_id(raw)
        if canonical:
            queue.append(canonical)

        while queue:
            candidate = str(queue.pop(0)).strip()
            if not candidate or candidate in resolved:
                continue
            resolved.add(candidate)

            canonical_row = self._conn.execute(
                "SELECT canonical_ontology_node_id "
                "FROM family_scope_aliases WHERE legacy_family_id = ?",
                [candidate],
            ).fetchone()
            if canonical_row and canonical_row[0] is not None:
                canonical_value = str(canonical_row[0]).strip()
                if canonical_value and canonical_value not in resolved:
                    queue.append(canonical_value)

            legacy_rows = self._conn.execute(
                "SELECT legacy_family_id "
                "FROM family_scope_aliases WHERE canonical_ontology_node_id = ?",
                [candidate],
            ).fetchall()
            for row in legacy_rows:
                legacy_value = str(row[0] or "").strip()
                if legacy_value and legacy_value not in resolved:
                    queue.append(legacy_value)

        canonical_scope = self.get_canonical_scope_id(raw) or raw
        canonical_token = _canonical_family_token(canonical_scope)
        if canonical_token:
            rows = self._conn.execute(
                "SELECT legacy_family_id, canonical_ontology_node_id "
                "FROM family_scope_aliases"
            ).fetchall()
            token_matches: set[str] = set()
            for row in rows:
                legacy_value = str(row[0] or "").strip()
                canonical_value = str(row[1] or "").strip()
                for value in (legacy_value, canonical_value):
                    if value and _canonical_family_token(value) == canonical_token:
                        token_matches.add(canonical_value or value)
            if len(token_matches) == 1:
                only_match = next(iter(token_matches))
                if only_match and only_match not in resolved:
                    resolved.add(only_match)
                more_legacy_rows = self._conn.execute(
                    "SELECT legacy_family_id FROM family_scope_aliases "
                    "WHERE canonical_ontology_node_id = ?",
                    [only_match],
                ).fetchall()
                for row in more_legacy_rows:
                    legacy_value = str(row[0] or "").strip()
                    if legacy_value:
                        resolved.add(legacy_value)

        # Include ontology descendants for hierarchical scope IDs.
        # This allows domain/family scopes to transparently include concept-level
        # links/rules/runs whose ontology_node_id is nested under the scope.
        canonical_scope = str(canonical_scope or "").strip()
        if canonical_scope:
            descendant_prefix = f"{canonical_scope}.%"
            known_scope_rows = self._conn.execute(
                """
                SELECT DISTINCT scope_id
                FROM (
                    SELECT COALESCE(NULLIF(TRIM(ontology_node_id), ''), NULLIF(TRIM(family_id), '')) AS scope_id
                    FROM family_links
                    UNION ALL
                    SELECT COALESCE(NULLIF(TRIM(ontology_node_id), ''), NULLIF(TRIM(family_id), '')) AS scope_id
                    FROM family_link_rules
                    UNION ALL
                    SELECT COALESCE(NULLIF(TRIM(rr.ontology_node_id), ''), NULLIF(TRIM(r.family_id), '')) AS scope_id
                    FROM family_link_runs AS r
                    LEFT JOIN family_link_rules AS rr ON rr.rule_id = r.rule_id
                ) AS known_scopes
                WHERE scope_id IS NOT NULL
                  AND TRIM(scope_id) <> ''
                  AND (scope_id = ? OR scope_id LIKE ?)
                """,
                [canonical_scope, descendant_prefix],
            ).fetchall()
            for row in known_scope_rows:
                scope_value = str(row[0] or "").strip()
                if not scope_value:
                    continue
                resolved.add(scope_value)
                # Bring in any legacy aliases that map to discovered descendant scopes.
                legacy_rows = self._conn.execute(
                    "SELECT legacy_family_id "
                    "FROM family_scope_aliases WHERE canonical_ontology_node_id = ?",
                    [scope_value],
                ).fetchall()
                for legacy_row in legacy_rows:
                    legacy_value = str(legacy_row[0] or "").strip()
                    if legacy_value:
                        resolved.add(legacy_value)

        return sorted(resolved)

    def _refresh_family_scope_aliases(self) -> None:
        now = _now()

        rows = self._conn.execute(
            """
            SELECT DISTINCT family_id,
                   COALESCE(NULLIF(TRIM(ontology_node_id), ''), NULLIF(TRIM(family_id), ''))
            FROM family_link_rules
            WHERE family_id IS NOT NULL AND TRIM(family_id) <> ''
            """
        ).fetchall()
        for row in rows:
            legacy = str(row[0] or "").strip()
            canonical = str(row[1] or "").strip() or legacy
            if legacy and canonical:
                self.upsert_family_alias(legacy, canonical, source="rules")

        rows = self._conn.execute(
            """
            SELECT DISTINCT family_id,
                   COALESCE(NULLIF(TRIM(ontology_node_id), ''), NULLIF(TRIM(family_id), ''))
            FROM family_links
            WHERE family_id IS NOT NULL AND TRIM(family_id) <> ''
            """
        ).fetchall()
        for row in rows:
            legacy = str(row[0] or "").strip()
            canonical = str(row[1] or "").strip() or legacy
            if legacy and canonical:
                self.upsert_family_alias(legacy, canonical, source="links")

        rows = self._conn.execute(
            """
            SELECT DISTINCT r.family_id,
                   COALESCE(
                       NULLIF(TRIM(rr.ontology_node_id), ''),
                       NULLIF(TRIM(r.family_id), '')
                   )
            FROM family_link_runs AS r
            LEFT JOIN family_link_rules AS rr ON rr.rule_id = r.rule_id
            WHERE r.family_id IS NOT NULL AND TRIM(r.family_id) <> ''
            """
        ).fetchall()
        for row in rows:
            legacy = str(row[0] or "").strip()
            canonical = str(row[1] or "").strip() or legacy
            if legacy and canonical:
                self.upsert_family_alias(legacy, canonical, source="runs")

        token_rows = self._conn.execute(
            "SELECT DISTINCT legacy_family_id, canonical_ontology_node_id "
            "FROM family_scope_aliases"
        ).fetchall()
        all_scopes = {
            str(row[1] or "").strip()
            for row in token_rows
            if row and row[1] is not None and str(row[1]).strip()
        }
        token_to_candidates: dict[str, set[str]] = {}
        for scope in all_scopes:
            token = _canonical_family_token(scope)
            if not token:
                continue
            token_to_candidates.setdefault(token, set()).add(scope)

        for row in token_rows:
            legacy = str(row[0] or "").strip()
            current_canonical = str(row[1] or "").strip()
            if not legacy:
                continue
            # Only infer remaps for legacy-style IDs (e.g., FAM-*)
            # to avoid downgrading canonical dotted namespaces.
            if "." in legacy and not legacy.lower().startswith("fam-"):
                continue
            token = _canonical_family_token(legacy)
            if not token:
                continue
            candidates = {
                candidate
                for candidate in token_to_candidates.get(token, set())
                if candidate != legacy
            }
            preferred = {
                candidate
                for candidate in candidates
                if "." in candidate and not candidate.lower().startswith("fam-")
            }
            if len(preferred) == 1:
                target = next(iter(preferred))
            elif len(candidates) == 1:
                target = next(iter(candidates))
            else:
                continue
            if target and target != current_canonical:
                self._conn.execute(
                    """
                    UPDATE family_scope_aliases
                    SET canonical_ontology_node_id = ?, source = ?, updated_at = ?
                    WHERE legacy_family_id = ?
                    """,
                    [target, "token_inferred", now, legacy],
                )

    def _ensure_undo_state(self) -> None:
        """Ensure undo_state singleton row exists."""
        try:
            row = self._conn.execute(
                "SELECT current_position FROM undo_state WHERE id = 1"
            ).fetchone()
            if row is None:
                self._conn.execute("INSERT INTO undo_state (id, current_position) VALUES (1, 0)")
        except Exception:
            pass

    def truncate_all(self) -> None:
        """Delete all row data from link tables while preserving schema."""
        rows = self._conn.execute("""
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'main' AND table_type = 'BASE TABLE'
        """).fetchall()
        keep = {"_schema_version"}
        table_names = [str(row[0]) for row in rows if str(row[0]) not in keep]

        # Rebuild undo state after all deletes.
        if "undo_state" in table_names:
            table_names.remove("undo_state")
            table_names.append("undo_state")

        for table_name in table_names:
            self._conn.execute(f'DELETE FROM "{table_name}"')

        self._ensure_undo_state()

    def _normalize_filter_ast(
        self,
        payload: Any,
        *,
        field_name: str,
        allow_empty: bool = False,
    ) -> dict[str, Any]:
        """Decode + validate a persisted filter AST payload."""
        raw = payload
        if raw is None:
            if allow_empty:
                return {}
            raise ValueError(f"{field_name} cannot be null")

        if isinstance(raw, str):
            raw_text = raw.strip()
            if not raw_text:
                if allow_empty:
                    return {}
                raise ValueError(f"{field_name} cannot be empty")
            try:
                raw = _json_loads(raw_text)
            except Exception as exc:
                raise ValueError(f"{field_name} must be valid JSON") from exc

        if not isinstance(raw, dict):
            raise ValueError(f"{field_name} must be a JSON object")
        if not raw:
            if allow_empty:
                return {}
            raise ValueError(f"{field_name} cannot be empty")

        expr = filter_expr_from_json(raw)
        return filter_expr_to_json(expr)

    def _validate_rule_row(self, row: dict[str, Any]) -> None:
        rule_id = row.get("rule_id", "")
        self._normalize_filter_ast(
            row.get("heading_filter_ast"),
            field_name=f"rule[{rule_id}].heading_filter_ast",
            allow_empty=True,
        )

    def _validate_macro_row(self, row: dict[str, Any]) -> None:
        macro_id = row.get("macro_id", "")
        self._normalize_filter_ast(
            row.get("ast_json"),
            field_name=f"macro[{macro_id}].ast_json",
            allow_empty=True,
        )

    def _decode_json_column(self, value: Any) -> Any:
        if not isinstance(value, str):
            return value
        text = value.strip()
        if not text:
            return None
        try:
            return _json_loads(text)
        except Exception:
            return value

    def _normalize_rule_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        rule_id = str(payload.get("rule_id", ""))
        self._validate_rule_row(payload)
        payload["article_concepts"] = self._decode_json_column(payload.get("article_concepts")) or []
        payload["heading_filter_ast"] = self._normalize_filter_ast(
            payload.get("heading_filter_ast"),
            field_name=f"rule[{rule_id}].heading_filter_ast",
            allow_empty=True,
        )
        # Backfill filter_dsl from heading_filter_ast if missing
        filter_dsl = str(payload.get("filter_dsl") or "").strip()
        if not filter_dsl and payload.get("heading_filter_ast"):
            filter_dsl = dsl_from_heading_ast(payload["heading_filter_ast"])
        payload["filter_dsl"] = filter_dsl
        payload.setdefault("result_granularity", "section")
        ontology_node_id = str(payload.get("ontology_node_id") or payload.get("family_id") or "").strip()
        payload["ontology_node_id"] = ontology_node_id or None
        payload["parent_family_id"] = payload.get("parent_family_id") or None
        payload["parent_rule_id"] = payload.get("parent_rule_id") or None
        payload["parent_run_id"] = payload.get("parent_run_id") or None
        scope_mode = str(payload.get("scope_mode") or "corpus").strip().lower()
        payload["scope_mode"] = scope_mode if scope_mode in {"corpus", "inherited"} else "corpus"
        for key in (
            "clause_text_filter_ast",
            "clause_header_filter_ast",
            "required_defined_terms",
            "excluded_cue_phrases",
            "template_overrides",
        ):
            payload[key] = self._decode_json_column(payload.get(key))
        return payload

    # ─── Rules CRUD ───────────────────────────────────────────────

    def get_rules(
        self,
        *,
        family_id: str | None = None,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        conditions: list[str] = []
        params: list[Any] = []
        if family_id:
            scope_ids = self.resolve_scope_aliases(family_id)
            if not scope_ids:
                scope_ids = [str(family_id).strip()]
            placeholders = ", ".join("?" for _ in scope_ids)
            scope_expr = self._scope_sql_expr()
            conditions.append(f"{scope_expr} IN ({placeholders})")
            params.extend(scope_ids)
        if status:
            conditions.append("status = ?")
            params.append(status)
        where = " WHERE " + " AND ".join(conditions) if conditions else ""
        rows = self._conn.execute(
            f"SELECT * FROM family_link_rules{where} ORDER BY family_id, version DESC",
            params,
        ).fetchall()
        cols = [d[0] for d in self._conn.description]
        results: list[dict[str, Any]] = []
        for row in rows:
            payload = _to_dict(cols, row)
            results.append(self._normalize_rule_payload(payload))
        return results

    def get_rule(self, rule_id: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM family_link_rules WHERE rule_id = ?", [rule_id]
        ).fetchone()
        if row is None:
            return None
        cols = [d[0] for d in self._conn.description]
        payload = _to_dict(cols, row)
        return self._normalize_rule_payload(payload)

    def _auto_rule_name(self, family_id: str) -> str:
        """Generate a default rule name like 'Family Name #N'."""
        # Derive human-readable family name from family_id
        family_name = (
            family_id.replace("FAM-", "")
            .replace("_", " ")
            .replace("-", " ")
            .strip()
            .title()
        ) if family_id else "Rule"
        row = self._conn.execute(
            "SELECT COUNT(*) FROM family_link_rules WHERE family_id = ?",
            [family_id],
        ).fetchone()
        seq = (row[0] if row else 0) + 1
        return f"{family_name} #{seq}"

    def save_rule(self, rule: dict[str, Any]) -> None:
        rule_id = rule.get("rule_id") or _uuid()
        now = _now()
        family_id = str(rule.get("family_id", "") or "").strip()
        ontology_node_id = str(rule.get("ontology_node_id") or family_id or "").strip() or None

        # Auto-generate name if not provided
        name = str(rule.get("name") or "").strip()
        if not name:
            name = self._auto_rule_name(family_id)

        # Bidirectional sync: filter_dsl ↔ heading_filter_ast
        filter_dsl = str(rule.get("filter_dsl") or "").strip()
        heading_filter_ast = self._normalize_filter_ast(
            rule.get("heading_filter_ast", {}),
            field_name="heading_filter_ast",
            allow_empty=True,
        )
        if filter_dsl and not heading_filter_ast:
            # Derive heading_filter_ast from filter_dsl
            derived = heading_ast_from_dsl(filter_dsl)
            if derived:
                heading_filter_ast = derived
        elif heading_filter_ast and not filter_dsl:
            # Synthesize filter_dsl from heading_filter_ast
            filter_dsl = dsl_from_heading_ast(heading_filter_ast)

        result_granularity = str(rule.get("result_granularity", "section") or "section")
        if result_granularity not in ("section", "clause"):
            result_granularity = "section"
        scope_mode = str(rule.get("scope_mode") or "corpus").strip().lower()
        if scope_mode not in {"corpus", "inherited"}:
            scope_mode = "corpus"

        self._conn.execute("""
            INSERT OR REPLACE INTO family_link_rules
            (rule_id, family_id, ontology_node_id, parent_family_id, parent_rule_id, parent_run_id, scope_mode,
             name, description, version, status, owner,
             locked_by, locked_at, article_concepts, heading_filter_ast,
             filter_dsl, result_granularity,
             clause_text_filter_ast, clause_header_filter_ast,
             required_defined_terms, excluded_cue_phrases,
             template_overrides, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, [
            rule_id,
            family_id,
            ontology_node_id,
            rule.get("parent_family_id"),
            rule.get("parent_rule_id"),
            rule.get("parent_run_id"),
            scope_mode,
            name,
            rule.get("description", ""),
            rule.get("version", 1),
            rule.get("status", "draft"),
            rule.get("owner", ""),
            rule.get("locked_by"),
            rule.get("locked_at"),
            _json_dumps(rule.get("article_concepts", [])),
            _json_dumps(heading_filter_ast),
            filter_dsl,
            result_granularity,
            rule.get("clause_text_filter_ast"),
            rule.get("clause_header_filter_ast"),
            _opt_json(rule, "required_defined_terms"),
            _opt_json(rule, "excluded_cue_phrases"),
            _opt_json(rule, "template_overrides"),
            rule.get("created_at", now),
            now,
        ])
        if family_id and ontology_node_id:
            self.upsert_family_alias(family_id, ontology_node_id, source="rule_write")

    def clone_rule(self, rule_id: str, new_rule_id: str) -> dict[str, Any]:
        original = self.get_rule(rule_id)
        if original is None:
            raise ValueError(f"Rule not found: {rule_id}")
        original["rule_id"] = new_rule_id
        original["name"] = ""  # Auto-generate a new name
        original["version"] = 1
        original["status"] = "draft"
        original["locked_by"] = None
        original["locked_at"] = None
        original["created_at"] = _now()
        self.save_rule(original)
        return original

    def delete_rule(self, rule_id: str) -> None:
        """Permanently delete a rule and its associated pins."""
        existing = self.get_rule(rule_id)
        if existing is None:
            raise ValueError(f"Rule not found: {rule_id}")
        self._conn.execute("DELETE FROM rule_pins WHERE rule_id = ?", [rule_id])
        self._conn.execute(
            "DELETE FROM family_link_rules WHERE rule_id = ?", [rule_id]
        )

    # ─── Links CRUD ───────────────────────────────────────────────

    def get_links(
        self,
        *,
        family_id: str | None = None,
        doc_id: str | None = None,
        status: str | None = None,
        confidence_tier: str | None = None,
        heading_ast: FilterExpression | None = None,
        doc_ids: list[str] | None = None,
        limit: int = 100,
        offset: int = 0,
        sort_by: str = "created_at",
        sort_dir: str = "desc",
    ) -> list[dict[str, Any]]:
        conditions: list[str] = []
        params: list[Any] = []
        if family_id:
            scope_ids = self.resolve_scope_aliases(family_id)
            if not scope_ids:
                scope_ids = [str(family_id).strip()]
            placeholders = ", ".join("?" for _ in scope_ids)
            scope_expr = self._scope_sql_expr()
            conditions.append(f"{scope_expr} IN ({placeholders})")
            params.extend(scope_ids)
        if doc_id:
            conditions.append("doc_id = ?")
            params.append(doc_id)
        if status:
            conditions.append("status = ?")
            params.append(status)
        if confidence_tier:
            conditions.append("confidence_tier = ?")
            params.append(confidence_tier)
        if heading_ast is not None:
            frag, fparams = build_filter_sql(heading_ast, "heading")
            conditions.append(frag)
            params.extend(fparams)
        if doc_ids is not None:
            if not doc_ids:
                return []
            placeholders = ", ".join("?" for _ in doc_ids)
            conditions.append(f"doc_id IN ({placeholders})")
            params.extend(doc_ids)
        where = " WHERE " + " AND ".join(conditions) if conditions else ""
        allowed_sort_cols = {
            "created_at",
            "confidence",
            "doc_id",
            "section_number",
            "family_id",
            "status",
            "confidence_tier",
        }
        sort_col = sort_by if sort_by in allowed_sort_cols else "created_at"
        sort_order = "ASC" if sort_dir.lower() == "asc" else "DESC"
        params.extend([limit, offset])
        rows = self._conn.execute(
            f"SELECT * FROM family_links{where} "
            f"ORDER BY {sort_col} {sort_order}, created_at DESC, link_id ASC "
            "LIMIT ? OFFSET ?",
            params,
        ).fetchall()
        cols = [d[0] for d in self._conn.description]
        return [_to_dict(cols, row) for row in rows]

    def count_links(
        self,
        *,
        family_id: str | None = None,
        doc_id: str | None = None,
        status: str | None = None,
        confidence_tier: str | None = None,
        heading_ast: FilterExpression | None = None,
        doc_ids: list[str] | None = None,
    ) -> int:
        conditions: list[str] = []
        params: list[Any] = []
        if family_id:
            scope_ids = self.resolve_scope_aliases(family_id)
            if not scope_ids:
                scope_ids = [str(family_id).strip()]
            placeholders = ", ".join("?" for _ in scope_ids)
            scope_expr = self._scope_sql_expr()
            conditions.append(f"{scope_expr} IN ({placeholders})")
            params.extend(scope_ids)
        if doc_id:
            conditions.append("doc_id = ?")
            params.append(doc_id)
        if status:
            conditions.append("status = ?")
            params.append(status)
        if confidence_tier:
            conditions.append("confidence_tier = ?")
            params.append(confidence_tier)
        if heading_ast is not None:
            frag, fparams = build_filter_sql(heading_ast, "heading")
            conditions.append(frag)
            params.extend(fparams)
        if doc_ids is not None:
            if not doc_ids:
                return 0
            placeholders = ", ".join("?" for _ in doc_ids)
            conditions.append(f"doc_id IN ({placeholders})")
            params.extend(doc_ids)
        where = " WHERE " + " AND ".join(conditions) if conditions else ""
        row = self._conn.execute(
            f"SELECT COUNT(*) FROM family_links{where}", params
        ).fetchone()
        return int(row[0]) if row else 0

    def create_links(self, links: list[dict[str, Any]], run_id: str) -> int:
        created = 0
        alias_pairs: set[tuple[str, str]] = set()
        for link in links:
            link_id = link.get("link_id") or _uuid()
            family_id = str(link.get("family_id") or "").strip()
            ontology_node_id = str(link.get("ontology_node_id") or family_id or "").strip()
            if family_id and ontology_node_id:
                alias_pairs.add((family_id, ontology_node_id))
            try:
                self._conn.execute("""
                    INSERT INTO family_links
                    (link_id, family_id, ontology_node_id, doc_id, section_number, heading,
                     article_num, article_concept, rule_id, rule_version,
                     rule_hash, run_id, source, section_char_start,
                     section_char_end, section_text_hash, clause_id,
                     clause_char_start, clause_char_end, clause_text, link_role,
                     confidence, confidence_tier, confidence_breakdown,
                     status, corpus_version, parser_version, created_at)
                    VALUES (
                        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, [
                    link_id,
                    family_id,
                    ontology_node_id or None,
                    link["doc_id"],
                    link["section_number"],
                    link.get("heading", ""),
                    link.get("article_num", 0),
                    link.get("article_concept", ""),
                    link.get("rule_id"),
                    link.get("rule_version"),
                    link.get("rule_hash"),
                    run_id,
                    link.get("source", "bulk_linker"),
                    link.get("section_char_start"),
                    link.get("section_char_end"),
                    link.get("section_text_hash"),
                    link.get("clause_id"),
                    link.get("clause_char_start"),
                    link.get("clause_char_end"),
                    link.get("clause_text"),
                    link.get("link_role", "primary_covenant"),
                    link.get("confidence", 1.0),
                    link.get("confidence_tier", "high"),
                    _opt_json(link, "confidence_breakdown"),
                    link.get("status", "active"),
                    link.get("corpus_version"),
                    link.get("parser_version"),
                    _now(),
                ])
                created += 1
            except Exception:
                pass  # Skip duplicates (UNIQUE constraint)
        for family_id, ontology_node_id in alias_pairs:
            self.upsert_family_alias(family_id, ontology_node_id, source="link_write")
        return created

    def unlink(self, link_id: str, reason: str, note: str = "") -> None:
        self._conn.execute(
            "UPDATE family_links SET status = 'unlinked', unlinked_at = ?, "
            "unlinked_reason = ?, unlinked_note = ? WHERE link_id = ?",
            [_now(), reason, note, link_id],
        )
        self.log_event(link_id, "unlink", "user", reason=reason, note=note)

    def relink(self, link_id: str) -> None:
        self._conn.execute(
            "UPDATE family_links SET status = 'active', unlinked_at = NULL, "
            "unlinked_reason = NULL, unlinked_note = NULL WHERE link_id = ?",
            [link_id],
        )
        self.log_event(link_id, "relink", "user")

    # ─── Batch operations ─────────────────────────────────────────

    def _existing_link_ids(self, link_ids: list[str]) -> list[str]:
        """Return input link IDs that currently exist, preserving input order."""
        if not link_ids:
            return []
        placeholders = ", ".join("?" for _ in link_ids)
        rows = self._conn.execute(
            f"SELECT link_id FROM family_links WHERE link_id IN ({placeholders})",
            link_ids,
        ).fetchall()
        existing = {row[0] for row in rows}
        return [lid for lid in link_ids if lid in existing]

    def batch_unlink(self, link_ids: list[str], reason: str, note: str = "") -> int:
        existing_ids = self._existing_link_ids(link_ids)
        if not existing_ids:
            return 0
        batch_id = _uuid()
        count = 0
        for lid in existing_ids:
            # Record undo action
            self.record_action(
                batch_id=batch_id,
                batch_label=f"Unlink {len(existing_ids)} links",
                entity_type="family_link",
                entity_id=lid,
                op="update",
                forward_patch=_json_dumps({"status": "unlinked", "unlinked_reason": reason}),
                reverse_patch=_json_dumps({"status": "active", "unlinked_reason": None}),
            )
            self.unlink(lid, reason, note)
            count += 1
        return count

    def batch_relink(self, link_ids: list[str]) -> int:
        existing_ids = self._existing_link_ids(link_ids)
        if not existing_ids:
            return 0
        batch_id = _uuid()
        count = 0
        for lid in existing_ids:
            self.record_action(
                batch_id=batch_id,
                batch_label=f"Relink {len(existing_ids)} links",
                entity_type="family_link",
                entity_id=lid,
                op="update",
                forward_patch=_json_dumps({"status": "active"}),
                reverse_patch=_json_dumps({"status": "unlinked"}),
            )
            self.relink(lid)
            count += 1
        return count

    def select_all_matching(
        self,
        family_id: str,
        heading_ast: FilterExpression | None,
        status: str | None,
    ) -> list[str]:
        scope_ids = self.resolve_scope_aliases(family_id)
        if not scope_ids:
            scope_ids = [str(family_id).strip()]
        placeholders = ", ".join("?" for _ in scope_ids)
        scope_expr = self._scope_sql_expr()
        conditions = [f"{scope_expr} IN ({placeholders})"]
        params: list[Any] = [*scope_ids]
        if status:
            conditions.append("status = ?")
            params.append(status)
        if heading_ast is not None:
            frag, fparams = build_filter_sql(heading_ast, "heading")
            conditions.append(frag)
            params.extend(fparams)
        where = " AND ".join(conditions)
        rows = self._conn.execute(
            f"SELECT link_id FROM family_links WHERE {where}", params
        ).fetchall()
        return [row[0] for row in rows]

    # ─── Conflicts ────────────────────────────────────────────────

    def get_conflicts(self, *, family_id: str | None = None) -> list[dict[str, Any]]:
        if family_id:
            rows = self._conn.execute(
                "SELECT * FROM family_conflict_policies WHERE family_a = ? OR family_b = ?",
                [family_id, family_id],
            ).fetchall()
        else:
            rows = self._conn.execute("SELECT * FROM family_conflict_policies").fetchall()
        cols = [d[0] for d in self._conn.description]
        return [_to_dict(cols, row) for row in rows]

    def get_conflict_policy(self, family_a: str, family_b: str) -> str:
        a, b = (family_a, family_b) if family_a < family_b else (family_b, family_a)
        row = self._conn.execute(
            "SELECT policy FROM family_conflict_policies WHERE family_a = ? AND family_b = ?",
            [a, b],
        ).fetchone()
        return row[0] if row else "independent"

    def save_conflict_policy(self, policy: dict[str, Any]) -> None:
        family_a = str(policy.get("family_a", "")).strip()
        family_b = str(policy.get("family_b", "")).strip()
        if not family_a or not family_b:
            raise ValueError("family_a and family_b are required")
        a, b = (family_a, family_b) if family_a < family_b else (family_b, family_a)

        reason = str(policy.get("reason") or "manual override")
        edge_types_raw = policy.get("edge_types")
        if isinstance(edge_types_raw, str):
            edge_types = edge_types_raw
        elif isinstance(edge_types_raw, (list, tuple, set)):
            edge_types = _json_dumps([str(v) for v in edge_types_raw])
        else:
            edge_types = _json_dumps([])
        ontology_version = str(policy.get("ontology_version") or "manual")

        self._conn.execute("""
            INSERT OR REPLACE INTO family_conflict_policies
            (family_a, family_b, policy, reason, edge_types, ontology_version)
            VALUES (?, ?, ?, ?, ?, ?)
        """, [
            a,
            b,
            str(policy.get("policy", "independent")),
            reason,
            edge_types,
            ontology_version,
        ])

    # ─── Events ───────────────────────────────────────────────────

    def log_event(
        self,
        link_id: str,
        event_type: str,
        actor: str,
        *,
        reason: str | None = None,
        note: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self._conn.execute("""
            INSERT INTO family_link_events
            (event_id, link_id, event_type, actor, reason, note, metadata, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, [
            _uuid(), link_id, event_type, actor,
            reason, note,
            _json_dumps(metadata) if metadata else None,
            _now(),
        ])

    def get_events(self, link_id: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM family_link_events WHERE link_id = ? ORDER BY created_at DESC",
            [link_id],
        ).fetchall()
        cols = [d[0] for d in self._conn.description]
        return [_to_dict(cols, row) for row in rows]

    # ─── Evidence ─────────────────────────────────────────────────

    def save_evidence(self, evidence: list[dict[str, Any]]) -> int:
        count = 0
        for ev in evidence:
            self._conn.execute("""
                INSERT INTO link_evidence
                (evidence_id, link_id, evidence_type, char_start, char_end,
                 text_hash, matched_pattern, reason_code, score, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, [
                ev.get("evidence_id") or _uuid(),
                ev["link_id"], ev["evidence_type"],
                ev["char_start"], ev["char_end"], ev["text_hash"],
                ev.get("matched_pattern"), ev["reason_code"],
                ev.get("score", 1.0),
                _json_dumps(ev["metadata"]) if ev.get("metadata") else None,
            ])
            count += 1
        return count

    def get_evidence(self, link_id: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM link_evidence WHERE link_id = ? ORDER BY char_start",
            [link_id],
        ).fetchall()
        cols = [d[0] for d in self._conn.description]
        return [_to_dict(cols, row) for row in rows]

    # ─── Runs ─────────────────────────────────────────────────────

    def create_run(self, run: dict[str, Any]) -> None:
        scope_mode = str(run.get("scope_mode") or "corpus").strip().lower()
        if scope_mode not in {"corpus", "inherited"}:
            scope_mode = "corpus"
        family_id = str(run.get("family_id") or "").strip()
        rule_id = str(run.get("rule_id") or "").strip()
        canonical_scope = str(run.get("ontology_node_id") or "").strip()
        if not canonical_scope and rule_id:
            with contextlib.suppress(Exception):
                rule = self.get_rule(rule_id)
                if rule:
                    canonical_scope = str(
                        rule.get("ontology_node_id") or rule.get("family_id") or ""
                    ).strip()
        if not canonical_scope:
            canonical_scope = family_id
        if family_id and canonical_scope and family_id != "_all":
            self.upsert_family_alias(family_id, canonical_scope, source="run")
        self._conn.execute("""
            INSERT INTO family_link_runs
            (run_id, run_type, family_id, rule_id, parent_family_id, parent_run_id, scope_mode, rule_version,
             corpus_version, corpus_doc_count, parser_version,
             links_created, links_skipped_existing, links_skipped_low_confidence,
             conflicts_detected, outlier_count, preview_summary, started_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, [
            run["run_id"], run["run_type"], family_id or None,
            rule_id or None, run.get("parent_family_id"),
            run.get("parent_run_id"), scope_mode, run.get("rule_version"),
            run["corpus_version"], run["corpus_doc_count"], run["parser_version"],
            run.get("links_created", 0), run.get("links_skipped_existing", 0),
            run.get("links_skipped_low_confidence", 0),
            run.get("conflicts_detected", 0), run.get("outlier_count", 0),
            _json_dumps(run.get("preview_summary")) if run.get("preview_summary") else None,
            _now(),
        ])

    def complete_run(self, run_id: str, stats: dict[str, Any]) -> None:
        self._conn.execute(
            "UPDATE family_link_runs SET links_created = ?, "
            "links_skipped_existing = ?, links_skipped_low_confidence = ?, "
            "conflicts_detected = ?, outlier_count = ?, completed_at = ? "
            "WHERE run_id = ?",
            [
                stats.get("links_created", 0),
                stats.get("links_skipped_existing", 0),
                stats.get("links_skipped_low_confidence", 0),
                stats.get("conflicts_detected", 0),
                stats.get("outlier_count", 0),
                _now(),
                run_id,
            ],
        )

    def get_runs(self, *, family_id: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
        if family_id:
            scope_ids = self.resolve_scope_aliases(family_id)
            if not scope_ids:
                scope_ids = [str(family_id).strip()]
            placeholders = ", ".join("?" for _ in scope_ids)
            scope_expr = self._scope_sql_expr(
                ontology_column="rr.ontology_node_id",
                family_column="r.family_id",
            )
            rows = self._conn.execute(
                f"SELECT r.* FROM family_link_runs AS r "
                f"LEFT JOIN family_link_rules AS rr ON rr.rule_id = r.rule_id "
                f"WHERE {scope_expr} IN ({placeholders}) "
                f"ORDER BY r.started_at DESC LIMIT ?",
                [*scope_ids, limit],
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM family_link_runs ORDER BY started_at DESC LIMIT ?", [limit]
            ).fetchall()
        cols = [d[0] for d in self._conn.description]
        return [_to_dict(cols, row) for row in rows]

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM family_link_runs WHERE run_id = ?",
            [run_id],
        ).fetchone()
        if row is None:
            return None
        cols = [d[0] for d in self._conn.description]
        return _to_dict(cols, row)

    # ─── Coverage ─────────────────────────────────────────────────

    def family_summary(self) -> list[dict[str, Any]]:
        scope_expr = self._scope_sql_expr()
        rows = self._conn.execute("""
            SELECT {scope_expr} AS family_id,
                   COUNT(*) as total_links,
                   SUM(CASE WHEN status = 'active' THEN 1 ELSE 0 END) as active_links,
                   SUM(CASE WHEN status = 'pending_review' THEN 1 ELSE 0 END) as pending_links,
                   SUM(CASE WHEN status = 'unlinked' THEN 1 ELSE 0 END) as unlinked_links,
                   AVG(confidence) as avg_confidence
            FROM family_links GROUP BY 1 ORDER BY 1
        """.format(scope_expr=scope_expr)).fetchall()
        cols = [d[0] for d in self._conn.description]
        return [_to_dict(cols, row) for row in rows]

    # ─── Previews ─────────────────────────────────────────────────

    def save_preview(self, preview: dict[str, Any]) -> None:
        expires_at = preview.get("expires_at")
        if isinstance(expires_at, datetime):
            expires_at_value = expires_at.astimezone(UTC).isoformat()
        elif isinstance(expires_at, str) and expires_at.strip():
            expires_at_value = expires_at
        else:
            expires_at_value = (datetime.now(UTC) + timedelta(hours=24)).isoformat()

        params_json = preview.get("params_json")
        if params_json is None and "query_ast" in preview:
            params_json = {"query_ast": preview.get("query_ast")}
        ontology_node_id = str(preview.get("ontology_node_id") or preview.get("family_id") or "").strip() or None

        self._conn.execute("""
            INSERT INTO family_link_previews
            (preview_id, family_id, ontology_node_id, rule_id, rule_hash, corpus_version,
             parser_version, candidate_set_hash, candidate_count,
             new_link_count, already_linked_count, conflict_count,
             by_confidence_tier, avg_confidence, params_json, expires_at, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, [
            preview["preview_id"], preview["family_id"], ontology_node_id,
            preview.get("rule_id"), str(preview.get("rule_hash") or ""),
            str(preview.get("corpus_version") or ""), str(preview.get("parser_version") or ""),
            preview["candidate_set_hash"], preview.get("candidate_count", 0),
            preview.get("new_link_count", 0), preview.get("already_linked_count", 0),
            preview.get("conflict_count", 0),
            _json_dumps(preview.get("by_confidence_tier", {})),
            preview.get("avg_confidence", 0.0),
            _json_dumps(params_json) if params_json else None,
            expires_at_value,
            _now(),
        ])
        family_id = str(preview.get("family_id") or "").strip()
        if family_id and ontology_node_id:
            self.upsert_family_alias(family_id, ontology_node_id, source="preview")

    def get_preview(self, preview_id: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM family_link_previews WHERE preview_id = ?", [preview_id]
        ).fetchone()
        if row is None:
            return None
        cols = [d[0] for d in self._conn.description]
        return _to_dict(cols, row)

    def validate_preview(self, preview_id: str) -> bool:
        preview = self.get_preview(preview_id)
        if preview is None:
            return False
        if preview.get("applied_at") is not None:
            return False
        expires = preview.get("expires_at")
        return not (expires and str(expires) < _now())

    def save_preview_candidates(self, preview_id: str, candidates: list[dict[str, Any]]) -> int:
        count = 0
        for c in candidates:
            self._conn.execute("""
                INSERT INTO preview_candidates
                (preview_id, doc_id, section_number, heading, article_num,
                 article_concept, template_family, confidence, confidence_tier,
                 confidence_breakdown, why_matched, priority_score,
                 uncertainty_score, impact_score, drift_score,
                 flags, conflict_families, clause_id, clause_path, clause_label,
                 clause_char_start, clause_char_end, clause_text,
                 user_verdict)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, [
                preview_id, c["doc_id"], c["section_number"],
                c.get("heading"), c.get("article_num"), c.get("article_concept"),
                c.get("template_family"),
                c.get("confidence", 0.0), c.get("confidence_tier", "high"),
                _opt_json(c, "confidence_breakdown"),
                _opt_json(c, "why_matched"),
                c.get("priority_score", 0.0),
                c.get("uncertainty_score", 0.0),
                c.get("impact_score", 0.0),
                c.get("drift_score", 0.0),
                _opt_json(c, "flags"),
                _opt_json(c, "conflict_families"),
                c.get("clause_id"),
                c.get("clause_path"),
                c.get("clause_label"),
                c.get("clause_char_start"),
                c.get("clause_char_end"),
                c.get("clause_text"),
                c.get("user_verdict"),
            ])
            count += 1
        return count

    def get_preview_candidates(
        self,
        preview_id: str,
        *,
        page_size: int = 50,
        after_score: float | None = None,
        after_doc_id: str | None = None,
        verdict: str | None = None,
        tier: str | None = None,
    ) -> list[dict[str, Any]]:
        conditions = ["preview_id = ?"]
        params: list[Any] = [preview_id]
        if verdict:
            conditions.append("user_verdict = ?")
            params.append(verdict)
        if tier:
            conditions.append("confidence_tier = ?")
            params.append(tier)
        if after_score is not None and after_doc_id is not None:
            conditions.append("(priority_score < ? OR (priority_score = ? AND doc_id > ?))")
            params.extend([after_score, after_score, after_doc_id])
        where = " AND ".join(conditions)
        params.append(page_size)
        rows = self._conn.execute(
            f"SELECT * FROM preview_candidates WHERE {where} "
            "ORDER BY priority_score DESC, doc_id LIMIT ?",
            params,
        ).fetchall()
        cols = [d[0] for d in self._conn.description]
        return [_to_dict(cols, row) for row in rows]

    def set_candidate_verdict(
        self, preview_id: str, doc_id: str, section_number: str, verdict: str,
    ) -> None:
        self._conn.execute(
            "UPDATE preview_candidates SET user_verdict = ?, verdict_at = ? "
            "WHERE preview_id = ? AND doc_id = ? AND section_number = ?",
            [verdict, _now(), preview_id, doc_id, section_number],
        )

    # ─── Calibration ──────────────────────────────────────────────

    def get_calibration(
        self, family_id: str, template_family: str = "_global",
    ) -> dict[str, Any] | None:
        scope_ids = self.resolve_scope_aliases(family_id)
        if not scope_ids:
            scope_ids = [str(family_id).strip()]
        placeholders = ", ".join("?" for _ in scope_ids)
        row = self._conn.execute(
            f"SELECT * FROM family_link_calibrations "
            f"WHERE family_id IN ({placeholders}) AND template_family = ? "
            "ORDER BY family_id LIMIT 1",
            [*scope_ids, template_family],
        ).fetchone()
        if row is None:
            return None
        cols = [d[0] for d in self._conn.description]
        return _to_dict(cols, row)

    def save_calibration(
        self, family_id: str, template_family: str,
        thresholds: dict[str, Any],
    ) -> None:
        canonical_scope = str(self.get_canonical_scope_id(family_id) or family_id).strip()
        if family_id and canonical_scope:
            self.upsert_family_alias(str(family_id), canonical_scope, source="calibration")
        self._conn.execute("""
            INSERT OR REPLACE INTO family_link_calibrations
            (family_id, template_family, high_threshold, medium_threshold,
             target_precision, sample_size, expected_review_load,
             queue_weights, last_calibrated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, [
            canonical_scope, template_family,
            thresholds.get("high_threshold", 0.8),
            thresholds.get("medium_threshold", 0.5),
            thresholds.get("target_precision", 0.9),
            thresholds.get("sample_size", 0),
            thresholds.get("expected_review_load", 0),
            _opt_json(thresholds, "queue_weights"),
            _now(),
        ])

    # ─── Jobs ─────────────────────────────────────────────────────

    def submit_job(self, job: dict[str, Any]) -> None:
        job_id = job.get("job_id") or _uuid()
        idem_key = job.get("idempotency_key")
        params_json = _json_dumps(job.get("params", {}))
        submitted_at = _now()
        if idem_key:
            self._conn.execute("""
                INSERT INTO job_queue
                (job_id, job_type, status, idempotency_key, params_json,
                 progress_pct, progress_message, submitted_at)
                VALUES (?, ?, 'pending', ?, ?, 0.0, 'Queued', ?)
                ON CONFLICT (idempotency_key) DO NOTHING
            """, [
                job_id,
                job["job_type"],
                idem_key,
                params_json,
                submitted_at,
            ])
            return

        self._conn.execute("""
            INSERT INTO job_queue
            (job_id, job_type, status, idempotency_key, params_json,
             progress_pct, progress_message, submitted_at)
            VALUES (?, ?, 'pending', ?, ?, 0.0, 'Queued', ?)
        """, [
            job_id,
            job["job_type"],
            idem_key,
            params_json,
            submitted_at,
        ])

    def claim_job(self, worker_pid: int) -> dict[str, Any] | None:
        row = self._conn.execute("""
            UPDATE job_queue SET status = 'claimed', claimed_at = current_timestamp,
            worker_pid = ?
            WHERE status = 'pending' AND job_id = (
                SELECT job_id FROM job_queue WHERE status = 'pending'
                ORDER BY submitted_at, job_id LIMIT 1
            ) RETURNING *
        """, [worker_pid]).fetchone()
        if row is None:
            return None
        cols = [d[0] for d in self._conn.description]
        return _to_dict(cols, row)

    def update_job_progress(self, job_id: str, pct: float, message: str) -> None:
        self._conn.execute(
            "UPDATE job_queue SET progress_pct = ?, progress_message = ?, status = 'running' "
            "WHERE job_id = ?", [pct, message, job_id],
        )

    def complete_job(self, job_id: str, result: dict[str, Any]) -> None:
        self._conn.execute(
            "UPDATE job_queue SET status = 'completed', result_json = ?, "
            "completed_at = ? WHERE job_id = ?",
            [_json_dumps(result), _now(), job_id],
        )

    def fail_job(self, job_id: str, error: str) -> None:
        self._conn.execute(
            "UPDATE job_queue SET status = 'failed', error_message = ?, "
            "completed_at = ? WHERE job_id = ?",
            [error, _now(), job_id],
        )

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        row = self._conn.execute("SELECT * FROM job_queue WHERE job_id = ?", [job_id]).fetchone()
        if row is None:
            return None
        cols = [d[0] for d in self._conn.description]
        return _to_dict(cols, row)

    def cancel_job(self, job_id: str) -> bool:
        result = self._conn.execute(
            "UPDATE job_queue SET status = 'cancelled' "
            "WHERE job_id = ? AND status IN ('pending', 'claimed')",
            [job_id],
        )
        return result.fetchone() is not None if hasattr(result, 'fetchone') else True

    # ─── Undo / Redo ──────────────────────────────────────────────

    def record_action(
        self,
        batch_id: str,
        batch_label: str,
        entity_type: str,
        entity_id: str,
        op: str,
        forward_patch: str,
        reverse_patch: str,
        *,
        created_by: str = "user",
    ) -> None:
        self._conn.execute("BEGIN TRANSACTION")
        try:
            row = self._conn.execute("""
                INSERT INTO action_log
                (batch_id, batch_label, entity_type, entity_id, operation,
                 forward_patch, reverse_patch, created_at, created_by)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                RETURNING action_id
            """, [
                batch_id, batch_label, entity_type, entity_id,
                op, forward_patch, reverse_patch, _now(), created_by,
            ]).fetchone()
            if row and row[0]:
                self._conn.execute(
                    "UPDATE undo_state SET current_position = ? WHERE id = 1", [row[0]]
                )
            self._conn.execute("COMMIT")
        except Exception:
            with contextlib.suppress(Exception):
                self._conn.execute("ROLLBACK")
            raise

    def undo(self) -> dict[str, Any] | None:
        pos_row = self._conn.execute(
            "SELECT current_position FROM undo_state WHERE id = 1"
        ).fetchone()
        if not pos_row or pos_row[0] == 0:
            return None
        current_pos = pos_row[0]

        # Find the batch at current position
        batch_row = self._conn.execute(
            "SELECT batch_id, batch_label FROM action_log WHERE action_id = ?",
            [current_pos],
        ).fetchone()
        if not batch_row:
            return None

        batch_id = batch_row[0]
        batch_label = batch_row[1]

        # Get all actions in this batch (in reverse order)
        actions = self._conn.execute(
            "SELECT action_id, entity_type, entity_id, operation, reverse_patch "
            "FROM action_log WHERE batch_id = ? ORDER BY action_id DESC",
            [batch_id],
        ).fetchall()

        # Apply reverse patches
        for action in actions:
            entity_type_ = action[1]
            entity_id = action[2]
            reverse_patch = _json_loads(action[4])
            if entity_type_ == "family_link":
                sets = ", ".join(f"{k} = ?" for k in reverse_patch)
                vals = list(reverse_patch.values()) + [entity_id]
                self._conn.execute(
                    f"UPDATE family_links SET {sets} WHERE link_id = ?", vals
                )

        # Move position back
        prev_actions = self._conn.execute(
            "SELECT MAX(action_id) FROM action_log WHERE action_id < ? AND batch_id != ?",
            [min(a[0] for a in actions), batch_id],
        ).fetchone()
        new_pos = prev_actions[0] if prev_actions and prev_actions[0] else 0
        self._conn.execute("UPDATE undo_state SET current_position = ? WHERE id = 1", [new_pos])

        return {"batch_id": batch_id, "batch_label": batch_label, "actions_reversed": len(actions)}

    def redo(self) -> dict[str, Any] | None:
        pos_row = self._conn.execute(
            "SELECT current_position FROM undo_state WHERE id = 1"
        ).fetchone()
        if not pos_row:
            return None
        current_pos = pos_row[0]

        # Find the next batch after current position
        next_action = self._conn.execute(
            "SELECT batch_id, batch_label FROM action_log WHERE action_id > ? "
            "ORDER BY action_id LIMIT 1",
            [current_pos],
        ).fetchone()
        if not next_action:
            return None

        batch_id = next_action[0]
        batch_label = next_action[1]

        # Get all actions in this batch (forward order)
        actions = self._conn.execute(
            "SELECT action_id, entity_type, entity_id, operation, forward_patch "
            "FROM action_log WHERE batch_id = ? ORDER BY action_id",
            [batch_id],
        ).fetchall()

        # Apply forward patches
        for action in actions:
            entity_type_ = action[1]
            entity_id = action[2]
            forward_patch = _json_loads(action[4])
            if entity_type_ == "family_link":
                sets = ", ".join(f"{k} = ?" for k in forward_patch)
                vals = list(forward_patch.values()) + [entity_id]
                self._conn.execute(
                    f"UPDATE family_links SET {sets} WHERE link_id = ?", vals
                )

        # Advance position
        new_pos = max(a[0] for a in actions)
        self._conn.execute("UPDATE undo_state SET current_position = ? WHERE id = 1", [new_pos])

        return {"batch_id": batch_id, "batch_label": batch_label, "actions_replayed": len(actions)}

    def get_undo_stack(self, limit: int = 20) -> dict[str, Any]:
        pos_row = self._conn.execute(
            "SELECT current_position FROM undo_state WHERE id = 1"
        ).fetchone()
        current_pos = pos_row[0] if pos_row else 0

        batches = self._conn.execute("""
            SELECT DISTINCT batch_id, batch_label, MIN(action_id) as min_id,
                   MAX(action_id) as max_id, COUNT(*) as action_count
            FROM action_log GROUP BY batch_id, batch_label
            ORDER BY max_id DESC LIMIT ?
        """, [limit]).fetchall()

        return {
            "current_position": current_pos,
            "batches": [
                {"batch_id": b[0], "batch_label": b[1], "min_id": b[2],
                 "max_id": b[3], "action_count": b[4]}
                for b in batches
            ],
        }

    # ─── Pins ─────────────────────────────────────────────────────

    def create_pin(
        self, rule_id: str, doc_id: str,
        section_number: str, expected: str,
        note: str | None = None,
    ) -> dict[str, Any]:
        pin_id = _uuid()
        self._conn.execute("""
            INSERT INTO rule_pins
            (pin_id, rule_id, doc_id, section_number,
             expected, note, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, [pin_id, rule_id, doc_id, section_number, expected, note, _now()])
        return {"pin_id": pin_id, "rule_id": rule_id, "doc_id": doc_id,
                "section_number": section_number, "expected": expected, "note": note}

    def save_pin(self, pin: dict[str, Any]) -> dict[str, Any]:
        expected_raw = (
            pin.get("expected")
            or pin.get("expected_verdict")
            or pin.get("pin_type")
            or "true_positive"
        )
        expected_str = str(expected_raw)
        if expected_str in {"tp", "true_positive", "positive"}:
            expected = "true_positive"
        elif expected_str in {"tn", "true_negative", "negative"}:
            expected = "true_negative"
        else:
            expected = "true_positive"
        return self.create_pin(
            str(pin.get("rule_id", "")),
            str(pin.get("doc_id", "")),
            str(pin.get("section_number", "")),
            expected,
            str(pin.get("note", "")) if pin.get("note") is not None else None,
        )

    def delete_pin(self, pin_id: str) -> None:
        self._conn.execute("DELETE FROM rule_pins WHERE pin_id = ?", [pin_id])

    def get_pins(self, rule_id: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM rule_pins WHERE rule_id = ? ORDER BY created_at", [rule_id]
        ).fetchall()
        cols = [d[0] for d in self._conn.description]
        payloads = [_to_dict(cols, row) for row in rows]
        normalized: list[dict[str, Any]] = []
        for payload in payloads:
            expected = str(payload.get("expected", "true_positive"))
            if expected in {"tp", "true_positive", "positive"}:
                pin_type = "tp"
                expected_verdict = "true_positive"
            elif expected in {"tn", "true_negative", "negative"}:
                pin_type = "tn"
                expected_verdict = "true_negative"
            else:
                pin_type = "tp"
                expected_verdict = expected

            heading_row = self._conn.execute(
                "SELECT heading FROM family_links WHERE doc_id = ? AND section_number = ? "
                "ORDER BY created_at DESC LIMIT 1",
                [payload.get("doc_id", ""), payload.get("section_number", "")],
            ).fetchone()
            heading = str(heading_row[0]) if heading_row and heading_row[0] is not None else ""

            normalized.append(
                {
                    **payload,
                    "pin_type": pin_type,
                    "expected_verdict": expected_verdict,
                    "heading": heading,
                }
            )
        return normalized

    def save_pin_evaluation(self, eval_result: dict[str, Any]) -> None:
        self._conn.execute("""
            INSERT INTO pin_evaluations
            (eval_id, rule_id, rule_version, evaluated_at, total_pins, passed, failed, results_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, [
            eval_result.get("eval_id") or _uuid(),
            eval_result["rule_id"], eval_result["rule_version"],
            _now(), eval_result["total_pins"],
            eval_result["passed"], eval_result["failed"],
            _json_dumps(eval_result["results"]),
        ])

    # ─── Sessions & bookmarks ─────────────────────────────────────

    def get_or_create_session(self, scope_type: str, scope_id: str) -> dict[str, Any]:
        row = self._conn.execute(
            "SELECT * FROM review_sessions "
            "WHERE scope_type = ? AND scope_id = ? "
            "AND status = 'active' "
            "ORDER BY last_active_at DESC LIMIT 1",
            [scope_type, scope_id],
        ).fetchone()
        if row:
            cols = [d[0] for d in self._conn.description]
            return _to_dict(cols, row)
        session_id = _uuid()
        now = _now()
        self._conn.execute("""
            INSERT INTO review_sessions
            (session_id, scope_type, scope_id, started_at, last_active_at, status)
            VALUES (?, ?, ?, ?, ?, 'active')
        """, [session_id, scope_type, scope_id, now, now])
        return {"session_id": session_id, "scope_type": scope_type,
                "scope_id": scope_id, "status": "active"}

    def update_session_cursor(self, session_id: str, cursor: dict[str, Any]) -> None:
        self._conn.execute(
            "UPDATE review_sessions SET last_cursor = ?, last_active_at = ? WHERE session_id = ?",
            [_json_dumps(cursor), _now(), session_id],
        )

    def add_mark(
        self, session_id: str, doc_id: str,
        section_number: str, mark_type: str,
        note: str | None = None,
    ) -> None:
        self._conn.execute("""
            INSERT OR REPLACE INTO review_marks
            (session_id, doc_id, section_number, mark_type, note, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, [session_id, doc_id, section_number, mark_type, note, _now()])
        # Update session counters
        if mark_type == "viewed":
            self._conn.execute(
                "UPDATE review_sessions SET rows_viewed = rows_viewed + 1 WHERE session_id = ?",
                [session_id],
            )
        elif mark_type == "bookmarked":
            self._conn.execute(
                "UPDATE review_sessions "
                "SET rows_bookmarked = rows_bookmarked + 1 "
                "WHERE session_id = ?",
                [session_id],
            )

    def get_bookmarks(self, session_id: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM review_marks WHERE session_id = ? AND mark_type = 'bookmarked' "
            "ORDER BY created_at", [session_id],
        ).fetchall()
        cols = [d[0] for d in self._conn.description]
        return [_to_dict(cols, row) for row in rows]

    def session_progress(self, session_id: str) -> dict[str, Any]:
        row = self._conn.execute(
            "SELECT rows_viewed, rows_acted_on, rows_bookmarked, status "
            "FROM review_sessions WHERE session_id = ?", [session_id],
        ).fetchone()
        if not row:
            return {}
        return {"rows_viewed": row[0], "rows_acted_on": row[1],
                "rows_bookmarked": row[2], "status": row[3]}

    # ─── Drift ────────────────────────────────────────────────────

    def save_baseline(self, baseline: dict[str, Any]) -> None:
        self._conn.execute("""
            INSERT INTO rule_baselines
            (baseline_id, rule_id, rule_version, promoted_at,
             total_docs, total_hits, overall_hit_rate, profile_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, [
            baseline.get("baseline_id") or _uuid(),
            baseline["rule_id"], baseline["rule_version"],
            baseline.get("promoted_at", _now()),
            baseline["total_docs"], baseline["total_hits"],
            baseline["overall_hit_rate"],
            _json_dumps(baseline["profile"]),
        ])

    def get_latest_baseline(self, rule_id: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM rule_baselines WHERE rule_id = ? ORDER BY promoted_at DESC LIMIT 1",
            [rule_id],
        ).fetchone()
        if row is None:
            return None
        cols = [d[0] for d in self._conn.description]
        return _to_dict(cols, row)

    def save_drift_check(self, check: dict[str, Any]) -> None:
        self._conn.execute("""
            INSERT INTO drift_checks
            (check_id, rule_id, baseline_id, checked_at, overall_hit_rate,
             chi2_statistic, p_value, max_cell_delta, drift_detected,
             current_profile_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, [
            check.get("check_id") or _uuid(),
            check["rule_id"], check["baseline_id"], _now(),
            check["overall_hit_rate"], check["chi2_statistic"],
            check["p_value"], check["max_cell_delta"],
            check["drift_detected"],
            _json_dumps(check["current_profile"]),
        ])

    def create_drift_alert(self, alert: dict[str, Any]) -> None:
        self._conn.execute("""
            INSERT INTO drift_alerts
            (alert_id, rule_id, check_id, severity, message, cells_affected, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, [
            alert.get("alert_id") or _uuid(),
            alert["rule_id"], alert["check_id"],
            alert["severity"], alert["message"],
            _json_dumps(alert["cells_affected"]), _now(),
        ])

    def get_drift_alerts(
        self, *, acknowledged: bool | None = None, rule_id: str | None = None,
    ) -> list[dict[str, Any]]:
        conditions: list[str] = []
        params: list[Any] = []
        if acknowledged is not None:
            conditions.append("acknowledged = ?")
            params.append(acknowledged)
        if rule_id:
            conditions.append("rule_id = ?")
            params.append(rule_id)
        where = " WHERE " + " AND ".join(conditions) if conditions else ""
        rows = self._conn.execute(
            f"SELECT * FROM drift_alerts{where} ORDER BY created_at DESC", params
        ).fetchall()
        cols = [d[0] for d in self._conn.description]
        return [_to_dict(cols, row) for row in rows]

    def get_drift_checks(self, *, rule_id: str | None = None) -> list[dict[str, Any]]:
        params: list[Any] = []
        where = ""
        if rule_id:
            where = " WHERE rule_id = ?"
            params.append(rule_id)
        rows = self._conn.execute(
            f"SELECT * FROM drift_checks{where} ORDER BY checked_at DESC",
            params,
        ).fetchall()
        cols = [d[0] for d in self._conn.description]
        return [_to_dict(cols, row) for row in rows]

    def acknowledge_alert(self, alert_id: str) -> None:
        self._conn.execute(
            "UPDATE drift_alerts SET acknowledged = TRUE, acknowledged_at = ? WHERE alert_id = ?",
            [_now(), alert_id],
        )

    def acknowledge_drift_alert(self, alert_id: str) -> None:
        self.acknowledge_alert(alert_id)

    # ─── Macros ───────────────────────────────────────────────────

    def get_macros(self, *, family_id: str | None = None) -> list[dict[str, Any]]:
        if family_id:
            rows = self._conn.execute(
                "SELECT * FROM family_link_macros WHERE family_id = ? OR family_id = '_global' "
                "ORDER BY family_id, name", [family_id]
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM family_link_macros ORDER BY family_id, name"
            ).fetchall()
        cols = [d[0] for d in self._conn.description]
        results: list[dict[str, Any]] = []
        for row in rows:
            payload = _to_dict(cols, row)
            self._validate_macro_row(payload)
            results.append(payload)
        return results

    def get_macro(self, macro_id: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM family_link_macros WHERE macro_id = ?", [macro_id]
        ).fetchone()
        if row is None:
            return None
        cols = [d[0] for d in self._conn.description]
        payload = _to_dict(cols, row)
        self._validate_macro_row(payload)
        return payload

    def resolve_macro(self, name: str, family_id: str) -> dict[str, Any] | None:
        # Family-scoped first, then global fallback
        row = self._conn.execute(
            "SELECT * FROM family_link_macros WHERE name = ? AND family_id = ?",
            [name, family_id],
        ).fetchone()
        if row is None:
            row = self._conn.execute(
                "SELECT * FROM family_link_macros WHERE name = ? AND family_id = '_global'",
                [name],
            ).fetchone()
        if row is None:
            return None
        cols = [d[0] for d in self._conn.description]
        payload = _to_dict(cols, row)
        self._validate_macro_row(payload)
        return payload

    def save_macro(self, macro: dict[str, Any]) -> None:
        macro_id = macro.get("macro_id") or _uuid()
        family_id = macro.get("family_id", "_global")
        name = macro["name"]
        ast_json = self._normalize_filter_ast(
            macro.get("ast_json", {}),
            field_name="ast_json",
            allow_empty=True,
        )
        # Delete existing by PK or by unique (family_id, name) before insert
        self._conn.execute(
            "DELETE FROM family_link_macros WHERE macro_id = ? OR (family_id = ? AND name = ?)",
            [macro_id, family_id, name],
        )
        self._conn.execute("""
            INSERT INTO family_link_macros
            (macro_id, family_id, name, description, ast_json, created_by, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, [
            macro_id, family_id, name,
            macro.get("description", ""),
            _json_dumps(ast_json),
            macro.get("created_by", ""),
            macro.get("created_at", _now()), _now(),
        ])

    def delete_macro(self, macro_id: str) -> None:
        self._conn.execute(
            "DELETE FROM family_link_macros WHERE macro_id = ? OR name = ?",
            [macro_id, macro_id],
        )

    # ─── Template baselines ───────────────────────────────────────

    def get_template_baseline(
        self, template_family: str, section_pattern: str,
    ) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM template_baselines WHERE template_family = ? AND section_pattern = ?",
            [template_family, section_pattern],
        ).fetchone()
        if row is None:
            return None
        cols = [d[0] for d in self._conn.description]
        return _to_dict(cols, row)

    def save_template_baseline(self, baseline: dict[str, Any]) -> None:
        bl_id = baseline.get("baseline_id") or _uuid()
        tf = baseline["template_family"]
        sp = baseline["section_pattern"]
        # Delete existing by PK or by unique (template_family, section_pattern)
        self._conn.execute(
            "DELETE FROM template_baselines "
            "WHERE baseline_id = ? "
            "OR (template_family = ? AND section_pattern = ?)",
            [bl_id, tf, sp],
        )
        self._conn.execute("""
            INSERT INTO template_baselines
            (baseline_id, template_family, section_pattern, baseline_text,
             baseline_hash, source, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, [
            bl_id, tf, sp,
            baseline["baseline_text"], baseline["baseline_hash"],
            baseline.get("source", ""), _now(),
        ])

    def list_template_baselines(self, template_family: str | None = None) -> list[dict[str, Any]]:
        if template_family:
            rows = self._conn.execute(
                "SELECT * FROM template_baselines "
                "WHERE template_family = ? "
                "ORDER BY section_pattern",
                [template_family],
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM template_baselines ORDER BY template_family, section_pattern"
            ).fetchall()
        cols = [d[0] for d in self._conn.description]
        return [_to_dict(cols, row) for row in rows]

    def get_template_baselines(self, *, family_id: str | None = None) -> list[dict[str, Any]]:
        """Backward-compatible alias used by the API server."""
        return self.list_template_baselines(template_family=family_id)

    def get_coverage_gaps(self, *, family_id: str | None = None) -> list[dict[str, Any]]:
        """Compute lightweight coverage gaps by family across linked documents."""
        doc_rows = self._conn.execute(
            "SELECT DISTINCT doc_id FROM family_links ORDER BY doc_id"
        ).fetchall()
        all_docs = [str(r[0]) for r in doc_rows if r and r[0] is not None]
        scope_expr = self._scope_sql_expr()

        family_conditions: list[str] = []
        family_params: list[Any] = []
        if family_id:
            scope_ids = self.resolve_scope_aliases(family_id)
            if not scope_ids:
                scope_ids = [str(family_id).strip()]
            placeholders = ", ".join("?" for _ in scope_ids)
            family_conditions.append(f"{scope_expr} IN ({placeholders})")
            family_params.extend(scope_ids)
        family_where = " WHERE " + " AND ".join(family_conditions) if family_conditions else ""

        family_rows = self._conn.execute(
            f"SELECT DISTINCT {scope_expr} AS family_id FROM family_links{family_where} ORDER BY 1",
            family_params,
        ).fetchall()
        family_ids = [str(r[0]) for r in family_rows if r and r[0] is not None]
        requested_scope = self.get_canonical_scope_id(family_id) if family_id else None
        if requested_scope and requested_scope not in family_ids:
            family_ids = [requested_scope]

        results: list[dict[str, Any]] = []
        for fam in family_ids:
            linked_rows = self._conn.execute(
                f"SELECT DISTINCT doc_id FROM family_links "
                f"WHERE {scope_expr} = ? ORDER BY doc_id",
                [fam],
            ).fetchall()
            linked_docs = {str(r[0]) for r in linked_rows if r and r[0] is not None}
            gaps = [
                {
                    "doc_id": doc_id,
                    "why_not": "No link for this family in the document",
                }
                for doc_id in all_docs
                if doc_id not in linked_docs
            ]
            results.append(
                {
                    "family_id": fam,
                    "doc_count": len(linked_docs),
                    "gaps": gaps,
                },
            )
        return results

    # ─── Link defined terms ───────────────────────────────────────

    def get_link_defined_terms(self, link_id: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM link_defined_terms WHERE link_id = ? ORDER BY term", [link_id]
        ).fetchall()
        cols = [d[0] for d in self._conn.description]
        return [_to_dict(cols, row) for row in rows]

    def save_link_defined_terms(self, link_id: str, terms: list[dict[str, Any]]) -> int:
        count = 0
        for t in terms:
            term_id = t.get("id") or _uuid()
            term_name = t["term"]
            # Delete existing by PK or by unique (link_id, term) before insert
            self._conn.execute(
                "DELETE FROM link_defined_terms WHERE id = ? OR (link_id = ? AND term = ?)",
                [term_id, link_id, term_name],
            )
            self._conn.execute("""
                INSERT INTO link_defined_terms
                (id, link_id, term, definition_section_path, definition_char_start,
                 definition_char_end, confidence, extraction_engine, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, [
                term_id, link_id, term_name,
                t["definition_section_path"],
                t["definition_char_start"], t["definition_char_end"],
                t.get("confidence", 1.0),
                t.get("extraction_engine", "definitions"),
                _now(),
            ])
            count += 1
        return count

    def get_link_context_strip(self, link_id: str) -> dict[str, Any]:
        link_row = self._conn.execute(
            "SELECT link_id, family_id, ontology_node_id, doc_id, section_number, heading, link_role "
            "FROM family_links WHERE link_id = ?", [link_id]
        ).fetchone()
        if not link_row:
            return {}
        terms = self.get_link_defined_terms(link_id)
        # Find related xref/definitions links for the same doc
        doc_id = link_row[3]
        related = self._conn.execute(
            "SELECT link_id, family_id, section_number, heading, link_role "
            "FROM family_links WHERE doc_id = ? AND link_id != ? AND "
            "link_role IN ('definitions_support', 'xref_support') "
            "ORDER BY section_number",
            [doc_id, link_id],
        ).fetchall()
        current_scope = str(link_row[2] or link_row[1] or "").strip()
        return {
            "primary": {"link_id": link_row[0], "family_id": link_row[1],
                        "ontology_node_id": link_row[2], "scope_id": current_scope,
                        "doc_id": link_row[3], "section_number": link_row[4],
                        "heading": link_row[5], "role": link_row[6]},
            "defined_terms": terms,
            "related_links": [
                {"link_id": r[0], "family_id": r[1], "section_number": r[2],
                 "heading": r[3], "role": r[4]}
                for r in related
            ],
        }

    def get_context_strip(self, link_id: str) -> dict[str, Any]:
        """Backward-compatible alias expected by API handlers."""
        context = self.get_link_context_strip(link_id)
        if not context:
            return {
                "link_id": link_id,
                "primary_covenant_heading": "",
                "primary_covenant_preview": "",
                "definitions": [],
                "xrefs": [],
                "section_families": [],
                "section_text": None,
            }

        primary = context.get("primary", {})
        definitions = context.get("defined_terms", [])
        related = context.get("related_links", [])
        doc_id = str(primary.get("doc_id", ""))
        section_number = str(primary.get("section_number", ""))
        scope_expr = self._scope_sql_expr()
        section_rows = self._conn.execute(
            f"SELECT DISTINCT {scope_expr} AS family_id "
            "FROM family_links WHERE doc_id = ? AND section_number = ?",
            [doc_id, section_number],
        ).fetchall()
        current_scope = str(primary.get("scope_id") or primary.get("family_id", ""))
        section_families = [
            {
                "family_id": str(row[0]),
                "family_name": str(row[0]).replace("FAM-", "").replace("-", " ").title(),
                "is_current": str(row[0]) == current_scope,
            }
            for row in section_rows
            if row and row[0] is not None
        ]
        return {
            "link_id": str(primary.get("link_id", link_id)),
            "doc_id": doc_id,
            "section_number": section_number,
            "primary_covenant_heading": str(primary.get("heading", "")),
            "primary_covenant_preview": str(primary.get("heading", "")),
            "definitions": [
                {
                    "term": str(d.get("term", "")),
                    "definition_text": str(
                        d.get("definition_text")
                        or (
                            f"Defined in section {d.get('definition_section_path', '')}"
                            if d.get("definition_section_path")
                            else ""
                        )
                    ),
                }
                for d in definitions
            ],
            "xrefs": [
                {
                    "section_ref": str(r.get("section_number", "")),
                    "heading": str(r.get("heading", "")),
                    "text_preview": str(r.get("heading", "")),
                }
                for r in related
            ],
            "section_families": section_families,
            "section_text": None,
        }

    # ─── Reassign ─────────────────────────────────────────────────

    def reassign_link(
        self, link_id: str, new_family_id: str,
        *, reason: str = "",
    ) -> dict[str, Any]:
        # Get current link
        link = self._conn.execute(
            "SELECT * FROM family_links WHERE link_id = ?", [link_id]
        ).fetchone()
        if not link:
            raise ValueError(f"Link not found: {link_id}")
        cols = [d[0] for d in self._conn.description]
        link_dict = _to_dict(cols, link)

        old_family = link_dict["family_id"]

        # Unlink old
        self.unlink(link_id, f"reassigned_to_{new_family_id}", reason)

        # Create new link with new family
        new_link_id = _uuid()
        link_dict["link_id"] = new_link_id
        link_dict["family_id"] = new_family_id
        link_dict["status"] = "active"
        link_dict["run_id"] = link_dict.get("run_id", "reassign")
        self.create_links([link_dict], link_dict["run_id"])

        # Log events
        self.log_event(
            link_id, "reassign_out", "user",
            reason=reason,
            metadata={"new_family": new_family_id,
                      "new_link_id": new_link_id},
        )
        self.log_event(
            new_link_id, "reassign_in", "user",
            reason=reason,
            metadata={"old_family": old_family,
                      "old_link_id": link_id},
        )

        return {"old_link_id": link_id, "new_link_id": new_link_id,
                "old_family": old_family, "new_family": new_family_id}

    # ─── Comparables ──────────────────────────────────────────────

    def find_comparables(
        self, link_id: str, *, family_id: str, template_family: str | None = None, limit: int = 5,
    ) -> list[dict[str, Any]]:
        scope_ids = self.resolve_scope_aliases(family_id)
        if not scope_ids:
            scope_ids = [str(family_id).strip()]
        placeholders = ", ".join("?" for _ in scope_ids)
        scope_expr = self._scope_sql_expr(ontology_column="fl.ontology_node_id", family_column="fl.family_id")
        conditions = [f"{scope_expr} IN ({placeholders})", "fl.link_id != ?", "fl.status = 'active'"]
        params: list[Any] = [*scope_ids, link_id]
        if template_family:
            # Try same template first
            rows = self._conn.execute("""
                SELECT fl.*, d.template_family FROM family_links fl
                LEFT JOIN (SELECT DISTINCT doc_id, ? as template_family) d ON fl.doc_id = d.doc_id
                WHERE {scope_expr} IN ({placeholders}) AND fl.link_id != ? AND fl.status = 'active'
                ORDER BY fl.confidence DESC LIMIT ?
            """.format(scope_expr=scope_expr, placeholders=placeholders), [template_family, *scope_ids, link_id, limit]).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT fl.* FROM family_links fl WHERE " + " AND ".join(conditions) +
                " ORDER BY confidence DESC LIMIT ?",
                params + [limit],
            ).fetchall()
        cols = [d[0] for d in self._conn.description]
        return [_to_dict(cols, row) for row in rows]

    def get_comparables(self, link_id: str, *, limit: int = 5) -> list[dict[str, Any]]:
        """Backward-compatible comparable payload for API handlers."""
        row = self._conn.execute(
            "SELECT family_id FROM family_links WHERE link_id = ?",
            [link_id],
        ).fetchone()
        if row is None:
            return []
        family_id = str(row[0])
        rows = self.find_comparables(link_id, family_id=family_id, limit=limit)
        comparables: list[dict[str, Any]] = []
        for item in rows:
            comparables.append(
                {
                    "doc_id": str(item.get("doc_id", "")),
                    "borrower": str(item.get("doc_id", "")),
                    "section_number": str(item.get("section_number", "")),
                    "heading": str(item.get("heading", "")),
                    "template_family": str(item.get("template_family") or family_id),
                    "similarity_score": float(item.get("confidence", 0.0) or 0.0),
                    "text_preview": str(item.get("heading", "")),
                }
            )
        return comparables

    # ─── Embeddings ───────────────────────────────────────────────

    def get_section_embedding(
        self, doc_id: str, section_number: str, model_version: str,
    ) -> bytes | None:
        row = self._conn.execute(
            "SELECT embedding_vector FROM section_embeddings "
            "WHERE doc_id = ? AND section_number = ? AND model_version = ?",
            [doc_id, section_number, model_version],
        ).fetchone()
        return bytes(row[0]) if row else None

    def save_section_embeddings(self, embeddings: list[dict[str, Any]]) -> int:
        count = 0
        for emb in embeddings:
            self._conn.execute("""
                INSERT OR REPLACE INTO section_embeddings
                (doc_id, section_number, embedding_vector, model_version, text_hash, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, [
                emb["doc_id"], emb["section_number"],
                emb["embedding_vector"], emb["model_version"],
                emb["text_hash"], _now(),
            ])
            count += 1
        return count

    def get_family_centroid(
        self, family_id: str, template_family: str, model_version: str,
    ) -> bytes | None:
        scope_ids = self.resolve_scope_aliases(family_id)
        if not scope_ids:
            scope_ids = [str(family_id).strip()]
        placeholders = ", ".join("?" for _ in scope_ids)
        row = self._conn.execute(
            "SELECT centroid_vector FROM family_centroids "
            f"WHERE family_id IN ({placeholders}) AND template_family = ? AND model_version = ? "
            "ORDER BY family_id LIMIT 1",
            [*scope_ids, template_family, model_version],
        ).fetchone()
        return bytes(row[0]) if row else None

    def save_family_centroid(
        self, family_id: str, template_family: str, centroid: bytes,
        model_version: str, sample_count: int,
    ) -> None:
        canonical_scope = str(self.get_canonical_scope_id(family_id) or family_id).strip()
        if family_id and canonical_scope:
            self.upsert_family_alias(str(family_id), canonical_scope, source="centroid")
        self._conn.execute("""
            INSERT OR REPLACE INTO family_centroids
            (family_id, template_family, centroid_vector, model_version,
             sample_count, last_updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, [canonical_scope, template_family, centroid, model_version, sample_count, _now()])

    def find_similar_sections(
        self, family_id: str, doc_id: str, *, top_k: int = 5,
    ) -> list[dict[str, Any]]:
        # Simple: return sections from same doc that have embeddings
        _ = family_id  # Reserved for future centroid-based similarity
        rows = self._conn.execute(
            "SELECT doc_id, section_number, model_version, text_hash "
            "FROM section_embeddings WHERE doc_id = ? LIMIT ?",
            [doc_id, top_k],
        ).fetchall()
        cols = ["doc_id", "section_number", "model_version", "text_hash"]
        return [_to_dict(cols, row) for row in rows]

    # ─── Starter kits ─────────────────────────────────────────────

    def get_starter_kit(self, family_id: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM family_starter_kits WHERE family_id = ?", [family_id]
        ).fetchone()
        if row is None:
            return None
        cols = [d[0] for d in self._conn.description]
        payload = _to_dict(cols, row)
        return {
            "family_id": str(payload.get("family_id", family_id)),
            "typical_location": self._decode_json_column(payload.get("typical_location")) or {},
            "top_heading_variants": self._decode_json_column(payload.get("top_heading_variants")) or [],
            "top_defined_terms": self._decode_json_column(payload.get("top_defined_terms")) or [],
            "top_dna_phrases": self._decode_json_column(payload.get("top_dna_phrases")) or [],
            "known_exclusions": self._decode_json_column(payload.get("known_exclusions")) or [],
            "auto_generated_rule_ast": self._decode_json_column(payload.get("auto_generated_rule_ast")),
            "last_computed_at": payload.get("last_computed_at"),
        }

    def get_starter_kits(self) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT family_id FROM family_starter_kits ORDER BY family_id"
        ).fetchall()
        out: list[dict[str, Any]] = []
        for row in rows:
            fam_id = str(row[0])
            kit = self.get_starter_kit(fam_id)
            if kit is not None:
                out.append(kit)
        return out

    def save_starter_kit(
        self,
        family_id: str | dict[str, Any],
        kit: dict[str, Any] | None = None,
    ) -> None:
        if isinstance(family_id, dict):
            payload = dict(family_id)
            family_key = str(payload.get("family_id", ""))
        else:
            family_key = str(family_id)
            payload = dict(kit or {})
        self._conn.execute("""
            INSERT OR REPLACE INTO family_starter_kits
            (family_id, typical_location, top_heading_variants, top_defined_terms,
             top_dna_phrases, known_exclusions, auto_generated_rule_ast, last_computed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, [
            family_key,
            _json_dumps(payload.get("typical_location", {})),
            _json_dumps(payload.get("top_heading_variants", payload.get("heading_variants", []))),
            _json_dumps(payload.get("top_defined_terms", payload.get("defined_terms", []))),
            _json_dumps(payload.get("top_dna_phrases", payload.get("dna_phrases", []))),
            _json_dumps(payload.get("known_exclusions", payload.get("exclusions", []))),
            _opt_json(payload, "auto_generated_rule_ast"),
            _now(),
        ])

    def generate_starter_kit(
        self, family_id: str, corpus_stats: dict[str, Any], ontology: dict[str, Any],
    ) -> dict[str, Any]:
        kit = {
            "typical_location": ontology.get("primary_location", {}),
            "top_heading_variants": corpus_stats.get("top_headings", []),
            "top_defined_terms": corpus_stats.get("top_terms", []),
            "top_dna_phrases": corpus_stats.get("top_phrases", []),
            "known_exclusions": ontology.get("known_exclusions", []),
        }
        self.save_starter_kit(family_id, kit)
        return kit

    # ─── Analytics ────────────────────────────────────────────────

    def unlink_reason_analytics(self, *, family_id: str | None = None) -> dict[str, Any]:
        if family_id:
            scope_ids = self.resolve_scope_aliases(family_id)
            if not scope_ids:
                scope_ids = [str(family_id).strip()]
            placeholders = ", ".join("?" for _ in scope_ids)
            scope_expr = self._scope_sql_expr()
            rows = self._conn.execute(
                "SELECT unlinked_reason, COUNT(*) as cnt FROM family_links "
                f"WHERE status = 'unlinked' AND {scope_expr} IN ({placeholders}) "
                "GROUP BY unlinked_reason ORDER BY cnt DESC",
                scope_ids,
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT unlinked_reason, COUNT(*) as cnt FROM family_links "
                "WHERE status = 'unlinked' GROUP BY unlinked_reason ORDER BY cnt DESC"
            ).fetchall()
        return {
            "reasons": [{"reason": r[0], "count": r[1]} for r in rows],
            "total_unlinked": sum(r[1] for r in rows),
        }

    def family_dashboard(self) -> list[dict[str, Any]]:
        return self.family_summary()

    # ─── Cleanup ──────────────────────────────────────────────────

    def run_cleanup(self) -> dict[str, Any]:
        """Enforce all retention policies."""
        stats: dict[str, int] = {}

        # Previews: expire after 1 hour
        self._conn.execute(
            "DELETE FROM preview_candidates WHERE preview_id IN "
            "(SELECT preview_id FROM family_link_previews "
            "WHERE expires_at < current_timestamp AND applied_at IS NULL)"
        )
        stats["expired_candidates"] = 0

        self._conn.execute(
            "DELETE FROM family_link_previews "
            "WHERE expires_at < current_timestamp AND applied_at IS NULL"
        )
        stats["expired_previews"] = 0

        # Jobs: completed/failed older than 7 days, cap 200
        self._conn.execute(
            "DELETE FROM job_queue WHERE status IN ('completed', 'failed') "
            "AND completed_at < current_timestamp - INTERVAL 7 DAY"
        )

        # Cap terminal jobs at 200
        self._conn.execute("""
            DELETE FROM job_queue WHERE job_id IN (
                SELECT job_id FROM job_queue WHERE status IN ('completed', 'failed', 'cancelled')
                ORDER BY completed_at DESC OFFSET 200
            )
        """)

        # Sessions: inactive > 7 days → abandoned
        self._conn.execute(
            "UPDATE review_sessions SET status = 'abandoned' "
            "WHERE last_active_at < current_timestamp - INTERVAL 7 DAY "
            "AND status = 'active'"
        )

        # Delete marks for abandoned sessions
        self._conn.execute(
            "DELETE FROM review_marks WHERE session_id IN "
            "(SELECT session_id FROM review_sessions WHERE status = 'abandoned')"
        )

        # Action log: retain last 500 batches
        self._conn.execute("""
            DELETE FROM action_log WHERE batch_id NOT IN (
                SELECT DISTINCT batch_id FROM (
                    SELECT batch_id, MAX(action_id) as max_id
                    FROM action_log GROUP BY batch_id
                    ORDER BY max_id DESC LIMIT 500
                )
            )
        """)

        # Drift checks: retain last 30 per rule
        self._conn.execute("""
            DELETE FROM drift_checks WHERE check_id NOT IN (
                SELECT check_id FROM (
                    SELECT check_id, ROW_NUMBER() OVER (
                        PARTITION BY rule_id
                        ORDER BY checked_at DESC) as rn
                    FROM drift_checks
                ) WHERE rn <= 30
            )
        """)

        return stats

    # ─── Lifecycle ────────────────────────────────────────────────

    def close(self) -> None:
        """Close the DuckDB connection."""
        if self._conn:
            self._conn.close()
            self._conn = None
