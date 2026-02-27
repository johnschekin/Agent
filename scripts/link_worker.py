#!/usr/bin/env python3
"""Link worker subprocess — sole heavy writer for the linking system.

Polls the ``job_queue`` table in ``links.duckdb`` and processes jobs. The API
server submits jobs; this worker claims and executes them.

**Write discipline**: The API server only writes to ``job_queue``,
``review_sessions``, ``review_marks``, and ``undo_state``. All heavy writes
(links, evidence, previews, candidates, etc.) flow through this worker.

**Crash recovery**: On startup, resets jobs with ``status='claimed'`` or
``status='running'`` and stale worker PIDs back to ``pending``.

Usage:
    python3 scripts/link_worker.py --links-db corpus_index/links.duckdb

    # With optional corpus for preview/apply jobs
    python3 scripts/link_worker.py \\
      --links-db corpus_index/links.duckdb \\
      --db corpus_index/corpus.duckdb

    # Poll interval (seconds, default=2)
    python3 scripts/link_worker.py --links-db corpus_index/links.duckdb --poll-interval 1
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import signal
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


def _json_loads(s: str) -> Any:
    if _orjson is not None:
        return _orjson.loads(s)
    return json.loads(s)


def _json_dumps(obj: Any) -> str:
    if _orjson is not None:
        return _orjson.dumps(obj).decode("utf-8")
    return json.dumps(obj)


def _normalized_clause_key(clause_id: Any, clause_path: Any = None) -> str:
    clause_path_value = str(clause_path or "").strip()
    if clause_path_value:
        return clause_path_value
    clause_id_value = str(clause_id or "").strip()
    if clause_id_value:
        return clause_id_value
    return "__section__"


def _preview_candidate_id(doc_id: Any, section_number: Any, clause_key: Any) -> str:
    return (
        f"{str(doc_id or '').strip()}::"
        f"{str(section_number or '').strip()}::"
        f"{str(clause_key or '__section__').strip() or '__section__'}"
    )


def _log(msg: str) -> None:
    """Write log message to stderr with timestamp."""
    ts = datetime.now(UTC).strftime("%H:%M:%S")
    print(f"[worker {ts}] {msg}", file=sys.stderr)


_PLACEHOLDER_VERSION_VALUES = {
    "",
    "unknown",
    "parser-unknown",
    "bulk_linker_v1",
    "worker_v1",
    "1.0",
}


def _required_lineage_value(field: str, value: Any) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(f"Missing lineage field: {field}")
    if normalized.lower() in _PLACEHOLDER_VERSION_VALUES:
        raise ValueError(f"Placeholder lineage field disallowed: {field}={normalized}")
    return normalized


def _best_effort_git_sha() -> str:
    with contextlib.suppress(Exception):
        from agent.run_manifest import git_commit_hash

        value = git_commit_hash(search_from=Path(__file__).resolve().parents[1])
        if value:
            return str(value).strip()
    return ""


def _resolve_apply_lineage(preview: dict[str, Any], params: dict[str, Any]) -> dict[str, str]:
    preview_params: dict[str, Any] = {}
    raw_params = preview.get("params_json")
    if isinstance(raw_params, str) and raw_params.strip():
        with contextlib.suppress(Exception):
            parsed = _json_loads(raw_params)
            if isinstance(parsed, dict):
                preview_params = parsed
    elif isinstance(raw_params, dict):
        preview_params = dict(raw_params)

    lineage_raw = preview_params.get("lineage")
    lineage = lineage_raw if isinstance(lineage_raw, dict) else {}

    def _pick(field: str) -> Any:
        return (
            params.get(field)
            or preview.get(field)
            or lineage.get(field)
            or preview_params.get(field)
        )

    ruleset_seed = {
        "preview_id": str(preview.get("preview_id") or ""),
        "family_id": str(preview.get("family_id") or ""),
        "rule_id": str(preview.get("rule_id") or ""),
        "candidate_set_hash": str(preview.get("candidate_set_hash") or ""),
    }
    ruleset_digest = hashlib.sha256(
        _json_dumps(ruleset_seed).encode("utf-8")
    ).hexdigest()[:16]

    git_sha = str(_pick("git_sha") or _best_effort_git_sha()).strip()
    corpus_snapshot_id = str(
        _pick("corpus_snapshot_id")
        or f"preview-apply-{str(preview.get('preview_id') or '')[:16]}"
    ).strip()
    ruleset_version = str(
        _pick("ruleset_version")
        or f"preview-ruleset-{ruleset_digest}"
    ).strip()

    now_utc = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    return {
        "corpus_version": _required_lineage_value("corpus_version", _pick("corpus_version")),
        "corpus_snapshot_id": _required_lineage_value("corpus_snapshot_id", corpus_snapshot_id),
        "parser_version": _required_lineage_value("parser_version", _pick("parser_version")),
        "ontology_version": _required_lineage_value("ontology_version", _pick("ontology_version")),
        "ruleset_version": _required_lineage_value("ruleset_version", ruleset_version),
        "git_sha": _required_lineage_value("git_sha", git_sha),
        "created_at_utc": str(_pick("created_at_utc") or now_utc),
    }


# ---------------------------------------------------------------------------
# Worker state
# ---------------------------------------------------------------------------

class LinkWorker:
    """Worker subprocess that polls and processes link jobs.

    Parameters
    ----------
    links_db_path:
        Path to links.duckdb (writable).
    corpus_db_path:
        Optional path to corpus.duckdb (read-only). Required for preview/apply jobs.
    poll_interval:
        Seconds between poll attempts when idle.
    """

    def __init__(
        self,
        links_db_path: Path,
        corpus_db_path: Path | None = None,
        poll_interval: float = 2.0,
    ) -> None:
        self._links_db_path = links_db_path
        self._corpus_db_path = corpus_db_path
        self._poll_interval = poll_interval
        self._running = True
        self._pid = os.getpid()
        self._store: Any = None
        self._corpus: Any = None

    @staticmethod
    def _load_dotenv() -> None:
        """Load .env from project root if it exists."""
        env_path = Path(__file__).resolve().parents[1] / ".env"
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

    def start(self) -> None:
        """Start the worker loop."""
        self._load_dotenv()

        # Add agent source to path
        agent_src = Path(__file__).resolve().parents[1] / "src"
        if str(agent_src) not in sys.path:
            sys.path.insert(0, str(agent_src))

        from agent.link_store import LinkStore

        _log(f"Starting worker (pid={self._pid})")
        _log(f"  links-db: {self._links_db_path}")
        if self._corpus_db_path:
            _log(f"  corpus-db: {self._corpus_db_path}")

        # Open the links store
        self._store = LinkStore(self._links_db_path)

        # Open corpus if provided
        if self._corpus_db_path and self._corpus_db_path.exists():
            from agent.corpus import CorpusIndex
            self._corpus = CorpusIndex(self._corpus_db_path)

        # Crash recovery: reset stale jobs
        self._recover_stale_jobs()

        # Install signal handlers for graceful shutdown
        signal.signal(signal.SIGTERM, self._handle_signal)
        signal.signal(signal.SIGINT, self._handle_signal)

        # Main poll loop
        _log("Worker ready, entering poll loop")
        self._poll_loop()

        # Shutdown
        _log("Worker shutting down")
        self._store.close()
        _log("Worker stopped")

    def stop(self) -> None:
        """Signal the worker to stop after current job completes."""
        self._running = False

    def _handle_signal(self, signum: int, _frame: Any) -> None:
        """Handle SIGTERM/SIGINT for graceful shutdown."""
        sig_name = signal.Signals(signum).name
        _log(f"Received {sig_name}, stopping after current job...")
        self._running = False

    # ─── Crash recovery ──────────────────────────────────────────

    def _recover_stale_jobs(self) -> None:
        """Reset jobs that were claimed/running by a crashed worker.

        On startup, checks for jobs with status='claimed' or 'running' whose
        worker_pid is not alive. Resets them to 'pending'.
        """
        if self._store is None:
            return

        conn = self._store._conn
        stale_rows = conn.execute(
            "SELECT job_id, worker_pid, status FROM job_queue "
            "WHERE status IN ('claimed', 'running')",
        ).fetchall()

        recovered = 0
        for row in stale_rows:
            job_id, worker_pid, status = row[0], row[1], row[2]
            if worker_pid is not None and _is_pid_alive(int(worker_pid)):
                # Still alive — don't reset
                _log(f"  Job {job_id} ({status}) held by live pid {worker_pid}, skipping")
                continue
            conn.execute(
                "UPDATE job_queue SET status = 'pending', worker_pid = NULL, "
                "claimed_at = NULL, progress_pct = 0.0, "
                "progress_message = 'Recovered after worker crash' "
                "WHERE job_id = ?",
                [job_id],
            )
            recovered += 1
            _log(f"  Recovered stale job {job_id} (was {status}, pid={worker_pid})")

        if recovered:
            _log(f"  Recovered {recovered} stale job(s)")
        else:
            _log("  No stale jobs found")

    # ─── Poll loop ───────────────────────────────────────────────

    def _poll_loop(self) -> None:
        """Main polling loop: claim and process jobs."""
        idle_cycles = 0
        while self._running:
            job = self._store.claim_job(self._pid)

            if job is None:
                idle_cycles += 1
                # Exponential backoff up to 5x poll interval
                sleep_time = min(
                    self._poll_interval * (1 + idle_cycles * 0.2),
                    self._poll_interval * 5,
                )
                time.sleep(sleep_time)
                continue

            idle_cycles = 0
            self._process_job(job)

    # ─── Job dispatch ────────────────────────────────────────────

    def _process_job(self, job: dict[str, Any]) -> None:
        """Dispatch a job to the appropriate handler."""
        job_id = job["job_id"]
        job_type = job["job_type"]
        params = _json_loads(job.get("params_json", "{}"))

        _log(f"Processing job {job_id} (type={job_type})")

        try:
            self._store.update_job_progress(job_id, 0.0, f"Starting {job_type}")

            handler = self._get_handler(job_type)
            if handler is None:
                self._store.fail_job(job_id, f"Unknown job type: {job_type}")
                _log(f"  Failed: unknown job type {job_type}")
                return

            result = handler(job_id, params)

            self._store.complete_job(job_id, result or {})
            _log(f"  Completed job {job_id}")

        except Exception as e:
            error_msg = f"{type(e).__name__}: {e}"
            with contextlib.suppress(Exception):
                self._store.fail_job(job_id, error_msg)
            _log(f"  Failed job {job_id}: {error_msg}")

    def _get_handler(self, job_type: str) -> Any:
        """Return the handler function for a job type."""
        handlers: dict[str, Any] = {
            "preview": self._handle_preview,
            "apply": self._handle_apply,
            "canary": self._handle_canary,
            "batch_run": self._handle_batch_run,
            "embeddings_compute": self._handle_embeddings_compute,
            "check_drift": self._handle_check_drift,
            "export": self._handle_export,
        }
        return handlers.get(job_type)

    def _is_cancelled(self, job_id: str) -> bool:
        """Check if a job has been cancelled."""
        job = self._store.get_job(job_id)
        return job is not None and job.get("status") == "cancelled"

    # ─── Job handlers ────────────────────────────────────────────

    def _handle_preview(
        self, job_id: str, params: dict[str, Any],
    ) -> dict[str, Any]:
        """Generate a link preview for a rule/query.

        Evaluates the rule against corpus sections, computes confidence,
        and stores candidates in the preview tables.
        """
        family_id = params.get("family_id", "")
        rule_id = params.get("rule_id")
        heading_ast_raw = params.get("heading_filter_ast")

        # Load rule if rule_id provided
        rule: dict[str, Any] | None = None
        if rule_id:
            rule = self._store.get_rule(rule_id)
            if rule is None:
                return {"error": f"Rule not found: {rule_id}"}
            heading_ast_raw = heading_ast_raw or rule.get("heading_filter_ast")
            family_id = family_id or rule.get("family_id", "")
        resolved_scope = self._store.get_canonical_scope_id(family_id) if family_id else None
        family_id = resolved_scope or family_id

        if heading_ast_raw is None:
            return {"error": "No heading_filter_ast provided"}

        self._store.update_job_progress(job_id, 10.0, "Scanning corpus")

        # Scan corpus for matches
        candidates = self._scan_for_candidates(
            job_id, family_id, heading_ast_raw, rule,
        )

        if self._is_cancelled(job_id):
            return {"status": "cancelled"}

        self._store.update_job_progress(
            job_id, 80.0, f"Found {len(candidates)} candidates",
        )

        # Store preview
        import hashlib
        import uuid

        preview_id = str(uuid.uuid4())
        candidate_hashes = sorted(
            _preview_candidate_id(
                c.get("doc_id", ""),
                c.get("section_number", ""),
                _normalized_clause_key(c.get("clause_id"), c.get("clause_path")),
            )
            for c in candidates
        )
        candidate_set_hash = hashlib.sha256(
            "|".join(candidate_hashes).encode(),
        ).hexdigest()[:16]

        git_sha = str(params.get("git_sha") or _best_effort_git_sha()).strip()
        if not git_sha:
            git_sha = f"worker-src-{hashlib.sha256(preview_id.encode('utf-8')).hexdigest()[:12]}"
        corpus_version = str(
            params.get("corpus_version")
            or getattr(self._corpus, "schema_version", "")
            or "corpus-preview"
        ).strip()
        parser_version = str(
            params.get("parser_version")
            or (f"parser-{git_sha[:12]}" if git_sha else "")
            or "parser-preview"
        ).strip()
        rule_ontology_version = str(
            rule.get("ontology_version") if isinstance(rule, dict) else ""
        ).strip()
        ontology_version = str(
            params.get("ontology_version")
            or rule_ontology_version
            or "ontology-preview"
        ).strip()
        ruleset_version = str(
            params.get("ruleset_version")
            or f"preview-ruleset-{candidate_set_hash}"
        ).strip()
        corpus_snapshot_id = str(
            params.get("corpus_snapshot_id")
            or f"preview-snapshot-{preview_id[:12]}"
        ).strip()
        created_at_utc = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        preview_lineage = {
            "corpus_version": _required_lineage_value("corpus_version", corpus_version),
            "corpus_snapshot_id": _required_lineage_value("corpus_snapshot_id", corpus_snapshot_id),
            "parser_version": _required_lineage_value("parser_version", parser_version),
            "ontology_version": _required_lineage_value("ontology_version", ontology_version),
            "ruleset_version": _required_lineage_value("ruleset_version", ruleset_version),
            "git_sha": _required_lineage_value("git_sha", git_sha),
            "created_at_utc": created_at_utc,
        }

        # Tier breakdown
        by_tier: dict[str, int] = {"high": 0, "medium": 0, "low": 0}
        for c in candidates:
            tier = c.get("confidence_tier", "low")
            by_tier[tier] = by_tier.get(tier, 0) + 1

        self._store.save_preview({
            "preview_id": preview_id,
            "family_id": family_id,
            "ontology_node_id": family_id,
            "rule_id": rule_id or "",
            "corpus_version": preview_lineage["corpus_version"],
            "parser_version": preview_lineage["parser_version"],
            "ontology_version": preview_lineage["ontology_version"],
            "params_json": {
                "query_ast": heading_ast_raw,
                "lineage": preview_lineage,
            },
            "candidate_count": len(candidates),
            "candidate_set_hash": candidate_set_hash,
        })

        # Store candidates
        preview_candidates = []
        for c in candidates:
            clause_key = _normalized_clause_key(c.get("clause_id"), c.get("clause_path"))
            preview_candidates.append({
                "candidate_id": _preview_candidate_id(
                    c.get("doc_id", ""),
                    c.get("section_number", ""),
                    clause_key,
                ),
                "doc_id": c["doc_id"],
                "section_number": c["section_number"],
                "heading": c.get("heading", ""),
                "clause_id": c.get("clause_id"),
                "clause_path": c.get("clause_path"),
                "clause_key": clause_key,
                "confidence": c.get("confidence", 0.0),
                "confidence_tier": c.get("confidence_tier", "low"),
                "user_verdict": "pending",
            })

        if preview_candidates:
            self._store.save_preview_candidates(preview_id, preview_candidates)

        self._store.update_job_progress(job_id, 100.0, "Preview ready")

        return {
            "preview_id": preview_id,
            "candidate_count": len(candidates),
            "candidate_set_hash": candidate_set_hash,
            "by_confidence_tier": by_tier,
        }

    def _handle_apply(
        self, job_id: str, params: dict[str, Any],
    ) -> dict[str, Any]:
        """Apply a preview — create links from accepted candidates.

        Validates preview_id, checks candidate_set_hash integrity,
        and rejects expired previews.
        """
        preview_id = params.get("preview_id", "")
        expected_hash = params.get("candidate_set_hash")
        # Load preview
        preview = self._store.get_preview(preview_id)
        if preview is None:
            return {"error": "Preview not found", "code": 404}

        # Check expiry (1 hour)
        created_at = preview.get("created_at", "")
        if created_at:
            try:
                created = datetime.fromisoformat(created_at)
                age = datetime.now(UTC) - created.replace(
                    tzinfo=UTC,
                )
                if age.total_seconds() > 3600:
                    return {"error": "Preview expired", "code": 409}
            except (ValueError, TypeError):
                pass

        # Check candidate set hash
        if expected_hash and preview.get("candidate_set_hash") != expected_hash:
            return {
                "error": "Candidate set hash mismatch",
                "code": 409,
                "expected": expected_hash,
                "actual": preview.get("candidate_set_hash"),
            }

        self._store.update_job_progress(job_id, 20.0, "Loading candidates")

        # Load accepted candidates (full preview set).
        candidates = self._store.get_preview_candidates(preview_id, page_size=100000)
        accepted = [
            c for c in candidates
            if c.get("user_verdict") == "accepted"
        ]

        if not accepted:
            return {"links_created": 0, "message": "No accepted candidates"}

        try:
            lineage = _resolve_apply_lineage(preview, params)
        except ValueError as exc:
            return {
                "error": str(exc),
                "code": 409,
                "preview_id": preview_id,
            }

        self._store.update_job_progress(
            job_id, 50.0, f"Creating {len(accepted)} links",
        )

        # Create/update links
        import uuid
        run_id = str(uuid.uuid4())
        preview_params: dict[str, Any] = {}
        raw_preview_params = preview.get("params_json")
        if isinstance(raw_preview_params, str):
            with contextlib.suppress(Exception):
                parsed_preview_params = _json_loads(raw_preview_params)
                if isinstance(parsed_preview_params, dict):
                    preview_params = parsed_preview_params
        elif isinstance(raw_preview_params, dict):
            preview_params = dict(raw_preview_params)
        ontology_node_id = str(
            preview.get("ontology_node_id")
            or preview_params.get("ontology_node_id")
            or preview.get("family_id")
            or ""
        ).strip() or None
        family_scope = str(preview.get("family_id", "") or "").strip()
        link_scope_id = str(ontology_node_id or family_scope or "").strip()
        scope_aliases = self._store.resolve_scope_aliases(link_scope_id) if link_scope_id else []
        if link_scope_id and not scope_aliases:
            scope_aliases = [link_scope_id]
        scope_aliases = [str(scope).strip() for scope in scope_aliases if str(scope).strip()]

        links_to_create = []
        links_updated = 0
        clause_details_cache: dict[
            tuple[str, str, str],
            tuple[int | None, int | None, str | None],
        ] = {}

        def _resolve_clause_details(
            doc_id: str,
            section_number: str,
            clause_id: str | None,
        ) -> tuple[int | None, int | None, str | None]:
            cid = str(clause_id or "").strip()
            if not cid:
                return (None, None, None)
            key = (doc_id, section_number, cid)
            if key in clause_details_cache:
                return clause_details_cache[key]
            details: tuple[int | None, int | None, str | None] = (None, None, None)
            if self._corpus is not None:
                row = self._corpus._conn.execute(  # noqa: SLF001
                    "SELECT span_start, span_end, clause_text FROM clauses "
                    "WHERE doc_id = ? AND section_number = ? AND clause_id = ? LIMIT 1",
                    [doc_id, section_number, cid],
                ).fetchone()
                if row is not None:
                    details = (
                        int(row[0]) if row[0] is not None else None,
                        int(row[1]) if row[1] is not None else None,
                        str(row[2]) if row[2] is not None else None,
                    )
            clause_details_cache[key] = details
            return details

        for cand in accepted:
            doc_id = str(cand.get("doc_id", ""))
            section_number = str(cand.get("section_number", ""))
            clause_id = str(cand.get("clause_id", "") or "").strip() or None
            clause_path = str(cand.get("clause_path", "") or "").strip() or None
            clause_key = _normalized_clause_key(clause_id, clause_path)
            clause_char_start = cand.get("clause_char_start")
            clause_char_end = cand.get("clause_char_end")
            clause_text = str(cand.get("clause_text") or "").strip() or None
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

            link_payload = {
                "family_id": preview.get("family_id", ""),
                "ontology_node_id": ontology_node_id,
                "scope_id": link_scope_id or str(preview.get("family_id", "") or ""),
                "doc_id": doc_id,
                "section_number": section_number,
                "heading": cand.get("heading", ""),
                "rule_id": preview.get("rule_id"),
                "source": "preview_apply",
                "confidence": cand.get("confidence", 0.0),
                "score_raw": cand.get("score_raw", cand.get("confidence", 0.0)),
                "score_calibrated": cand.get("score_calibrated", cand.get("confidence", 0.0)),
                "threshold_profile_id": cand.get("threshold_profile_id"),
                "policy_decision": cand.get("policy_decision"),
                "policy_reasons": cand.get("policy_reasons"),
                "confidence_tier": cand.get("confidence_tier", "low"),
                "status": "active",
                "clause_id": clause_id,
                "clause_key": clause_key,
                "clause_char_start": clause_char_start,
                "clause_char_end": clause_char_end,
                "clause_text": clause_text,
                "corpus_version": lineage["corpus_version"],
                "parser_version": lineage["parser_version"],
                "ontology_version": lineage["ontology_version"],
            }

            if scope_aliases:
                placeholders = ", ".join("?" for _ in scope_aliases)
                existing = self._store._conn.execute(  # noqa: SLF001
                    "SELECT link_id FROM family_links "
                    "WHERE COALESCE(NULLIF(TRIM(scope_id), ''), NULLIF(TRIM(ontology_node_id), ''), NULLIF(TRIM(family_id), ''), '') "
                    f"IN ({placeholders}) AND doc_id = ? AND section_number = ? "
                    "AND COALESCE(NULLIF(TRIM(clause_key), ''), NULLIF(TRIM(clause_id), ''), '__section__') = ? "
                    "LIMIT 1",
                    [
                        *scope_aliases,
                        link_payload["doc_id"],
                        link_payload["section_number"],
                        clause_key,
                    ],
                ).fetchone()
            else:
                existing = self._store._conn.execute(  # noqa: SLF001
                    "SELECT link_id FROM family_links "
                    "WHERE family_id = ? AND doc_id = ? AND section_number = ? "
                    "AND COALESCE(NULLIF(TRIM(clause_key), ''), NULLIF(TRIM(clause_id), ''), '__section__') = ? "
                    "LIMIT 1",
                    [
                        link_payload["family_id"],
                        link_payload["doc_id"],
                        link_payload["section_number"],
                        clause_key,
                    ],
                ).fetchone()
            if existing:
                self._store._conn.execute(  # noqa: SLF001
                    "UPDATE family_links SET "
                    "ontology_node_id = ?, scope_id = ?, heading = ?, rule_id = ?, run_id = ?, source = ?, "
                    "clause_id = ?, clause_key = ?, clause_char_start = ?, clause_char_end = ?, clause_text = ?, "
                    "confidence = ?, score_raw = ?, score_calibrated = ?, threshold_profile_id = ?, "
                    "policy_decision = ?, policy_reasons = ?, "
                    "confidence_tier = ?, status = 'active', "
                    "corpus_version = ?, parser_version = ?, ontology_version = ?, "
                    "unlinked_at = NULL, unlinked_reason = NULL, unlinked_note = NULL "
                    "WHERE link_id = ?",
                    [
                        link_payload["ontology_node_id"],
                        link_payload["scope_id"],
                        link_payload["heading"],
                        link_payload["rule_id"],
                        run_id,
                        link_payload["source"],
                        link_payload["clause_id"],
                        link_payload["clause_key"],
                        link_payload["clause_char_start"],
                        link_payload["clause_char_end"],
                        link_payload["clause_text"],
                        link_payload["confidence"],
                        link_payload["score_raw"],
                        link_payload["score_calibrated"],
                        link_payload["threshold_profile_id"],
                        link_payload["policy_decision"],
                        json.dumps(link_payload["policy_reasons"]) if link_payload.get("policy_reasons") is not None else None,
                        link_payload["confidence_tier"],
                        link_payload["corpus_version"],
                        link_payload["parser_version"],
                        link_payload["ontology_version"],
                        str(existing[0]),
                    ],
                )
                links_updated += 1
                continue

            links_to_create.append({
                **link_payload,
            })

        created_new = self._store.create_links(links_to_create, run_id)
        created = created_new + links_updated

        # Save run metadata
        self._store.create_run({
            "run_id": run_id,
            "run_type": "apply",
            "family_id": preview.get("family_id", ""),
            "rule_id": preview.get("rule_id"),
            "corpus_version": lineage["corpus_version"],
            "corpus_snapshot_id": lineage["corpus_snapshot_id"],
            "corpus_doc_count": len(accepted),
            "parser_version": lineage["parser_version"],
            "ontology_version": lineage["ontology_version"],
            "ruleset_version": lineage["ruleset_version"],
            "git_sha": lineage["git_sha"],
            "created_at_utc": lineage["created_at_utc"],
            "links_created": created,
        })

        self._store.update_job_progress(job_id, 100.0, "Apply complete")

        return {
            "run_id": run_id,
            "links_created": created,
            "links_updated": links_updated,
            "preview_id": preview_id,
        }

    def _handle_canary(
        self, job_id: str, params: dict[str, Any],
    ) -> dict[str, Any]:
        """Canary apply: apply to first N documents only.

        Delegates to bulk_family_linker with --canary N.
        """
        from scripts.bulk_family_linker import run_bulk_linking

        canary_n = params.get("canary_n", 10)
        family_id = params.get("family_id")
        resolved_scope = self._store.get_canonical_scope_id(family_id) if family_id else None

        if self._corpus is None:
            return {"error": "Corpus not available for canary run"}

        rules = self._store.get_rules(
            family_id=resolved_scope or family_id, status="published",
        )
        if not rules:
            return {"error": "No published rules found"}

        self._store.update_job_progress(job_id, 10.0, f"Canary: {canary_n} docs")

        result = run_bulk_linking(
            self._corpus,
            self._store,
            rules,
            family_filter=resolved_scope or family_id,
            canary_n=canary_n,
            dry_run=False,
        )

        return result

    def _handle_batch_run(
        self, job_id: str, params: dict[str, Any],
    ) -> dict[str, Any]:
        """Run all published rules against the full corpus."""
        from scripts.bulk_family_linker import run_bulk_linking

        if self._corpus is None:
            return {"error": "Corpus not available for batch run"}

        rules = self._store.get_rules(status="published")
        if not rules:
            return {"error": "No published rules found"}

        family_id = params.get("family_id")
        resolved_scope = self._store.get_canonical_scope_id(family_id) if family_id else None

        self._store.update_job_progress(
            job_id, 5.0, f"Batch run: {len(rules)} rules",
        )

        result = run_bulk_linking(
            self._corpus,
            self._store,
            rules,
            family_filter=resolved_scope or family_id,
            dry_run=False,
        )

        return result

    def _handle_embeddings_compute(
        self, job_id: str, params: dict[str, Any],
    ) -> dict[str, Any]:
        """Compute/refresh section embeddings for a family.

        If ``family_id`` is provided, embeds sections from active links for
        that family plus recomputes the family centroid.  If omitted, embeds
        sections from *all* active links across all families.
        """
        from agent.embeddings import VoyageEmbeddingModel, EmbeddingManager

        family_id = params.get("family_id")
        resolved_scope = self._store.get_canonical_scope_id(family_id) if family_id else None
        self._store.update_job_progress(job_id, 10.0, "Loading active links")

        # Get sections that need embedding
        links = self._store.get_links(
            family_id=resolved_scope or family_id, status="active", limit=100000,
        )

        if not links:
            return {
                "family_id": family_id,
                "sections_prepared": 0,
                "sections_embedded": 0,
                "status": "sections_ready",
            }

        # Collect section texts from corpus
        sections: list[dict[str, str]] = []
        skipped = 0
        for link in links:
            if self._corpus:
                text = self._corpus.get_section_text(
                    link["doc_id"], link["section_number"],
                )
                if text:
                    sections.append({
                        "doc_id": link["doc_id"],
                        "section_number": link["section_number"],
                        "text": text,
                    })
                else:
                    skipped += 1

        if not sections:
            return {
                "family_id": family_id,
                "sections_prepared": 0,
                "sections_embedded": 0,
                "skipped": skipped,
                "status": "sections_ready",
            }

        # Keep local/dev workflows usable without external embedding credentials:
        # when model init fails, return prepared sections for later embedding.
        self._store.update_job_progress(job_id, 15.0, "Initializing Voyage model")
        try:
            model = VoyageEmbeddingModel()
        except ValueError:
            self._store.update_job_progress(job_id, 100.0, "Sections prepared")
            return {
                "family_id": family_id,
                "sections_prepared": len(sections),
                "sections_embedded": 0,
                "skipped": skipped,
                "status": "sections_ready",
            }

        manager = EmbeddingManager(model=model, store=self._store)
        self._store.update_job_progress(
            job_id, 20.0, f"Embedding {len(sections)} sections via Voyage",
        )

        # Embed in batches (EmbeddingManager handles batching internally)
        # Process in chunks of 500 to allow progress updates
        chunk_size = 500
        total_stored = 0
        for chunk_start in range(0, len(sections), chunk_size):
            if self._is_cancelled(job_id):
                return {
                    "family_id": family_id,
                    "sections_embedded": total_stored,
                    "status": "cancelled",
                }
            chunk = sections[chunk_start:chunk_start + chunk_size]
            stored = manager.embed_and_store(chunk)
            total_stored += stored
            pct = 20.0 + (70.0 * min(chunk_start + chunk_size, len(sections)) / len(sections))
            self._store.update_job_progress(
                job_id, pct, f"Embedded {total_stored}/{len(sections)} sections",
            )

        # Recompute family centroid(s)
        self._store.update_job_progress(job_id, 92.0, "Computing centroids")

        centroid_families: list[str] = []
        if resolved_scope or family_id:
            centroid_families = [resolved_scope or family_id]
        else:
            # Collect unique family_ids from the links
            seen: set[str] = set()
            for link in links:
                fid = str(link.get("ontology_node_id") or link.get("family_id", ""))
                if fid and fid not in seen:
                    seen.add(fid)
                    centroid_families.append(fid)

        centroids_computed = 0
        for fid in centroid_families:
            fam_links = [
                {"doc_id": l["doc_id"], "section_number": l["section_number"]}
                for l in links if (l.get("ontology_node_id") or l.get("family_id")) == fid
            ]
            centroid = manager.compute_centroid(fid, fam_links)
            if centroid is not None:
                centroids_computed += 1

        self._store.update_job_progress(job_id, 100.0, "Done")

        return {
            "family_id": family_id,
            "sections_prepared": len(sections),
            "sections_embedded": total_stored,
            "skipped": skipped,
            "centroids_computed": centroids_computed,
            "model": model.model_version(),
            "dimensions": model.dimensions(),
            "status": "completed",
        }

    def _handle_check_drift(
        self, job_id: str, params: dict[str, Any],
    ) -> dict[str, Any]:
        """Check for drift in a rule's match set."""
        rule_id = params.get("rule_id", "")

        self._store.update_job_progress(job_id, 10.0, "Checking drift")

        # Get current matches
        rule = self._store.get_rule(rule_id)
        if rule is None:
            return {"error": f"Rule not found: {rule_id}"}

        # Count current links for this rule
        links = self._store.get_links(limit=100000)
        rule_links = [lnk for lnk in links if lnk.get("rule_id") == rule_id]

        self._store.update_job_progress(job_id, 50.0, "Computing statistics")

        # Simple drift detection: compare current count to expected
        current_count = len(rule_links)

        result: dict[str, Any] = {
            "rule_id": rule_id,
            "family_id": rule.get("family_id", ""),
            "current_link_count": current_count,
            "drift_detected": False,
            "details": {},
        }

        # If there's a drift baseline, compare
        baselines = self._store._conn.execute(
            "SELECT * FROM drift_baselines WHERE rule_id = ? "
            "ORDER BY created_at DESC LIMIT 1",
            [rule_id],
        ).fetchone()

        if baselines:
            cols = [d[0] for d in self._store._conn.description]
            baseline = dict(zip(cols, baselines, strict=True))
            expected = baseline.get("expected_count", current_count)
            if expected > 0:
                drift_pct = abs(current_count - expected) / expected
                if drift_pct > 0.1:  # >10% drift
                    result["drift_detected"] = True
                    result["details"] = {
                        "expected_count": expected,
                        "actual_count": current_count,
                        "drift_pct": round(drift_pct * 100, 2),
                    }

        self._store.update_job_progress(job_id, 100.0, "Drift check complete")
        return result

    def _handle_export(
        self, job_id: str, params: dict[str, Any],
    ) -> dict[str, Any]:
        """Export links data as CSV/JSONL."""
        export_format = params.get("format", "csv")
        family_id = params.get("family_id")
        resolved_scope = self._store.get_canonical_scope_id(family_id) if family_id else None
        status = params.get("status")
        contract_format = str(params.get("contract_format") or "wave3-handoff").strip() or "wave3-handoff"
        evidence_schema_version = str(params.get("evidence_schema_version") or "evidence_v3").strip() or "evidence_v3"
        labeled_export_schema_version = (
            str(params.get("labeled_export_schema_version") or "labeled_export_v2").strip()
            or "labeled_export_v2"
        )

        self._store.update_job_progress(job_id, 10.0, "Fetching links")

        links = self._store.get_links(
            family_id=resolved_scope or family_id,
            status=status,
            limit=1000000,
        )

        self._store.update_job_progress(
            job_id, 50.0, f"Exporting {len(links)} links as {export_format}",
        )

        if export_format == "csv":
            import csv
            import io
            output = io.StringIO()
            if links:
                writer = csv.DictWriter(
                    output,
                    fieldnames=[
                        "link_id", "family_id", "doc_id", "section_number",
                        "heading", "confidence", "confidence_tier", "status",
                    ],
                )
                writer.writeheader()
                for lnk in links:
                    writer.writerow({
                        k: lnk.get(k, "") for k in writer.fieldnames  # type: ignore[union-attr]
                    })
            export_data = output.getvalue()
        else:
            rows = []
            for lnk in links:
                rows.append(_json_dumps(lnk))
            export_data = "\n".join(rows)

        self._store.update_job_progress(job_id, 100.0, "Export complete")

        return {
            "schema_version": "link_export_v1",
            "format": export_format,
            "contract_format": contract_format,
            "evidence_schema_version": evidence_schema_version,
            "labeled_export_schema_version": labeled_export_schema_version,
            "row_count": len(links),
            "data_length": len(export_data),
        }

    # ─── Internal helpers ────────────────────────────────────────

    def _scan_for_candidates(
        self,
        job_id: str,
        family_id: str,
        heading_ast_raw: dict[str, Any],
        rule: dict[str, Any] | None,
    ) -> list[dict[str, Any]]:
        """Scan corpus sections matching a heading AST."""
        from scripts.bulk_family_linker import scan_corpus_for_family

        if self._corpus is None:
            return []

        # Build a rule-like dict for scan_corpus_for_family
        scan_rule: dict[str, Any] = rule or {}
        scan_rule.setdefault("family_id", family_id)
        scan_rule.setdefault("heading_filter_ast", heading_ast_raw)

        candidates = scan_corpus_for_family(
            self._corpus,
            scan_rule,
        )

        return candidates


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _is_pid_alive(pid: int) -> bool:
    """Check if a process with the given PID is still running."""
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser."""
    parser = argparse.ArgumentParser(
        description="Link worker subprocess: polls job_queue and processes jobs",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--links-db", required=True,
        help="Path to links DuckDB (corpus_index/links.duckdb)",
    )
    parser.add_argument(
        "--db", default=None,
        help="Path to corpus DuckDB (for preview/apply jobs)",
    )
    parser.add_argument(
        "--poll-interval", type=float, default=2.0,
        help="Seconds between poll attempts (default: 2.0)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Main entry point."""
    parser = build_parser()
    args = parser.parse_args(argv)

    links_db_path = Path(args.links_db)
    if not links_db_path.exists():
        _log(f"Error: links database not found: {links_db_path}")
        return 1

    corpus_db_path = Path(args.db) if args.db else None
    if corpus_db_path and not corpus_db_path.exists():
        _log(f"Warning: corpus database not found: {corpus_db_path}")
        corpus_db_path = None

    # Add agent source to path
    agent_src = Path(__file__).resolve().parents[1] / "src"
    if str(agent_src) not in sys.path:
        sys.path.insert(0, str(agent_src))

    worker = LinkWorker(
        links_db_path=links_db_path,
        corpus_db_path=corpus_db_path,
        poll_interval=args.poll_interval,
    )

    worker.start()
    return 0


if __name__ == "__main__":
    sys.exit(main())
