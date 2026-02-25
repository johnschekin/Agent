"""Section embedding generation + centroid management for semantic similarity.

Provides embedding generation (via API or local model), centroid computation
from active links, and similarity search. Used by the ``semantic_similarity``
factor in ``link_confidence.py`` and by the Coverage Gaps panel for suggesting
candidate sections.

Design:
- ``EmbeddingModel`` is the abstract interface (API-backed and local variants)
- ``EmbeddingManager`` orchestrates batch embedding, centroid updates, and
  similarity queries using a ``LinkStore`` backend
- All vectors are stored as ``bytes`` (little-endian float32 arrays)
- Graceful degradation: when no model is configured, all methods return None
  or empty results — callers must handle the ``None`` case
"""
from __future__ import annotations

import hashlib
import json
import math
import struct
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

# orjson with stdlib fallback
_orjson: Any
try:
    import orjson  # type: ignore[import-untyped]
    _orjson = orjson
except ImportError:
    _orjson = None


def _json_dumps(obj: Any) -> str:
    if _orjson is not None:
        return _orjson.dumps(obj).decode("utf-8")
    return json.dumps(obj)


# ---------------------------------------------------------------------------
# Vector utilities
# ---------------------------------------------------------------------------

def floats_to_bytes(floats: list[float]) -> bytes:
    """Serialize a float list to little-endian float32 bytes."""
    return struct.pack(f"<{len(floats)}f", *floats)


def bytes_to_floats(data: bytes) -> list[float]:
    """Deserialize little-endian float32 bytes to a float list."""
    if len(data) == 0:
        raise ValueError("Empty embedding vector")
    if len(data) % 4 != 0:
        raise ValueError(f"Byte length {len(data)} is not a multiple of 4")
    n = len(data) // 4
    return list(struct.unpack(f"<{n}f", data))


def cosine_similarity(a: bytes, b: bytes) -> float:
    """Compute cosine similarity between two float32 byte vectors.

    Returns a value in [-1.0, 1.0]. Raises ValueError for empty or
    mismatched dimensions.
    """
    if len(a) == 0 or len(b) == 0:
        raise ValueError("Empty embedding vector(s)")
    if len(a) != len(b):
        raise ValueError(
            f"Dimension mismatch: {len(a) // 4} vs {len(b) // 4}"
        )

    va = bytes_to_floats(a)
    vb = bytes_to_floats(b)

    dot = sum(x * y for x, y in zip(va, vb, strict=True))
    norm_a = math.sqrt(sum(x * x for x in va))
    norm_b = math.sqrt(sum(x * x for x in vb))

    if norm_a < 1e-10 or norm_b < 1e-10:
        return 0.0

    return dot / (norm_a * norm_b)


def vector_mean(vectors: list[bytes]) -> bytes:
    """Compute the element-wise mean of multiple float32 byte vectors.

    All vectors must have the same dimension. Returns the mean as bytes.
    Raises ValueError if the list is empty or dimensions mismatch.
    """
    if not vectors:
        raise ValueError("Cannot compute mean of empty vector list")

    first_len = len(vectors[0])
    if any(len(v) != first_len for v in vectors):
        raise ValueError("All vectors must have the same dimension")

    dim = first_len // 4
    all_floats = [bytes_to_floats(v) for v in vectors]

    mean = [
        sum(vf[i] for vf in all_floats) / len(all_floats)
        for i in range(dim)
    ]
    return floats_to_bytes(mean)


def l2_normalize(v: bytes) -> bytes:
    """L2-normalize a float32 byte vector. Returns unit-length vector."""
    floats = bytes_to_floats(v)
    norm = math.sqrt(sum(x * x for x in floats))
    if norm < 1e-10:
        return v  # Zero vector stays zero
    normalized = [x / norm for x in floats]
    return floats_to_bytes(normalized)


def text_hash(text: str) -> str:
    """SHA-256 hash of section text for cache invalidation."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Embedding result
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class EmbeddingResult:
    """Result of embedding a single text."""

    text: str
    text_hash: str
    vector: bytes  # float32 little-endian
    model_version: str
    dimensions: int


# ---------------------------------------------------------------------------
# Embedding model interface
# ---------------------------------------------------------------------------

class EmbeddingModel(ABC):
    """Abstract interface for generating text embeddings."""

    @abstractmethod
    def embed(self, texts: list[str]) -> list[bytes]:
        """Generate embeddings for a batch of texts.

        Parameters
        ----------
        texts:
            List of text strings to embed.

        Returns
        -------
        list[bytes]
            One float32 byte vector per input text, all same dimension.
        """

    @abstractmethod
    def model_version(self) -> str:
        """Return the model version string (e.g., 'text-embedding-3-small')."""

    @abstractmethod
    def dimensions(self) -> int:
        """Return the embedding dimension (e.g., 1536)."""


# ---------------------------------------------------------------------------
# Mock model (for tests and offline use)
# ---------------------------------------------------------------------------

class MockEmbeddingModel(EmbeddingModel):
    """Deterministic mock model for testing.

    Generates reproducible embeddings by hashing the input text and
    using the hash bytes as seeds for a simple float sequence.
    """

    def __init__(self, dim: int = 128, version: str = "mock-v1") -> None:
        self._dim = dim
        self._version = version

    def embed(self, texts: list[str]) -> list[bytes]:
        results: list[bytes] = []
        for t in texts:
            h = hashlib.sha256(t.encode("utf-8")).digest()
            # Generate dim floats from hash bytes, cycling if needed
            floats: list[float] = []
            for i in range(self._dim):
                byte_idx = i % len(h)
                # Map byte (0-255) to float (-1, 1)
                floats.append((h[byte_idx] / 127.5) - 1.0)
            # L2-normalize
            norm = math.sqrt(sum(x * x for x in floats))
            if norm > 1e-10:
                floats = [x / norm for x in floats]
            results.append(floats_to_bytes(floats))
        return results

    def model_version(self) -> str:
        return self._version

    def dimensions(self) -> int:
        return self._dim


# ---------------------------------------------------------------------------
# API-backed model (for production use)
# ---------------------------------------------------------------------------

class ApiEmbeddingModel(EmbeddingModel):
    """Embedding model backed by an HTTP API (e.g., OpenAI embeddings).

    Parameters
    ----------
    api_url:
        The embedding API endpoint URL.
    api_key:
        API key for authentication.
    model_name:
        Model identifier (e.g., 'text-embedding-3-small').
    dim:
        Expected embedding dimension.
    batch_size:
        Maximum texts per API call.
    """

    def __init__(
        self,
        *,
        api_url: str = "https://api.openai.com/v1/embeddings",
        api_key: str = "",
        model_name: str = "text-embedding-3-small",
        dim: int = 1536,
        batch_size: int = 100,
    ) -> None:
        self._api_url = api_url
        self._api_key = api_key
        self._model_name = model_name
        self._dim = dim
        self._batch_size = batch_size

    def embed(self, texts: list[str]) -> list[bytes]:
        """Embed texts via API, batching as needed."""
        import urllib.request

        all_vectors: list[bytes] = []
        for i in range(0, len(texts), self._batch_size):
            batch = texts[i:i + self._batch_size]
            payload = _json_dumps({
                "input": batch,
                "model": self._model_name,
            })
            req = urllib.request.Request(
                self._api_url,
                data=payload.encode("utf-8"),
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self._api_key}",
                },
                method="POST",
            )
            with urllib.request.urlopen(req) as resp:
                body = resp.read().decode("utf-8")
                result = json.loads(body)
                for item in sorted(result["data"], key=lambda x: x["index"]):
                    vec = item["embedding"]
                    all_vectors.append(floats_to_bytes(vec))
        return all_vectors

    def model_version(self) -> str:
        return self._model_name

    def dimensions(self) -> int:
        return self._dim


# ---------------------------------------------------------------------------
# Voyage AI model (finance-domain embeddings)
# ---------------------------------------------------------------------------

class VoyageEmbeddingModel(EmbeddingModel):
    """Embedding model backed by the Voyage AI API.

    Defaults to ``voyage-finance-2`` (1024 dims), purpose-built for financial
    text such as credit agreements.  Supports ``input_type`` differentiation
    between *document* embeddings (corpus text) and *query* embeddings (search).

    Parameters
    ----------
    api_key:
        Voyage AI API key.  Falls back to ``VOYAGE_API_KEY`` env var.
    model_name:
        Model identifier (``voyage-finance-2``, ``voyage-3``, etc.).
    dim:
        Expected embedding dimension.
    batch_size:
        Maximum texts per API call (Voyage allows up to 128).
    input_type:
        ``"document"`` for corpus text, ``"query"`` for search queries,
        or ``None`` for raw (no retrieval prompt).
    """

    _API_URL = "https://api.voyageai.com/v1/embeddings"

    def __init__(
        self,
        *,
        api_key: str = "",
        model_name: str = "voyage-finance-2",
        dim: int = 1024,
        batch_size: int = 128,
        input_type: str | None = "document",
    ) -> None:
        import os
        self._api_key = api_key or os.environ.get("VOYAGE_API_KEY", "")
        if not self._api_key:
            raise ValueError(
                "Voyage API key required: pass api_key= or set VOYAGE_API_KEY"
            )
        self._model_name = model_name
        self._dim = dim
        self._batch_size = batch_size
        self._input_type = input_type

    def embed(self, texts: list[str]) -> list[bytes]:
        """Embed texts via Voyage API, batching as needed."""
        import ssl
        import urllib.request

        # Build SSL context — use certifi CA bundle if available (fixes macOS)
        ssl_ctx: ssl.SSLContext | None = None
        try:
            import certifi  # type: ignore[import-untyped]
            ssl_ctx = ssl.create_default_context(cafile=certifi.where())
        except ImportError:
            ssl_ctx = ssl.create_default_context()

        all_vectors: list[bytes] = []
        for i in range(0, len(texts), self._batch_size):
            batch = texts[i:i + self._batch_size]
            body: dict[str, Any] = {
                "input": batch,
                "model": self._model_name,
                "truncation": True,
            }
            if self._input_type is not None:
                body["input_type"] = self._input_type
            payload = _json_dumps(body)
            req = urllib.request.Request(
                self._API_URL,
                data=payload.encode("utf-8"),
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self._api_key}",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, context=ssl_ctx) as resp:
                raw = resp.read().decode("utf-8")
                result = json.loads(raw)
                for item in sorted(result["data"], key=lambda x: x["index"]):
                    vec: list[float] = item["embedding"]
                    all_vectors.append(floats_to_bytes(vec))
        return all_vectors

    def model_version(self) -> str:
        return self._model_name

    def dimensions(self) -> int:
        return self._dim

    def with_input_type(self, input_type: str | None) -> "VoyageEmbeddingModel":
        """Return a copy with a different input_type (document vs query)."""
        return VoyageEmbeddingModel(
            api_key=self._api_key,
            model_name=self._model_name,
            dim=self._dim,
            batch_size=self._batch_size,
            input_type=input_type,
        )


# ---------------------------------------------------------------------------
# Embedding manager
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class SimilarSection:
    """A section similar to a query vector, with its similarity score."""

    doc_id: str
    section_number: str
    similarity: float
    text_hash: str


class EmbeddingManager:
    """Orchestrates embedding generation, storage, and retrieval.

    Parameters
    ----------
    model:
        The embedding model to use. If None, all operations gracefully
        degrade (return None or empty lists).
    store:
        The LinkStore for persisting embeddings and centroids.
        If None, embeddings are computed but not persisted.
    """

    def __init__(
        self,
        model: EmbeddingModel | None = None,
        store: Any = None,
    ) -> None:
        self._model = model
        self._store = store

    @property
    def available(self) -> bool:
        """Whether an embedding model is configured."""
        return self._model is not None

    @property
    def model_version(self) -> str:
        """The model version string, or 'none' if unavailable."""
        if self._model is None:
            return "none"
        return self._model.model_version()

    @property
    def dimensions(self) -> int:
        """The embedding dimension, or 0 if unavailable."""
        if self._model is None:
            return 0
        return self._model.dimensions()

    # ─── Embedding generation ─────────────────────────────────────

    def embed_texts(self, texts: list[str]) -> list[EmbeddingResult] | None:
        """Generate embeddings for a list of texts.

        Returns None if no model is configured.
        """
        if self._model is None:
            return None

        try:
            vectors = self._model.embed(texts)
        except Exception:
            return None

        results: list[EmbeddingResult] = []
        mv = self._model.model_version()
        dim = self._model.dimensions()
        try:
            for t, v in zip(texts, vectors, strict=True):
                results.append(EmbeddingResult(
                    text=t,
                    text_hash=text_hash(t),
                    vector=v,
                    model_version=mv,
                    dimensions=dim,
                ))
        except Exception:
            return None
        return results

    def embed_and_store(
        self,
        sections: list[dict[str, str]],
    ) -> int:
        """Embed sections and persist to the store.

        Parameters
        ----------
        sections:
            List of dicts with keys: ``doc_id``, ``section_number``, ``text``.

        Returns
        -------
        int
            Number of embeddings stored. Returns 0 if no model or store.
        """
        if self._model is None or self._store is None:
            return 0

        texts = [s["text"] for s in sections]
        results = self.embed_texts(texts)
        if results is None:
            return 0

        embeddings: list[dict[str, Any]] = []
        for section, result in zip(sections, results, strict=True):
            embeddings.append({
                "doc_id": section["doc_id"],
                "section_number": section["section_number"],
                "embedding_vector": result.vector,
                "model_version": result.model_version,
                "text_hash": result.text_hash,
            })

        return self._store.save_section_embeddings(embeddings)

    # ─── Retrieval ───────────────────────────────────────────────

    def get_section_embedding(
        self, doc_id: str, section_number: str,
    ) -> bytes | None:
        """Retrieve a stored section embedding.

        Returns None if not found or no store configured.
        """
        if self._store is None or self._model is None:
            return None
        return self._store.get_section_embedding(
            doc_id, section_number, self._model.model_version(),
        )

    # ─── Centroid computation ────────────────────────────────────

    def compute_centroid(
        self,
        family_id: str,
        active_link_sections: list[dict[str, str]],
        *,
        template_family: str = "_global",
    ) -> bytes | None:
        """Compute and store a family centroid from active link sections.

        Parameters
        ----------
        family_id:
            The family to compute the centroid for.
        active_link_sections:
            List of dicts with ``doc_id`` and ``section_number`` for active links.
        template_family:
            Template family scope (default ``_global``).

        Returns
        -------
        bytes | None
            The centroid vector, or None if no embeddings available.
        """
        if self._model is None:
            return None

        mv = self._model.model_version()
        vectors: list[bytes] = []

        for section in active_link_sections:
            emb: bytes | None = None
            if self._store is not None:
                emb = self._store.get_section_embedding(
                    section["doc_id"], section["section_number"], mv,
                )
            if emb is not None:
                vectors.append(emb)

        if not vectors:
            return None

        centroid = vector_mean(vectors)
        centroid = l2_normalize(centroid)

        if self._store is not None:
            self._store.save_family_centroid(
                family_id, template_family, centroid, mv, len(vectors),
            )

        return centroid

    def get_family_centroid(
        self, family_id: str, template_family: str = "_global",
    ) -> bytes | None:
        """Retrieve a stored family centroid.

        Returns None if not found or no store/model configured.
        """
        if self._store is None or self._model is None:
            return None
        return self._store.get_family_centroid(
            family_id, template_family, self._model.model_version(),
        )

    # ─── Similarity search ───────────────────────────────────────

    def find_similar(
        self,
        query_vector: bytes,
        candidate_embeddings: list[dict[str, Any]],
        *,
        top_k: int = 5,
        min_similarity: float = 0.0,
    ) -> list[SimilarSection]:
        """Find sections most similar to a query vector.

        Parameters
        ----------
        query_vector:
            The query embedding (float32 bytes).
        candidate_embeddings:
            List of dicts with ``doc_id``, ``section_number``,
            ``embedding_vector`` (bytes), ``text_hash``.
        top_k:
            Maximum number of results.
        min_similarity:
            Minimum cosine similarity threshold.

        Returns
        -------
        list[SimilarSection]
            Results sorted by similarity (highest first).
        """
        scored: list[SimilarSection] = []
        for cand in candidate_embeddings:
            try:
                sim = cosine_similarity(query_vector, cand["embedding_vector"])
            except ValueError:
                continue
            if sim >= min_similarity:
                scored.append(SimilarSection(
                    doc_id=cand["doc_id"],
                    section_number=cand["section_number"],
                    similarity=sim,
                    text_hash=cand.get("text_hash", ""),
                ))

        scored.sort(key=lambda s: s.similarity, reverse=True)
        return scored[:top_k]

    def section_similarity(
        self,
        doc_id_a: str, section_a: str,
        doc_id_b: str, section_b: str,
    ) -> float | None:
        """Compute cosine similarity between two stored sections.

        Returns None if either embedding is missing.
        """
        emb_a = self.get_section_embedding(doc_id_a, section_a)
        emb_b = self.get_section_embedding(doc_id_b, section_b)
        if emb_a is None or emb_b is None:
            return None
        return cosine_similarity(emb_a, emb_b)

    # ─── Cache invalidation ──────────────────────────────────────

    def needs_recompute(
        self, current_text: str, stored_hash: str,
    ) -> bool:
        """Check if an embedding needs recomputation due to text change."""
        return text_hash(current_text) != stored_hash

    # ─── Batch statistics ────────────────────────────────────────

    def embedding_coverage(
        self,
        total_sections: int,
        embedded_count: int,
    ) -> dict[str, Any]:
        """Compute embedding coverage statistics.

        Returns a dict with coverage percentage and status.
        """
        if total_sections == 0:
            return {
                "total": 0,
                "embedded": 0,
                "coverage_pct": 0.0,
                "status": "empty",
            }
        pct = (embedded_count / total_sections) * 100.0
        status = "complete" if pct >= 99.9 else "partial" if pct > 0 else "none"
        return {
            "total": total_sections,
            "embedded": embedded_count,
            "coverage_pct": round(pct, 2),
            "status": status,
        }
