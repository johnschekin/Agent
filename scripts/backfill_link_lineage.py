#!/usr/bin/env python3
"""Backfill lineage fields on historical runs/links/evidence rows.

This script repairs lineage at the run source first, then propagates to links
and evidence. It is idempotent and supports dry-run reporting.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb


_PLACEHOLDERS = ("", "unknown", "parser-unknown", "bulk_linker_v1", "worker_v1", "1.0")


def _bad_expr(column: str) -> str:
    placeholder_sql = ", ".join(f"'{v}'" for v in _PLACEHOLDERS if v)
    return (
        f"(COALESCE(NULLIF(TRIM({column}), ''), '') = '' "
        f"OR LOWER(TRIM({column})) IN ({placeholder_sql}))"
    )


def _literal(value: str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _sanitize(value: Any, fallback: str) -> str:
    text = str(value or "").strip()
    if not text or text.lower() in _PLACEHOLDERS:
        return fallback
    return text


def _git_sha_from_repo(project_root: Path) -> str:
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=str(project_root),
            capture_output=True,
            text=True,
            check=False,
        )
    except Exception:
        return ""
    if proc.returncode != 0:
        return ""
    return str(proc.stdout or "").strip()


def _schema_version_from_corpus(corpus_db: Path | None) -> str:
    if corpus_db is None or not corpus_db.exists():
        return ""
    conn = duckdb.connect(str(corpus_db), read_only=True)
    try:
        row = conn.execute(
            "SELECT version FROM _schema_version WHERE table_name = 'corpus'"
        ).fetchone()
        return str(row[0] or "").strip() if row else ""
    except Exception:
        return ""
    finally:
        conn.close()


def _manifest_payload(corpus_dir: Path) -> dict[str, Any]:
    manifest_path = corpus_dir / "run_manifest.json"
    if not manifest_path.exists():
        return {}
    try:
        payload = json.loads(manifest_path.read_text())
    except Exception:
        return {}
    if not isinstance(payload, dict):
        return {}
    return payload


def _ontology_version_from_default_file(project_root: Path) -> str:
    ontology_path = project_root / "data" / "ontology" / "r36a_production_ontology_v2.5.1.json"
    if not ontology_path.exists():
        return ""
    try:
        payload = json.loads(ontology_path.read_text())
    except Exception:
        return ""
    if not isinstance(payload, dict):
        return ""
    metadata = payload.get("metadata")
    if isinstance(metadata, dict):
        value = str(metadata.get("version") or "").strip()
        if value:
            return value
    return ""


def _derive_ruleset_version(conn: duckdb.DuckDBPyConnection) -> str:
    try:
        rows = conn.execute(
            """
            SELECT
                COALESCE(rule_id, ''),
                COALESCE(family_id, ''),
                COALESCE(version, 0),
                COALESCE(ontology_node_id, '')
            FROM family_link_rules
            ORDER BY 1, 2, 3, 4
            """
        ).fetchall()
    except Exception:
        rows = []
    if not rows:
        return "ruleset-reconstructed"
    digest = hashlib.sha256(json.dumps(rows, separators=(",", ":"), default=str).encode("utf-8")).hexdigest()
    return f"ruleset-{digest[:16]}"


def _resolve_defaults(
    *,
    conn: duckdb.DuckDBPyConnection,
    links_db: Path,
    corpus_db: Path | None,
    corpus_version: str | None,
    corpus_snapshot_id: str | None,
    parser_version: str | None,
    ontology_version: str | None,
    ruleset_version: str | None,
    git_sha: str | None,
) -> dict[str, str]:
    project_root = Path(__file__).resolve().parents[1]
    manifest = _manifest_payload(links_db.parent)

    default_git_sha = _sanitize(
        git_sha or manifest.get("git_commit") or _git_sha_from_repo(project_root),
        "reconstructed-git",
    )
    schema_version = _schema_version_from_corpus(corpus_db)
    default_corpus_version = _sanitize(
        corpus_version or manifest.get("schema_version") or schema_version,
        f"corpus-{links_db.parent.name}",
    )
    default_corpus_snapshot_id = _sanitize(
        corpus_snapshot_id or manifest.get("run_id"),
        f"{default_corpus_version}-snapshot",
    )

    parser_seed = ""
    try:
        from agent import parsing_types

        parser_seed = str(getattr(parsing_types, "__version__", "") or "").strip()
    except Exception:
        parser_seed = ""
    default_parser_version = _sanitize(
        parser_version or manifest.get("parser_version") or (f"parser-v{parser_seed}" if parser_seed else ""),
        f"parser-{default_git_sha[:12]}",
    )

    default_ontology_version = _sanitize(
        ontology_version or manifest.get("ontology_version") or _ontology_version_from_default_file(project_root),
        "ontology-reconstructed",
    )

    default_ruleset_version = _sanitize(
        ruleset_version or manifest.get("ruleset_version") or _derive_ruleset_version(conn),
        "ruleset-reconstructed",
    )

    created_at_utc = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    return {
        "corpus_version": default_corpus_version,
        "corpus_snapshot_id": default_corpus_snapshot_id,
        "parser_version": default_parser_version,
        "ontology_version": default_ontology_version,
        "ruleset_version": default_ruleset_version,
        "git_sha": default_git_sha,
        "created_at_utc": created_at_utc,
    }


def _count_state(conn: duckdb.DuckDBPyConnection) -> dict[str, int]:
    runs_row = conn.execute(
        f"""
        SELECT COUNT(*)
        FROM family_link_runs
        WHERE {_bad_expr('corpus_version')}
           OR {_bad_expr('corpus_snapshot_id')}
           OR {_bad_expr('parser_version')}
           OR {_bad_expr('ontology_version')}
           OR {_bad_expr('ruleset_version')}
           OR {_bad_expr('git_sha')}
           OR COALESCE(NULLIF(TRIM(created_at_utc), ''), '') = ''
        """
    ).fetchone()
    links_row = conn.execute(
        f"""
        SELECT COUNT(*)
        FROM family_links
        WHERE {_bad_expr('corpus_version')}
           OR {_bad_expr('parser_version')}
           OR {_bad_expr('ontology_version')}
           OR COALESCE(NULLIF(TRIM(run_id), ''), '') = ''
        """
    ).fetchone()
    evidence_row = conn.execute(
        f"""
        SELECT COUNT(*)
        FROM link_evidence
        WHERE COALESCE(NULLIF(TRIM(run_id), ''), '') = ''
           OR {_bad_expr('corpus_version')}
           OR {_bad_expr('parser_version')}
           OR {_bad_expr('ontology_version')}
           OR {_bad_expr('ruleset_version')}
           OR {_bad_expr('git_sha')}
           OR COALESCE(NULLIF(TRIM(doc_id), ''), '') = ''
           OR COALESCE(NULLIF(TRIM(section_number), ''), '') = ''
        """
    ).fetchone()
    total_runs = conn.execute("SELECT COUNT(*) FROM family_link_runs").fetchone()
    total_links = conn.execute("SELECT COUNT(*) FROM family_links").fetchone()
    total_evidence = conn.execute("SELECT COUNT(*) FROM link_evidence").fetchone()
    return {
        "family_link_runs_bad": int(runs_row[0] if runs_row else 0),
        "family_link_runs_total": int(total_runs[0] if total_runs else 0),
        "family_links_bad": int(links_row[0] if links_row else 0),
        "family_links_total": int(total_links[0] if total_links else 0),
        "link_evidence_bad": int(evidence_row[0] if evidence_row else 0),
        "link_evidence_total": int(total_evidence[0] if total_evidence else 0),
    }


def _ensure_run_rows_exist(conn: duckdb.DuckDBPyConnection, defaults: dict[str, str]) -> None:
    conn.execute(
        f"""
        INSERT INTO family_link_runs
        (
            run_id, run_type, family_id, rule_id, scope_mode, rule_version,
            corpus_version, corpus_snapshot_id, corpus_doc_count, parser_version,
            ontology_version, ruleset_version, git_sha, links_created, created_at_utc, started_at
        )
        SELECT
            src.run_id,
            'reconstructed',
            src.family_id,
            NULL,
            'corpus',
            1,
            {_literal(defaults['corpus_version'])},
            {_literal(defaults['corpus_snapshot_id'])} || '-' || SUBSTR(sha256(src.run_id), 1, 12),
            src.corpus_doc_count,
            {_literal(defaults['parser_version'])},
            {_literal(defaults['ontology_version'])},
            {_literal(defaults['ruleset_version'])},
            {_literal(defaults['git_sha'])},
            src.links_created,
            {_literal(defaults['created_at_utc'])},
            current_timestamp
        FROM (
            SELECT
                run_id,
                NULLIF(TRIM(MAX(family_id)), '') AS family_id,
                COUNT(DISTINCT COALESCE(NULLIF(TRIM(doc_id), ''), '__missing_doc__')) AS corpus_doc_count,
                COUNT(*) AS links_created
            FROM family_links
            WHERE COALESCE(NULLIF(TRIM(run_id), ''), '') <> ''
            GROUP BY run_id

            UNION ALL

            SELECT
                run_id,
                NULL AS family_id,
                COUNT(DISTINCT COALESCE(NULLIF(TRIM(doc_id), ''), '__missing_doc__')) AS corpus_doc_count,
                0 AS links_created
            FROM link_evidence
            WHERE COALESCE(NULLIF(TRIM(run_id), ''), '') <> ''
            GROUP BY run_id
        ) AS src
        LEFT JOIN family_link_runs AS r ON r.run_id = src.run_id
        WHERE r.run_id IS NULL
        GROUP BY src.run_id, src.family_id, src.corpus_doc_count, src.links_created
        """
    )


def _apply_backfill(conn: duckdb.DuckDBPyConnection, defaults: dict[str, str]) -> None:
    # Normalize missing run ids for links/evidence so every row can be tied to a run.
    conn.execute(
        """
        UPDATE family_links
        SET run_id = 'reconstructed-run-' || SUBSTR(
            sha256(
                COALESCE(NULLIF(TRIM(family_id), ''), '') || '|' ||
                COALESCE(NULLIF(TRIM(doc_id), ''), '') || '|' ||
                COALESCE(NULLIF(TRIM(section_number), ''), '') || '|' ||
                COALESCE(NULLIF(TRIM(clause_key), ''), COALESCE(NULLIF(TRIM(clause_id), ''), '__section__'))
            ),
            1,
            16
        )
        WHERE COALESCE(NULLIF(TRIM(run_id), ''), '') = ''
        """
    )

    conn.execute(
        """
        UPDATE link_evidence AS e
        SET run_id = COALESCE(
            NULLIF(TRIM(e.run_id), ''),
            NULLIF(TRIM(l.run_id), ''),
            'reconstructed-run-' || SUBSTR(
                sha256(
                    COALESCE(NULLIF(TRIM(e.link_id), ''), '') || '|' ||
                    COALESCE(NULLIF(TRIM(e.doc_id), ''), '') || '|' ||
                    COALESCE(NULLIF(TRIM(e.section_number), ''), '')
                ),
                1,
                16
            )
        )
        FROM family_links AS l
        WHERE e.link_id = l.link_id
        """
    )

    conn.execute(
        """
        UPDATE link_evidence
        SET run_id = 'reconstructed-run-' || SUBSTR(
            sha256(
                COALESCE(NULLIF(TRIM(link_id), ''), '') || '|' ||
                COALESCE(NULLIF(TRIM(doc_id), ''), '') || '|' ||
                COALESCE(NULLIF(TRIM(section_number), ''), '')
            ),
            1,
            16
        )
        WHERE COALESCE(NULLIF(TRIM(run_id), ''), '') = ''
        """
    )

    _ensure_run_rows_exist(conn, defaults)

    # Repair run lineage first (source of truth for propagation).
    conn.execute(
        f"""
        UPDATE family_link_runs AS r
        SET
            corpus_version = CASE
                WHEN {_bad_expr('r.corpus_version')} THEN COALESCE(
                    (SELECT NULLIF(TRIM(l.corpus_version), '') FROM family_links l
                     WHERE l.run_id = r.run_id AND NOT {_bad_expr('l.corpus_version')} LIMIT 1),
                    (SELECT NULLIF(TRIM(e.corpus_version), '') FROM link_evidence e
                     WHERE e.run_id = r.run_id AND NOT {_bad_expr('e.corpus_version')} LIMIT 1),
                    {_literal(defaults['corpus_version'])}
                )
                ELSE r.corpus_version
            END,
            corpus_snapshot_id = CASE
                WHEN {_bad_expr('r.corpus_snapshot_id')} THEN
                    {_literal(defaults['corpus_snapshot_id'])} || '-' || SUBSTR(sha256(r.run_id), 1, 12)
                ELSE r.corpus_snapshot_id
            END,
            parser_version = CASE
                WHEN {_bad_expr('r.parser_version')} THEN COALESCE(
                    (SELECT NULLIF(TRIM(l.parser_version), '') FROM family_links l
                     WHERE l.run_id = r.run_id AND NOT {_bad_expr('l.parser_version')} LIMIT 1),
                    (SELECT NULLIF(TRIM(e.parser_version), '') FROM link_evidence e
                     WHERE e.run_id = r.run_id AND NOT {_bad_expr('e.parser_version')} LIMIT 1),
                    {_literal(defaults['parser_version'])}
                )
                ELSE r.parser_version
            END,
            ontology_version = CASE
                WHEN {_bad_expr('r.ontology_version')} THEN COALESCE(
                    (SELECT NULLIF(TRIM(l.ontology_version), '') FROM family_links l
                     WHERE l.run_id = r.run_id AND NOT {_bad_expr('l.ontology_version')} LIMIT 1),
                    (SELECT NULLIF(TRIM(e.ontology_version), '') FROM link_evidence e
                     WHERE e.run_id = r.run_id AND NOT {_bad_expr('e.ontology_version')} LIMIT 1),
                    {_literal(defaults['ontology_version'])}
                )
                ELSE r.ontology_version
            END,
            ruleset_version = CASE
                WHEN {_bad_expr('r.ruleset_version')} THEN COALESCE(
                    (SELECT NULLIF(TRIM(e.ruleset_version), '') FROM link_evidence e
                     WHERE e.run_id = r.run_id AND NOT {_bad_expr('e.ruleset_version')} LIMIT 1),
                    {_literal(defaults['ruleset_version'])}
                )
                ELSE r.ruleset_version
            END,
            git_sha = CASE
                WHEN {_bad_expr('r.git_sha')} THEN COALESCE(
                    (SELECT NULLIF(TRIM(e.git_sha), '') FROM link_evidence e
                     WHERE e.run_id = r.run_id AND NOT {_bad_expr('e.git_sha')} LIMIT 1),
                    {_literal(defaults['git_sha'])}
                )
                ELSE r.git_sha
            END,
            created_at_utc = COALESCE(
                NULLIF(TRIM(r.created_at_utc), ''),
                CAST(r.started_at AS VARCHAR),
                {_literal(defaults['created_at_utc'])}
            )
        """
    )

    # Propagate repaired lineage from runs to links.
    conn.execute(
        f"""
        UPDATE family_links AS l
        SET
            corpus_version = CASE
                WHEN {_bad_expr('l.corpus_version')}
                    THEN COALESCE(NULLIF(TRIM(r.corpus_version), ''), {_literal(defaults['corpus_version'])})
                ELSE l.corpus_version
            END,
            parser_version = CASE
                WHEN {_bad_expr('l.parser_version')}
                    THEN COALESCE(NULLIF(TRIM(r.parser_version), ''), {_literal(defaults['parser_version'])})
                ELSE l.parser_version
            END,
            ontology_version = CASE
                WHEN {_bad_expr('l.ontology_version')}
                    THEN COALESCE(NULLIF(TRIM(r.ontology_version), ''), {_literal(defaults['ontology_version'])})
                ELSE l.ontology_version
            END
        FROM family_link_runs AS r
        WHERE l.run_id = r.run_id
        """
    )

    # Repair/propagate evidence lineage and identifiers.
    conn.execute(
        f"""
        UPDATE link_evidence AS e
        SET
            doc_id = COALESCE(
                NULLIF(TRIM(e.doc_id), ''),
                NULLIF(TRIM(l.doc_id), ''),
                NULLIF(TRIM(split_part(COALESCE(e.section_reference_key, ''), ':', 1)), '')
            ),
            section_number = COALESCE(
                NULLIF(TRIM(e.section_number), ''),
                NULLIF(TRIM(l.section_number), ''),
                NULLIF(TRIM(split_part(COALESCE(e.section_reference_key, ''), ':', 2)), '')
            ),
            corpus_version = CASE
                WHEN {_bad_expr('e.corpus_version')} THEN COALESCE(
                    NULLIF(TRIM(l.corpus_version), ''),
                    NULLIF(TRIM(r.corpus_version), ''),
                    {_literal(defaults['corpus_version'])}
                )
                ELSE e.corpus_version
            END,
            parser_version = CASE
                WHEN {_bad_expr('e.parser_version')} THEN COALESCE(
                    NULLIF(TRIM(l.parser_version), ''),
                    NULLIF(TRIM(r.parser_version), ''),
                    {_literal(defaults['parser_version'])}
                )
                ELSE e.parser_version
            END,
            ontology_version = CASE
                WHEN {_bad_expr('e.ontology_version')} THEN COALESCE(
                    NULLIF(TRIM(l.ontology_version), ''),
                    NULLIF(TRIM(r.ontology_version), ''),
                    {_literal(defaults['ontology_version'])}
                )
                ELSE e.ontology_version
            END,
            ruleset_version = CASE
                WHEN {_bad_expr('e.ruleset_version')} THEN COALESCE(
                    NULLIF(TRIM(r.ruleset_version), ''),
                    {_literal(defaults['ruleset_version'])}
                )
                ELSE e.ruleset_version
            END,
            git_sha = CASE
                WHEN {_bad_expr('e.git_sha')} THEN COALESCE(
                    NULLIF(TRIM(r.git_sha), ''),
                    {_literal(defaults['git_sha'])}
                )
                ELSE e.git_sha
            END,
            created_at_utc = COALESCE(
                NULLIF(TRIM(e.created_at_utc), ''),
                NULLIF(TRIM(r.created_at_utc), ''),
                CAST(r.started_at AS VARCHAR),
                {_literal(defaults['created_at_utc'])}
            )
        FROM family_links AS l
        LEFT JOIN family_link_runs AS r ON l.run_id = r.run_id
        WHERE e.link_id = l.link_id
        """
    )

    conn.execute(
        f"""
        UPDATE link_evidence AS e
        SET
            corpus_version = CASE
                WHEN {_bad_expr('e.corpus_version')}
                    THEN COALESCE(NULLIF(TRIM(r.corpus_version), ''), {_literal(defaults['corpus_version'])})
                ELSE e.corpus_version
            END,
            parser_version = CASE
                WHEN {_bad_expr('e.parser_version')}
                    THEN COALESCE(NULLIF(TRIM(r.parser_version), ''), {_literal(defaults['parser_version'])})
                ELSE e.parser_version
            END,
            ontology_version = CASE
                WHEN {_bad_expr('e.ontology_version')}
                    THEN COALESCE(NULLIF(TRIM(r.ontology_version), ''), {_literal(defaults['ontology_version'])})
                ELSE e.ontology_version
            END,
            ruleset_version = CASE
                WHEN {_bad_expr('e.ruleset_version')}
                    THEN COALESCE(NULLIF(TRIM(r.ruleset_version), ''), {_literal(defaults['ruleset_version'])})
                ELSE e.ruleset_version
            END,
            git_sha = CASE
                WHEN {_bad_expr('e.git_sha')}
                    THEN COALESCE(NULLIF(TRIM(r.git_sha), ''), {_literal(defaults['git_sha'])})
                ELSE e.git_sha
            END,
            created_at_utc = COALESCE(
                NULLIF(TRIM(e.created_at_utc), ''),
                NULLIF(TRIM(r.created_at_utc), ''),
                CAST(r.started_at AS VARCHAR),
                {_literal(defaults['created_at_utc'])}
            )
        FROM family_link_runs AS r
        WHERE e.run_id = r.run_id
        """
    )

    _ensure_run_rows_exist(conn, defaults)


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill lineage fields on runs/links/evidence tables.")
    parser.add_argument("--links-db", required=True, help="Path to links DuckDB")
    parser.add_argument("--corpus-db", default=None, help="Optional corpus DuckDB path for schema lineage")
    parser.add_argument("--corpus-version", default=None, help="Override reconstructed corpus_version")
    parser.add_argument("--corpus-snapshot-id", default=None, help="Override reconstructed corpus_snapshot_id")
    parser.add_argument("--parser-version", default=None, help="Override reconstructed parser_version")
    parser.add_argument("--ontology-version", default=None, help="Override reconstructed ontology_version")
    parser.add_argument("--ruleset-version", default=None, help="Override reconstructed ruleset_version")
    parser.add_argument("--git-sha", default=None, help="Override reconstructed git sha")
    parser.add_argument("--dry-run", action="store_true", help="Report only; do not write")
    args = parser.parse_args()

    links_db = Path(args.links_db)
    if not links_db.exists():
        raise SystemExit(f"links db not found: {links_db}")
    corpus_db = Path(args.corpus_db) if args.corpus_db else (links_db.parent / "corpus.duckdb")

    conn = duckdb.connect(str(links_db))
    try:
        defaults = _resolve_defaults(
            conn=conn,
            links_db=links_db,
            corpus_db=corpus_db if corpus_db.exists() else None,
            corpus_version=args.corpus_version,
            corpus_snapshot_id=args.corpus_snapshot_id,
            parser_version=args.parser_version,
            ontology_version=args.ontology_version,
            ruleset_version=args.ruleset_version,
            git_sha=args.git_sha,
        )
        before = _count_state(conn)
        if not args.dry_run:
            _apply_backfill(conn, defaults)
        after = _count_state(conn)
    finally:
        conn.close()

    result: dict[str, Any] = {
        "status": "dry_run" if args.dry_run else "ok",
        "links_db": str(links_db),
        "defaults": defaults,
        "before": before,
        "after": after,
        "delta": {
            "family_link_runs_bad": before["family_link_runs_bad"] - after["family_link_runs_bad"],
            "family_links_bad": before["family_links_bad"] - after["family_links_bad"],
            "link_evidence_bad": before["link_evidence_bad"] - after["link_evidence_bad"],
        },
    }
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
