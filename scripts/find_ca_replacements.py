#!/usr/bin/env python3
"""Find credit agreement replacements for amendment documents in the corpus.

For each CIK whose current corpus document is classified as an amendment,
scans the full S3 corpus (``documents/`` prefix) for alternative filings
that classify as actual credit agreements.

Uses the full Agent classifier pipeline (17 regex patterns + structural
signals) rather than the EDGAR Extractor's lightweight 5KB header check,
but applies it to a partial download (~120KB) for speed.

**EDGAR Extractor filter (phase2_worker.py) limitations:**
    - Only checks first 5000 chars
    - 3 signals: "CREDIT AGREEMENT" presence, AMENDMENT count, "AMENDED AND RESTATED"
    - No structural depth (articles, definitions, signature blocks)
    - No market segment classification

**This script enhances it with:**
    - Full classifier.py (5-priority classification, 14+ keyword lists)
    - Structural signals (article count, definition count, signature block)
    - Market segment classification (leveraged vs investment_grade)
    - Cohort inclusion check (same gate as corpus builder)
    - Accession-based date ordering to pick the best replacement

Usage::

    python3 scripts/find_ca_replacements.py [--limit N] [--dry-run] [--verbose]
    python3 scripts/find_ca_replacements.py --apply  # download replacements to corpus/
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

import boto3
import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from agent.classifier import (
    classify_document_type,
    classify_market_segment,
    extract_classification_signals,
)
from agent.document_processor import (
    accession_sort_key,
    extract_accession,
    extract_cik,
    is_cohort_included,
)
from agent.html_utils import strip_html

log = logging.getLogger("find_ca_replacements")

BUCKET = "edgar-pipeline-documents-216213517387"
DOC_PREFIX = "documents/"
# Download enough for structural signal extraction (articles, defs, signature)
DOWNLOAD_BYTES = 120 * 1024  # 120KB — covers title, definitions article, structure


# ── Data structures ────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class CandidateDoc:
    """A candidate document from S3 with classification results."""

    s3_key: str
    cik: str
    accession: str
    doc_type: str
    doc_type_confidence: str
    market_segment: str
    segment_confidence: str
    cohort_included: bool
    word_count: int
    definition_count: int
    article_count: int
    reasons: list[str]


@dataclass(frozen=True, slots=True)
class ReplacementResult:
    """Result for one amendment CIK: current amendment + best replacement."""

    cik: str
    current_amendment_path: str
    current_accession: str
    alternatives_checked: int
    ca_alternatives_found: int
    cohort_ca_found: int
    best_replacement: CandidateDoc | None
    all_candidates: list[CandidateDoc]


# ── S3 helpers ─────────────────────────────────────────────────────────


def _list_cik_docs(s3_client: boto3.client, cik: str) -> list[str]:
    """List all HTML document keys for a CIK in S3."""
    prefix = f"{DOC_PREFIX}cik={cik}/"
    keys: list[str] = []
    paginator = s3_client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=BUCKET, Prefix=prefix):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            if key.endswith((".htm", ".html")):
                keys.append(key)
    return keys


def _download_partial(s3_client: boto3.client, key: str) -> str | None:
    """Download the first DOWNLOAD_BYTES of an S3 object as text."""
    try:
        resp = s3_client.get_object(
            Bucket=BUCKET, Key=key,
            Range=f"bytes=0-{DOWNLOAD_BYTES - 1}",
        )
        raw = resp["Body"].read()
        return raw.decode("utf-8", errors="replace")
    except Exception as exc:
        log.debug("Failed to download %s: %s", key, exc)
        return None


# ── Classification ─────────────────────────────────────────────────────


def classify_candidate(
    s3_client: boto3.client,
    s3_key: str,
) -> CandidateDoc | None:
    """Download and classify a single S3 document."""
    html = _download_partial(s3_client, s3_key)
    if html is None:
        return None

    text = strip_html(html)
    if len(text.strip()) < 500:
        return None

    cik = extract_cik(s3_key)
    accession = extract_accession(s3_key)
    filename = PurePosixPath(s3_key).name

    signals = extract_classification_signals(text, filename)
    doc_type, dt_confidence, reasons = classify_document_type(filename, signals)
    segment, seg_confidence, seg_reasons = classify_market_segment(signals)

    cohort = is_cohort_included(doc_type, dt_confidence, segment, seg_confidence)

    return CandidateDoc(
        s3_key=s3_key,
        cik=cik,
        accession=accession,
        doc_type=doc_type,
        doc_type_confidence=dt_confidence,
        market_segment=segment,
        segment_confidence=seg_confidence,
        cohort_included=cohort,
        word_count=signals.word_count,
        definition_count=signals.definition_count,
        article_count=signals.article_count,
        reasons=reasons + seg_reasons,
    )


# ── Per-CIK analysis ──────────────────────────────────────────────────


def analyze_cik(
    s3_client: boto3.client,
    cik: str,
    current_path: str,
    current_accession: str,
    verbose: bool = False,
) -> ReplacementResult:
    """Analyze all S3 docs for a CIK and find the best CA replacement."""
    all_keys = _list_cik_docs(s3_client, cik)

    # Exclude the current amendment
    alt_keys = [k for k in all_keys if k != current_path]

    candidates: list[CandidateDoc] = []
    for key in alt_keys:
        candidate = classify_candidate(s3_client, key)
        if candidate is not None:
            candidates.append(candidate)

    # Filter to credit agreements
    ca_candidates = [c for c in candidates if c.doc_type == "credit_agreement"]

    # Filter to cohort-included (leveraged CAs)
    cohort_cas = [c for c in ca_candidates if c.cohort_included]

    # Pick best: latest accession among cohort CAs, falling back to any CA
    best: CandidateDoc | None = None
    pool = cohort_cas if cohort_cas else ca_candidates
    if pool:
        pool_sorted = sorted(
            pool,
            key=lambda c: accession_sort_key(c.s3_key),
            reverse=True,
        )
        best = pool_sorted[0]

    if verbose and best:
        log.info(
            "CIK %s: found replacement %s (%s, %s, %d words, %d defs)",
            cik, best.accession, best.doc_type, best.market_segment,
            best.word_count, best.definition_count,
        )

    return ReplacementResult(
        cik=cik,
        current_amendment_path=current_path,
        current_accession=current_accession,
        alternatives_checked=len(alt_keys),
        ca_alternatives_found=len(ca_candidates),
        cohort_ca_found=len(cohort_cas),
        best_replacement=best,
        all_candidates=candidates,
    )


# ── Report helpers ─────────────────────────────────────────────────────


def _replacement_record(r: ReplacementResult) -> dict[str, object]:
    """Build a JSON-serialisable dict for one CIK's replacement result."""
    b = r.best_replacement
    return {
        "cik": r.cik,
        "current_amendment": r.current_amendment_path,
        "current_accession": r.current_accession,
        "replacement_key": b.s3_key if b else None,
        "replacement_accession": b.accession if b else None,
        "replacement_doc_type": b.doc_type if b else None,
        "replacement_confidence": b.doc_type_confidence if b else None,
        "replacement_segment": b.market_segment if b else None,
        "replacement_cohort": b.cohort_included if b else None,
        "replacement_words": b.word_count if b else None,
        "replacement_defs": b.definition_count if b else None,
        "alternatives_checked": r.alternatives_checked,
        "ca_found": r.ca_alternatives_found,
        "cohort_ca_found": r.cohort_ca_found,
    }


# ── Main ───────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Find CA replacements for amendment documents in the corpus.",
    )
    parser.add_argument(
        "--corpus-db", default="corpus_index/corpus.duckdb",
        help="Path to DuckDB corpus index (default: corpus_index/corpus.duckdb)",
    )
    parser.add_argument(
        "--limit", type=int, default=0,
        help="Limit number of CIKs to check (0 = all)",
    )
    parser.add_argument(
        "--workers", type=int, default=8,
        help="Number of parallel S3 workers (default: 8)",
    )
    parser.add_argument(
        "--output", default="plans/ca_replacement_report.json",
        help="Output report path",
    )
    parser.add_argument("--verbose", "-v", action="store_true")
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Only report findings, don't download anything",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        stream=sys.stderr,
    )

    # Step 1: Get amendment documents from corpus
    db = duckdb.connect(args.corpus_db, read_only=True)
    amendments = db.execute("""
        SELECT cik, path, accession
        FROM documents
        WHERE doc_type = 'amendment'
        ORDER BY cik
    """).fetchall()
    db.close()

    log.info("Found %d amendment documents in corpus", len(amendments))

    if args.limit > 0:
        amendments = amendments[: args.limit]
        log.info("Limited to %d CIKs", len(amendments))

    # Step 2: Analyze each CIK in parallel
    s3_client = boto3.client("s3")
    results: list[ReplacementResult] = []
    t0 = time.monotonic()

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {
            pool.submit(
                analyze_cik,
                s3_client,
                row[0],  # cik
                row[1],  # path
                row[2],  # accession
                args.verbose,
            ): row[0]
            for row in amendments
        }

        for done_count, future in enumerate(as_completed(futures), 1):
            cik = futures[future]
            try:
                result = future.result()
                results.append(result)
            except Exception as exc:
                log.warning("CIK %s failed: %s", cik, exc)

            if done_count % 50 == 0:
                replaceable = sum(1 for r in results if r.best_replacement is not None)
                elapsed = time.monotonic() - t0
                rate = done_count / elapsed if elapsed > 0 else 0
                log.info(
                    "Progress: %d/%d CIKs (%.1f/sec), %d replaceable so far",
                    done_count, len(amendments), rate, replaceable,
                )

    elapsed = time.monotonic() - t0

    # Step 3: Summarize
    replaceable = [r for r in results if r.best_replacement is not None]
    cohort_replaceable = [
        r for r in replaceable
        if r.best_replacement is not None and r.best_replacement.cohort_included
    ]
    no_alternatives = [r for r in results if r.alternatives_checked == 0]
    has_ca_but_not_cohort = [
        r for r in results
        if r.ca_alternatives_found > 0 and r.cohort_ca_found == 0
    ]

    log.info("=" * 60)
    log.info("RESULTS (%.1fs elapsed)", elapsed)
    log.info("  Amendment CIKs analyzed:         %d", len(results))
    log.info("  CIKs with NO alternatives:       %d", len(no_alternatives))
    log.info("  CIKs with a CA replacement:      %d", len(replaceable))
    log.info("    ... of which cohort-included:   %d", len(cohort_replaceable))
    log.info("  CIKs with CA but NOT cohort:     %d", len(has_ca_but_not_cohort))
    log.info(
        "  CIKs with no CA alternative:     %d",
        len(results) - len(replaceable),
    )

    # Build JSON report
    report = {
        "summary": {
            "total_amendments": len(results),
            "no_alternatives_on_s3": len(no_alternatives),
            "replaceable_with_ca": len(replaceable),
            "replaceable_with_cohort_ca": len(cohort_replaceable),
            "ca_found_but_not_cohort": len(has_ca_but_not_cohort),
            "no_ca_alternative": len(results) - len(replaceable),
            "elapsed_seconds": round(elapsed, 1),
        },
        "replacements": [
            _replacement_record(r)
            for r in sorted(results, key=lambda x: x.cik)
        ],
    }

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(report, f, indent=2)
    log.info("Report written to %s", output_path)


if __name__ == "__main__":
    main()
