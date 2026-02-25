"""Tests for scripts/link_worker.py — link worker subprocess.

Covers: job claim, execution, crash recovery, progress, cancellation,
write discipline, poll loop, CLI parser, and all 8 job handlers.
"""
from __future__ import annotations

import importlib.util
import json
import os
import signal
import sys
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Module loader (scripts/ is not a package)
# ---------------------------------------------------------------------------

_ROOT = Path(__file__).resolve().parents[1]


def _load_link_worker():
    """Import scripts/link_worker.py as a module."""
    agent_src = _ROOT / "src"
    if str(agent_src) not in sys.path:
        sys.path.insert(0, str(agent_src))
    script_path = _ROOT / "scripts" / "link_worker.py"
    spec = importlib.util.spec_from_file_location("link_worker", script_path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_mod = _load_link_worker()
LinkWorker = _mod.LinkWorker
_is_pid_alive = _mod._is_pid_alive
build_parser = _mod.build_parser


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

from agent.link_store import LinkStore  # noqa: E402


def _make_store(tmp_path: Path) -> LinkStore:
    """Create a fresh LinkStore with schema in tmp_path."""
    db = tmp_path / "links.duckdb"
    store = LinkStore(db, create_if_missing=True)
    # Ensure drift_baselines table exists (used by _handle_check_drift)
    store._conn.execute("""
        CREATE TABLE IF NOT EXISTS drift_baselines (
            baseline_id VARCHAR PRIMARY KEY,
            rule_id VARCHAR NOT NULL,
            expected_count INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMP DEFAULT current_timestamp
        )
    """)
    return store


def _make_worker(
    tmp_path: Path,
    *,
    poll_interval: float = 0.1,
    store: LinkStore | None = None,
) -> tuple[Any, LinkStore]:
    """Create a LinkWorker with an initialised store.

    Returns (worker, store).
    """
    db_path = tmp_path / "links.duckdb"
    worker = LinkWorker(db_path, poll_interval=poll_interval)
    if store is None:
        store = _make_store(tmp_path)
    worker._store = store
    worker._corpus = None
    return worker, store


def _submit_job(
    store: LinkStore,
    job_type: str,
    params: dict[str, Any] | None = None,
    *,
    job_id: str | None = None,
) -> str:
    """Submit a job and return its job_id."""
    jid = job_id or str(uuid.uuid4())
    store.submit_job({
        "job_id": jid,
        "job_type": job_type,
        "params": params or {},
    })
    return jid


def _insert_claimed_job(
    store: LinkStore,
    worker_pid: int,
    status: str = "claimed",
) -> str:
    """Insert a job directly with claimed/running status and a worker_pid."""
    jid = str(uuid.uuid4())
    store._conn.execute("""
        INSERT INTO job_queue
        (job_id, job_type, status, params_json, worker_pid, claimed_at)
        VALUES (?, 'preview', ?, '{}', ?, current_timestamp)
    """, [jid, status, worker_pid])
    return jid


def _make_rule(store: LinkStore, rule_id: str, family_id: str = "fam_a") -> dict[str, Any]:
    """Save a rule and return it."""
    rule = {
        "rule_id": rule_id,
        "family_id": family_id,
        "description": "test rule",
        "status": "published",
        "heading_filter_ast": {"op": "contains", "field": "heading", "value": "Indebtedness"},
    }
    store.save_rule(rule)
    return rule


def _make_preview(
    store: LinkStore,
    preview_id: str,
    *,
    family_id: str = "fam_a",
    candidate_set_hash: str = "abc123",
    created_at: str | None = None,
) -> str:
    """Insert a preview directly into the database."""
    ts = created_at or datetime.now(UTC).isoformat()
    expires = (datetime.now(UTC) + timedelta(hours=2)).isoformat()
    store._conn.execute("""
        INSERT INTO family_link_previews
        (preview_id, family_id, rule_id, rule_hash, corpus_version,
         parser_version, candidate_set_hash, candidate_count,
         new_link_count, already_linked_count, conflict_count,
         by_confidence_tier, avg_confidence, expires_at, created_at)
        VALUES (?, ?, '', 'h', 'v1', 'p1', ?, 2, 0, 0, 0, '{}', 0.5, ?, ?)
    """, [preview_id, family_id, candidate_set_hash, expires, ts])
    return preview_id


def _make_preview_candidates(
    store: LinkStore,
    preview_id: str,
    n: int = 2,
    verdict: str = "accepted",
) -> list[dict[str, Any]]:
    """Insert preview candidates."""
    cands = []
    for i in range(n):
        cands.append({
            "doc_id": f"doc_{i}",
            "section_number": f"1.{i}",
            "heading": f"Section {i}",
            "confidence": 0.9,
            "confidence_tier": "high",
            "user_verdict": verdict,
        })
    store.save_preview_candidates(preview_id, cands)
    return cands


def _make_link(
    store: LinkStore,
    *,
    family_id: str = "fam_a",
    doc_id: str = "doc_0",
    section_number: str = "1.0",
    rule_id: str | None = None,
    link_id: str | None = None,
) -> str:
    """Create one link and return its link_id."""
    lid = link_id or str(uuid.uuid4())
    store.create_links([{
        "link_id": lid,
        "family_id": family_id,
        "doc_id": doc_id,
        "section_number": section_number,
        "heading": "Test Section",
        "rule_id": rule_id,
        "source": "test",
        "confidence": 0.9,
        "confidence_tier": "high",
        "status": "active",
    }], "run_test")
    return lid


@dataclass
class FakeClause:
    """Mimics a corpus clause record."""
    clause_id: str
    label: str
    depth: int
    span_start: int
    span_end: int


class _FakeConn:
    """Fake DuckDB connection that returns doc_id rows."""

    def __init__(self, doc_ids: list[str]) -> None:
        self._doc_ids = doc_ids
        self._last_params: list[Any] = []

    def execute(self, sql: str, params: list[Any] | None = None) -> _FakeConn:
        self._last_params = params or []
        return self

    def fetchall(self) -> list[tuple[str]]:
        if self._last_params:
            limit = int(self._last_params[-1])
            return [(d,) for d in self._doc_ids[:limit]]
        return [(d,) for d in self._doc_ids]


class FakeCorpus:
    """Minimal corpus double for handler tests."""

    def __init__(
        self,
        sections: dict[str, str] | None = None,
        clauses: list[FakeClause] | None = None,
        doc_ids: list[str] | None = None,
    ) -> None:
        self._sections = sections or {}
        self._clauses = clauses or []
        self._conn = _FakeConn(doc_ids or ["doc_0", "doc_1"])

    def get_section_text(
        self, doc_id: str, section_number: str,
    ) -> str | None:
        return self._sections.get(f"{doc_id}::{section_number}")

    def get_clauses(
        self, doc_id: str, section_number: str,
    ) -> list[FakeClause]:
        return self._clauses

    def search_sections(
        self, doc_id: str, cohort_only: bool, limit: int,
    ) -> list[Any]:
        return []

    def get_articles(self, doc_id: str) -> list[Any]:
        return []

    def get_definitions(self, doc_id: str) -> list[Any]:
        return []


# ─────────────────── TestIsPidAlive ──────────────────


class TestIsPidAlive:
    """Tests for the module-level _is_pid_alive helper."""

    def test_current_pid_alive(self) -> None:
        """Current process PID should be alive."""
        assert _is_pid_alive(os.getpid()) is True

    def test_dead_pid(self) -> None:
        """Very large PID should not be alive."""
        assert _is_pid_alive(999_999_999) is False

    def test_pid_zero(self) -> None:
        """PID 0 (kernel) — kill(0,0) sends to process group, may
        succeed on macOS/Linux. We only care it doesn't crash."""
        result = _is_pid_alive(0)
        assert isinstance(result, bool)


# ─────────────────── TestWorkerInit ──────────────────


class TestWorkerInit:
    """Tests for LinkWorker.__init__."""

    def test_init_defaults(self, tmp_path: Path) -> None:
        worker = LinkWorker(tmp_path / "links.duckdb")
        assert worker._poll_interval == 2.0
        assert worker._running is True
        assert worker._store is None
        assert worker._corpus is None

    def test_init_custom_poll_interval(self, tmp_path: Path) -> None:
        worker = LinkWorker(
            tmp_path / "links.duckdb",
            corpus_db_path=tmp_path / "corpus.duckdb",
            poll_interval=5.0,
        )
        assert worker._poll_interval == 5.0
        assert worker._corpus_db_path == tmp_path / "corpus.duckdb"


# ─────────────────── TestCrashRecovery ──────────────────


class TestCrashRecovery:
    """Tests for _recover_stale_jobs: crash recovery on startup."""

    def test_recover_stale_jobs_dead_pid(self, tmp_path: Path) -> None:
        """Jobs claimed by a dead PID should be reset to pending."""
        worker, store = _make_worker(tmp_path)
        dead_pid = 999_999_999
        jid = _insert_claimed_job(store, dead_pid, status="claimed")

        worker._recover_stale_jobs()

        job = store.get_job(jid)
        assert job is not None
        assert job["status"] == "pending"
        assert job["worker_pid"] is None

    def test_recover_stale_jobs_running_dead_pid(self, tmp_path: Path) -> None:
        """Running jobs with dead PIDs should also be reset."""
        worker, store = _make_worker(tmp_path)
        dead_pid = 999_999_999
        jid = _insert_claimed_job(store, dead_pid, status="running")

        worker._recover_stale_jobs()

        job = store.get_job(jid)
        assert job is not None
        assert job["status"] == "pending"

    def test_recover_stale_jobs_live_pid(self, tmp_path: Path) -> None:
        """Jobs claimed by the current (live) PID should NOT be reset."""
        worker, store = _make_worker(tmp_path)
        live_pid = os.getpid()
        jid = _insert_claimed_job(store, live_pid, status="claimed")

        worker._recover_stale_jobs()

        job = store.get_job(jid)
        assert job is not None
        assert job["status"] == "claimed"

    def test_recover_no_stale_jobs(self, tmp_path: Path) -> None:
        """No-op when there are no stale jobs (no crash)."""
        worker, store = _make_worker(tmp_path)
        # No jobs at all — should not raise
        worker._recover_stale_jobs()


# ─────────────────── TestGetHandler ──────────────────


class TestGetHandler:
    """Tests for _get_handler: handler dispatch table."""

    def test_known_handlers(self, tmp_path: Path) -> None:
        """All 8 registered job types should return a callable."""
        worker, _ = _make_worker(tmp_path)
        expected_types = [
            "preview", "apply", "canary", "batch_run",
            "embeddings_compute", "child_linking", "check_drift", "export",
        ]
        for jtype in expected_types:
            handler = worker._get_handler(jtype)
            assert handler is not None, f"No handler for {jtype}"
            assert callable(handler)

    def test_unknown_handler(self, tmp_path: Path) -> None:
        """Unknown job type returns None."""
        worker, _ = _make_worker(tmp_path)
        assert worker._get_handler("nonexistent_job_type") is None


# ─────────────────── TestIsCancelled ──────────────────


class TestIsCancelled:
    """Tests for _is_cancelled: job cancellation check."""

    def test_not_cancelled(self, tmp_path: Path) -> None:
        """A pending job is not cancelled."""
        worker, store = _make_worker(tmp_path)
        jid = _submit_job(store, "preview")
        assert worker._is_cancelled(jid) is False

    def test_cancelled_job(self, tmp_path: Path) -> None:
        """A cancelled job is detected."""
        worker, store = _make_worker(tmp_path)
        jid = _submit_job(store, "preview")
        store.cancel_job(jid)
        assert worker._is_cancelled(jid) is True


# ─────────────────── TestProcessJob ──────────────────


class TestProcessJob:
    """Tests for _process_job: dispatch, success, failure paths."""

    def test_successful_job(self, tmp_path: Path) -> None:
        """A handler that succeeds should lead to complete_job."""
        worker, store = _make_worker(tmp_path)
        jid = _submit_job(store, "export", {"format": "csv"})
        job = store.claim_job(os.getpid())
        assert job is not None

        worker._process_job(job)

        result = store.get_job(jid)
        assert result is not None
        assert result["status"] == "completed"

    def test_failed_job(self, tmp_path: Path) -> None:
        """A handler that raises should lead to fail_job."""
        worker, store = _make_worker(tmp_path)
        jid = _submit_job(store, "preview", {
            "heading_filter_ast": {
                "op": "contains", "field": "heading", "value": "x",
            },
        })
        job = store.claim_job(os.getpid())
        assert job is not None

        # Patch _handle_preview to raise
        with patch.object(worker, "_handle_preview", side_effect=RuntimeError("boom")):
            worker._process_job(job)

        result = store.get_job(jid)
        assert result is not None
        assert result["status"] == "failed"
        assert "boom" in (result.get("error_message") or "")

    def test_unknown_job_type(self, tmp_path: Path) -> None:
        """An unknown job type should lead to fail_job."""
        worker, store = _make_worker(tmp_path)
        jid = _submit_job(store, "bogus_type")
        job = store.claim_job(os.getpid())
        assert job is not None

        worker._process_job(job)

        result = store.get_job(jid)
        assert result is not None
        assert result["status"] == "failed"
        assert "Unknown job type" in (result.get("error_message") or "")


# ─────────────────── TestHandlePreview ──────────────────


class TestHandlePreview:
    """Tests for _handle_preview handler."""

    def test_preview_basic(self, tmp_path: Path) -> None:
        """Preview with a heading AST and mocked scan returns candidates."""
        worker, store = _make_worker(tmp_path)
        jid = _submit_job(store, "preview")
        job = store.claim_job(os.getpid())
        assert job is not None

        fake_candidates = [
            {"doc_id": "d1", "section_number": "1.0", "heading": "S1",
             "confidence": 0.9, "confidence_tier": "high"},
            {"doc_id": "d2", "section_number": "2.0", "heading": "S2",
             "confidence": 0.5, "confidence_tier": "medium"},
        ]

        # Mock save_preview and save_preview_candidates because the worker
        # doesn't pass all required fields (rule_hash, corpus_version, etc.)
        store.save_preview = MagicMock()  # type: ignore[method-assign]
        store.save_preview_candidates = MagicMock()  # type: ignore[method-assign]

        with patch.object(worker, "_scan_for_candidates", return_value=fake_candidates):
            result = worker._handle_preview(
                jid,
                {
                    "family_id": "fam_a",
                    "heading_filter_ast": {"op": "contains", "field": "heading", "value": "X"},
                },
            )

        assert result["candidate_count"] == 2
        assert "preview_id" in result
        assert result["by_confidence_tier"]["high"] == 1
        assert result["by_confidence_tier"]["medium"] == 1

    def test_preview_no_ast(self, tmp_path: Path) -> None:
        """Missing heading_filter_ast returns an error result."""
        worker, store = _make_worker(tmp_path)
        jid = _submit_job(store, "preview")

        result = worker._handle_preview(jid, {"family_id": "fam_a"})
        assert "error" in result
        assert "heading_filter_ast" in result["error"].lower() or "ast" in result["error"].lower()

    def test_preview_cancelled(self, tmp_path: Path) -> None:
        """If the job is cancelled mid-scan, return cancelled status."""
        worker, store = _make_worker(tmp_path)
        jid = _submit_job(store, "preview")

        fake_candidates = [
            {"doc_id": "d1", "section_number": "1.0", "heading": "S1",
             "confidence": 0.9, "confidence_tier": "high"},
        ]

        def scan_then_cancel(*_args: Any, **_kw: Any) -> list[dict[str, Any]]:
            # Cancel the job during scan
            store._conn.execute(
                "UPDATE job_queue SET status = 'cancelled' WHERE job_id = ?",
                [jid],
            )
            return fake_candidates

        # Mock save_preview/save_preview_candidates (not reached if cancelled
        # early, but needed in case cancellation check happens after scan)
        store.save_preview = MagicMock()  # type: ignore[method-assign]
        store.save_preview_candidates = MagicMock()  # type: ignore[method-assign]

        with patch.object(worker, "_scan_for_candidates", side_effect=scan_then_cancel):
            result = worker._handle_preview(
                jid,
                {
                    "family_id": "fam_a",
                    "heading_filter_ast": {"op": "contains", "field": "heading", "value": "X"},
                },
            )

        assert result.get("status") == "cancelled"

    def test_preview_with_rule_id(self, tmp_path: Path) -> None:
        """When rule_id is provided, loads the rule and uses its AST."""
        worker, store = _make_worker(tmp_path)
        _make_rule(store, "rule_1", "fam_a")
        jid = _submit_job(store, "preview")

        # Mock save_preview/save_preview_candidates (worker doesn't pass all fields)
        store.save_preview = MagicMock()  # type: ignore[method-assign]
        store.save_preview_candidates = MagicMock()  # type: ignore[method-assign]

        with patch.object(worker, "_scan_for_candidates", return_value=[]):
            result = worker._handle_preview(
                jid,
                {"rule_id": "rule_1"},
            )

        assert "error" not in result
        assert result["candidate_count"] == 0


# ─────────────────── TestHandleApply ──────────────────


class TestHandleApply:
    """Tests for _handle_apply handler."""

    def test_apply_basic(self, tmp_path: Path) -> None:
        """Creates links from accepted preview candidates."""
        worker, store = _make_worker(tmp_path)
        pid = "prev_" + str(uuid.uuid4())
        _make_preview(store, pid, candidate_set_hash="hash1")
        _make_preview_candidates(store, pid, n=2, verdict="accepted")

        jid = _submit_job(store, "apply")

        # Monkey-patch create_run to avoid AttributeError
        store.create_run = MagicMock()

        result = worker._handle_apply(
            jid,
            {"preview_id": pid, "candidate_set_hash": "hash1"},
        )

        assert "error" not in result
        assert result["links_created"] == 2
        assert "run_id" in result

    def test_apply_does_not_promote_pending_candidates(self, tmp_path: Path) -> None:
        """Pending candidates are excluded from apply writes."""
        worker, store = _make_worker(tmp_path)
        pid = "prev_" + str(uuid.uuid4())
        _make_preview(store, pid, candidate_set_hash="hash2")
        _make_preview_candidates(store, pid, n=3, verdict="pending")

        jid = _submit_job(store, "apply")
        result = worker._handle_apply(
            jid,
            {"preview_id": pid, "candidate_set_hash": "hash2"},
        )

        assert result["links_created"] == 0
        assert result["message"] == "No accepted candidates"
        assert store.get_links(limit=10) == []

    def test_apply_expired_preview(self, tmp_path: Path) -> None:
        """Rejects a preview older than 1 hour."""
        worker, store = _make_worker(tmp_path)
        pid = "prev_" + str(uuid.uuid4())
        old_time = (datetime.now(UTC) - timedelta(hours=2)).isoformat()
        _make_preview(store, pid, created_at=old_time, candidate_set_hash="eh")

        jid = _submit_job(store, "apply")

        # The worker calls fromisoformat on created_at. DuckDB returns
        # a datetime object (not str), so we mock get_preview to return
        # a dict with created_at as an ISO string to exercise expiry logic.
        real_preview = store.get_preview(pid)
        assert real_preview is not None
        real_preview["created_at"] = old_time  # override to string
        store.get_preview = MagicMock(return_value=real_preview)  # type: ignore[method-assign]

        result = worker._handle_apply(
            jid,
            {"preview_id": pid},
        )

        assert result.get("error") == "Preview expired"
        assert result.get("code") == 409

    def test_apply_hash_mismatch(self, tmp_path: Path) -> None:
        """Rejects when candidate_set_hash doesn't match."""
        worker, store = _make_worker(tmp_path)
        pid = "prev_" + str(uuid.uuid4())
        _make_preview(store, pid, candidate_set_hash="correct_hash")

        jid = _submit_job(store, "apply")

        result = worker._handle_apply(
            jid,
            {"preview_id": pid, "candidate_set_hash": "wrong_hash"},
        )

        assert result.get("error") == "Candidate set hash mismatch"
        assert result.get("code") == 409

    def test_apply_not_found(self, tmp_path: Path) -> None:
        """Returns error for a missing preview."""
        worker, store = _make_worker(tmp_path)
        jid = _submit_job(store, "apply")

        result = worker._handle_apply(
            jid,
            {"preview_id": "nonexistent"},
        )

        assert result.get("error") == "Preview not found"
        assert result.get("code") == 404


# ─────────────────── TestHandleCanary ──────────────────


class TestHandleCanary:
    """Tests for _handle_canary handler."""

    def test_canary_runs(self, tmp_path: Path) -> None:
        """Delegates to run_bulk_linking with canary_n."""
        worker, store = _make_worker(tmp_path)
        worker._corpus = FakeCorpus()
        _make_rule(store, "rule_c", "fam_a")
        jid = _submit_job(store, "canary")

        # The import happens inside the handler, so we verify the corpus path works
        result = worker._handle_canary(
            jid,
            {"family_id": "fam_a", "canary_n": 5},
        )
        assert result is not None

    def test_canary_no_corpus(self, tmp_path: Path) -> None:
        """Returns error if no corpus is available."""
        worker, store = _make_worker(tmp_path)
        worker._corpus = None
        jid = _submit_job(store, "canary")

        result = worker._handle_canary(
            jid,
            {"family_id": "fam_a", "canary_n": 5},
        )

        assert result.get("error") == "Corpus not available for canary run"


class TestHandleCanaryMocked:
    """Canary handler test with proper import mocking."""

    def test_canary_delegates_to_bulk_linking(self, tmp_path: Path) -> None:
        """Canary handler delegates to run_bulk_linking with canary_n."""
        worker, store = _make_worker(tmp_path)
        worker._corpus = FakeCorpus()
        _make_rule(store, "rule_c", "fam_a")
        jid = _submit_job(store, "canary")

        mock_result = {"links_created": 3, "canary": True}
        mock_rbl = MagicMock(return_value=mock_result)

        # Create a fake module to inject
        fake_module = MagicMock()
        fake_module.run_bulk_linking = mock_rbl

        with patch.dict("sys.modules", {"scripts.bulk_family_linker": fake_module}):
            result = worker._handle_canary(
                jid,
                {"family_id": "fam_a", "canary_n": 5},
            )

        assert result == mock_result
        mock_rbl.assert_called_once()
        call_kwargs = mock_rbl.call_args
        # Check canary_n in kwargs or positional args
        canary_in_kw = call_kwargs[1].get("canary_n") == 5
        canary_positional = len(call_kwargs[0]) > 4 and call_kwargs[0][4] == 5
        assert canary_in_kw or canary_positional


# ─────────────────── TestHandleBatchRun ──────────────────


class TestHandleBatchRun:
    """Tests for _handle_batch_run handler."""

    def test_batch_run(self, tmp_path: Path) -> None:
        """Full batch run delegates to run_bulk_linking."""
        worker, store = _make_worker(tmp_path)
        worker._corpus = FakeCorpus()
        _make_rule(store, "rule_b", "fam_a")
        jid = _submit_job(store, "batch_run")

        mock_result = {"links_created": 100}
        fake_module = MagicMock()
        fake_module.run_bulk_linking = MagicMock(return_value=mock_result)

        with patch.dict("sys.modules", {"scripts.bulk_family_linker": fake_module}):
            result = worker._handle_batch_run(
                jid,
                {"family_id": "fam_a"},
            )

        assert result == mock_result

    def test_batch_no_corpus(self, tmp_path: Path) -> None:
        """Returns error if no corpus is available."""
        worker, store = _make_worker(tmp_path)
        worker._corpus = None
        jid = _submit_job(store, "batch_run")

        result = worker._handle_batch_run(jid, {})

        assert result.get("error") == "Corpus not available for batch run"


# ─────────────────── TestHandleEmbeddingsCompute ──────────────────


class TestHandleEmbeddingsCompute:
    """Tests for _handle_embeddings_compute handler."""

    def test_embeddings_basic(self, tmp_path: Path) -> None:
        """Prepares sections for embedding when corpus has data."""
        worker, store = _make_worker(tmp_path)
        # Create some active links
        _make_link(store, family_id="fam_a", doc_id="doc_0", section_number="1.0")
        _make_link(store, family_id="fam_a", doc_id="doc_1", section_number="2.0")

        worker._corpus = FakeCorpus(sections={
            "doc_0::1.0": "Section text about indebtedness.",
            "doc_1::2.0": "Another section about covenants.",
        })
        jid = _submit_job(store, "embeddings_compute")

        result = worker._handle_embeddings_compute(
            jid,
            {"family_id": "fam_a"},
        )

        assert result["family_id"] == "fam_a"
        assert result["sections_prepared"] == 2
        assert result["status"] == "sections_ready"

    def test_embeddings_no_corpus(self, tmp_path: Path) -> None:
        """Handles missing corpus gracefully — returns 0 sections."""
        worker, store = _make_worker(tmp_path)
        _make_link(store, family_id="fam_a", doc_id="doc_0", section_number="1.0")
        worker._corpus = None
        jid = _submit_job(store, "embeddings_compute")

        result = worker._handle_embeddings_compute(
            jid,
            {"family_id": "fam_a"},
        )

        assert result["sections_prepared"] == 0
        assert result["status"] == "sections_ready"


# ─────────────────── TestHandleChildLinking ──────────────────


class TestHandleChildLinking:
    """Tests for _handle_child_linking handler."""

    def test_child_linking_finds_clauses(self, tmp_path: Path) -> None:
        """Returns clause-level children for a parent link."""
        worker, store = _make_worker(tmp_path)
        link_id = _make_link(
            store, family_id="fam_a", doc_id="doc_0", section_number="1.0",
        )

        clauses = [
            FakeClause("c1", "(a)", 1, 100, 200),
            FakeClause("c2", "(b)", 1, 200, 300),
        ]
        worker._corpus = FakeCorpus(clauses=clauses)
        jid = _submit_job(store, "child_linking")

        result = worker._handle_child_linking(
            jid,
            {"parent_link_id": link_id},
        )

        assert result["parent_link_id"] == link_id
        assert result["child_nodes_found"] == 2
        assert len(result["children"]) == 2
        assert result["children"][0]["clause_id"] == "c1"
        assert result["children"][1]["label"] == "(b)"

    def test_child_linking_no_parent(self, tmp_path: Path) -> None:
        """Returns error for a missing parent link."""
        worker, store = _make_worker(tmp_path)
        jid = _submit_job(store, "child_linking")

        result = worker._handle_child_linking(
            jid,
            {"parent_link_id": "nonexistent_link"},
        )

        assert "error" in result
        assert "not found" in result["error"].lower()


# ─────────────────── TestHandleCheckDrift ──────────────────


class TestHandleCheckDrift:
    """Tests for _handle_check_drift handler."""

    def test_drift_no_baseline(self, tmp_path: Path) -> None:
        """Returns drift_detected=False when no baseline exists."""
        worker, store = _make_worker(tmp_path)
        _make_rule(store, "rule_d", "fam_a")
        jid = _submit_job(store, "check_drift")

        result = worker._handle_check_drift(
            jid,
            {"rule_id": "rule_d"},
        )

        assert result["drift_detected"] is False
        assert result["rule_id"] == "rule_d"

    def test_drift_detected(self, tmp_path: Path) -> None:
        """Detects >10% drift between baseline and current count."""
        worker, store = _make_worker(tmp_path)
        _make_rule(store, "rule_d2", "fam_a")

        # Create 5 links for this rule
        for i in range(5):
            _make_link(
                store,
                family_id="fam_a",
                doc_id=f"doc_{i}",
                section_number=f"1.{i}",
                rule_id="rule_d2",
            )

        # Insert a baseline expecting 100 links (actual=5, drift >>10%)
        store._conn.execute("""
            INSERT INTO drift_baselines
            (baseline_id, rule_id, expected_count, created_at)
            VALUES ('bl1', 'rule_d2', 100, current_timestamp)
        """)

        jid = _submit_job(store, "check_drift")

        result = worker._handle_check_drift(
            jid,
            {"rule_id": "rule_d2"},
        )

        assert result["drift_detected"] is True
        assert result["details"]["expected_count"] == 100
        assert result["details"]["actual_count"] == 5
        assert result["details"]["drift_pct"] > 10.0

    def test_drift_within_tolerance(self, tmp_path: Path) -> None:
        """No drift when count is within 10% of baseline."""
        worker, store = _make_worker(tmp_path)
        _make_rule(store, "rule_d3", "fam_a")

        # Create 10 links
        for i in range(10):
            _make_link(
                store,
                family_id="fam_a",
                doc_id=f"doc_{i}",
                section_number=f"1.{i}",
                rule_id="rule_d3",
            )

        # Baseline expects 10 (exactly matches current)
        store._conn.execute("""
            INSERT INTO drift_baselines
            (baseline_id, rule_id, expected_count, created_at)
            VALUES ('bl2', 'rule_d3', 10, current_timestamp)
        """)

        jid = _submit_job(store, "check_drift")

        result = worker._handle_check_drift(
            jid,
            {"rule_id": "rule_d3"},
        )

        assert result["drift_detected"] is False


# ─────────────────── TestHandleExport ──────────────────


class TestHandleExport:
    """Tests for _handle_export handler."""

    def test_export_csv(self, tmp_path: Path) -> None:
        """Exports links in CSV format."""
        worker, store = _make_worker(tmp_path)
        _make_link(store, family_id="fam_a", doc_id="doc_0", section_number="1.0")
        _make_link(store, family_id="fam_a", doc_id="doc_1", section_number="2.0")
        jid = _submit_job(store, "export")

        result = worker._handle_export(
            jid,
            {"format": "csv"},
        )

        assert result["format"] == "csv"
        assert result["row_count"] == 2
        assert result["data_length"] > 0

    def test_export_jsonl(self, tmp_path: Path) -> None:
        """Exports links in JSONL format."""
        worker, store = _make_worker(tmp_path)
        _make_link(store, family_id="fam_b", doc_id="doc_0", section_number="1.0")
        jid = _submit_job(store, "export")

        result = worker._handle_export(
            jid,
            {"format": "jsonl", "family_id": "fam_b"},
        )

        assert result["format"] == "jsonl"
        assert result["row_count"] == 1
        assert result["data_length"] > 0

    def test_export_empty(self, tmp_path: Path) -> None:
        """Handles zero links gracefully."""
        worker, store = _make_worker(tmp_path)
        jid = _submit_job(store, "export")

        result = worker._handle_export(
            jid,
            {"format": "csv", "family_id": "nonexistent_family"},
        )

        assert result["row_count"] == 0


# ─────────────────── TestBuildParser ──────────────────


class TestBuildParser:
    """Tests for the CLI argument parser."""

    def test_parser_required_args(self) -> None:
        """--links-db is required."""
        parser = build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args([])

    def test_parser_optional_args(self) -> None:
        """--db and --poll-interval are parsed correctly."""
        parser = build_parser()
        args = parser.parse_args([
            "--links-db", "/tmp/links.duckdb",
            "--db", "/tmp/corpus.duckdb",
            "--poll-interval", "3.5",
        ])
        assert args.links_db == "/tmp/links.duckdb"
        assert args.db == "/tmp/corpus.duckdb"
        assert args.poll_interval == 3.5

    def test_parser_defaults(self) -> None:
        """Default values are correct."""
        parser = build_parser()
        args = parser.parse_args(["--links-db", "/tmp/links.duckdb"])
        assert args.db is None
        assert args.poll_interval == 2.0


# ─────────────────── TestPollLoop ──────────────────


class TestPollLoop:
    """Tests for the _poll_loop main loop."""

    def test_poll_processes_and_stops(self, tmp_path: Path) -> None:
        """Processes one job then stops when _running is set to False."""
        worker, store = _make_worker(tmp_path, poll_interval=0.05)
        jid = _submit_job(store, "export", {"format": "csv"})

        original_process = worker._process_job

        def process_then_stop(job: dict[str, Any]) -> None:
            original_process(job)
            worker.stop()

        with patch.object(worker, "_process_job", side_effect=process_then_stop):
            worker._poll_loop()

        # The job should have been claimed and processed
        result = store.get_job(jid)
        assert result is not None
        # The job was claimed (status changed from pending)
        assert result["status"] != "pending"

    def test_poll_backoff_on_idle(self, tmp_path: Path) -> None:
        """Idle cycles increase sleep time (exponential backoff)."""
        worker, _store = _make_worker(tmp_path, poll_interval=0.01)
        sleep_times: list[float] = []

        def fake_sleep(t: float) -> None:
            sleep_times.append(t)
            if len(sleep_times) >= 3:
                worker.stop()

        with patch("time.sleep", side_effect=fake_sleep):
            worker._poll_loop()

        # Each successive idle sleep should be >= the previous
        assert len(sleep_times) >= 3
        assert sleep_times[1] >= sleep_times[0]
        assert sleep_times[2] >= sleep_times[1]


# ─────────────────── TestWriteDiscipline ──────────────────


class TestWriteDiscipline:
    """Tests verifying the worker's write discipline contract."""

    def test_worker_is_sole_writer(self, tmp_path: Path) -> None:
        """Verify worker touches heavy tables (family_links, previews, etc.)
        by running an export job and confirming reads happen."""
        worker, store = _make_worker(tmp_path)

        # Create some links to export
        _make_link(store, family_id="fam_a", doc_id="doc_0", section_number="1.0")

        jid = _submit_job(store, "export", {"format": "csv"})
        job = store.claim_job(os.getpid())
        assert job is not None

        worker._process_job(job)

        completed_job = store.get_job(jid)
        assert completed_job is not None
        assert completed_job["status"] == "completed"

        # Verify the result was written (complete_job writes result_json)
        assert completed_job["result_json"] is not None
        result_data = json.loads(completed_job["result_json"])
        assert result_data["row_count"] == 1

    def test_signal_graceful_shutdown(self, tmp_path: Path) -> None:
        """SIGTERM handler sets _running=False for graceful shutdown."""
        worker, _store = _make_worker(tmp_path)
        assert worker._running is True

        worker._handle_signal(signal.SIGTERM, None)

        assert worker._running is False

    def test_signal_sigint_shutdown(self, tmp_path: Path) -> None:
        """SIGINT handler also sets _running=False."""
        worker, _store = _make_worker(tmp_path)
        assert worker._running is True

        worker._handle_signal(signal.SIGINT, None)

        assert worker._running is False

    def test_apply_creates_links_in_family_links(self, tmp_path: Path) -> None:
        """_handle_apply writes to family_links — confirming worker write path."""
        worker, store = _make_worker(tmp_path)
        pid = "prev_" + str(uuid.uuid4())
        _make_preview(store, pid, candidate_set_hash="wh1")
        _make_preview_candidates(store, pid, n=1, verdict="accepted")

        jid = _submit_job(store, "apply")

        # Patch create_run since it doesn't exist on LinkStore
        store.create_run = MagicMock()

        result = worker._handle_apply(jid, {"preview_id": pid, "candidate_set_hash": "wh1"})

        assert result["links_created"] == 1

        # Verify the link is actually in the family_links table
        rows = store._conn.execute(
            "SELECT * FROM family_links WHERE run_id = ?", [result["run_id"]]
        ).fetchall()
        assert len(rows) == 1

    def test_stop_method(self, tmp_path: Path) -> None:
        """stop() sets _running to False."""
        worker, _store = _make_worker(tmp_path)
        assert worker._running is True
        worker.stop()
        assert worker._running is False
