"""Core types for the parsing infrastructure.

Every layer in the pipeline shares these types. All span coordinates use
global char offsets (never section-relative). All dataclasses use
slots=True for memory efficiency.

Type hierarchy:
  SpanRef          — Universal span coordinate (the single currency)
  ArtifactMeta     — Content-addressed lineage metadata
  Ok[T] / Err[E]   — Strict algebraic Result type
  EvidenceItem     — Structured evidence signal
  CandidateSpan    — Document region that MAY contain relevant content
  CandidateCluster — Group of overlapping spans from different source types
  OutlineSection   — Section in a CA document
  OutlineArticle   — Article containing sections
  XrefSpan         — Resolved cross-reference with precise span
  XrefResolutionError — Typed failure for xref resolution
  ParsedXref       — Structured parse of a cross-reference string
  XrefEdge         — Directed edge in the per-document xref graph
  RetrievalPolicy  — Per-family retrieval configuration (loaded from JSON)

Ported from vantage_platform l0/_parsing_types.py — full version.
Only adaptation: FamilyConfig.from_dir() stub (Agent does not yet have
l2._config_loader; will be wired when L2 is ported).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path

import orjson

# ---------------------------------------------------------------------------
# Result ADT — strict Ok/Err, NOT tuple hack
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class Ok[T]:
    """Success case of Result[T, E].

    Usage::

        result: Result[XrefSpan, XrefResolutionError] = Ok(span)
        match result:
            case Ok(value=v): print(v)
            case Err(error=e): print(e.reason)
    """
    value: T


@dataclass(frozen=True, slots=True)
class Err[E]:
    """Failure case of Result[T, E].

    Preserves the typed failure reason — None erases why something failed.
    In legal text, a dangling cross-reference (pointing to a deleted section)
    is a valuable semantic signal, not a silent None.
    """
    error: E


# Result type alias — properly parameterized (C6).
# Usage: ``x: Result[XrefSpan, XrefResolutionError] = Ok(span)``
type Result[T, E] = Ok[T] | Err[E]


# ---------------------------------------------------------------------------
# SpanRef — Universal span coordinate
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class SpanRef:
    """Universal span coordinate — the single currency of the entire pipeline.

    Every component that points at text uses SpanRef. This eliminates the #1
    source of bugs in extraction pipelines: losing track of coordinate systems.

    Offsets are ALWAYS global (char positions in the full normalized text),
    never section-relative.

    Invariants (enforced in __post_init__):
        - start_global >= 0
        - end_global >= start_global
    """
    doc_id: str            # Stable document identifier (ca_file)
    text_version: str      # doc_fingerprint (SHA256 of normalized text)
    start_global: int      # Char offset (inclusive) in normalized text
    end_global: int        # Char offset (exclusive)
    layer: str             # "normalized_doc" | "section" | "candidate_span" | "clause_node" | "labeled_clause" | "node_extraction"
    parent_span_id: str    # ID of containing span ("" if top-level)
    provenance: str        # Source + evidence: "outline:article_7", "xref:Section_2.14(d)"
    score: float           # Retrieval confidence (1.0 for structural, 0.0-1.0 for candidates)

    def __post_init__(self) -> None:
        """Validate structural invariants at construction time."""
        if self.start_global < 0:
            raise ValueError(
                f"SpanRef.start_global must be >= 0, got {self.start_global}"
            )
        if self.end_global < self.start_global:
            raise ValueError(
                f"SpanRef.end_global ({self.end_global}) must be >= "
                f"start_global ({self.start_global})"
            )


# ---------------------------------------------------------------------------
# ArtifactMeta — Content-addressed lineage metadata
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class ArtifactMeta:
    """Content-addressed lineage metadata for every persisted artifact.

    The artifact_id is a true content address: SHA256 of all inputs joined
    with null-byte delimiters. Re-running the same parser on the same doc
    with the same config produces the same ID (idempotent). Any input change
    produces a new ID.
    """
    artifact_id: str           # Content-addressed (computed by compute_artifact_id)
    ca_file: str               # Source document
    layer: str                 # "outline" | "candidate_spans" | "clause_tree" | "labeled_clauses" | "node_spans"
    parser_version: str        # Semantic version of the parsing module
    config_hash: str           # SHA256 of config file contents
    doc_fingerprint: str       # SHA256 of normalized text
    span_identity: str         # For span-level: "section_2.14:4500:8200"; "" for doc-level
    git_commit: str            # HEAD commit at generation time
    parent_artifact_ids: list[str] = field(default_factory=list[str])  # Lineage
    generated_at: str = ""     # ISO timestamp


def compute_artifact_id(
    doc_fingerprint: str,
    layer: str,
    parser_version: str,
    config_hash: str,
    span_identity: str,
    parent_artifact_ids: list[str] | None = None,
) -> str:
    """Compute content-addressed artifact ID.

    Uses null-byte delimited concatenation to prevent collision boundary
    attacks (naive "A"+"BC" == "AB"+"C"). All inputs are joined with \\x00
    which cannot appear in any field value.
    """
    parts = [
        doc_fingerprint,
        layer,
        parser_version,
        config_hash,
        span_identity,
        *sorted(parent_artifact_ids or []),
    ]
    payload = b"\x00".join(p.encode() for p in parts)
    return hashlib.sha256(payload).hexdigest()


def compute_doc_fingerprint(text: str) -> str:
    """SHA256 fingerprint of normalized document text."""
    return hashlib.sha256(text.encode()).hexdigest()


def compute_config_hash(config_path: Path) -> str:
    """SHA256 of config file contents (not just semver — catches any edit)."""
    return hashlib.sha256(config_path.read_bytes()).hexdigest()


# ---------------------------------------------------------------------------
# EvidenceItem — Structured evidence signal
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class EvidenceItem:
    """Structured evidence signal — NOT a concatenated string.

    String concatenation for metadata ("DNA:may_at_any_time;marker:incremental")
    is a cardinal sin in structured data engineering — it breaks queryability.
    In Parquet, stored as Arrow ListArray of structs.
    """
    signal_type: str    # "dna" | "marker" | "label_match" | "xref_intent" | "heading"
    signal_value: str   # "may_at_any_time" | "incremental" | "Incremental Commitments"
    weight: float       # Contribution to retrieval_score (0.0-1.0)
    char_offset: int    # Where in the span this signal was found (-1 if N/A)


# ---------------------------------------------------------------------------
# Outline types — Document structure
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class OutlineSection:
    """A section in the document outline (e.g., Section 7.02)."""
    number: str         # "7.02"
    heading: str        # "Indebtedness"
    char_start: int
    char_end: int
    article_num: int
    word_count: int


@dataclass(frozen=True, slots=True)
class OutlineArticle:
    """An article containing sections (e.g., ARTICLE VII)."""
    num: int
    label: str          # "VII" or "7"
    title: str
    concept: str | None
    char_start: int
    char_end: int
    sections: tuple[OutlineSection, ...]
    is_synthetic: bool = False


# ---------------------------------------------------------------------------
# Xref types — Cross-reference resolution
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class XrefResolutionError:
    """Typed failure for xref resolution. None erases the reason; this preserves it."""
    reason: str  # "target_not_found" | "path_invalid" | "cycle_detected" | "budget_exceeded"
    raw_ref: str
    attempted_path: str  # What we tried to resolve


@dataclass(frozen=True, slots=True)
class XrefSpan:
    """Resolved cross-reference with precise span.

    NOTE: No 'text' field. Consistent with the "no text in Parquet" invariant.
    Text is stored ONCE in doc_texts; consumers use bundle.text_at(span) or
    text[char_start:char_end] to retrieve it.
    """
    section_num: str               # "2.14"
    clause_path: tuple[str, ...]   # ("(d)", "(iv)", "(A)") — empty if section-level only
    char_start: int                # Global offset in full CA text
    char_end: int
    resolution_method: str         # "section_only" | "section+clause_path" | "definition"


@dataclass(frozen=True, slots=True)
class ParsedXref:
    """Structured parse of a cross-reference string.

    Produced by the Lark grammar parser, consumed by DocOutline.resolve_xref().
    """
    section_num: str                # "2.14"
    clause_path: tuple[str, ...]    # ("(d)", "(iv)", "(A)", "(1)") — unbounded depth
    ref_type: str                   # "single" | "conjunction" | "range" | "conditional"


@dataclass(frozen=True, slots=True)
class XrefEdge:
    """Directed edge in the per-document xref graph."""
    src_section: str                          # "2.14"
    dst_section: str                          # "7.11"
    ref_type: str                             # "section" | "definition" | "exhibit" | "schedule"
    xref_intent: str                          # "incorporation" | "condition" | "exception" | "definition" | "amendment" | "other"
    raw_ref_text: str                         # The original text that produced this edge
    parsed_xrefs: tuple[ParsedXref, ...] = ()


# ---------------------------------------------------------------------------
# ClauseNode — AST node for contract clause structure
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class ClauseNode:
    """A node in the clause tree AST.

    Every validity constraint is scored as a flag/float per node.
    Low-signal nodes get ``is_structural_candidate=False`` + a demotion_reason
    but are KEPT in the tree. Downstream consumers can filter on
    ``is_structural_candidate`` or use their own threshold.

    Nodes are NEVER deleted from the tree — "we saw it, we demoted it."
    """
    id: str              # Path-style: "a", "a.i", "a.i.A", "a.i.A.1"
    label: str           # Raw: "(a)", "(i)", "(A)", "(1)"
    depth: int           # 0=root, 1=alpha, 2=roman, 3=caps, 4=numeric
    level_type: str      # "alpha" | "roman" | "caps" | "numeric" | "root"
    span_start: int      # char offset (inclusive) — ALWAYS global
    span_end: int        # char offset (exclusive)
    header_text: str     # first ~80 chars after label
    parent_id: str       # "" for root children
    children_ids: tuple[str, ...]
    # Per-constraint confidence flags
    anchor_ok: bool                # Enumerator at line start or after hard boundary
    run_length_ok: bool            # Level has >=2 sequential siblings
    gap_ok: bool                   # No ordinal skip >5 at this level
    indentation_score: float       # 0.0-1.0 (deeper = higher)
    xref_suspected: bool           # Pattern resembles inline cross-ref
    # Aggregate confidence
    is_structural_candidate: bool  # True=high-confidence structural
    parse_confidence: float        # 0.0-1.0: weighted combination of flags
    demotion_reason: str           # "" if structural, else: "singleton", "gap_too_large", "weak_anchor", "xref_false_positive"


# ---------------------------------------------------------------------------
# CandidateSpan — Document region for retrieval
# ---------------------------------------------------------------------------

# Source types ordered by typical retrieval_score:
SOURCE_TYPE_PRIMARY = "primary_section"    # Score: 0.8-1.0
SOURCE_TYPE_XREF = "xref_target"           # Score: 0.5-0.7
SOURCE_TYPE_DEFINITION = "definition"      # Score: 0.4-0.6
SOURCE_TYPE_NEG_COV = "neg_cov_ref"        # Score: 0.3-0.5
SOURCE_TYPE_DNA = "dna_hit"                # Score: 0.2-0.5
SOURCE_TYPE_PHRASE = "phrase_hit"           # Score: 0.2-0.4
SOURCE_TYPE_AMENDMENT = "amendment"         # Score: 0.2-0.4
SOURCE_TYPE_SECONDARY = "secondary"        # Score: 0.1-0.3

ALL_SOURCE_TYPES = (
    SOURCE_TYPE_PRIMARY, SOURCE_TYPE_XREF, SOURCE_TYPE_DEFINITION,
    SOURCE_TYPE_NEG_COV, SOURCE_TYPE_DNA, SOURCE_TYPE_PHRASE,
    SOURCE_TYPE_AMENDMENT, SOURCE_TYPE_SECONDARY,
)


def _compute_span_id(ca_file: str, family: str, source_type: str,
                     char_start: int, char_end: int) -> str:
    """Stable span ID: SHA256 of identifying fields, truncated to 16 hex chars.

    The 16-hex-char truncation yields 64 bits of entropy. By the birthday
    paradox, the probability of at least one collision among N span IDs is
    approximately N^2 / 2^65.  For N = 100,000 (worst case: 1,198 CAs x
    ~80 spans/CA), P(collision) ~ 10^10 / 3.7x10^19 ~ 2.7x10^-10 — safely
    below any operational threshold.
    """
    payload = f"{ca_file}\x00{family}\x00{source_type}\x00{char_start}\x00{char_end}"
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


@dataclass(slots=True)
class CandidateSpan:
    """First-class artifact: a document region that MAY contain relevant content.

    P2/P3 operate on CandidateSpans — they never see "whatever P1 extracted."

    Invariants (enforced in __post_init__):
        - char_start >= 0
        - char_end > char_start  (spans must have positive length)
        - 0.0 <= retrieval_score <= 1.0
    """
    span_id: str           # Stable ID: SHA256(ca_file + family + source_type + char_start + char_end)
    ca_file: str
    family: str            # "incremental", "indebtedness", etc.
    source_type: str       # One of SOURCE_TYPE_* constants
    source_detail: str     # Human-readable: "Section 7.11(d)(iv)"
    char_start: int
    char_end: int
    retrieval_score: float # 0-1, soft prior (NOT a hard gate)
    evidence: tuple[EvidenceItem, ...] = ()

    def __post_init__(self) -> None:
        """Validate structural invariants at construction time."""
        if self.char_start < 0:
            raise ValueError(
                f"CandidateSpan.char_start must be >= 0, got {self.char_start}"
            )
        if self.char_end <= self.char_start:
            raise ValueError(
                f"CandidateSpan.char_end ({self.char_end}) must be > "
                f"char_start ({self.char_start})"
            )
        if not (0.0 <= self.retrieval_score <= 1.0):
            raise ValueError(
                f"CandidateSpan.retrieval_score must be in [0.0, 1.0], "
                f"got {self.retrieval_score}"
            )

    @staticmethod
    def make_id(ca_file: str, family: str, source_type: str,
                char_start: int, char_end: int) -> str:
        """Compute the stable span_id for given fields."""
        return _compute_span_id(ca_file, family, source_type, char_start, char_end)


def _compute_cluster_id(span_ids: tuple[str, ...]) -> str:
    """Cluster ID: SHA256 of sorted constituent span_ids."""
    payload = "\x00".join(sorted(span_ids))
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


@dataclass(slots=True)
class CandidateCluster:
    """Group of overlapping CandidateSpans from different source_types.

    Preserves exact SpanRef boundaries of each constituent while sharing
    a cluster_id to save P3 extractor compute (process cluster once, not N times).
    Same source_type spans are merged before clustering; different source_type
    spans are grouped into clusters without merging.
    """
    cluster_id: str                    # SHA256 of sorted constituent span_ids
    spans: tuple[CandidateSpan, ...]   # All constituent spans (exact boundaries preserved)
    envelope_start: int                # min(char_start) across all spans
    envelope_end: int                  # max(char_end) across all spans
    best_retrieval_score: float        # max(retrieval_score) across all spans

    @classmethod
    def make(cls, spans: tuple[CandidateSpan, ...]) -> CandidateCluster:
        """Build a cluster from constituent spans, computing ID and envelope."""
        span_ids = tuple(s.span_id for s in spans)
        return cls(
            cluster_id=_compute_cluster_id(span_ids),
            spans=spans,
            envelope_start=min(s.char_start for s in spans),
            envelope_end=max(s.char_end for s in spans),
            best_retrieval_score=max(s.retrieval_score for s in spans),
        )


# ---------------------------------------------------------------------------
# RetrievalPolicy — Per-family retrieval configuration
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class RetrievalPolicy:
    """Per-family retrieval configuration loaded from JSON.

    Keeps the CandidateSpan generator from becoming "49 if-statements in Python."
    Adding a new family means writing a retrieval_policy.json, not modifying code.
    """
    version: str
    family: str
    anchor_terms: list[str]
    defined_terms_to_resolve: list[str]
    source_type_weights: dict[str, tuple[float, float]]  # source_type → (min_score, max_score)
    allowed_xref_intents_to_promote: list[str]
    phrase_weights: dict[str, float]  # phrase → weight
    generic_phrases: list[str]
    co_occurrence_radius_chars: int = 500
    max_k: int = 10
    tier2_enable_threshold: int = 3
    # Extended fields for candidate span generation
    heading_keywords: list[str] = field(default_factory=list[str])
    dna_tiers_tier1: list[str] = field(default_factory=list[str])
    dna_tiers_tier2: list[str] = field(default_factory=list[str])
    neg_cov_articles: list[int] = field(default_factory=lambda: [6, 7])
    definitions_article: int = 1
    min_dna_phrases: int = 2
    min_section_chars: int = 200
    max_section_chars: int = 50000
    xref_hop_penalty: float = 0.1
    xref_max_hops: int = 3
    xref_max_nodes: int = 20
    early_stop_score_sum: float = 3.0

    @classmethod
    def from_json(cls, path: Path) -> RetrievalPolicy:
        """Load from a retrieval_policy.json file."""
        data = orjson.loads(path.read_bytes())
        # Convert source_type_weights lists to tuples
        weights: dict[str, tuple[float, float]] = {}
        for k, v in data.get("source_type_weights", {}).items():
            weights[k] = (float(v[0]), float(v[1]))
        # Extract DNA tiers from nested dict
        dna_tiers = data.get("dna_tiers", {})
        return cls(
            version=data["version"],
            family=data["family"],
            anchor_terms=data.get("anchor_terms", []),
            defined_terms_to_resolve=data.get("defined_terms_to_resolve", []),
            source_type_weights=weights,
            allowed_xref_intents_to_promote=data.get("allowed_xref_intents_to_promote", []),
            phrase_weights=data.get("phrase_weights", {}),
            generic_phrases=data.get("generic_phrases", []),
            co_occurrence_radius_chars=data.get("co_occurrence_radius_chars", 500),
            max_k=data.get("max_k", 10),
            tier2_enable_threshold=data.get("tier2_enable_threshold", 3),
            heading_keywords=data.get("heading_keywords", []),
            dna_tiers_tier1=dna_tiers.get("tier1", []),
            dna_tiers_tier2=dna_tiers.get("tier2", []),
            neg_cov_articles=data.get("neg_cov_articles", [6, 7]),
            definitions_article=data.get("definitions_article", 1),
            min_dna_phrases=data.get("min_dna_phrases", 2),
            min_section_chars=data.get("min_section_chars", 200),
            max_section_chars=data.get("max_section_chars", 50000),
            xref_hop_penalty=data.get("xref_hop_penalty", 0.1),
            xref_max_hops=data.get("xref_max_hops", 3),
            xref_max_nodes=data.get("xref_max_nodes", 20),
            early_stop_score_sum=data.get("early_stop_score_sum", 3.0),
        )


# ---------------------------------------------------------------------------
# Labeler types — Sequence labeling for clause functions
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class FunctionDef:
    """Definition of a single function (clause category) within a family."""
    name: str                         # "authority_and_capacity"
    label_patterns: tuple[str, ...]   # Header label strings for matching
    dna_phrases: tuple[str, ...]      # DNA phrases (family-specific)
    content_markers: tuple[str, ...]  # Content markers (sub-concept signals)
    depth_affinity: tuple[int, ...]   # Which depths this function appears at
    description: str = ""             # Human-readable description


@dataclass(slots=True)
class ParentChildTransition:
    """Parent-conditioned priors for child decoding at a given depth."""
    start_priors: dict[str, float]     # child_label -> log_prob for sequence start
    emission_bias: dict[str, float]    # child_label -> additive emission bias


@dataclass(slots=True)
class TransitionMatrix:
    """Transition probabilities at a single depth level."""
    sibling_transitions: dict[str, dict[str, float]]  # label → {next_label → log_prob}
    start_priors: dict[str, float]                     # label → log_prob for sequence start
    # parent_label -> ParentChildTransition
    parent_child_transitions: dict[str, ParentChildTransition] | None = None


@dataclass(slots=True)
class FamilyConfig:
    """Family-specific labeling configuration loaded from JSON.

    All domain-specific knowledge lives here — the SequenceLabelerCore
    is family-agnostic. Adding a new family = writing a config directory,
    not modifying Python code.
    """
    family: str                                      # "incremental"
    version: str                                     # Config version
    depth_strategy: list[int]                        # [1, 2] — depths to run Viterbi on
    adapter: str                                     # "default" or custom adapter name
    functions: dict[str, FunctionDef]                # function_name → definition
    non_family_functions: list[str]                  # Functions from other families
    transitions: dict[int, TransitionMatrix]         # depth → transition matrix

    @classmethod
    def from_dir(cls, config_dir: Path) -> FamilyConfig:  # noqa: ARG003
        """Load taxonomy.json + transition_priors.json from a config directory.

        NOTE: Requires l2._config_loader which will be ported when the L2
        sequence labeling pipeline is added to Agent. Until then, use
        manual construction or from_dict() patterns.
        """
        raise NotImplementedError(
            "FamilyConfig.from_dir() requires the L2 config loader. "
            "Construct FamilyConfig directly or port l2._config_loader."
        )


@dataclass(slots=True)
class LabeledClause:
    """Result of labeling a single clause node.

    Carries the full label distribution, not just the argmax —
    enables active learning, calibration, and multi-label detection.
    """
    node_id: str
    label: str               # Raw clause label: "(a)", "(i)", etc.
    best_label: str          # Primary function assignment
    confidence: float        # 0-1
    method: str              # "label_match" | "dna_match" | "viterbi" | "inherited"
    # Uncertainty signals
    runner_up_label: str     # Second-best function
    margin: float            # confidence - runner_up_confidence
    entropy: float           # Shannon entropy over label_distribution
    # Multi-label support
    secondary_label: str | None = None  # Non-null when margin < threshold AND runner_up has evidence
    # Provenance
    top_features: tuple[EvidenceItem, ...] = ()  # Signals that fired
    sequence_context: str = ""    # "prev=request_mechanics,next=lender_mechanics"
    # Full distribution (top 5+ at least)
    label_distribution: dict[str, float] = field(default_factory=dict[str, float])


# ---------------------------------------------------------------------------
# DefinitionEntry — Extracted defined term
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class DefinitionEntry:
    """A defined term extracted from the document."""
    term: str
    definition_text: str
    char_start: int
    char_end: int
    section_path: str = ""       # Section where definition appears
    pattern_engine: str = ""     # "quoted" | "smart_quote" | "parenthetical" | "colon" | "unquoted"
    confidence: float = 1.0


# ---------------------------------------------------------------------------
# Inverse Mapping Array (normalized char offset → raw byte offset)
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class InverseMapRun:
    """A single run in the RLE-compressed inverse mapping array.

    Each run represents a contiguous region where normalized offsets map to
    raw offsets with a constant delta (raw_start - norm_start).
    """
    norm_start: int   # Start of run in normalized text
    raw_start: int    # Corresponding start in raw source
    length: int       # Length of this run (in chars)


class InverseMap:
    """RLE-compressed mapping from normalized char offsets → raw byte offsets.

    The normalization pipeline (HTML → text) strips tags, collapses whitespace,
    and inserts newlines at block boundaries. This mapping allows resolving any
    SpanRef back to exact source bytes for UI highlighting and audit trails.

    Storage: serialized as a list of (norm_start, raw_start, length) triples.
    Lookup: O(log N) via binary search on norm_start.

    Usage::

        imap = InverseMap(runs)
        raw_offset = imap.to_raw(normalized_offset)
        raw_start, raw_end = imap.to_raw_range(norm_start, norm_end)
    """
    __slots__ = ("_runs",)

    def __init__(self, runs: list[InverseMapRun]) -> None:
        self._runs = sorted(runs, key=lambda r: r.norm_start)

    @property
    def runs(self) -> list[InverseMapRun]:
        return self._runs

    def to_raw(self, norm_offset: int) -> int:
        """Map a normalized char offset to the raw source byte offset.

        Returns the raw offset. If the normalized offset falls in a gap
        (inserted newlines, collapsed whitespace), returns the raw offset
        of the nearest preceding mapped position.
        """
        if not self._runs:
            return norm_offset  # identity if no mapping

        # Binary search for the run containing norm_offset
        lo, hi = 0, len(self._runs) - 1
        while lo <= hi:
            mid = (lo + hi) // 2
            run = self._runs[mid]
            if norm_offset < run.norm_start:
                hi = mid - 1
            elif norm_offset >= run.norm_start + run.length:
                lo = mid + 1
            else:
                # Inside this run
                delta = norm_offset - run.norm_start
                return run.raw_start + delta

        # Fell between runs — use the closest preceding run's end
        if hi >= 0:
            run = self._runs[hi]
            return run.raw_start + run.length
        return self._runs[0].raw_start

    def to_raw_range(self, norm_start: int, norm_end: int) -> tuple[int, int]:
        """Map a normalized [start, end) range to raw [start, end) range."""
        return self.to_raw(norm_start), self.to_raw(norm_end)

    def serialize(self) -> bytes:
        """Serialize to compact binary format for Parquet storage.

        Format: 3 x uint32 per run (norm_start, raw_start, length).
        Total: 12 bytes per run. Typical CA: ~200-500 runs -> 2.4-6 KB.

        Each field is packed as a little-endian unsigned 32-bit integer,
        supporting offsets up to 2^32 - 1 = 4,294,967,295 chars (~4 GiB).
        The largest EDGAR CA in the corpus is ~2 MB, so this limit is safe
        by three orders of magnitude.
        """
        import struct
        parts: list[bytes] = []
        for run in self._runs:
            parts.append(struct.pack("<III", run.norm_start, run.raw_start, run.length))
        return b"".join(parts)

    @classmethod
    def deserialize(cls, data: bytes) -> InverseMap:
        """Deserialize from compact binary format."""
        import struct
        runs: list[InverseMapRun] = []
        for i in range(0, len(data), 12):
            ns, rs, length = struct.unpack("<III", data[i:i + 12])
            runs.append(InverseMapRun(norm_start=ns, raw_start=rs, length=length))
        return cls(runs)

    def __len__(self) -> int:
        return len(self._runs)

    def __repr__(self) -> str:
        return f"InverseMap({len(self._runs)} runs)"


# ---------------------------------------------------------------------------
# Module version (used in ArtifactMeta.parser_version)
# ---------------------------------------------------------------------------
__version__ = "0.1.0"
