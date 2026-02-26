"""Tests for agent.link_store — DuckDB read/write storage with 28+ tables."""
from __future__ import annotations

import hashlib
import struct
import uuid
from pathlib import Path
from typing import Any

import duckdb
import pytest

from agent.link_store import SCHEMA_VERSION, LinkStore


# ───────────────────── Fixtures ──────────────────────────────────────


@pytest.fixture()
def store(tmp_path: Path) -> LinkStore:
    """Create a fresh LinkStore in a temp directory."""
    db_path = tmp_path / "links.duckdb"
    s = LinkStore(db_path, create_if_missing=True)
    yield s  # type: ignore[misc]
    s.close()


def _make_link(
    family_id: str = "debt",
    doc_id: str = "doc_001",
    section_number: str = "7.01",
    *,
    heading: str = "Indebtedness",
    confidence: float = 0.85,
    confidence_tier: str = "high",
    link_id: str | None = None,
    status: str = "active",
    rule_id: str | None = None,
    ontology_node_id: str | None = None,
) -> dict[str, Any]:
    return {
        "link_id": link_id or str(uuid.uuid4()),
        "family_id": family_id,
        "ontology_node_id": ontology_node_id,
        "doc_id": doc_id,
        "section_number": section_number,
        "heading": heading,
        "article_num": 7,
        "article_concept": "negative_covenants",
        "rule_id": rule_id or "rule_debt_v1",
        "rule_version": 1,
        "rule_hash": "abc123",
        "source": "bulk_linker",
        "section_char_start": 10000,
        "section_char_end": 15000,
        "section_text_hash": hashlib.sha256(b"test").hexdigest(),
        "link_role": "primary_covenant",
        "confidence": confidence,
        "confidence_tier": confidence_tier,
        "status": status,
    }


def _make_run(
    run_id: str | None = None,
    family_id: str = "debt",
    rule_id: str = "rule_debt_v1",
) -> dict[str, Any]:
    return {
        "run_id": run_id or str(uuid.uuid4()),
        "run_type": "bulk_link",
        "family_id": family_id,
        "rule_id": rule_id,
        "rule_version": 1,
        "corpus_version": "v1.0.0",
        "corpus_doc_count": 3298,
        "parser_version": "v3.0.0",
    }


# ───────────────────── Initialization ────────────────────────────────


class TestInit:
    def test_create_new_db(self, tmp_path: Path) -> None:
        db_path = tmp_path / "new.duckdb"
        s = LinkStore(db_path, create_if_missing=True)
        assert db_path.exists()
        s.close()

    def test_missing_db_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            LinkStore(tmp_path / "does_not_exist.duckdb")

    def test_schema_version_tracked(self, store: LinkStore) -> None:
        row = store._conn.execute(
            "SELECT version FROM _schema_version WHERE table_name = 'links'"
        ).fetchone()
        assert row is not None
        assert row[0] == SCHEMA_VERSION

    def test_undo_state_initialized(self, store: LinkStore) -> None:
        row = store._conn.execute(
            "SELECT current_position FROM undo_state WHERE id = 1"
        ).fetchone()
        assert row is not None
        assert row[0] == 0

    def test_all_tables_created(self, store: LinkStore) -> None:
        """Verify all core tables exist."""
        rows = store._conn.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'"
        ).fetchall()
        table_names = {r[0] for r in rows}
        expected_tables = {
            "_schema_version", "family_link_rules", "family_links",
            "family_link_events", "link_evidence", "link_defined_terms",
            "family_link_runs", "family_link_previews", "preview_candidates",
            "family_link_calibrations", "job_queue", "action_log", "undo_state",
            "rule_pins", "pin_evaluations", "family_conflict_policies",
            "review_sessions", "review_marks", "rule_baselines",
            "drift_checks", "drift_alerts", "family_link_macros",
            "template_baselines", "section_embeddings", "family_centroids",
            "family_starter_kits",
        }
        for table in expected_tables:
            assert table in table_names, f"Missing table: {table}"

    def test_save_rule_on_legacy_db_without_name_column(self, tmp_path: Path) -> None:
        db_path = tmp_path / "legacy.duckdb"
        conn = duckdb.connect(str(db_path))
        conn.execute(
            """
            CREATE TABLE family_link_rules (
                rule_id VARCHAR PRIMARY KEY,
                family_id VARCHAR NOT NULL,
                description VARCHAR NOT NULL DEFAULT '',
                version INTEGER NOT NULL DEFAULT 1,
                status VARCHAR NOT NULL DEFAULT 'draft',
                owner VARCHAR NOT NULL DEFAULT '',
                article_concepts VARCHAR NOT NULL,
                heading_filter_ast VARCHAR NOT NULL,
                clause_text_filter_ast VARCHAR,
                clause_header_filter_ast VARCHAR,
                required_defined_terms VARCHAR,
                excluded_cue_phrases VARCHAR,
                template_overrides VARCHAR,
                created_at TIMESTAMP DEFAULT current_timestamp,
                updated_at TIMESTAMP DEFAULT current_timestamp
            )
            """
        )
        conn.close()

        # create_if_missing=False should still run additive migrations.
        store = LinkStore(db_path, create_if_missing=False)
        store.save_rule(
            {
                "rule_id": "legacy_rule",
                "family_id": "debt",
                "article_concepts": [],
                "heading_filter_ast": {},
            }
        )
        rule = store.get_rule("legacy_rule")
        assert rule is not None
        assert rule["family_id"] == "debt"
        assert isinstance(rule["name"], str)
        store.close()


# ───────────────────── Rules CRUD ────────────────────────────────────


class TestRulesCrud:
    def test_save_and_get_rule(self, store: LinkStore) -> None:
        rule = {
            "rule_id": "rule_debt_v1",
            "family_id": "debt",
            "description": "Match indebtedness sections",
            "version": 1,
            "status": "published",
            "owner": "agent_debt",
            "article_concepts": ["negative_covenants"],
            "heading_filter_ast": {"type": "match", "value": "Indebtedness"},
        }
        store.save_rule(rule)
        result = store.get_rule("rule_debt_v1")
        assert result is not None
        assert result["family_id"] == "debt"
        assert result["description"] == "Match indebtedness sections"
        assert result["status"] == "published"

    def test_get_missing_rule_returns_none(self, store: LinkStore) -> None:
        assert store.get_rule("nonexistent") is None

    def test_get_rules_filter_by_family(self, store: LinkStore) -> None:
        store.save_rule({
            "rule_id": "r1", "family_id": "debt",
            "article_concepts": [], "heading_filter_ast": {},
        })
        store.save_rule({
            "rule_id": "r2", "family_id": "liens",
            "article_concepts": [], "heading_filter_ast": {},
        })
        debt_rules = store.get_rules(family_id="debt")
        assert len(debt_rules) == 1
        assert debt_rules[0]["rule_id"] == "r1"

    def test_get_rules_filter_by_status(self, store: LinkStore) -> None:
        store.save_rule({
            "rule_id": "r1", "family_id": "debt", "status": "published",
            "article_concepts": [], "heading_filter_ast": {},
        })
        store.save_rule({
            "rule_id": "r2", "family_id": "debt", "status": "draft",
            "article_concepts": [], "heading_filter_ast": {},
        })
        published = store.get_rules(status="published")
        assert len(published) == 1
        assert published[0]["rule_id"] == "r1"

    def test_get_rules_filter_by_canonical_scope_alias(self, store: LinkStore) -> None:
        store.save_rule({
            "rule_id": "r_legacy",
            "family_id": "FAM-indebtedness",
            "ontology_node_id": "debt_capacity.indebtedness",
            "status": "published",
            "article_concepts": [],
            "heading_filter_ast": {},
        })
        rules = store.get_rules(family_id="debt_capacity.indebtedness")
        assert len(rules) == 1
        assert rules[0]["rule_id"] == "r_legacy"
        assert store.get_canonical_scope_id("FAM-indebtedness") == "debt_capacity.indebtedness"
        aliases = set(store.resolve_scope_aliases("debt_capacity.indebtedness"))
        assert "FAM-indebtedness" in aliases

    def test_clone_rule(self, store: LinkStore) -> None:
        store.save_rule({
            "rule_id": "r_original", "family_id": "debt",
            "description": "original", "version": 5, "status": "published",
            "article_concepts": ["neg_cov"], "heading_filter_ast": {"value": "X"},
        })
        cloned = store.clone_rule("r_original", "r_clone")
        assert cloned["rule_id"] == "r_clone"
        assert cloned["version"] == 1
        assert cloned["status"] == "draft"
        assert cloned["family_id"] == "debt"
        # Verify in DB
        db_clone = store.get_rule("r_clone")
        assert db_clone is not None

    def test_clone_nonexistent_raises(self, store: LinkStore) -> None:
        with pytest.raises(ValueError, match="Rule not found"):
            store.clone_rule("nonexistent", "new_id")

    def test_save_rule_upsert(self, store: LinkStore) -> None:
        store.save_rule({
            "rule_id": "r1", "family_id": "debt", "description": "v1",
            "article_concepts": [], "heading_filter_ast": {},
        })
        store.save_rule({
            "rule_id": "r1", "family_id": "debt", "description": "v2",
            "article_concepts": [], "heading_filter_ast": {},
        })
        r = store.get_rule("r1")
        assert r is not None
        assert r["description"] == "v2"

    def test_save_rule_rejects_ast_over_guardrails(self, store: LinkStore) -> None:
        large_ast = {
            "type": "group",
            "operator": "or",
            "children": [{"type": "match", "value": f"term_{i}"} for i in range(51)],
        }
        with pytest.raises(ValueError, match="maximum"):
            store.save_rule({
                "rule_id": "r_guardrail",
                "family_id": "debt",
                "article_concepts": [],
                "heading_filter_ast": large_ast,
            })

    def test_get_rule_rejects_invalid_stored_ast(self, store: LinkStore) -> None:
        store._conn.execute("""
            INSERT INTO family_link_rules
            (rule_id, family_id, description, version, status, owner, article_concepts,
             heading_filter_ast, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, [
            "r_bad", "debt", "", 1, "draft", "", "[]",
            '{"op":"xor","children":[]}', "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z",
        ])
        with pytest.raises(ValueError, match="Invalid filter group operator"):
            store.get_rule("r_bad")


# ───────────────────── Links CRUD ────────────────────────────────────


class TestLinksCrud:
    def test_create_and_get_links(self, store: LinkStore) -> None:
        run_id = str(uuid.uuid4())
        link = _make_link()
        created = store.create_links([link], run_id)
        assert created == 1
        links = store.get_links(family_id="debt")
        assert len(links) == 1
        assert links[0]["heading"] == "Indebtedness"
        assert links[0]["confidence"] == 0.85

    def test_create_link_persists_ontology_node_and_clause_text(self, store: LinkStore) -> None:
        run_id = str(uuid.uuid4())
        link = _make_link(
            family_id="debt_capacity.indebtedness",
            doc_id="doc_clause_1",
            section_number="6.01",
        )
        link["ontology_node_id"] = "debt_capacity.indebtedness.general_basket"
        link["clause_id"] = "a.iii"
        link["clause_char_start"] = 100
        link["clause_char_end"] = 180
        link["clause_text"] = "(iii) other Indebtedness ..."

        created = store.create_links([link], run_id)
        assert created == 1

        rows = store.get_links(family_id="debt_capacity.indebtedness", doc_id="doc_clause_1")
        assert len(rows) == 1
        assert rows[0]["ontology_node_id"] == "debt_capacity.indebtedness.general_basket"
        assert rows[0]["clause_id"] == "a.iii"
        assert rows[0]["clause_text"] == "(iii) other Indebtedness ..."

    def test_get_links_filter_by_canonical_scope_alias(self, store: LinkStore) -> None:
        run_id = str(uuid.uuid4())
        created = store.create_links([
            _make_link(
                family_id="FAM-indebtedness",
                ontology_node_id="debt_capacity.indebtedness",
                doc_id="doc_scope_1",
            ),
            _make_link(
                family_id="FAM-liens",
                ontology_node_id="debt_capacity.liens",
                doc_id="doc_scope_2",
                section_number="7.02",
            ),
        ], run_id)
        assert created == 2
        rows = store.get_links(family_id="debt_capacity.indebtedness")
        assert len(rows) == 1
        assert rows[0]["doc_id"] == "doc_scope_1"
        assert store.count_links(family_id="debt_capacity.indebtedness") == 1

    def test_create_multiple_links(self, store: LinkStore) -> None:
        run_id = str(uuid.uuid4())
        links = [
            _make_link(doc_id="d1", section_number="7.01"),
            _make_link(doc_id="d2", section_number="7.01"),
            _make_link(doc_id="d3", section_number="7.01"),
        ]
        created = store.create_links(links, run_id)
        assert created == 3

    def test_duplicate_link_skipped(self, store: LinkStore) -> None:
        """UNIQUE (scope_id, doc_id, section_number, clause_key) prevents dupes."""
        run_id = str(uuid.uuid4())
        link = _make_link()
        store.create_links([link], run_id)
        # Try again with different link_id but same (family, doc, section)
        link2 = _make_link(link_id=str(uuid.uuid4()))
        created = store.create_links([link2], run_id)
        assert created == 0

    def test_allows_multiple_clause_links_same_section_scope(self, store: LinkStore) -> None:
        run_id = str(uuid.uuid4())
        created = store.create_links([
            {
                **_make_link(),
                "doc_id": "doc_clause",
                "section_number": "6.01",
                "ontology_node_id": "debt_capacity.indebtedness.general_basket",
                "clause_id": "6.01(a)(i)",
                "clause_text": "(i) first clause",
            },
            {
                **_make_link(link_id=str(uuid.uuid4())),
                "doc_id": "doc_clause",
                "section_number": "6.01",
                "ontology_node_id": "debt_capacity.indebtedness.general_basket",
                "clause_id": "6.01(a)(iii)",
                "clause_text": "(iii) other indebtedness",
            },
        ], run_id)
        assert created == 2
        rows = store.get_links(family_id="debt_capacity.indebtedness.general_basket", doc_id="doc_clause")
        assert len(rows) == 2
        assert {str(row.get("clause_id")) for row in rows} == {"6.01(a)(i)", "6.01(a)(iii)"}

    def test_count_links(self, store: LinkStore) -> None:
        run_id = str(uuid.uuid4())
        store.create_links([
            _make_link(doc_id="d1"),
            _make_link(doc_id="d2"),
            _make_link(family_id="liens", doc_id="d1", section_number="7.02"),
        ], run_id)
        assert store.count_links(family_id="debt") == 2
        assert store.count_links(family_id="liens") == 1
        assert store.count_links() == 3

    def test_count_links_with_heading_filter(self, store: LinkStore) -> None:
        from agent.query_filters import FilterMatch
        run_id = str(uuid.uuid4())
        store.create_links([
            _make_link(doc_id="d1", heading="Indebtedness"),
            _make_link(doc_id="d2", heading="Liens"),
        ], run_id)
        count = store.count_links(
            heading_ast=FilterMatch(value="Indebtedness"),
        )
        assert count == 1

    def test_get_links_filter_by_status(self, store: LinkStore) -> None:
        run_id = str(uuid.uuid4())
        lid = str(uuid.uuid4())
        store.create_links([_make_link(link_id=lid)], run_id)
        store.unlink(lid, "wrong_section")
        active = store.get_links(status="active")
        unlinked = store.get_links(status="unlinked")
        assert len(active) == 0
        assert len(unlinked) == 1

    def test_get_links_filter_by_tier(self, store: LinkStore) -> None:
        run_id = str(uuid.uuid4())
        store.create_links([
            _make_link(doc_id="d1", confidence_tier="high"),
            _make_link(doc_id="d2", confidence_tier="medium"),
        ], run_id)
        high = store.get_links(confidence_tier="high")
        assert len(high) == 1
        assert high[0]["doc_id"] == "d1"

    def test_get_links_pagination(self, store: LinkStore) -> None:
        run_id = str(uuid.uuid4())
        links = [_make_link(doc_id=f"d{i}") for i in range(10)]
        store.create_links(links, run_id)
        page1 = store.get_links(limit=3, offset=0)
        page2 = store.get_links(limit=3, offset=3)
        assert len(page1) == 3
        assert len(page2) == 3
        # No overlap
        ids1 = {l["link_id"] for l in page1}
        ids2 = {l["link_id"] for l in page2}
        assert ids1.isdisjoint(ids2)

    def test_unlink_and_relink(self, store: LinkStore) -> None:
        run_id = str(uuid.uuid4())
        lid = str(uuid.uuid4())
        store.create_links([_make_link(link_id=lid)], run_id)

        # Unlink
        store.unlink(lid, "wrong_section", "User correction")
        link = store.get_links(status="unlinked")[0]
        assert link["unlinked_reason"] == "wrong_section"
        assert link["unlinked_note"] == "User correction"

        # Verify event was logged
        events = store.get_events(lid)
        assert len(events) >= 1
        assert events[0]["event_type"] == "unlink"

        # Relink
        store.relink(lid)
        link = store.get_links(status="active")[0]
        assert link["link_id"] == lid
        assert link["unlinked_reason"] is None


# ───────────────────── Batch operations ──────────────────────────────


class TestBatchOperations:
    def test_batch_unlink(self, store: LinkStore) -> None:
        run_id = str(uuid.uuid4())
        lids = [str(uuid.uuid4()) for _ in range(3)]
        links = [_make_link(link_id=lid, doc_id=f"d{i}") for i, lid in enumerate(lids)]
        store.create_links(links, run_id)

        count = store.batch_unlink(lids, "bulk_removal", "Cleaning up")
        assert count == 3
        assert store.count_links(status="unlinked") == 3

    def test_batch_relink(self, store: LinkStore) -> None:
        run_id = str(uuid.uuid4())
        lids = [str(uuid.uuid4()) for _ in range(2)]
        links = [_make_link(link_id=lid, doc_id=f"d{i}") for i, lid in enumerate(lids)]
        store.create_links(links, run_id)
        store.batch_unlink(lids, "test")

        count = store.batch_relink(lids)
        assert count == 2
        assert store.count_links(status="active") == 2

    def test_batch_unlink_ignores_missing_ids(self, store: LinkStore) -> None:
        run_id = str(uuid.uuid4())
        existing = str(uuid.uuid4())
        store.create_links([_make_link(link_id=existing)], run_id)

        count = store.batch_unlink([existing, "missing-link-id"], "cleanup")
        assert count == 1
        assert store.count_links(status="unlinked") == 1

    def test_batch_relink_ignores_missing_ids(self, store: LinkStore) -> None:
        run_id = str(uuid.uuid4())
        existing = str(uuid.uuid4())
        store.create_links([_make_link(link_id=existing)], run_id)
        store.batch_unlink([existing], "test")

        count = store.batch_relink([existing, "missing-link-id"])
        assert count == 1
        assert store.count_links(status="active") == 1

    def test_select_all_matching(self, store: LinkStore) -> None:
        from agent.query_filters import FilterMatch
        run_id = str(uuid.uuid4())
        store.create_links([
            _make_link(doc_id="d1", heading="Indebtedness"),
            _make_link(doc_id="d2", heading="Liens"),
            _make_link(doc_id="d3", heading="Indebtedness Limitation"),
        ], run_id)
        matching = store.select_all_matching(
            "debt",
            FilterMatch(value="Indebtedness"),
            "active",
        )
        # Only exact "Indebtedness" match — FilterMatch wraps with %
        assert len(matching) >= 1


# ───────────────────── Conflicts ─────────────────────────────────────


class TestConflicts:
    def test_save_and_get_conflict_policy(self, store: LinkStore) -> None:
        store.save_conflict_policy({
            "family_a": "debt", "family_b": "liens",
            "policy": "exclusive",
            "reason": "debt and liens are mutually exclusive",
            "edge_types": '["EXCLUDES_FROM"]',
            "ontology_version": "v2.5.1",
        })
        policy = store.get_conflict_policy("debt", "liens")
        assert policy == "exclusive"

    def test_canonical_order(self, store: LinkStore) -> None:
        """Reversed arguments still find the policy."""
        store.save_conflict_policy({
            "family_a": "alpha", "family_b": "zebra",
            "policy": "warn", "reason": "test",
            "edge_types": "[]", "ontology_version": "v1",
        })
        assert store.get_conflict_policy("zebra", "alpha") == "warn"

    def test_missing_returns_independent(self, store: LinkStore) -> None:
        assert store.get_conflict_policy("unknown_a", "unknown_b") == "independent"

    def test_get_conflicts_all(self, store: LinkStore) -> None:
        store.save_conflict_policy({
            "family_a": "a", "family_b": "b", "policy": "exclusive",
            "reason": "test", "edge_types": "[]", "ontology_version": "v1",
        })
        store.save_conflict_policy({
            "family_a": "c", "family_b": "d", "policy": "warn",
            "reason": "test", "edge_types": "[]", "ontology_version": "v1",
        })
        all_conflicts = store.get_conflicts()
        assert len(all_conflicts) == 2

    def test_get_conflicts_by_family(self, store: LinkStore) -> None:
        store.save_conflict_policy({
            "family_a": "a", "family_b": "b", "policy": "exclusive",
            "reason": "test", "edge_types": "[]", "ontology_version": "v1",
        })
        store.save_conflict_policy({
            "family_a": "a", "family_b": "c", "policy": "warn",
            "reason": "test", "edge_types": "[]", "ontology_version": "v1",
        })
        store.save_conflict_policy({
            "family_a": "d", "family_b": "e", "policy": "shared_ok",
            "reason": "test", "edge_types": "[]", "ontology_version": "v1",
        })
        a_conflicts = store.get_conflicts(family_id="a")
        assert len(a_conflicts) == 2


# ───────────────────── Events ────────────────────────────────────────


class TestEvents:
    def test_log_and_get_events(self, store: LinkStore) -> None:
        store.log_event("link_001", "create", "bulk_linker")
        store.log_event("link_001", "review", "human", reason="Looks correct")
        events = store.get_events("link_001")
        assert len(events) == 2
        # Most recent first
        assert events[0]["event_type"] == "review"
        assert events[0]["reason"] == "Looks correct"

    def test_event_with_metadata(self, store: LinkStore) -> None:
        store.log_event(
            "link_001", "reassign", "user",
            metadata={"old_family": "debt", "new_family": "liens"},
        )
        events = store.get_events("link_001")
        assert events[0]["metadata"] is not None


# ───────────────────── Evidence ──────────────────────────────────────


class TestEvidence:
    def test_save_and_get_evidence(self, store: LinkStore) -> None:
        evidence = [
            {
                "link_id": "link_001",
                "evidence_type": "heading_match",
                "char_start": 100,
                "char_end": 120,
                "text_hash": "abc",
                "matched_pattern": "Indebtedness",
                "reason_code": "heading_exact",
                "score": 1.0,
            },
            {
                "link_id": "link_001",
                "evidence_type": "keyword_density",
                "char_start": 200,
                "char_end": 500,
                "text_hash": "def",
                "reason_code": "keyword_above_threshold",
                "score": 0.85,
            },
        ]
        count = store.save_evidence(evidence)
        assert count == 2
        result = store.get_evidence("link_001")
        assert len(result) == 2
        # Ordered by char_start
        assert result[0]["char_start"] == 100
        assert result[1]["char_start"] == 200

    def test_evidence_with_metadata(self, store: LinkStore) -> None:
        store.save_evidence([{
            "link_id": "link_002",
            "evidence_type": "dna_phrase",
            "char_start": 50,
            "char_end": 80,
            "text_hash": "xyz",
            "reason_code": "dna_hit",
            "score": 0.9,
            "metadata": {"phrase": "incur additional indebtedness"},
        }])
        result = store.get_evidence("link_002")
        assert result[0]["metadata"] is not None


# ───────────────────── Runs ──────────────────────────────────────────


class TestRuns:
    def test_create_and_complete_run(self, store: LinkStore) -> None:
        run = _make_run(run_id="run_001")
        store.create_run(run)

        runs = store.get_runs()
        assert len(runs) == 1
        assert runs[0]["run_id"] == "run_001"
        assert runs[0]["completed_at"] is None

        store.complete_run("run_001", {
            "links_created": 150,
            "links_skipped_existing": 10,
            "links_skipped_low_confidence": 5,
            "conflicts_detected": 2,
            "outlier_count": 1,
        })
        completed = store.get_runs()
        assert completed[0]["links_created"] == 150
        assert completed[0]["completed_at"] is not None

    def test_get_runs_by_family(self, store: LinkStore) -> None:
        store.create_run(_make_run(run_id="r1", family_id="debt"))
        store.create_run(_make_run(run_id="r2", family_id="liens"))
        debt_runs = store.get_runs(family_id="debt")
        assert len(debt_runs) == 1

    def test_get_runs_by_canonical_scope_alias(self, store: LinkStore) -> None:
        store.save_rule({
            "rule_id": "r_scope",
            "family_id": "FAM-indebtedness",
            "ontology_node_id": "debt_capacity.indebtedness",
            "status": "published",
            "article_concepts": [],
            "heading_filter_ast": {},
        })
        store.create_run(_make_run(run_id="r_scope_run", family_id="FAM-indebtedness", rule_id="r_scope"))
        runs = store.get_runs(family_id="debt_capacity.indebtedness")
        assert len(runs) == 1
        assert runs[0]["run_id"] == "r_scope_run"


# ───────────────────── Coverage ──────────────────────────────────────


class TestCoverage:
    def test_family_summary(self, store: LinkStore) -> None:
        run_id = str(uuid.uuid4())
        store.create_links([
            _make_link(doc_id="d1", confidence=0.9),
            _make_link(doc_id="d2", confidence=0.7),
            _make_link(family_id="liens", doc_id="d1", section_number="7.02"),
        ], run_id)

        # Unlink one
        links = store.get_links(family_id="debt")
        store.unlink(links[0]["link_id"], "test")

        summary = store.family_summary()
        assert len(summary) == 2
        debt_summary = next(s for s in summary if s["family_id"] == "debt")
        assert debt_summary["total_links"] == 2
        assert debt_summary["active_links"] == 1
        assert debt_summary["unlinked_links"] == 1


# ───────────────────── Previews ──────────────────────────────────────


class TestPreviews:
    def test_save_and_get_preview(self, store: LinkStore) -> None:
        preview = {
            "preview_id": "prev_001",
            "family_id": "debt",
            "rule_hash": "hash123",
            "corpus_version": "v1",
            "parser_version": "v3",
            "candidate_set_hash": "cshash",
            "candidate_count": 10,
            "new_link_count": 8,
            "already_linked_count": 2,
            "expires_at": "2099-12-31T23:59:59Z",
        }
        store.save_preview(preview)
        result = store.get_preview("prev_001")
        assert result is not None
        assert result["candidate_count"] == 10

    def test_validate_preview_fresh(self, store: LinkStore) -> None:
        store.save_preview({
            "preview_id": "p1", "family_id": "debt",
            "rule_hash": "h", "corpus_version": "v1",
            "parser_version": "v3", "candidate_set_hash": "c",
            "expires_at": "2099-12-31T23:59:59Z",
        })
        assert store.validate_preview("p1") is True

    def test_validate_nonexistent_preview(self, store: LinkStore) -> None:
        assert store.validate_preview("nonexistent") is False

    def test_preview_candidates_crud(self, store: LinkStore) -> None:
        store.save_preview({
            "preview_id": "p1", "family_id": "debt",
            "rule_hash": "h", "corpus_version": "v1",
            "parser_version": "v3", "candidate_set_hash": "c",
            "expires_at": "2099-12-31T23:59:59Z",
        })
        candidates = [
            {"doc_id": "d1", "section_number": "7.01", "confidence": 0.9,
             "confidence_tier": "high", "priority_score": 0.8},
            {"doc_id": "d2", "section_number": "7.01", "confidence": 0.5,
             "confidence_tier": "medium", "priority_score": 0.6},
        ]
        count = store.save_preview_candidates("p1", candidates)
        assert count == 2

        result = store.get_preview_candidates("p1")
        assert len(result) == 2
        # Ordered by priority_score DESC
        assert result[0]["priority_score"] >= result[1]["priority_score"]

    def test_candidate_verdict(self, store: LinkStore) -> None:
        store.save_preview({
            "preview_id": "p1", "family_id": "debt",
            "rule_hash": "h", "corpus_version": "v1",
            "parser_version": "v3", "candidate_set_hash": "c",
            "expires_at": "2099-12-31T23:59:59Z",
        })
        store.save_preview_candidates("p1", [{
            "doc_id": "d1", "section_number": "7.01",
            "confidence": 0.9, "priority_score": 0.8,
        }])
        store.set_candidate_verdict("p1", "accept", doc_id="d1", section_number="7.01")
        cands = store.get_preview_candidates("p1", verdict="accept")
        assert len(cands) == 1
        assert cands[0]["user_verdict"] == "accept"

    def test_preview_candidates_same_section_different_clause_ids(self, store: LinkStore) -> None:
        store.save_preview({
            "preview_id": "p1", "family_id": "debt",
            "rule_hash": "h", "corpus_version": "v1",
            "parser_version": "v3", "candidate_set_hash": "c",
            "expires_at": "2099-12-31T23:59:59Z",
        })
        store.save_preview_candidates("p1", [
            {
                "doc_id": "d1",
                "section_number": "6.01",
                "clause_id": "6.01(a)(i)",
                "confidence": 0.9,
                "priority_score": 0.8,
            },
            {
                "doc_id": "d1",
                "section_number": "6.01",
                "clause_id": "6.01(a)(iii)",
                "confidence": 0.91,
                "priority_score": 0.79,
            },
        ])
        rows = store.get_preview_candidates("p1", page_size=100)
        assert len(rows) == 2
        ids = {str(row.get("candidate_id")) for row in rows}
        assert "d1::6.01::6.01(a)(i)" in ids
        assert "d1::6.01::6.01(a)(iii)" in ids

        store.set_candidate_verdict("p1", "accepted", candidate_id="d1::6.01::6.01(a)(iii)")
        accepted = store.get_preview_candidates("p1", verdict="accepted", page_size=100)
        assert len(accepted) == 1
        assert accepted[0]["candidate_id"] == "d1::6.01::6.01(a)(iii)"

    def test_candidates_filter_by_tier(self, store: LinkStore) -> None:
        store.save_preview({
            "preview_id": "p1", "family_id": "debt",
            "rule_hash": "h", "corpus_version": "v1",
            "parser_version": "v3", "candidate_set_hash": "c",
            "expires_at": "2099-12-31T23:59:59Z",
        })
        store.save_preview_candidates("p1", [
            {"doc_id": "d1", "section_number": "7.01",
             "confidence_tier": "high", "priority_score": 0.9},
            {"doc_id": "d2", "section_number": "7.01",
             "confidence_tier": "low", "priority_score": 0.3},
        ])
        high = store.get_preview_candidates("p1", tier="high")
        assert len(high) == 1


# ───────────────────── Calibration ───────────────────────────────────


class TestCalibration:
    def test_save_and_get_calibration(self, store: LinkStore) -> None:
        store.save_calibration("debt", "_global", {
            "high_threshold": 0.82,
            "medium_threshold": 0.55,
            "target_precision": 0.92,
            "sample_size": 50,
            "expected_review_load": 120,
        })
        cal = store.get_calibration("debt")
        assert cal is not None
        assert cal["high_threshold"] == 0.82
        assert cal["sample_size"] == 50

    def test_get_missing_calibration(self, store: LinkStore) -> None:
        assert store.get_calibration("nonexistent") is None

    def test_template_specific_calibration(self, store: LinkStore) -> None:
        store.save_calibration("debt", "kirkland", {"high_threshold": 0.75})
        store.save_calibration("debt", "_global", {"high_threshold": 0.80})
        kirk = store.get_calibration("debt", "kirkland")
        assert kirk is not None
        assert kirk["high_threshold"] == 0.75


# ───────────────────── Jobs ──────────────────────────────────────────


class TestJobs:
    def test_submit_and_get_job(self, store: LinkStore) -> None:
        store.submit_job({
            "job_id": "j1",
            "job_type": "bulk_link",
            "params": {"family_id": "debt", "rule_id": "r1"},
        })
        job = store.get_job("j1")
        assert job is not None
        assert job["status"] == "pending"
        assert job["progress_pct"] == 0.0

    def test_idempotent_submit(self, store: LinkStore) -> None:
        store.submit_job({
            "job_id": "j1", "job_type": "bulk_link",
            "idempotency_key": "idem_1",
            "params": {},
        })
        # Second submit with same idempotency key is a no-op
        store.submit_job({
            "job_id": "j2", "job_type": "bulk_link",
            "idempotency_key": "idem_1",
            "params": {},
        })
        # j2 should not exist
        assert store.get_job("j2") is None
        row = store._conn.execute(
            "SELECT COUNT(*) FROM job_queue WHERE idempotency_key = 'idem_1'"
        ).fetchone()
        assert row is not None
        assert row[0] == 1

    def test_claim_job(self, store: LinkStore) -> None:
        store.submit_job({"job_id": "j1", "job_type": "bulk_link", "params": {}})
        claimed = store.claim_job(worker_pid=12345)
        assert claimed is not None
        assert claimed["status"] == "claimed"
        assert claimed["worker_pid"] == 12345

    def test_claim_empty_queue_returns_none(self, store: LinkStore) -> None:
        assert store.claim_job(worker_pid=1) is None

    def test_job_lifecycle(self, store: LinkStore) -> None:
        store.submit_job({"job_id": "j1", "job_type": "bulk_link", "params": {}})
        store.claim_job(worker_pid=100)

        store.update_job_progress("j1", 50.0, "Processing 500/1000")
        job = store.get_job("j1")
        assert job is not None
        assert job["progress_pct"] == 50.0
        assert job["status"] == "running"

        store.complete_job("j1", {"links_created": 150})
        job = store.get_job("j1")
        assert job is not None
        assert job["status"] == "completed"
        assert job["completed_at"] is not None

    def test_fail_job(self, store: LinkStore) -> None:
        store.submit_job({"job_id": "j1", "job_type": "bulk_link", "params": {}})
        store.fail_job("j1", "DuckDB connection timeout")
        job = store.get_job("j1")
        assert job is not None
        assert job["status"] == "failed"
        assert job["error_message"] == "DuckDB connection timeout"

    def test_cancel_job(self, store: LinkStore) -> None:
        store.submit_job({"job_id": "j1", "job_type": "bulk_link", "params": {}})
        store.cancel_job("j1")
        job = store.get_job("j1")
        assert job is not None
        assert job["status"] == "cancelled"


# ───────────────────── Undo / Redo ───────────────────────────────────


class TestUndoRedo:
    def test_batch_unlink_then_undo(self, store: LinkStore) -> None:
        run_id = str(uuid.uuid4())
        lids = [str(uuid.uuid4()) for _ in range(2)]
        store.create_links([
            _make_link(link_id=lids[0], doc_id="d1"),
            _make_link(link_id=lids[1], doc_id="d2"),
        ], run_id)

        store.batch_unlink(lids, "test_removal")
        assert store.count_links(status="active") == 0
        assert store.count_links(status="unlinked") == 2

        # Undo
        result = store.undo()
        assert result is not None
        assert result["actions_reversed"] == 2
        assert store.count_links(status="active") == 2

    def test_undo_then_redo(self, store: LinkStore) -> None:
        run_id = str(uuid.uuid4())
        lid = str(uuid.uuid4())
        store.create_links([_make_link(link_id=lid)], run_id)
        store.batch_unlink([lid], "test")

        # Undo
        store.undo()
        assert store.count_links(status="active") == 1

        # Redo
        result = store.redo()
        assert result is not None
        assert result["actions_replayed"] == 1
        assert store.count_links(status="unlinked") == 1

    def test_undo_empty_stack(self, store: LinkStore) -> None:
        result = store.undo()
        assert result is None

    def test_redo_at_head(self, store: LinkStore) -> None:
        """Redo when already at latest position returns None."""
        result = store.redo()
        assert result is None

    def test_get_undo_stack(self, store: LinkStore) -> None:
        run_id = str(uuid.uuid4())
        lids = [str(uuid.uuid4()) for _ in range(3)]
        store.create_links([
            _make_link(link_id=lids[i], doc_id=f"d{i}") for i in range(3)
        ], run_id)
        store.batch_unlink(lids[:2], "first_batch")
        store.batch_unlink(lids[2:], "second_batch")

        stack = store.get_undo_stack()
        assert stack["current_position"] > 0
        assert len(stack["batches"]) >= 2


# ───────────────────── Pins ──────────────────────────────────────────


class TestPins:
    def test_create_and_get_pins(self, store: LinkStore) -> None:
        pin = store.create_pin("rule_1", "doc_1", "7.01", "hit", note="Expected match")
        assert pin["pin_id"] is not None

        pins = store.get_pins("rule_1")
        assert len(pins) == 1
        assert pins[0]["expected"] == "hit"
        assert pins[0]["note"] == "Expected match"

    def test_delete_pin(self, store: LinkStore) -> None:
        pin = store.create_pin("rule_1", "doc_1", "7.01", "hit")
        store.delete_pin(pin["pin_id"])
        assert store.get_pins("rule_1") == []

    def test_duplicate_pin_raises(self, store: LinkStore) -> None:
        """UNIQUE (rule_id, doc_id, section_number) prevents duplicates."""
        store.create_pin("rule_1", "doc_1", "7.01", "hit")
        with pytest.raises(Exception):
            store.create_pin("rule_1", "doc_1", "7.01", "miss")

    def test_save_pin_evaluation(self, store: LinkStore) -> None:
        store.save_pin_evaluation({
            "rule_id": "rule_1",
            "rule_version": 3,
            "total_pins": 10,
            "passed": 9,
            "failed": 1,
            "results": [{"pin_id": "p1", "passed": True}],
        })
        # Verify it was stored
        rows = store._conn.execute(
            "SELECT * FROM pin_evaluations WHERE rule_id = 'rule_1'"
        ).fetchall()
        assert len(rows) == 1


# ───────────────────── Sessions & Bookmarks ──────────────────────────


class TestSessions:
    def test_create_new_session(self, store: LinkStore) -> None:
        session = store.get_or_create_session("family", "debt")
        assert session["session_id"] is not None
        assert session["scope_type"] == "family"
        assert session["scope_id"] == "debt"

    def test_get_existing_session(self, store: LinkStore) -> None:
        s1 = store.get_or_create_session("family", "debt")
        s2 = store.get_or_create_session("family", "debt")
        assert s1["session_id"] == s2["session_id"]

    def test_update_cursor(self, store: LinkStore) -> None:
        session = store.get_or_create_session("family", "debt")
        store.update_session_cursor(session["session_id"], {"doc_id": "d5", "score": 0.7})
        # Verify stored
        row = store._conn.execute(
            "SELECT last_cursor FROM review_sessions WHERE session_id = ?",
            [session["session_id"]],
        ).fetchone()
        assert row is not None
        assert row[0] is not None

    def test_add_bookmark_and_retrieve(self, store: LinkStore) -> None:
        session = store.get_or_create_session("family", "debt")
        sid = session["session_id"]
        store.add_mark(sid, "doc_1", "7.01", "bookmarked", "Check later")
        store.add_mark(sid, "doc_2", "7.01", "bookmarked")
        store.add_mark(sid, "doc_3", "7.01", "viewed")

        bookmarks = store.get_bookmarks(sid)
        assert len(bookmarks) == 2
        assert bookmarks[0]["note"] == "Check later"

    def test_session_progress(self, store: LinkStore) -> None:
        session = store.get_or_create_session("family", "debt")
        sid = session["session_id"]
        store.add_mark(sid, "doc_1", "7.01", "viewed")
        store.add_mark(sid, "doc_2", "7.01", "viewed")
        store.add_mark(sid, "doc_3", "7.01", "bookmarked")

        progress = store.session_progress(sid)
        assert progress["rows_viewed"] == 2
        assert progress["rows_bookmarked"] == 1


# ───────────────────── Drift ─────────────────────────────────────────


class TestDrift:
    def test_save_and_get_baseline(self, store: LinkStore) -> None:
        store.save_baseline({
            "rule_id": "rule_1", "rule_version": 3,
            "total_docs": 3298, "total_hits": 2800,
            "overall_hit_rate": 0.849,
            "profile": {"kirkland": 0.92, "simpson": 0.88},
        })
        bl = store.get_latest_baseline("rule_1")
        assert bl is not None
        assert bl["overall_hit_rate"] == 0.849

    def test_latest_baseline(self, store: LinkStore) -> None:
        """Returns the most recently promoted baseline."""
        store.save_baseline({
            "baseline_id": "bl_1", "rule_id": "r1", "rule_version": 1,
            "promoted_at": "2025-01-01T00:00:00Z",
            "total_docs": 100, "total_hits": 80, "overall_hit_rate": 0.8,
            "profile": {},
        })
        store.save_baseline({
            "baseline_id": "bl_2", "rule_id": "r1", "rule_version": 2,
            "promoted_at": "2025-06-01T00:00:00Z",
            "total_docs": 200, "total_hits": 170, "overall_hit_rate": 0.85,
            "profile": {},
        })
        bl = store.get_latest_baseline("r1")
        assert bl is not None
        assert bl["baseline_id"] == "bl_2"

    def test_save_drift_check(self, store: LinkStore) -> None:
        store.save_drift_check({
            "rule_id": "r1", "baseline_id": "bl_1",
            "overall_hit_rate": 0.78,
            "chi2_statistic": 12.5,
            "p_value": 0.002,
            "max_cell_delta": 0.15,
            "drift_detected": True,
            "current_profile": {"kirkland": 0.75},
        })
        # Verify it was stored
        row = store._conn.execute(
            "SELECT drift_detected, chi2_statistic FROM drift_checks WHERE rule_id = 'r1'"
        ).fetchone()
        assert row is not None
        assert row[0] == True  # drift_detected
        assert row[1] == 12.5  # chi2_statistic

    def test_drift_alerts(self, store: LinkStore) -> None:
        store.create_drift_alert({
            "rule_id": "r1", "check_id": "chk_1",
            "severity": "warning",
            "message": "Hit rate dropped 7%",
            "cells_affected": ["kirkland"],
        })
        alerts = store.get_drift_alerts(acknowledged=False)
        assert len(alerts) == 1
        assert alerts[0]["severity"] == "warning"

        # Acknowledge
        store.acknowledge_alert(alerts[0]["alert_id"])
        unacked = store.get_drift_alerts(acknowledged=False)
        assert len(unacked) == 0
        acked = store.get_drift_alerts(acknowledged=True)
        assert len(acked) == 1

    def test_drift_alerts_filter_by_rule(self, store: LinkStore) -> None:
        store.create_drift_alert({
            "rule_id": "r1", "check_id": "c1", "severity": "warning",
            "message": "test", "cells_affected": [],
        })
        store.create_drift_alert({
            "rule_id": "r2", "check_id": "c2", "severity": "critical",
            "message": "test", "cells_affected": [],
        })
        r1_alerts = store.get_drift_alerts(rule_id="r1")
        assert len(r1_alerts) == 1


# ───────────────────── Macros ────────────────────────────────────────


class TestMacros:
    def test_save_and_get_macro(self, store: LinkStore) -> None:
        store.save_macro({
            "macro_id": "m1",
            "family_id": "_global",
            "name": "debt_phrases",
            "description": "Common debt phrases",
            "ast_json": {
                "type": "group",
                "operator": "or",
                "children": [{"type": "match", "value": "Debt"}],
            },
            "created_by": "admin",
        })
        macro = store.get_macro("m1")
        assert macro is not None
        assert macro["name"] == "debt_phrases"

    def test_resolve_macro_family_scoped(self, store: LinkStore) -> None:
        store.save_macro({
            "macro_id": "m_global", "family_id": "_global",
            "name": "debt_terms", "ast_json": {"value": "Debt"},
        })
        store.save_macro({
            "macro_id": "m_debt", "family_id": "debt",
            "name": "debt_terms", "ast_json": {"value": "Indebtedness"},
        })
        # Family-scoped takes priority
        result = store.resolve_macro("debt_terms", "debt")
        assert result is not None
        assert result["macro_id"] == "m_debt"

    def test_resolve_macro_global_fallback(self, store: LinkStore) -> None:
        store.save_macro({
            "macro_id": "m_global", "family_id": "_global",
            "name": "common_phrases", "ast_json": {"value": "Common Phrase"},
        })
        result = store.resolve_macro("common_phrases", "liens")
        assert result is not None
        assert result["macro_id"] == "m_global"

    def test_resolve_macro_not_found(self, store: LinkStore) -> None:
        assert store.resolve_macro("nonexistent", "debt") is None

    def test_delete_macro(self, store: LinkStore) -> None:
        store.save_macro({
            "macro_id": "m1", "family_id": "_global",
            "name": "test", "ast_json": {},
        })
        store.delete_macro("m1")
        assert store.get_macro("m1") is None

    def test_get_macros_by_family(self, store: LinkStore) -> None:
        store.save_macro({
            "macro_id": "m1", "family_id": "_global",
            "name": "global_1", "ast_json": {},
        })
        store.save_macro({
            "macro_id": "m2", "family_id": "debt",
            "name": "debt_1", "ast_json": {},
        })
        store.save_macro({
            "macro_id": "m3", "family_id": "liens",
            "name": "liens_1", "ast_json": {},
        })
        # family_id=debt returns debt + _global
        debt_macros = store.get_macros(family_id="debt")
        names = {m["name"] for m in debt_macros}
        assert "global_1" in names
        assert "debt_1" in names
        assert "liens_1" not in names

    def test_save_macro_rejects_ast_over_guardrails(self, store: LinkStore) -> None:
        large_ast = {
            "op": "or",
            "children": [{"value": f"%wild_{i}%"} for i in range(11)],
        }
        with pytest.raises(ValueError, match="wildcard"):
            store.save_macro({
                "macro_id": "m_bad",
                "family_id": "_global",
                "name": "too_wild",
                "ast_json": large_ast,
            })

    def test_get_macro_rejects_invalid_stored_ast(self, store: LinkStore) -> None:
        store._conn.execute("""
            INSERT INTO family_link_macros
            (macro_id, family_id, name, description, ast_json, created_by, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, [
            "m_bad_load", "_global", "bad_macro", "", '{"op":"xor","children":[]}', "tester",
            "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z",
        ])
        with pytest.raises(ValueError, match="Invalid filter group operator"):
            store.get_macro("m_bad_load")


# ───────────────────── Template baselines ────────────────────────────


class TestTemplateBaselines:
    def test_save_and_get(self, store: LinkStore) -> None:
        store.save_template_baseline({
            "template_family": "kirkland",
            "section_pattern": "7.*/Indebtedness",
            "baseline_text": "Standard indebtedness covenant text...",
            "baseline_hash": "sha256:abc",
            "source": "corpus_analysis",
        })
        result = store.get_template_baseline("kirkland", "7.*/Indebtedness")
        assert result is not None
        assert result["baseline_hash"] == "sha256:abc"

    def test_list_template_baselines(self, store: LinkStore) -> None:
        store.save_template_baseline({
            "template_family": "kirkland", "section_pattern": "7.01",
            "baseline_text": "t1", "baseline_hash": "h1",
        })
        store.save_template_baseline({
            "template_family": "kirkland", "section_pattern": "7.02",
            "baseline_text": "t2", "baseline_hash": "h2",
        })
        store.save_template_baseline({
            "template_family": "simpson", "section_pattern": "7.01",
            "baseline_text": "t3", "baseline_hash": "h3",
        })
        all_baselines = store.list_template_baselines()
        assert len(all_baselines) == 3
        kirk = store.list_template_baselines("kirkland")
        assert len(kirk) == 2


# ───────────────────── Link defined terms ────────────────────────────


class TestLinkDefinedTerms:
    def test_save_and_get(self, store: LinkStore) -> None:
        count = store.save_link_defined_terms("link_001", [
            {
                "term": "Permitted Indebtedness",
                "definition_section_path": "1.01/Definitions",
                "definition_char_start": 500,
                "definition_char_end": 800,
                "confidence": 0.95,
            },
            {
                "term": "Debt",
                "definition_section_path": "1.01/Definitions",
                "definition_char_start": 900,
                "definition_char_end": 1100,
            },
        ])
        assert count == 2
        terms = store.get_link_defined_terms("link_001")
        assert len(terms) == 2
        # Ordered by term
        assert terms[0]["term"] == "Debt"
        assert terms[1]["term"] == "Permitted Indebtedness"

    def test_context_strip(self, store: LinkStore) -> None:
        run_id = str(uuid.uuid4())
        lid = str(uuid.uuid4())
        store.create_links([_make_link(link_id=lid)], run_id)
        store.save_link_defined_terms(lid, [{
            "term": "Debt", "definition_section_path": "1.01",
            "definition_char_start": 100, "definition_char_end": 200,
        }])
        ctx = store.get_link_context_strip(lid)
        assert ctx["primary"]["link_id"] == lid
        assert len(ctx["defined_terms"]) == 1

    def test_context_strip_missing_link(self, store: LinkStore) -> None:
        ctx = store.get_link_context_strip("nonexistent")
        assert ctx == {}


# ───────────────────── Reassign ──────────────────────────────────────


class TestReassign:
    def test_reassign_link(self, store: LinkStore) -> None:
        run_id = str(uuid.uuid4())
        lid = str(uuid.uuid4())
        store.create_links([_make_link(link_id=lid, family_id="debt")], run_id)

        result = store.reassign_link(lid, "liens", reason="Misclassified")
        assert result["old_family"] == "debt"
        assert result["new_family"] == "liens"
        assert result["old_link_id"] == lid
        assert result["new_link_id"] != lid

        # Old link is unlinked
        old = store.get_links(status="unlinked")
        assert len(old) == 1
        assert old[0]["link_id"] == lid

        # New link is active under liens
        new = store.get_links(family_id="liens", status="active")
        assert len(new) == 1

    def test_reassign_nonexistent_raises(self, store: LinkStore) -> None:
        with pytest.raises(ValueError, match="Link not found"):
            store.reassign_link("nonexistent", "liens")


# ───────────────────── Comparables ───────────────────────────────────


class TestComparables:
    def test_find_comparables(self, store: LinkStore) -> None:
        run_id = str(uuid.uuid4())
        lid_main = str(uuid.uuid4())
        store.create_links([
            _make_link(link_id=lid_main, doc_id="d1"),
            _make_link(doc_id="d2", confidence=0.9),
            _make_link(doc_id="d3", confidence=0.7),
        ], run_id)
        comps = store.find_comparables(lid_main, family_id="debt", limit=5)
        # Should not include lid_main
        comp_ids = {c["link_id"] for c in comps}
        assert lid_main not in comp_ids
        assert len(comps) == 2


# ───────────────────── Embeddings ────────────────────────────────────


def _make_embedding(dim: int = 3) -> bytes:
    """Create a test embedding as bytes."""
    floats = [0.1 * i for i in range(dim)]
    return struct.pack(f"<{dim}f", *floats)


class TestEmbeddings:
    def test_save_and_get_section_embedding(self, store: LinkStore) -> None:
        emb = _make_embedding()
        store.save_section_embeddings([{
            "doc_id": "d1", "section_number": "7.01",
            "embedding_vector": emb, "model_version": "v1",
            "text_hash": "abc",
        }])
        result = store.get_section_embedding("d1", "7.01", "v1")
        assert result is not None
        assert len(result) == len(emb)

    def test_missing_embedding_returns_none(self, store: LinkStore) -> None:
        assert store.get_section_embedding("nonexistent", "1.01", "v1") is None

    def test_save_and_get_family_centroid(self, store: LinkStore) -> None:
        centroid = _make_embedding(dim=5)
        store.save_family_centroid("debt", "_global", centroid, "v1", sample_count=500)
        result = store.get_family_centroid("debt", "_global", "v1")
        assert result is not None
        assert len(result) == len(centroid)

    def test_missing_centroid_returns_none(self, store: LinkStore) -> None:
        assert store.get_family_centroid("x", "y", "z") is None

    def test_find_similar_sections(self, store: LinkStore) -> None:
        store.save_section_embeddings([
            {"doc_id": "d1", "section_number": "7.01",
             "embedding_vector": _make_embedding(), "model_version": "v1",
             "text_hash": "h1"},
            {"doc_id": "d1", "section_number": "7.02",
             "embedding_vector": _make_embedding(), "model_version": "v1",
             "text_hash": "h2"},
        ])
        similar = store.find_similar_sections("debt", "d1", top_k=5)
        assert len(similar) == 2

    def test_embedding_upsert(self, store: LinkStore) -> None:
        """Re-saving embedding for same (doc, section, model) overwrites."""
        emb1 = _make_embedding(3)
        emb2 = _make_embedding(5)
        store.save_section_embeddings([{
            "doc_id": "d1", "section_number": "7.01",
            "embedding_vector": emb1, "model_version": "v1", "text_hash": "h1",
        }])
        store.save_section_embeddings([{
            "doc_id": "d1", "section_number": "7.01",
            "embedding_vector": emb2, "model_version": "v1", "text_hash": "h2",
        }])
        result = store.get_section_embedding("d1", "7.01", "v1")
        assert result is not None
        assert len(result) == len(emb2)


# ───────────────────── Starter kits ──────────────────────────────────


class TestStarterKits:
    def test_save_and_get(self, store: LinkStore) -> None:
        store.save_starter_kit("debt", {
            "typical_location": {"article": 7, "section_pattern": "7.*"},
            "top_heading_variants": ["Indebtedness", "Limitation on Indebtedness"],
            "top_defined_terms": ["Permitted Indebtedness", "Debt"],
            "top_dna_phrases": ["incur additional indebtedness"],
            "known_exclusions": ["liens"],
        })
        kit = store.get_starter_kit("debt")
        assert kit is not None
        assert kit["family_id"] == "debt"

    def test_missing_kit_returns_none(self, store: LinkStore) -> None:
        assert store.get_starter_kit("nonexistent") is None

    def test_generate_starter_kit(self, store: LinkStore) -> None:
        kit = store.generate_starter_kit(
            "debt",
            corpus_stats={
                "top_headings": ["Indebtedness"],
                "top_terms": ["Debt"],
                "top_phrases": ["incur debt"],
            },
            ontology={
                "primary_location": {"article": 7},
                "known_exclusions": ["liens"],
            },
        )
        assert "typical_location" in kit
        assert "known_exclusions" in kit
        # Verify persisted
        stored = store.get_starter_kit("debt")
        assert stored is not None


# ───────────────────── Analytics ─────────────────────────────────────


class TestAnalytics:
    def test_unlink_reason_analytics(self, store: LinkStore) -> None:
        run_id = str(uuid.uuid4())
        lids = [str(uuid.uuid4()) for _ in range(4)]
        store.create_links([
            _make_link(link_id=lids[i], doc_id=f"d{i}") for i in range(4)
        ], run_id)
        store.unlink(lids[0], "wrong_section")
        store.unlink(lids[1], "wrong_section")
        store.unlink(lids[2], "low_confidence")

        analytics = store.unlink_reason_analytics()
        assert analytics["total_unlinked"] == 3
        reasons = {r["reason"]: r["count"] for r in analytics["reasons"]}
        assert reasons["wrong_section"] == 2
        assert reasons["low_confidence"] == 1

    def test_unlink_analytics_by_family(self, store: LinkStore) -> None:
        run_id = str(uuid.uuid4())
        lid1 = str(uuid.uuid4())
        lid2 = str(uuid.uuid4())
        store.create_links([
            _make_link(link_id=lid1, family_id="debt", doc_id="d1"),
            _make_link(link_id=lid2, family_id="liens", doc_id="d1", section_number="7.02"),
        ], run_id)
        store.unlink(lid1, "wrong_section")
        store.unlink(lid2, "low_confidence")

        debt_analytics = store.unlink_reason_analytics(family_id="debt")
        assert debt_analytics["total_unlinked"] == 1

    def test_family_dashboard(self, store: LinkStore) -> None:
        """family_dashboard() delegates to family_summary()."""
        run_id = str(uuid.uuid4())
        store.create_links([_make_link()], run_id)
        dashboard = store.family_dashboard()
        assert len(dashboard) == 1


# ───────────────────── Cleanup ───────────────────────────────────────


class TestCleanup:
    def test_run_cleanup_no_error(self, store: LinkStore) -> None:
        """Cleanup should not error on empty database."""
        stats = store.run_cleanup()
        assert isinstance(stats, dict)
        assert "expired_candidates" in stats

    def test_cleanup_returns_stats(self, store: LinkStore) -> None:
        store.submit_job({"job_id": "j1", "job_type": "test", "params": {}})
        stats = store.run_cleanup()
        assert "expired_previews" in stats


# ───────────────────── Lifecycle ─────────────────────────────────────


class TestLifecycle:
    def test_close_and_reopen(self, tmp_path: Path) -> None:
        db_path = tmp_path / "links.duckdb"
        s1 = LinkStore(db_path, create_if_missing=True)
        s1.save_rule({
            "rule_id": "r1", "family_id": "debt",
            "article_concepts": [], "heading_filter_ast": {},
        })
        s1.close()

        # Reopen
        s2 = LinkStore(db_path)
        rule = s2.get_rule("r1")
        assert rule is not None
        assert rule["family_id"] == "debt"
        s2.close()

    def test_double_close_no_error(self, store: LinkStore) -> None:
        store.close()
        store.close()  # Should not raise
