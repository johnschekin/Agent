"""End-to-end integration test on a small fixture corpus."""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from agent.corpus import CorpusIndex

TERMINTEL_DOCS_DIR = Path(
    "/Users/johnchtchekine/Projects/TermIntelligence/data/credit_agreements"
)
TERMINTEL_META_DIR = Path(
    "/Users/johnchtchekine/Projects/TermIntelligence/data/sidecar_metadata"
)
TERMINTEL_SAMPLE_FILES = [
    "000000217822000083_a4q20228-kccaxksaex101.htm",
    "000000296924000026_apd-exhibit101x31mar24.htm",
    "000000703918000031_exhibit10-1.htm",
    "000002166523000007_colgate-palmolive_credit.htm",
    "000004501225000062_halliburton-2025creditag.htm",
]


def _load_build_module() -> object:
    root = Path(__file__).resolve().parents[1]
    script_path = root / "scripts" / "build_corpus_index.py"
    spec = importlib.util.spec_from_file_location("build_corpus_index", script_path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _write_fixture_corpus(corpus_dir: Path) -> None:
    if not TERMINTEL_DOCS_DIR.exists() or not TERMINTEL_META_DIR.exists():
        pytest.skip(
            "TermIntelligence fixture corpus not available at "
            f"{TERMINTEL_DOCS_DIR} / {TERMINTEL_META_DIR}"
        )

    docs_dir = corpus_dir / "documents"
    meta_dir = corpus_dir / "metadata"
    docs_dir.mkdir(parents=True, exist_ok=True)
    meta_dir.mkdir(parents=True, exist_ok=True)

    for filename in TERMINTEL_SAMPLE_FILES:
        src_doc = TERMINTEL_DOCS_DIR / filename
        src_meta = TERMINTEL_META_DIR / f"{Path(filename).stem}.meta.json"
        assert src_doc.exists(), f"Missing source fixture document: {src_doc}"
        assert src_meta.exists(), f"Missing source fixture metadata: {src_meta}"

        meta_obj = json.loads(src_meta.read_text())
        cik = str(meta_obj.get("cik", "")).strip()
        if not cik:
            cik = "0000000000"

        cik_dir = f"cik={cik}"
        dst_doc_dir = docs_dir / cik_dir
        dst_meta_dir = meta_dir / cik_dir
        dst_doc_dir.mkdir(parents=True, exist_ok=True)
        dst_meta_dir.mkdir(parents=True, exist_ok=True)

        shutil.copy2(src_doc, dst_doc_dir / filename)
        shutil.copy2(src_meta, dst_meta_dir / src_meta.name)


def _run_script(script: str, args: list[str], root: Path) -> object:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(root / "src")
    proc = subprocess.run(
        [sys.executable, str(root / "scripts" / script), *args],
        cwd=str(root),
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(proc.stdout)


def test_fixture_ingest_and_cli_flow(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    mod = _load_build_module()

    corpus_dir = tmp_path / "corpus"
    _write_fixture_corpus(corpus_dir)
    db_path = tmp_path / "corpus.duckdb"

    files = mod._discover_html_files(corpus_dir)
    assert len(files) == len(TERMINTEL_SAMPLE_FILES)

    results = []
    for i, f in enumerate(files):
        out = mod._process_one_doc((f, corpus_dir, i, len(files)))
        assert out is not None
        results.append(out)

    mod._write_to_duckdb(db_path, results, verbose=False)

    with CorpusIndex(db_path) as corpus:
        assert corpus.doc_count == len(TERMINTEL_SAMPLE_FILES)
        doc_ids = corpus.doc_ids(cohort_only=False)
        assert doc_ids
        secs = corpus.search_sections(doc_id=doc_ids[0], cohort_only=False, limit=50)
        assert secs

    # Script smoke flow on built DB.
    search_out = _run_script(
        "corpus_search.py",
        [
            "--db",
            str(db_path),
            "--pattern",
            "Indebtedness",
            "--max-results",
            "10",
            "--include-all",
        ],
        root,
    )
    assert isinstance(search_out, list)

    sample_out = _run_script(
        "sample_selector.py",
        ["--db", str(db_path), "--n", "1", "--include-all"],
        root,
    )
    assert isinstance(sample_out, list)
    assert len(sample_out) == 1

    stats_out = _run_script(
        "metadata_reader.py",
        ["--db", str(db_path), "--stats", "--include-all"],
        root,
    )
    assert isinstance(stats_out, dict)
    assert int(stats_out["total_documents"]) == len(TERMINTEL_SAMPLE_FILES)

    # Evidence collector v2 contract smoke (HIT + NOT_FOUND).
    evidence_workspace = tmp_path / "workspace"
    evidence_input = tmp_path / "evidence_input.json"
    evidence_input.write_text(
        json.dumps(
            {
                "schema_version": "pattern_tester_v2",
                "run_id": "integration_run_1",
                "strategy_version": 3,
                "matches": [
                    {
                        "doc_id": doc_ids[0],
                        "section": "7.01",
                        "heading": "Indebtedness",
                        "score": 0.8,
                        "match_method": "heading",
                        "template_family": "cluster_001",
                        "confidence_components": {"heading": 1.0},
                        "confidence_final": 0.82,
                    }
                ],
                "miss_records": [
                    {
                        "doc_id": doc_ids[-1],
                        "best_score": 0.12,
                        "best_section": "",
                        "best_heading": "",
                    }
                ],
            }
        )
    )
    evidence_out = _run_script(
        "evidence_collector.py",
        [
            "--matches",
            str(evidence_input),
            "--concept-id",
            "debt_capacity.indebtedness",
            "--workspace",
            str(evidence_workspace),
        ],
        root,
    )
    assert isinstance(evidence_out, dict)
    assert int(evidence_out["hit_records"]) == 1
    assert int(evidence_out["not_found_records"]) == 1
