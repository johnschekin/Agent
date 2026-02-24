"""Strategy dataclass and versioned persistence.

A Strategy defines how to find a concept in credit agreements — heading patterns,
keywords, DNA phrases, structural hints. Agents create and refine strategies
through iterative corpus testing.

Enriched from VP's ValidatedStrategy + domain expert guidance.
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field, fields
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_orjson: Any
try:
    import orjson
    _orjson = orjson
except ImportError:
    _orjson = None

_VERSION_RE = re.compile(r"_v(\d+)\.json$")
_PROFILE_TYPES = {"family_core", "concept_standard", "concept_advanced"}


def _json_compatible(value: Any) -> Any:
    """Recursively convert dataclass payloads into JSON-compatible types."""
    if isinstance(value, tuple):
        return [_json_compatible(v) for v in value]
    if isinstance(value, list):
        return [_json_compatible(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _json_compatible(v) for k, v in value.items()}
    return value


def _coerce_template_overrides(value: Any) -> dict[str, dict[str, Any]]:
    """Normalize template overrides from legacy/list formats into dict format."""
    out: dict[str, dict[str, Any]] = {}

    def _decode_leaf(raw: Any) -> Any:
        if not isinstance(raw, str):
            return raw
        text = raw.strip()
        if not text:
            return raw
        with_json = None
        try:
            with_json = json.loads(text)
        except json.JSONDecodeError:
            return raw
        return with_json

    def _ensure_group(group: str) -> dict[str, Any]:
        if group not in out:
            out[group] = {}
        return out[group]

    if isinstance(value, dict):
        for group, payload in value.items():
            if not isinstance(group, str):
                continue
            if isinstance(payload, dict):
                out[group] = dict(payload)
            else:
                out[group] = {"value": _decode_leaf(payload)}
        return out

    if isinstance(value, (list, tuple)):
        for item in value:
            if isinstance(item, dict):
                group = item.get("template_family") or item.get("template")
                overrides = item.get("overrides")
                if isinstance(group, str) and isinstance(overrides, dict):
                    _ensure_group(group).update(overrides)
                continue

            if not isinstance(item, (list, tuple)) or len(item) != 2:
                continue
            raw_key, raw_val = item
            if not isinstance(raw_key, str):
                continue

            decoded_val = _decode_leaf(raw_val)
            if "." in raw_key:
                group, field_name = raw_key.split(".", 1)
                if group and field_name:
                    _ensure_group(group)[field_name] = decoded_val
                    continue
            if isinstance(decoded_val, dict):
                _ensure_group(raw_key).update(decoded_val)
            else:
                _ensure_group(raw_key)["value"] = decoded_val
        return out

    return out


def normalize_template_overrides(value: Any) -> dict[str, dict[str, Any]]:
    """Public helper for migrating template override payloads."""
    return _coerce_template_overrides(value)


def _load_json_payload(path: Path) -> dict[str, Any]:
    """Load a strategy JSON payload as a dict."""
    raw = path.read_bytes()
    payload = _orjson.loads(raw) if _orjson is not None else json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError(f"Strategy payload must be a JSON object: {path}")
    return payload


def _strip_private_fields(payload: dict[str, Any]) -> dict[str, Any]:
    """Drop private/internal keys from a strategy payload."""
    return {
        k: v for k, v in payload.items()
        if not (isinstance(k, str) and k.startswith("_"))
    }


def _strategy_version_from_path(path: Path) -> int:
    m = _VERSION_RE.search(path.name)
    if not m:
        return 0
    try:
        return int(m.group(1))
    except ValueError:
        return 0


def _resolve_parent_path(
    reference: str,
    source_path: Path,
    *,
    search_paths: tuple[Path, ...] = (),
) -> Path:
    """Resolve `inherits_from` reference to a concrete strategy file path."""
    ref = reference.strip()
    if not ref:
        raise ValueError(f"Empty inherits_from reference in {source_path}")

    maybe_path = Path(ref)
    if maybe_path.is_absolute():
        return maybe_path.resolve()

    base_dir = source_path.parent
    all_dirs: list[Path] = [base_dir]
    for p in search_paths:
        rp = p.resolve()
        if rp not in all_dirs:
            all_dirs.append(rp)

    if maybe_path.suffix == ".json" or "/" in ref or "\\" in ref or ref.startswith("."):
        candidate = (base_dir / maybe_path).resolve()
        if candidate.exists():
            return candidate
        for directory in all_dirs[1:]:
            alt = (directory / maybe_path).resolve()
            if alt.exists():
                return alt
        return candidate

    # Treat as concept id / stem and pick latest version in directory.
    candidates: list[Path] = []
    for directory in all_dirs:
        candidates.extend(directory.glob(f"{ref}_v*.json"))
    candidates = sorted(
        candidates,
        key=lambda p: (_strategy_version_from_path(p), p.name),
    )
    if candidates:
        return candidates[-1].resolve()
    for directory in all_dirs:
        direct = (directory / f"{ref}.json").resolve()
        if direct.exists():
            return direct
    return (base_dir / ref).resolve()


def resolve_strategy_dict(
    payload: dict[str, Any],
    *,
    source_path: Path,
    search_paths: tuple[Path, ...] = (),
    _visited: set[Path] | None = None,
) -> dict[str, Any]:
    """Resolve parent inheritance (`inherits_from`) for a strategy payload.

    Rules:
    - Parent values are inherited when child omits a field.
    - Child values override parent values when present (including explicit null/empty).
    - Private keys (`_meta`, `_resolved`, etc.) are ignored during resolution.
    - `inherits_from` may be:
      - relative/absolute file path
      - concept id / stem (resolved to latest `{concept}_v*.json` in same directory)
    """
    visited = set() if _visited is None else set(_visited)
    src = source_path.resolve()
    if src in visited:
        raise ValueError(f"Inheritance cycle detected at {src}")
    visited.add(src)

    child = _strip_private_fields(dict(payload))
    ref = child.get("inherits_from")
    if not isinstance(ref, str) or not ref.strip():
        return child

    parent_path = _resolve_parent_path(
        ref,
        src,
        search_paths=search_paths,
    )
    if not parent_path.exists():
        raise FileNotFoundError(
            f"inherits_from target not found for {src}: {parent_path}"
        )

    parent_payload = _load_json_payload(parent_path)
    parent_resolved = resolve_strategy_dict(
        parent_payload,
        source_path=parent_path,
        search_paths=search_paths,
        _visited=visited,
    )
    merged: dict[str, Any] = dict(parent_resolved)
    merged.update(child)
    return merged


def load_strategy_with_views(path: Path) -> tuple[Strategy, dict[str, Any], dict[str, Any]]:
    """Load a strategy and return `(resolved_strategy, raw_payload, resolved_payload)`."""
    raw_payload = _load_json_payload(path)
    resolved_payload = resolve_strategy_dict(raw_payload, source_path=path)
    return strategy_from_dict(resolved_payload), raw_payload, resolved_payload


@dataclass(frozen=True, slots=True)
class Strategy:
    """Search strategy for a concept — what agents create and refine."""

    # Identity
    concept_id: str                              # "debt_capacity.indebtedness.general_basket"
    concept_name: str                            # "General Debt Basket"
    family: str                                  # "indebtedness"

    # Core search vocabulary (3-tier keyword architecture)
    heading_patterns: tuple[str, ...]            # Section heading patterns
    keyword_anchors: tuple[str, ...]             # Global keywords across all documents

    # Strategy profile + inheritance
    profile_type: str = "concept_standard"       # family_core|concept_standard|concept_advanced
    inherits_from: str | None = None             # Parent strategy path or concept-id stem
    keyword_anchors_section_only: tuple[str, ...] = ()  # Keywords only meaningful within section
    concept_specific_keywords: tuple[str, ...] = ()     # Highly targeted keywords

    # DNA phrases (discovered statistically, tiered by confidence)
    dna_tier1: tuple[str, ...] = ()              # High-confidence distinctive phrases
    dna_tier2: tuple[str, ...] = ()              # Secondary distinctive phrases
    dna_negative_tier1: tuple[str, ...] = ()     # High-confidence anti-signals
    dna_negative_tier2: tuple[str, ...] = ()     # Secondary anti-signals

    # Domain knowledge
    defined_term_dependencies: tuple[str, ...] = ()  # Required defined terms
    concept_notes: tuple[str, ...] = ()              # Research notes, edge cases
    fallback_escalation: str | None = None           # What to try when primary search fails
    xref_follow: tuple[str, ...] = ()                # Cross-reference guidance

    # Structural location (from domain expert)
    primary_articles: tuple[int, ...] = ()       # Expected article numbers (e.g., (6, 7))
    primary_sections: tuple[str, ...] = ()       # Expected section patterns (e.g., ("7.01",))
    definitions_article: int | None = None       # Where definitions live (usually 1)

    # Universal precision controls (concept-agnostic)
    negative_heading_patterns: tuple[str, ...] = ()
    negative_keyword_patterns: tuple[str, ...] = ()
    min_score_by_method: dict[str, float] = field(default_factory=dict)
    min_score_margin: float = 0.0
    min_signal_channels: int = 1
    channel_requirements: dict[str, Any] = field(default_factory=dict)
    section_shape_bounds: dict[str, float] = field(default_factory=dict)
    heading_quality_policy: dict[str, Any] = field(default_factory=dict)
    outlier_policy: dict[str, Any] = field(default_factory=dict)
    template_stability_policy: dict[str, Any] = field(default_factory=dict)
    acceptance_policy_version: str = "v1"

    # Canonical heading + functional-area normalization
    canonical_heading_labels: tuple[str, ...] = ()
    functional_area_hints: tuple[str, ...] = ()

    # Definition-shape controls
    definition_type_allowlist: tuple[str, ...] = ()
    definition_type_blocklist: tuple[str, ...] = ()
    min_definition_dependency_overlap: float = 0.0

    # Scope/parity controls
    scope_parity_allow: tuple[str, ...] = ()
    scope_parity_block: tuple[str, ...] = ()
    boolean_operator_requirements: dict[str, Any] = field(default_factory=dict)

    # Preemption/override controls
    preemption_requirements: dict[str, Any] = field(default_factory=dict)
    max_preemption_depth: int | None = None

    # Template/structure controls
    template_module_constraints: dict[str, Any] = field(default_factory=dict)
    structural_fingerprint_allowlist: tuple[str, ...] = ()
    structural_fingerprint_blocklist: tuple[str, ...] = ()

    # Confidence controls (runtime + evaluation parity)
    confidence_policy: dict[str, Any] = field(default_factory=dict)
    confidence_components_min: dict[str, float] = field(default_factory=dict)
    did_not_find_policy: dict[str, Any] = field(default_factory=dict)

    # Corpus validation metrics (filled after testing)
    heading_hit_rate: float = 0.0
    keyword_precision: float = 0.0
    corpus_prevalence: float = 0.0
    cohort_coverage: float = 0.0
    dna_phrase_count: int = 0

    # QC indicators
    dropped_headings: tuple[str, ...] = ()       # Headings that failed validation
    false_positive_keywords: tuple[str, ...] = ()  # Low-precision keywords

    # Template-specific overrides (discovered during refinement)
    template_overrides: dict[str, dict[str, Any]] = field(default_factory=dict)
    # Example: {"cahill": {"heading_patterns": ["Limitation on Debt"]}}

    # Provenance
    validation_status: str = "bootstrap"         # bootstrap -> corpus_validated -> production
    version: int = 1
    last_updated: str = ""
    update_notes: tuple[str, ...] = ()


def strategy_to_dict(s: Strategy) -> dict[str, Any]:
    """Convert a Strategy to a JSON-serializable dict."""
    return _json_compatible(asdict(s))


def strategy_from_dict(d: dict[str, Any]) -> Strategy:
    """Create a Strategy from a dict (e.g., loaded from JSON)."""
    strategy_fields = fields(Strategy)
    valid_fields = {f.name for f in strategy_fields}
    tuple_fields = {
        f.name for f in strategy_fields
        if str(f.type).startswith("tuple[")
    }

    # Convert lists to tuples for frozen dataclass
    converted: dict[str, Any] = {}
    for key, val in d.items():
        if key not in valid_fields:
            continue
        if key == "template_overrides":
            converted[key] = _coerce_template_overrides(val)
            continue
        if key == "profile_type":
            profile = str(val).strip().lower() if val is not None else ""
            converted[key] = profile if profile in _PROFILE_TYPES else "concept_standard"
            continue
        if key == "inherits_from":
            converted[key] = str(val).strip() if isinstance(val, str) and val.strip() else None
            continue
        if key in tuple_fields and isinstance(val, list):
            converted[key] = tuple(val)
        else:
            converted[key] = val
    return Strategy(**converted)


def load_strategy(path: Path, *, resolve_inheritance: bool = True) -> Strategy:
    """Load a Strategy from a JSON file.

    By default, resolves `inherits_from` links before constructing the dataclass.
    """
    payload = _load_json_payload(path)
    if resolve_inheritance:
        payload = resolve_strategy_dict(payload, source_path=path)
    else:
        payload = _strip_private_fields(payload)
    return strategy_from_dict(payload)


def save_strategy(s: Strategy, path: Path) -> None:
    """Save a Strategy to a JSON file."""
    d = strategy_to_dict(s)
    path.parent.mkdir(parents=True, exist_ok=True)
    if _orjson is not None:
        path.write_bytes(_orjson.dumps(d, option=_orjson.OPT_INDENT_2 | _orjson.OPT_SORT_KEYS))
    else:
        with open(path, "w") as f:
            json.dump(d, f, indent=2, sort_keys=True)


def next_version(s: Strategy, *, note: str = "") -> Strategy:
    """Create a new version of a strategy with incremented version number."""
    d = strategy_to_dict(s)
    notes = list(s.update_notes)
    if note:
        notes.append(note)
    d["version"] = s.version + 1
    d["last_updated"] = datetime.now(UTC).isoformat()
    d["update_notes"] = notes
    return strategy_from_dict(d)


def merge_strategies(base: Strategy, update: dict[str, Any]) -> Strategy:
    """Merge updates into a base strategy, preserving unspecified fields.

    Args:
        base: The current strategy.
        update: Dict of fields to update (only specified fields change).

    Returns:
        New Strategy with merged fields.
    """
    d = strategy_to_dict(base)
    for key, val in update.items():
        if key in d:
            d[key] = val
    return strategy_from_dict(d)
