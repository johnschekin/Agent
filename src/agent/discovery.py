"""Hypothesis-free discovery primitives for corpus-wide analysis.

Pure analysis functions with zero I/O. All functions take arrays/dicts
and return frozen dataclasses. Used by exploratory_discoverer.py (Layer 1)
and discovery_seeder.py (Layer 2).

Primitive groups:
    1. Co-occurrence matrix — doc/article/adjacency counts for family pairs
    2. Metadata-structural correlation — Pearson + Spearman on feature pairs
    3. Adjacency pattern extraction — neighbor headings at ±1/±2 positions
    4. Anomaly scoring — per-section z-score outlier detection
    5. Template-conditioned profiling — how families manifest across templates
    6. Section clustering — PCA + KMeans with interpretable loadings
"""
from __future__ import annotations

import math
import statistics
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

# ---------------------------------------------------------------------------
# E1.1 — Co-occurrence Matrix
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class CooccurrenceMatrix:
    """NxN co-occurrence counts for family pairs at three granularities."""

    families: tuple[str, ...]
    doc_matrix: tuple[tuple[int, ...], ...]       # docs containing both families
    article_matrix: tuple[tuple[int, ...], ...]   # (doc, article) containing both
    adjacency_matrix: tuple[tuple[int, ...], ...]  # section within ±1 of each other


def compute_cooccurrence(
    family_sections: dict[str, list[tuple[str, str, int]]],
    all_sections_ordered: dict[str, list[tuple[str, str, int, int]]],
) -> CooccurrenceMatrix:
    """Compute co-occurrence at doc, article, and adjacency levels.

    Args:
        family_sections: family_id → [(doc_id, section_number, article_num), ...]
            Sections matched to each family.
        all_sections_ordered: doc_id → [(doc_id, section_number, article_num, position), ...]
            All sections per document, ordered by char_start (position = 0-based index).

    Returns:
        CooccurrenceMatrix with symmetric NxN counts.
    """
    families = tuple(sorted(family_sections.keys()))
    n = len(families)

    # Pre-compute per-family sets for fast lookup
    fam_docs: dict[str, set[str]] = {}
    fam_doc_articles: dict[str, set[tuple[str, int]]] = {}
    # family → {doc_id: set of positions}
    fam_doc_positions: dict[str, dict[str, set[int]]] = {}

    # Build position index: (doc_id, section_number) → position
    section_position: dict[tuple[str, str], int] = {}
    for doc_id, sec_list in all_sections_ordered.items():
        for _, sec_num, _, pos in sec_list:
            section_position[(doc_id, sec_num)] = pos

    for fam, sections in family_sections.items():
        docs: set[str] = set()
        doc_articles: set[tuple[str, int]] = set()
        doc_pos: dict[str, set[int]] = {}
        for doc_id, sec_num, article_num in sections:
            docs.add(doc_id)
            doc_articles.add((doc_id, article_num))
            pos = section_position.get((doc_id, sec_num))
            if pos is not None:
                doc_pos.setdefault(doc_id, set()).add(pos)
        fam_docs[fam] = docs
        fam_doc_articles[fam] = doc_articles
        fam_doc_positions[fam] = doc_pos

    # Compute pairwise counts
    doc_mat = [[0] * n for _ in range(n)]
    art_mat = [[0] * n for _ in range(n)]
    adj_mat = [[0] * n for _ in range(n)]

    for i in range(n):
        fi = families[i]
        for j in range(i, n):
            fj = families[j]

            # Doc-level
            doc_count = len(fam_docs.get(fi, set()) & fam_docs.get(fj, set()))
            doc_mat[i][j] = doc_count
            doc_mat[j][i] = doc_count

            # Article-level
            art_count = len(
                fam_doc_articles.get(fi, set()) & fam_doc_articles.get(fj, set())
            )
            art_mat[i][j] = art_count
            art_mat[j][i] = art_count

            # Adjacency (±1 position)
            adj_count = 0
            if i != j:
                pos_i = fam_doc_positions.get(fi, {})
                pos_j = fam_doc_positions.get(fj, {})
                shared_docs = set(pos_i.keys()) & set(pos_j.keys())
                for doc_id in shared_docs:
                    for pi in pos_i[doc_id]:
                        for pj in pos_j[doc_id]:
                            if abs(pi - pj) == 1:
                                adj_count += 1
                                break  # count once per (fi_section, fj) pair
            adj_mat[i][j] = adj_count
            adj_mat[j][i] = adj_count

    return CooccurrenceMatrix(
        families=families,
        doc_matrix=tuple(tuple(row) for row in doc_mat),
        article_matrix=tuple(tuple(row) for row in art_mat),
        adjacency_matrix=tuple(tuple(row) for row in adj_mat),
    )


# ---------------------------------------------------------------------------
# E1.2 — Metadata-Structural Correlation
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class CorrelationResult:
    """Pairwise correlation between two feature columns."""

    feature_a: str
    feature_b: str
    pearson_r: float
    spearman_rho: float
    n: int


def compute_correlations(
    features: Mapping[str, Sequence[float | None]],
    pairs: list[tuple[str, str]] | None = None,
) -> list[CorrelationResult]:
    """Compute Pearson and Spearman correlations between feature pairs.

    Args:
        features: column_name → values (one per document). None = missing.
        pairs: Specific pairs to compute. If None, computes all unique pairs.

    Returns:
        List of CorrelationResult, sorted by abs(pearson_r) descending.
    """
    columns = sorted(features.keys())
    if pairs is None:
        pairs = [
            (columns[i], columns[j])
            for i in range(len(columns))
            for j in range(i + 1, len(columns))
        ]

    results: list[CorrelationResult] = []
    for fa, fb in pairs:
        va = features.get(fa, [])
        vb = features.get(fb, [])
        # Filter pairs where both are non-None
        paired = [
            (a, b)
            for a, b in zip(va, vb, strict=False)
            if a is not None and b is not None
        ]
        if len(paired) < 3:
            continue

        xs = [p[0] for p in paired]
        ys = [p[1] for p in paired]

        pearson = _pearson(xs, ys)
        spearman = _spearman(xs, ys)

        results.append(CorrelationResult(
            feature_a=fa,
            feature_b=fb,
            pearson_r=round(pearson, 4),
            spearman_rho=round(spearman, 4),
            n=len(paired),
        ))

    results.sort(key=lambda r: -abs(r.pearson_r))
    return results


def _pearson(xs: list[float], ys: list[float]) -> float:
    """Compute Pearson correlation coefficient."""
    n = len(xs)
    if n < 2:
        return 0.0
    mx = sum(xs) / n
    my = sum(ys) / n
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True))
    sx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    sy = math.sqrt(sum((y - my) ** 2 for y in ys))
    if sx < 1e-12 or sy < 1e-12:
        return 0.0
    return cov / (sx * sy)


def _spearman(xs: list[float], ys: list[float]) -> float:
    """Compute Spearman rank correlation."""
    return _pearson(_rank(xs), _rank(ys))


def _rank(values: list[float]) -> list[float]:
    """Assign fractional ranks (1-based, average ties)."""
    n = len(values)
    indexed = sorted(range(n), key=lambda i: values[i])
    ranks = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j < n - 1 and values[indexed[j + 1]] == values[indexed[j]]:
            j += 1
        avg_rank = (i + j) / 2.0 + 1.0  # 1-based
        for k in range(i, j + 1):
            ranks[indexed[k]] = avg_rank
        i = j + 1
    return ranks


# ---------------------------------------------------------------------------
# E1.3 — Adjacency Pattern Extraction
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class AdjacencyPattern:
    """Recurring neighbor heading at a specific relative position from a family."""

    family: str
    position: int              # -2, -1, +1, +2
    neighbor_heading: str      # normalized heading
    frequency: int             # total occurrences
    doc_count: int             # distinct documents


def extract_adjacency_patterns(
    family_sections: dict[str, list[tuple[str, str, int]]],
    all_sections_ordered: dict[str, list[tuple[str, str, int, int]]],
    *,
    window: int = 2,
    min_frequency: int = 3,
) -> dict[str, list[AdjacencyPattern]]:
    """Extract recurring neighbor headings for each family.

    Args:
        family_sections: family_id → [(doc_id, section_number, article_num), ...]
        all_sections_ordered: doc_id → [(doc_id, section_number, article_num, position), ...]
            Ordered by char_start, position = 0-based index.
        window: How far to look (±1 to ±window).
        min_frequency: Minimum total occurrences to include.

    Returns:
        family_id → sorted list of AdjacencyPattern (by frequency desc).
    """
    # Build indexes from ordered section list
    section_position: dict[tuple[str, str], int] = {}
    doc_max_pos: dict[str, int] = {}
    doc_pos_secnum: dict[str, dict[int, str]] = {}
    for doc_id, sec_list in all_sections_ordered.items():
        pos_map: dict[int, str] = {}
        for _, sec_num, _, pos in sec_list:
            section_position[(doc_id, sec_num)] = pos
            doc_max_pos[doc_id] = max(doc_max_pos.get(doc_id, 0), pos)
            pos_map[pos] = sec_num
        doc_pos_secnum[doc_id] = pos_map

    result: dict[str, list[AdjacencyPattern]] = {}

    for fam, sections in family_sections.items():
        # Count (position_offset, neighbor_section_number) occurrences
        counter: Counter[tuple[int, str]] = Counter()
        doc_counter: dict[tuple[int, str], set[str]] = {}

        for doc_id, sec_num, _ in sections:
            my_pos = section_position.get((doc_id, sec_num))
            if my_pos is None:
                continue

            pos_map_inner = doc_pos_secnum.get(doc_id, {})
            max_pos = doc_max_pos.get(doc_id, 0)

            for offset in range(-window, window + 1):
                if offset == 0:
                    continue
                neighbor_pos = my_pos + offset
                if neighbor_pos < 0 or neighbor_pos > max_pos:
                    continue
                neighbor_sec = pos_map_inner.get(neighbor_pos)
                if neighbor_sec is None:
                    continue

                key = (offset, neighbor_sec)
                counter[key] += 1
                doc_counter.setdefault(key, set()).add(doc_id)

        patterns = [
            AdjacencyPattern(
                family=fam,
                position=offset,
                neighbor_heading=neighbor,
                frequency=count,
                doc_count=len(doc_counter.get((offset, neighbor), set())),
            )
            for (offset, neighbor), count in counter.items()
            if count >= min_frequency
        ]
        patterns.sort(key=lambda p: (-p.frequency, p.position))
        result[fam] = patterns

    return result


def extract_adjacency_patterns_with_headings(
    family_sections: dict[str, list[tuple[str, str, int]]],
    all_sections_with_headings: dict[str, list[tuple[str, str, str, int, int]]],
    *,
    window: int = 2,
    min_frequency: int = 3,
) -> dict[str, list[AdjacencyPattern]]:
    """Extract recurring neighbor headings using actual heading text.

    Args:
        family_sections: family_id → [(doc_id, section_number, article_num), ...]
        all_sections_with_headings: doc_id →
            [(doc_id, section_number, heading, article_num, position), ...]
        window: How far to look (±1 to ±window).
        min_frequency: Minimum total occurrences to include.

    Returns:
        family_id → sorted list of AdjacencyPattern (by frequency desc).
    """
    # Build position index: (doc_id, section_number) → position
    section_position: dict[tuple[str, str], int] = {}
    doc_pos_heading: dict[str, dict[int, str]] = {}
    doc_max_pos: dict[str, int] = {}

    for doc_id, sec_list in all_sections_with_headings.items():
        pos_map: dict[int, str] = {}
        for _, sec_num, heading, _, pos in sec_list:
            section_position[(doc_id, sec_num)] = pos
            # Normalize heading: lowercase, collapse whitespace
            normalized = " ".join(heading.lower().split())
            pos_map[pos] = normalized
            doc_max_pos[doc_id] = max(doc_max_pos.get(doc_id, 0), pos)
        doc_pos_heading[doc_id] = pos_map

    result: dict[str, list[AdjacencyPattern]] = {}

    for fam, sections in family_sections.items():
        counter: Counter[tuple[int, str]] = Counter()
        doc_counter: dict[tuple[int, str], set[str]] = {}

        for doc_id, sec_num, _ in sections:
            my_pos = section_position.get((doc_id, sec_num))
            if my_pos is None:
                continue

            pos_map = doc_pos_heading.get(doc_id, {})
            max_pos = doc_max_pos.get(doc_id, 0)

            for offset in range(-window, window + 1):
                if offset == 0:
                    continue
                neighbor_pos = my_pos + offset
                if neighbor_pos < 0 or neighbor_pos > max_pos:
                    continue
                neighbor_heading = pos_map.get(neighbor_pos)
                if neighbor_heading is None:
                    continue

                key = (offset, neighbor_heading)
                counter[key] += 1
                doc_counter.setdefault(key, set()).add(doc_id)

        patterns = [
            AdjacencyPattern(
                family=fam,
                position=offset,
                neighbor_heading=heading,
                frequency=count,
                doc_count=len(doc_counter.get((offset, heading), set())),
            )
            for (offset, heading), count in counter.items()
            if count >= min_frequency
        ]
        patterns.sort(key=lambda p: (-p.frequency, p.position))
        result[fam] = patterns

    return result


# ---------------------------------------------------------------------------
# E1.4 — Anomaly Scoring
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class AnomalyScore:
    """Outlier detection result for a single section."""

    doc_id: str
    section_number: str
    z_score: float
    anomalous_features: tuple[tuple[str, float, float], ...]  # (feature, value, z)


def score_anomalies(
    feature_vectors: list[dict[str, float]],
    section_ids: list[tuple[str, str]],
    *,
    threshold_z: float = 2.5,
) -> list[AnomalyScore]:
    """Detect anomalous sections via per-feature z-scores.

    Args:
        feature_vectors: Per-section feature dicts (same keys across all).
        section_ids: Parallel list of (doc_id, section_number).
        threshold_z: Aggregate z-score threshold for flagging.

    Returns:
        List of AnomalyScore for sections exceeding threshold, sorted by z_score desc.
    """
    if len(feature_vectors) < 3 or len(feature_vectors) != len(section_ids):
        return []

    # Collect per-feature statistics
    all_keys = sorted({k for fv in feature_vectors for k in fv})
    if not all_keys:
        return []

    means: dict[str, float] = {}
    stds: dict[str, float] = {}

    for key in all_keys:
        values = [fv.get(key, 0.0) for fv in feature_vectors]
        m = statistics.mean(values)
        s = statistics.pstdev(values)
        means[key] = m
        stds[key] = s

    # Score each section
    results: list[AnomalyScore] = []
    for i, fv in enumerate(feature_vectors):
        feature_zs: list[tuple[str, float, float]] = []
        z_squared_sum = 0.0
        n_features = 0

        for key in all_keys:
            val = fv.get(key, 0.0)
            s = stds[key]
            if s < 1e-12:
                continue
            z = (val - means[key]) / s
            n_features += 1
            z_squared_sum += z * z
            if abs(z) > threshold_z * 0.8:  # track features contributing to anomaly
                feature_zs.append((key, round(val, 4), round(z, 4)))

        if n_features == 0:
            continue

        aggregate_z = math.sqrt(z_squared_sum / n_features)

        if aggregate_z >= threshold_z:
            feature_zs.sort(key=lambda t: -abs(t[2]))
            doc_id, sec_num = section_ids[i]
            results.append(AnomalyScore(
                doc_id=doc_id,
                section_number=sec_num,
                z_score=round(aggregate_z, 4),
                anomalous_features=tuple(feature_zs[:10]),
            ))

    results.sort(key=lambda a: -a.z_score)
    return results


# ---------------------------------------------------------------------------
# E1.5 — Template-Conditioned Profiling
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class TemplateConditionedProfile:
    """How a family manifests within a specific law firm template."""

    family: str
    template_family: str
    section_count: int
    avg_article_num: float
    heading_distribution: dict[str, int]
    feature_means: dict[str, float]


def compute_template_conditioned_profiles(
    family_sections_with_template: dict[str, list[tuple[str, str, int, str]]],
    section_features: dict[tuple[str, str], dict[str, float]],
) -> dict[str, list[TemplateConditionedProfile]]:
    """Compute per-(family, template) profiles.

    Args:
        family_sections_with_template:
            family_id → [(doc_id, section_number, article_num, template_family), ...]
        section_features:
            (doc_id, section_number) → {feature_name: value, ...}

    Returns:
        family_id → list of TemplateConditionedProfile, sorted by section_count desc.
    """
    result: dict[str, list[TemplateConditionedProfile]] = {}

    for fam, sections in family_sections_with_template.items():
        # Group by template
        by_template: dict[str, list[tuple[str, str, int]]] = {}
        for doc_id, sec_num, article_num, template in sections:
            by_template.setdefault(template, []).append(
                (doc_id, sec_num, article_num)
            )

        profiles: list[TemplateConditionedProfile] = []
        for template, tpl_sections in by_template.items():
            article_nums = [a for _, _, a in tpl_sections]
            avg_article = statistics.mean(article_nums) if article_nums else 0.0

            # Heading distribution (section_number as proxy)
            heading_dist: Counter[str] = Counter()
            for _, sec_num, _ in tpl_sections:
                heading_dist[sec_num] += 1

            # Aggregate features
            feat_accum: dict[str, list[float]] = {}
            for doc_id, sec_num, _ in tpl_sections:
                feats = section_features.get((doc_id, sec_num), {})
                for k, v in feats.items():
                    feat_accum.setdefault(k, []).append(v)

            feat_means = {
                k: round(statistics.mean(vals), 4)
                for k, vals in feat_accum.items()
                if vals
            }

            profiles.append(TemplateConditionedProfile(
                family=fam,
                template_family=template,
                section_count=len(tpl_sections),
                avg_article_num=round(avg_article, 2),
                heading_distribution=dict(heading_dist.most_common()),
                feature_means=feat_means,
            ))

        profiles.sort(key=lambda p: -p.section_count)
        result[fam] = profiles

    return result


def compute_template_conditioned_profiles_with_headings(
    family_sections_with_template: dict[
        str, list[tuple[str, str, int, str, str]]
    ],
    section_features: dict[tuple[str, str], dict[str, float]],
) -> dict[str, list[TemplateConditionedProfile]]:
    """Compute per-(family, template) profiles using actual heading text.

    Args:
        family_sections_with_template:
            family_id → [(doc_id, section_number, article_num, template_family, heading), ...]
        section_features:
            (doc_id, section_number) → {feature_name: value, ...}

    Returns:
        family_id → list of TemplateConditionedProfile, sorted by section_count desc.
    """
    result: dict[str, list[TemplateConditionedProfile]] = {}

    for fam, sections in family_sections_with_template.items():
        by_template: dict[str, list[tuple[str, str, int, str]]] = {}
        for doc_id, sec_num, article_num, template, heading in sections:
            by_template.setdefault(template, []).append(
                (doc_id, sec_num, article_num, heading)
            )

        profiles: list[TemplateConditionedProfile] = []
        for template, tpl_sections in by_template.items():
            article_nums = [a for _, _, a, _ in tpl_sections]
            avg_article = statistics.mean(article_nums) if article_nums else 0.0

            heading_dist: Counter[str] = Counter()
            for _, _, _, heading in tpl_sections:
                normalized = " ".join(heading.lower().split())
                heading_dist[normalized] += 1

            feat_accum: dict[str, list[float]] = {}
            for doc_id, sec_num, _, _ in tpl_sections:
                feats = section_features.get((doc_id, sec_num), {})
                for k, v in feats.items():
                    feat_accum.setdefault(k, []).append(v)

            feat_means = {
                k: round(statistics.mean(vals), 4)
                for k, vals in feat_accum.items()
                if vals
            }

            profiles.append(TemplateConditionedProfile(
                family=fam,
                template_family=template,
                section_count=len(tpl_sections),
                avg_article_num=round(avg_article, 2),
                heading_distribution=dict(heading_dist.most_common()),
                feature_means=feat_means,
            ))

        profiles.sort(key=lambda p: -p.section_count)
        result[fam] = profiles

    return result


# ---------------------------------------------------------------------------
# E1.6 — Section Clustering
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class ClusterResult:
    """PCA + KMeans clustering result for a family's sections."""

    n_clusters: int
    labels: tuple[int, ...]
    silhouette_score: float
    pca_explained_variance: tuple[float, ...]
    pca_loadings: tuple[tuple[float, ...], ...]  # component × feature
    feature_names: tuple[str, ...]
    cluster_summaries: tuple[dict[str, float], ...]  # per-cluster mean features


def cluster_family_sections(
    feature_matrix: list[dict[str, float]],
    *,
    max_clusters: int = 8,
    pca_components: int = 3,
) -> ClusterResult | None:
    """Cluster family sections using StandardScaler → PCA → KMeans.

    Uses scikit-learn. Returns None if clustering fails or insufficient data.

    Args:
        feature_matrix: Per-section feature dicts (same keys across all).
        max_clusters: Maximum k to try.
        pca_components: Number of PCA components.

    Returns:
        ClusterResult with best-k clustering, or None on failure.
    """
    try:
        import numpy as np
        from sklearn.cluster import KMeans
        from sklearn.decomposition import PCA
        from sklearn.metrics import silhouette_score as sk_silhouette
        from sklearn.preprocessing import StandardScaler
    except ImportError:
        return None

    if len(feature_matrix) < 6:
        return None

    # Build numeric matrix
    all_keys = sorted({k for fv in feature_matrix for k in fv})
    if not all_keys:
        return None

    X_raw = np.array([
        [fv.get(k, 0.0) for k in all_keys]
        for fv in feature_matrix
    ])

    # StandardScaler
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X_raw)

    # PCA
    n_components = min(pca_components, X_scaled.shape[1], X_scaled.shape[0] - 1)
    if n_components < 1:
        return None

    pca = PCA(n_components=n_components)
    X_pca = pca.fit_transform(X_scaled)

    # KMeans: try k=2..max_clusters, pick best silhouette
    max_k = min(max_clusters, len(feature_matrix) - 1)
    if max_k < 2:
        return None

    best_k = 2
    best_score = -1.0
    best_labels: Any = None

    for k in range(2, max_k + 1):
        km = KMeans(n_clusters=k, n_init="auto", random_state=42)
        labels = km.fit_predict(X_pca)
        if len(set(labels)) < 2:
            continue
        score = float(sk_silhouette(X_pca, labels))
        if score > best_score:
            best_score = score
            best_k = k
            best_labels = labels

    if best_labels is None:
        return None

    # Per-cluster summaries
    cluster_summaries: list[dict[str, float]] = []
    for c in range(best_k):
        mask = best_labels == c
        if not np.any(mask):
            cluster_summaries.append({"size": 0.0})
            continue
        cluster_data = X_raw[mask]
        summary: dict[str, float] = {"size": float(np.sum(mask))}
        for j, key in enumerate(all_keys):
            summary[key] = round(float(np.mean(cluster_data[:, j])), 4)
        cluster_summaries.append(summary)

    # PCA loadings (which original features drive each component)
    loadings = pca.components_  # shape: (n_components, n_features)

    return ClusterResult(
        n_clusters=best_k,
        labels=tuple(int(v) for v in best_labels),
        silhouette_score=round(best_score, 4),
        pca_explained_variance=tuple(
            round(float(v), 4) for v in pca.explained_variance_ratio_
        ),
        pca_loadings=tuple(
            tuple(round(float(w), 4) for w in row) for row in loadings
        ),
        feature_names=tuple(all_keys),
        cluster_summaries=tuple(cluster_summaries),
    )


# ---------------------------------------------------------------------------
# Family notes helpers
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class FamilyNotes:
    """Domain-expert guidance for a single family from ontology_family_notes.json."""

    family_id: str
    status: str                              # active, defer_discussion, removed, skip
    location_guidance: str
    primary_location: str
    co_examine: tuple[str, ...]
    structural_variants: tuple[str, ...]
    definition_variants: tuple[str, ...]
    notes: str
    absorbs: tuple[str, ...]
    reparented_under: str


def parse_family_notes(raw: dict[str, Any]) -> dict[str, FamilyNotes]:
    """Parse ontology_family_notes.json into typed FamilyNotes per family.

    Filters out metadata keys (starting with '_').
    """
    result: dict[str, FamilyNotes] = {}
    for key, val in raw.items():
        if key.startswith("_") or not isinstance(val, dict):
            continue
        result[key] = FamilyNotes(
            family_id=key,
            status=str(val.get("status", "active")),
            location_guidance=str(val.get("location_guidance", "")),
            primary_location=str(val.get("primary_location", "")),
            co_examine=tuple(val.get("co_examine", [])),
            structural_variants=tuple(val.get("structural_variants", [])),
            definition_variants=tuple(val.get("definition_variants", [])),
            notes=str(val.get("notes", "")),
            absorbs=tuple(val.get("absorbs", [])),
            reparented_under=str(val.get("reparented_under", "")),
        )
    return result


def active_families(notes: dict[str, FamilyNotes]) -> dict[str, FamilyNotes]:
    """Return only families with status 'active'."""
    return {k: v for k, v in notes.items() if v.status == "active"}
