#!/usr/bin/env python3
"""Cluster template families from corpus boilerplate text.

This is a pragmatic phase-1.5 classifier:
- Extract a boilerplate-focused fingerprint per document
- Vectorize with character n-gram TF-IDF
- Cluster with DBSCAN (cosine distance)
- Persist doc_id -> template metadata JSON
- Optionally write cluster labels into documents.template_family

Usage:
    python3 scripts/template_classifier.py --db corpus_index/corpus.duckdb \
      --output corpus_index/templates/classifications.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

from agent.corpus import SchemaVersionError, ensure_schema_version

try:
    import orjson

    def dump_json(obj: object) -> None:
        sys.stdout.buffer.write(orjson.dumps(obj, option=orjson.OPT_INDENT_2))
        sys.stdout.buffer.write(b"\n")

    def write_json(path: Path, obj: object) -> None:
        path.write_bytes(orjson.dumps(obj, option=orjson.OPT_INDENT_2))
except ImportError:

    def dump_json(obj: object) -> None:
        json.dump(obj, sys.stdout, indent=2, default=str)
        print()

    def write_json(path: Path, obj: object) -> None:
        path.write_text(json.dumps(obj, indent=2, default=str))


try:
    import duckdb
except ImportError:
    print("Error: duckdb is required. Install with: pip install duckdb", file=sys.stderr)
    sys.exit(1)

import numpy as np
from sklearn.cluster import DBSCAN
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

try:
    from datasketch import MinHash, MinHashLSH
except ImportError:
    MinHash = None  # type: ignore[assignment]
    MinHashLSH = None  # type: ignore[assignment]


def _log(msg: str) -> None:
    print(msg, file=sys.stderr)


_DEF_LINE_RE = (
    r'["\u201c][A-Z0-9][^"\u201d]{1,100}["\u201d]\s+'
    r"(?:means|shall\s+mean|has\s+the\s+meaning|:)"
)
_MODULE_PATTERNS: dict[str, tuple[str, ...]] = {
    "definitions": (r"\bdefinition[s]?\b", r"\bmeans\b"),
    "negative_covenants": (
        r"\blimitation on\b",
        r"\bindebtedness\b",
        r"\bliens?\b",
        r"\brestricted payments?\b",
    ),
    "affirmative_covenants": (
        r"\baffirmative covenant",
        r"\bmaintenance of\b",
        r"\binsurance\b",
    ),
    "events_of_default": (r"\bevent[s]? of default\b", r"\bdefault\b"),
    "conditions_precedent": (r"\bconditions? precedent\b",),
}

_PROFILE_PRESETS: dict[str, dict[str, Any]] = {
    "pilot_balanced": {
        "cluster_method": "minhash",
        "eps": 0.34,
        "min_samples": 8,
        "max_features": 20000,
        "ngram_min": 5,
        "ngram_max": 7,
        "num_perm": 128,
        "lsh_threshold": 0.70,
        "shingle_size": 7,
    },
    "precision_strict": {
        "cluster_method": "minhash",
        "eps": 0.30,
        "min_samples": 10,
        "max_features": 25000,
        "ngram_min": 5,
        "ngram_max": 8,
        "num_perm": 128,
        "lsh_threshold": 0.74,
        "shingle_size": 7,
    },
    "recall_explore": {
        "cluster_method": "tfidf",
        "eps": 0.40,
        "min_samples": 5,
        "max_features": 30000,
        "ngram_min": 4,
        "ngram_max": 7,
        "num_perm": 128,
        "lsh_threshold": 0.66,
        "shingle_size": 6,
    },
}


def _resolve_profile_config(args: argparse.Namespace) -> dict[str, Any]:
    """Resolve clustering config from profile presets + explicit overrides."""
    preset = dict(_PROFILE_PRESETS[args.profile])

    def pick(name: str) -> Any:
        val = getattr(args, name)
        return val if val is not None else preset[name]

    return {
        "profile": args.profile,
        "cluster_method": pick("cluster_method"),
        "eps": float(pick("eps")),
        "min_samples": int(pick("min_samples")),
        "max_features": int(pick("max_features")),
        "ngram_min": int(pick("ngram_min")),
        "ngram_max": int(pick("ngram_max")),
        "num_perm": int(pick("num_perm")),
        "lsh_threshold": float(pick("lsh_threshold")),
        "shingle_size": int(pick("shingle_size")),
    }


def _canonicalize_cluster_labels(
    doc_ids: list[str],
    labels: list[int],
) -> tuple[list[int], dict[int, int]]:
    """Re-map non-noise cluster labels deterministically.

    DBSCAN labels are order-sensitive. To make reruns comparable, map labels by:
    1) descending cluster size
    2) lexicographically smallest doc_id in cluster (tie-breaker)
    """
    by_cluster: dict[int, list[int]] = {}
    for idx, label in enumerate(labels):
        if label < 0:
            continue
        by_cluster.setdefault(label, []).append(idx)

    ordered = sorted(
        by_cluster.items(),
        key=lambda kv: (-len(kv[1]), min(doc_ids[i] for i in kv[1])),
    )
    label_map = {old: new for new, (old, _idxs) in enumerate(ordered)}
    canonical: list[int] = [
        label_map.get(label, -1) if label >= 0 else -1
        for label in labels
    ]
    return canonical, label_map


def _primary_module_label(profile: dict[str, float]) -> str:
    if not profile:
        return "unclassified"
    best = sorted(
        profile.items(),
        key=lambda kv: (-float(kv[1]), kv[0]),
    )[0]
    return str(best[0])


def _cluster_assignment_signature(doc_ids: list[str], labels: list[int]) -> str:
    rows = [f"{doc}:{label}" for doc, label in zip(doc_ids, labels, strict=True)]
    payload = "\n".join(rows).encode("utf-8", errors="ignore")
    return hashlib.sha256(payload).hexdigest()[:16]


def _cluster_quality_metrics(
    *,
    doc_ids: list[str],
    labels: list[int],
    confidences: list[float],
    module_profiles: dict[str, dict[str, float]],
) -> dict[str, Any]:
    total = len(labels)
    if total == 0:
        return {
            "documents": 0,
            "clusters": 0,
            "noise_docs": 0,
            "noise_rate": 0.0,
            "non_noise_coverage": 0.0,
            "confidence_mean_non_noise": 0.0,
            "confidence_p50_non_noise": 0.0,
            "singleton_clusters": 0,
            "largest_cluster_share": 0.0,
            "cluster_balance_hhi": 0.0,
            "low_confidence_non_noise_docs": 0,
            "top_noise_modules": [],
            "size_distribution": {},
        }

    cluster_sizes: dict[int, int] = {}
    for label in labels:
        cluster_sizes[label] = cluster_sizes.get(label, 0) + 1

    noise_docs = cluster_sizes.get(-1, 0)
    non_noise_docs = total - noise_docs
    non_noise_labels = [label for label in cluster_sizes if label >= 0]
    non_noise_confidences = [
        float(confidences[i])
        for i, label in enumerate(labels)
        if label >= 0
    ]
    singleton_clusters = sum(
        1 for label in non_noise_labels if cluster_sizes.get(label, 0) <= 1
    )
    largest_cluster_size = max(
        (cluster_sizes.get(label, 0) for label in non_noise_labels),
        default=0,
    )
    low_conf_non_noise = sum(1 for c in non_noise_confidences if c < 0.45)

    size_values = [cluster_sizes.get(label, 0) for label in non_noise_labels]
    if size_values:
        size_dist = {
            "min": int(min(size_values)),
            "p50": float(np.percentile(size_values, 50)),
            "p90": float(np.percentile(size_values, 90)),
            "max": int(max(size_values)),
        }
    else:
        size_dist = {"min": 0, "p50": 0.0, "p90": 0.0, "max": 0}

    # Concentration: lower is more balanced.
    cluster_balance_hhi = 0.0
    if non_noise_docs > 0:
        cluster_balance_hhi = float(
            sum(
                (cluster_sizes.get(label, 0) / non_noise_docs) ** 2
                for label in non_noise_labels
            )
        )

    noise_module_counts: dict[str, int] = {}
    for i, label in enumerate(labels):
        if label >= 0:
            continue
        profile = module_profiles.get(doc_ids[i], {})
        module_name = _primary_module_label(profile)
        noise_module_counts[module_name] = noise_module_counts.get(module_name, 0) + 1
    top_noise_modules = [
        {"module": module, "count": count}
        for module, count in sorted(
            noise_module_counts.items(),
            key=lambda kv: (-kv[1], kv[0]),
        )[:8]
    ]

    return {
        "documents": total,
        "clusters": len(non_noise_labels),
        "noise_docs": noise_docs,
        "noise_rate": round(noise_docs / total, 4),
        "non_noise_coverage": round(non_noise_docs / total, 4),
        "confidence_mean_non_noise": round(
            float(np.mean(non_noise_confidences)) if non_noise_confidences else 0.0,
            4,
        ),
        "confidence_p50_non_noise": round(
            float(np.percentile(non_noise_confidences, 50)) if non_noise_confidences else 0.0,
            4,
        ),
        "singleton_clusters": singleton_clusters,
        "largest_cluster_share": round(
            (largest_cluster_size / non_noise_docs) if non_noise_docs > 0 else 0.0,
            4,
        ),
        "cluster_balance_hhi": round(cluster_balance_hhi, 4),
        "low_confidence_non_noise_docs": low_conf_non_noise,
        "top_noise_modules": top_noise_modules,
        "size_distribution": size_dist,
    }


def _evaluate_quality_gates(
    *,
    metrics: dict[str, Any],
    min_clusters: int,
    min_non_noise_coverage: float,
    max_noise_rate: float,
    min_mean_confidence: float,
) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    def add_min_gate(name: str, actual: float, threshold: float) -> None:
        checks.append(
            {
                "name": name,
                "operator": ">=",
                "threshold": round(float(threshold), 4),
                "actual": round(float(actual), 4),
                "passed": bool(actual >= threshold),
            }
        )

    def add_max_gate(name: str, actual: float, threshold: float) -> None:
        checks.append(
            {
                "name": name,
                "operator": "<=",
                "threshold": round(float(threshold), 4),
                "actual": round(float(actual), 4),
                "passed": bool(actual <= threshold),
            }
        )

    add_min_gate("min_clusters", float(metrics.get("clusters", 0)), float(min_clusters))
    add_min_gate(
        "min_non_noise_coverage",
        float(metrics.get("non_noise_coverage", 0.0)),
        float(min_non_noise_coverage),
    )
    add_max_gate(
        "max_noise_rate",
        float(metrics.get("noise_rate", 0.0)),
        float(max_noise_rate),
    )
    add_min_gate(
        "min_mean_confidence",
        float(metrics.get("confidence_mean_non_noise", 0.0)),
        float(min_mean_confidence),
    )

    failures = [c["name"] for c in checks if not bool(c["passed"])]
    return {
        "passed": len(failures) == 0,
        "checks": checks,
        "failures": failures,
    }


def _build_cluster_diagnostics(
    *,
    doc_ids: list[str],
    labels: list[int],
    confidences: list[float],
    module_profiles: dict[str, dict[str, float]],
) -> list[dict[str, Any]]:
    by_cluster: dict[int, list[int]] = {}
    for idx, label in enumerate(labels):
        by_cluster.setdefault(label, []).append(idx)

    diagnostics: list[dict[str, Any]] = []
    for label, idxs in sorted(
        by_cluster.items(),
        key=lambda kv: (kv[0] < 0, kv[0]),
    ):
        conf_vals = [float(confidences[i]) for i in idxs]
        top_docs = sorted(
            (
                (doc_ids[i], float(confidences[i]))
                for i in idxs
            ),
            key=lambda item: (-item[1], item[0]),
        )[:3]
        module_counts: dict[str, int] = {}
        for i in idxs:
            module_name = _primary_module_label(module_profiles.get(doc_ids[i], {}))
            module_counts[module_name] = module_counts.get(module_name, 0) + 1
        top_modules = [
            {"module": m, "count": c}
            for m, c in sorted(module_counts.items(), key=lambda kv: (-kv[1], kv[0]))[:5]
        ]
        diagnostics.append(
            {
                "cluster_id": int(label),
                "template_family": "noise" if label < 0 else f"cluster_{label:03d}",
                "size": len(idxs),
                "mean_confidence": round(float(np.mean(conf_vals)) if conf_vals else 0.0, 4),
                "p50_confidence": round(
                    float(np.percentile(conf_vals, 50)) if conf_vals else 0.0,
                    4,
                ),
                "top_modules": top_modules,
                "example_docs": [
                    {"doc_id": doc_id, "confidence": round(score, 4)}
                    for doc_id, score in top_docs
                ],
            }
        )
    return diagnostics


def _extract_boilerplate_fingerprint(text: str) -> str:
    """Extract a compact fingerprint emphasizing repeated boilerplate regions."""
    if not text:
        return ""

    n = len(text)
    head = text[: min(n, 12000)]
    tail = text[max(0, n - 5000):]

    import re

    def_lines: list[str] = []
    for m in re.finditer(_DEF_LINE_RE, text[: min(n, 30000)], flags=re.IGNORECASE):
        def_lines.append(m.group(0).strip())
        if len(def_lines) >= 80:
            break

    # Repeat heavy-signal zones to increase their influence on n-gram TF-IDF.
    return "\n".join(
        [
            head,
            head,
            "\n".join(def_lines),
            tail,
            tail,
        ]
    )


def _derive_module_profile(text: str) -> dict[str, float]:
    """Score coarse module signatures from a document text sample."""
    text_lower = (text or "").lower()
    profile: dict[str, float] = {}
    for module, patterns in _MODULE_PATTERNS.items():
        hits = 0
        for raw in patterns:
            try:
                if re.search(raw, text_lower, flags=re.IGNORECASE):
                    hits += 1
            except Exception:
                if raw.lower() in text_lower:
                    hits += 1
        if hits > 0:
            profile[module] = round(hits / max(1, len(patterns)), 4)
    return profile


def _cluster_confidence(
    matrix: Any,
    labels: list[int],
) -> list[float]:
    """Compute per-document confidence from similarity to cluster centroid."""
    n = len(labels)
    if n == 0:
        return []

    confidences: list[float] = [0.0] * n
    by_cluster: dict[int, list[int]] = {}
    for i, label in enumerate(labels):
        by_cluster.setdefault(label, []).append(i)

    for label, idxs in by_cluster.items():
        if label < 0:
            # DBSCAN noise
            for idx in idxs:
                confidences[idx] = 0.0
            continue

        sub = matrix[idxs]
        centroid = sub.mean(axis=0)
        centroid_arr = np.asarray(centroid)
        sims = cosine_similarity(sub, centroid_arr).ravel()
        for j, idx in enumerate(idxs):
            sim = float(sims[j])
            # Clamp and round for stable output
            confidences[idx] = max(0.0, min(1.0, sim))

    return confidences


def _label_docs_tfidf(
    *,
    doc_ids: list[str],
    fingerprints: list[str],
    eps: float,
    min_samples: int,
    max_features: int,
    ngram_min: int,
    ngram_max: int,
) -> tuple[list[int], list[float]]:
    """Cluster docs and compute confidences using TF-IDF + DBSCAN."""
    if not doc_ids:
        return [], []
    if len(doc_ids) == 1:
        return [0], [1.0]

    vectorizer = TfidfVectorizer(
        analyzer="char_wb",
        ngram_range=(ngram_min, ngram_max),
        max_features=max_features,
        min_df=1,
    )
    matrix = vectorizer.fit_transform(fingerprints)

    clustering = DBSCAN(
        eps=eps,
        min_samples=min_samples,
        metric="cosine",
    )
    labels_arr = clustering.fit_predict(matrix)
    labels = [int(v) for v in labels_arr.tolist()]
    confidences = _cluster_confidence(matrix, labels)
    return labels, confidences


def _fingerprint_to_shingles(text: str, shingle_size: int) -> set[str]:
    """Convert fingerprint text into character shingles for MinHash."""
    cleaned = " ".join(text.split())
    if not cleaned:
        return {"__empty__"}
    if len(cleaned) <= shingle_size:
        return {cleaned}
    return {
        cleaned[i:i + shingle_size]
        for i in range(0, len(cleaned) - shingle_size + 1)
    }


def _label_docs_minhash(
    *,
    doc_ids: list[str],
    fingerprints: list[str],
    eps: float,
    min_samples: int,
    num_perm: int,
    lsh_threshold: float,
    shingle_size: int,
) -> tuple[list[int], list[float]]:
    """Cluster docs via MinHash + LSH candidate graph + DBSCAN."""
    if MinHash is None or MinHashLSH is None:
        raise RuntimeError("datasketch is not installed")

    if not doc_ids:
        return [], []
    if len(doc_ids) == 1:
        return [0], [1.0]

    minhashes: list[Any] = []
    for fp in fingerprints:
        mh = MinHash(num_perm=num_perm)
        shingles = _fingerprint_to_shingles(fp, shingle_size)
        for token in shingles:
            mh.update(token.encode("utf-8", errors="ignore"))
        minhashes.append(mh)

    lsh = MinHashLSH(threshold=lsh_threshold, num_perm=num_perm)
    for i, mh in enumerate(minhashes):
        lsh.insert(str(i), mh)

    n = len(minhashes)
    dist = np.ones((n, n), dtype=np.float64)
    np.fill_diagonal(dist, 0.0)

    # Only evaluate pairwise distances for LSH-neighbor candidates.
    for i, mh in enumerate(minhashes):
        neighbors = lsh.query(mh)
        for key in neighbors:
            j = int(key)
            if j <= i:
                continue
            sim = float(mh.jaccard(minhashes[j]))
            d = 1.0 - max(0.0, min(1.0, sim))
            dist[i, j] = d
            dist[j, i] = d

    labels_arr = DBSCAN(
        eps=eps,
        min_samples=min_samples,
        metric="precomputed",
    ).fit_predict(dist)
    labels = [int(v) for v in labels_arr.tolist()]

    # Confidence: mean in-cluster similarity; noise=0.0.
    confidences: list[float] = [0.0] * n
    by_cluster: dict[int, list[int]] = {}
    for idx, label in enumerate(labels):
        by_cluster.setdefault(label, []).append(idx)

    for label, idxs in by_cluster.items():
        if label < 0:
            for idx in idxs:
                confidences[idx] = 0.0
            continue
        if len(idxs) == 1:
            confidences[idxs[0]] = 1.0
            continue
        for idx in idxs:
            sims = [1.0 - float(dist[idx, j]) for j in idxs if j != idx]
            confidences[idx] = max(0.0, min(1.0, float(sum(sims) / len(sims))))

    return labels, confidences


def main() -> None:
    parser = argparse.ArgumentParser(description="Template family classifier.")
    parser.add_argument("--db", required=True, help="Path to corpus.duckdb")
    parser.add_argument(
        "--output",
        default="corpus_index/templates/classifications.json",
        help="Output classifications JSON path",
    )
    parser.add_argument(
        "--include-all",
        action="store_true",
        help="Include non-cohort documents (default is cohort-only).",
    )
    parser.add_argument("--max-docs", type=int, default=None, help="Optional doc cap for fast runs")
    parser.add_argument(
        "--profile",
        choices=tuple(_PROFILE_PRESETS.keys()),
        default="pilot_balanced",
        help="Deterministic clustering profile preset.",
    )
    parser.add_argument(
        "--cluster-method",
        choices=("minhash", "tfidf"),
        default=None,
        help="Clustering backend override (defaults to profile preset).",
    )
    parser.add_argument(
        "--eps",
        type=float,
        default=None,
        help="DBSCAN eps override (defaults to profile preset).",
    )
    parser.add_argument(
        "--min-samples",
        type=int,
        default=None,
        help="DBSCAN min_samples override (defaults to profile preset).",
    )
    parser.add_argument(
        "--max-features",
        type=int,
        default=None,
        help="TF-IDF max features override (defaults to profile preset).",
    )
    parser.add_argument(
        "--ngram-min",
        type=int,
        default=None,
        help="Character n-gram min override (defaults to profile preset).",
    )
    parser.add_argument(
        "--ngram-max",
        type=int,
        default=None,
        help="Character n-gram max override (defaults to profile preset).",
    )
    parser.add_argument(
        "--num-perm",
        type=int,
        default=None,
        help="MinHash permutations override (defaults to profile preset).",
    )
    parser.add_argument(
        "--lsh-threshold",
        type=float,
        default=None,
        help="LSH threshold override (defaults to profile preset).",
    )
    parser.add_argument(
        "--shingle-size",
        type=int,
        default=None,
        help="Shingle size override (defaults to profile preset).",
    )
    parser.add_argument(
        "--min-clusters",
        type=int,
        default=5,
        help="Quality gate: minimum non-noise clusters.",
    )
    parser.add_argument(
        "--min-non-noise-coverage",
        type=float,
        default=0.65,
        help="Quality gate: minimum share of docs assigned to non-noise clusters.",
    )
    parser.add_argument(
        "--max-noise-rate",
        type=float,
        default=0.35,
        help="Quality gate: maximum allowed noise share.",
    )
    parser.add_argument(
        "--min-mean-confidence",
        type=float,
        default=0.50,
        help="Quality gate: minimum mean confidence over non-noise docs.",
    )
    parser.add_argument(
        "--fail-on-gate",
        action="store_true",
        help="Exit non-zero when one or more quality gates fail.",
    )
    parser.add_argument(
        "--report-output",
        default=None,
        help="Optional path for detailed classification report JSON.",
    )
    parser.add_argument(
        "--no-write-db",
        action="store_true",
        help="Do not write template_family labels back into documents table.",
    )
    args = parser.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        _log(f"Error: database not found at {db_path}")
        sys.exit(1)

    con = duckdb.connect(str(db_path))
    try:
        ensure_schema_version(con, db_path=db_path)
    except SchemaVersionError as exc:
        _log(f"Error: {exc}")
        con.close()
        sys.exit(1)

    where_clause = "" if args.include_all else "WHERE d.cohort_included = true"
    limit_clause = ""
    params: list[object] = []
    if args.max_docs is not None and args.max_docs > 0:
        limit_clause = "LIMIT ?"
        params.append(args.max_docs)

    rows = con.execute(
        f"""
        SELECT
            d.doc_id,
            COALESCE(string_agg(st.text, '\n' ORDER BY st.section_number), '') AS doc_text
        FROM documents d
        LEFT JOIN section_text st ON st.doc_id = d.doc_id
        {where_clause}
        GROUP BY d.doc_id
        ORDER BY d.doc_id
        {limit_clause}
        """,
        params,
    ).fetchall()

    if not rows:
        _log("No documents matched selection.")
        output = {
            "status": "ok",
            "db": str(db_path),
            "documents": 0,
            "clusters": 0,
            "classifications": {},
        }
        dump_json(output)
        con.close()
        return

    doc_ids = [str(r[0]) for r in rows]
    fingerprints = [_extract_boilerplate_fingerprint(str(r[1] or "")) for r in rows]

    config = _resolve_profile_config(args)

    cluster_method_used = str(config["cluster_method"])
    if cluster_method_used == "minhash":
        if MinHash is None or MinHashLSH is None:
            _log("datasketch is not installed; falling back to TF-IDF clustering.")
            cluster_method_used = "tfidf"
        else:
            labels, confidences = _label_docs_minhash(
                doc_ids=doc_ids,
                fingerprints=fingerprints,
                eps=float(config["eps"]),
                min_samples=int(config["min_samples"]),
                num_perm=int(config["num_perm"]),
                lsh_threshold=float(config["lsh_threshold"]),
                shingle_size=int(config["shingle_size"]),
            )
    if cluster_method_used == "tfidf":
        labels, confidences = _label_docs_tfidf(
            doc_ids=doc_ids,
            fingerprints=fingerprints,
            eps=float(config["eps"]),
            min_samples=int(config["min_samples"]),
            max_features=int(config["max_features"]),
            ngram_min=int(config["ngram_min"]),
            ngram_max=int(config["ngram_max"]),
        )

    labels, original_to_canonical = _canonicalize_cluster_labels(doc_ids, labels)

    classifications: dict[str, dict[str, object]] = {}
    cluster_sizes: dict[int, int] = {}
    module_profiles: dict[str, dict[str, float]] = {}
    for label in labels:
        cluster_sizes[label] = cluster_sizes.get(label, 0) + 1

    for i, doc_id in enumerate(doc_ids):
        label = labels[i]
        confidence = round(confidences[i], 4)
        family = "noise" if label < 0 else f"cluster_{label:03d}"
        module_profile = _derive_module_profile(fingerprints[i])
        module_profiles[doc_id] = module_profile

        classifications[doc_id] = {
            "template_family": family,
            "cluster_id": label,
            "cluster_size": cluster_sizes.get(label, 1),
            "confidence": confidence,
            "module_profile": module_profile,
            # placeholders; human labeling pass can enrich these:
            "law_firm_borrower": "unknown",
            "law_firm_lender": "unknown",
            "arranging_bank": "unknown",
            "vintage_era": "unknown",
        }

    quality_metrics = _cluster_quality_metrics(
        doc_ids=doc_ids,
        labels=labels,
        confidences=confidences,
        module_profiles=module_profiles,
    )
    quality_gates = _evaluate_quality_gates(
        metrics=quality_metrics,
        min_clusters=max(0, int(args.min_clusters)),
        min_non_noise_coverage=max(0.0, min(1.0, float(args.min_non_noise_coverage))),
        max_noise_rate=max(0.0, min(1.0, float(args.max_noise_rate))),
        min_mean_confidence=max(0.0, min(1.0, float(args.min_mean_confidence))),
    )
    assignment_signature = _cluster_assignment_signature(doc_ids, labels)
    cluster_diagnostics = _build_cluster_diagnostics(
        doc_ids=doc_ids,
        labels=labels,
        confidences=confidences,
        module_profiles=module_profiles,
    )

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    write_json(out_path, classifications)
    module_path = out_path.with_name("module_profiles.json")
    write_json(module_path, module_profiles)
    report_path = (
        Path(args.report_output)
        if args.report_output
        else out_path.with_name("classification_report.json")
    )
    report_payload = {
        "schema_version": "template_classifier_report_v1",
        "db": str(db_path),
        "documents": len(doc_ids),
        "cluster_method": cluster_method_used,
        "profile": config["profile"],
        "resolved_config": config,
        "quality_metrics": quality_metrics,
        "quality_gates": quality_gates,
        "assignment_signature": assignment_signature,
        "cluster_diagnostics": cluster_diagnostics,
        "cluster_label_map": {
            str(old): int(new)
            for old, new in sorted(original_to_canonical.items(), key=lambda kv: kv[0])
        },
        "output_path": str(out_path),
        "module_profile_path": str(module_path),
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    write_json(report_path, report_payload)

    wrote_db = False
    if not args.no_write_db:
        # Ensure column exists
        cols = {
            row[0]
            for row in con.execute(
                "SELECT column_name FROM information_schema.columns WHERE table_name = 'documents'"
            ).fetchall()
        }
        if "template_family" not in cols:
            con.execute("ALTER TABLE documents ADD COLUMN template_family VARCHAR DEFAULT ''")

        updates = [
            (str(payload["template_family"]), doc_id)
            for doc_id, payload in classifications.items()
        ]
        con.executemany(
            "UPDATE documents SET template_family = ? WHERE doc_id = ?",
            updates,
        )
        wrote_db = True

    con.close()

    cluster_count = len([k for k in cluster_sizes if k >= 0])
    noise_count = cluster_sizes.get(-1, 0)
    output = {
        "status": "ok" if quality_gates.get("passed", False) else "quality_gates_failed",
        "db": str(db_path),
        "documents": len(doc_ids),
        "clusters": cluster_count,
        "noise_docs": noise_count,
        "cluster_method": cluster_method_used,
        "profile": config["profile"],
        "resolved_config": config,
        "assignment_signature": assignment_signature,
        "quality_metrics": quality_metrics,
        "quality_gates": quality_gates,
        "cluster_label_map": {
            str(old): int(new)
            for old, new in sorted(original_to_canonical.items(), key=lambda kv: kv[0])
        },
        "output_path": str(out_path),
        "module_profile_path": str(module_path),
        "report_path": str(report_path),
        "wrote_template_family_to_db": wrote_db,
    }
    dump_json(output)
    if args.fail_on_gate and not bool(quality_gates.get("passed", False)):
        _log(
            "Template clustering quality gate failed: "
            + ", ".join(str(v) for v in quality_gates.get("failures", []))
        )
        sys.exit(2)


if __name__ == "__main__":
    main()
