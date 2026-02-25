"""Tests for agent.embeddings — section embedding generation + centroid management."""
from __future__ import annotations

import math
from pathlib import Path

import pytest

from agent.embeddings import (
    ApiEmbeddingModel,
    EmbeddingManager,
    EmbeddingResult,
    MockEmbeddingModel,
    SimilarSection,
    bytes_to_floats,
    cosine_similarity,
    floats_to_bytes,
    l2_normalize,
    text_hash,
    vector_mean,
)
from agent.link_store import LinkStore


# ───────────────────── Fixtures ──────────────────────────────────────


@pytest.fixture()
def mock_model() -> MockEmbeddingModel:
    return MockEmbeddingModel(dim=8, version="mock-v1")


@pytest.fixture()
def store(tmp_path: Path) -> LinkStore:
    db_path = tmp_path / "links.duckdb"
    s = LinkStore(db_path, create_if_missing=True)
    yield s  # type: ignore[misc]
    s.close()


@pytest.fixture()
def manager(mock_model: MockEmbeddingModel, store: LinkStore) -> EmbeddingManager:
    return EmbeddingManager(model=mock_model, store=store)


# ───────────────────── Vector utilities ──────────────────────────────


class TestFloatsToBytes:
    def test_round_trip(self) -> None:
        original = [1.0, -2.5, 0.0, 3.14]
        encoded = floats_to_bytes(original)
        decoded = bytes_to_floats(encoded)
        assert len(decoded) == 4
        for a, b in zip(original, decoded):
            assert abs(a - b) < 1e-6

    def test_empty_list(self) -> None:
        encoded = floats_to_bytes([])
        assert len(encoded) == 0

    def test_single_float(self) -> None:
        encoded = floats_to_bytes([42.0])
        assert len(encoded) == 4
        decoded = bytes_to_floats(encoded)
        assert abs(decoded[0] - 42.0) < 1e-6


class TestBytesToFloats:
    def test_empty_raises(self) -> None:
        with pytest.raises(ValueError, match="Empty"):
            bytes_to_floats(b"")

    def test_bad_length_raises(self) -> None:
        with pytest.raises(ValueError, match="not a multiple of 4"):
            bytes_to_floats(b"\x00\x00\x00")

    def test_correct_dimension(self) -> None:
        data = floats_to_bytes([1.0, 2.0, 3.0])
        floats = bytes_to_floats(data)
        assert len(floats) == 3


class TestCosineSimilarity:
    def test_identical_vectors(self) -> None:
        v = floats_to_bytes([1.0, 2.0, 3.0])
        assert abs(cosine_similarity(v, v) - 1.0) < 1e-6

    def test_opposite_vectors(self) -> None:
        a = floats_to_bytes([1.0, 0.0])
        b = floats_to_bytes([-1.0, 0.0])
        assert abs(cosine_similarity(a, b) - (-1.0)) < 1e-6

    def test_orthogonal_vectors(self) -> None:
        a = floats_to_bytes([1.0, 0.0])
        b = floats_to_bytes([0.0, 1.0])
        assert abs(cosine_similarity(a, b)) < 1e-6

    def test_dimension_mismatch(self) -> None:
        a = floats_to_bytes([1.0, 2.0])
        b = floats_to_bytes([1.0, 2.0, 3.0])
        with pytest.raises(ValueError, match="Dimension mismatch"):
            cosine_similarity(a, b)

    def test_empty_raises(self) -> None:
        with pytest.raises(ValueError, match="Empty"):
            cosine_similarity(b"", b"")

    def test_zero_vector(self) -> None:
        a = floats_to_bytes([0.0, 0.0])
        b = floats_to_bytes([1.0, 0.0])
        assert cosine_similarity(a, b) == 0.0

    def test_known_value(self) -> None:
        a = floats_to_bytes([1.0, 1.0])
        b = floats_to_bytes([1.0, 0.0])
        # cos(45°) = 1/√2 ≈ 0.7071
        assert abs(cosine_similarity(a, b) - (1.0 / math.sqrt(2))) < 1e-5


class TestVectorMean:
    def test_single_vector(self) -> None:
        v = floats_to_bytes([2.0, 4.0, 6.0])
        mean = vector_mean([v])
        floats = bytes_to_floats(mean)
        assert abs(floats[0] - 2.0) < 1e-6
        assert abs(floats[1] - 4.0) < 1e-6

    def test_two_vectors(self) -> None:
        a = floats_to_bytes([1.0, 3.0])
        b = floats_to_bytes([3.0, 1.0])
        mean = vector_mean([a, b])
        floats = bytes_to_floats(mean)
        assert abs(floats[0] - 2.0) < 1e-6
        assert abs(floats[1] - 2.0) < 1e-6

    def test_empty_raises(self) -> None:
        with pytest.raises(ValueError, match="empty"):
            vector_mean([])

    def test_dimension_mismatch_raises(self) -> None:
        a = floats_to_bytes([1.0, 2.0])
        b = floats_to_bytes([1.0, 2.0, 3.0])
        with pytest.raises(ValueError, match="same dimension"):
            vector_mean([a, b])

    def test_many_vectors(self) -> None:
        vecs = [floats_to_bytes([float(i), float(i * 2)]) for i in range(10)]
        mean = vector_mean(vecs)
        floats = bytes_to_floats(mean)
        # Mean of 0..9 = 4.5
        assert abs(floats[0] - 4.5) < 1e-6
        # Mean of 0,2,4,...,18 = 9.0
        assert abs(floats[1] - 9.0) < 1e-6


class TestL2Normalize:
    def test_unit_vector_unchanged(self) -> None:
        v = floats_to_bytes([1.0, 0.0, 0.0])
        n = l2_normalize(v)
        floats = bytes_to_floats(n)
        assert abs(floats[0] - 1.0) < 1e-6
        assert abs(floats[1]) < 1e-6

    def test_normalization(self) -> None:
        v = floats_to_bytes([3.0, 4.0])
        n = l2_normalize(v)
        floats = bytes_to_floats(n)
        norm = math.sqrt(sum(x * x for x in floats))
        assert abs(norm - 1.0) < 1e-6
        assert abs(floats[0] - 0.6) < 1e-6  # 3/5
        assert abs(floats[1] - 0.8) < 1e-6  # 4/5

    def test_zero_vector(self) -> None:
        v = floats_to_bytes([0.0, 0.0])
        n = l2_normalize(v)
        floats = bytes_to_floats(n)
        assert abs(floats[0]) < 1e-6
        assert abs(floats[1]) < 1e-6


class TestTextHash:
    def test_deterministic(self) -> None:
        assert text_hash("hello") == text_hash("hello")

    def test_different_texts(self) -> None:
        assert text_hash("hello") != text_hash("world")

    def test_returns_hex_string(self) -> None:
        h = text_hash("test")
        assert len(h) == 64  # SHA-256 hex
        assert all(c in "0123456789abcdef" for c in h)


# ───────────────────── EmbeddingResult ───────────────────────────────


class TestEmbeddingResult:
    def test_frozen(self) -> None:
        r = EmbeddingResult(
            text="test", text_hash="abc", vector=b"\x00",
            model_version="v1", dimensions=1,
        )
        with pytest.raises(AttributeError):
            r.text = "changed"  # type: ignore[misc]

    def test_fields(self) -> None:
        r = EmbeddingResult(
            text="hello", text_hash="h", vector=floats_to_bytes([1.0]),
            model_version="mock-v1", dimensions=1,
        )
        assert r.text == "hello"
        assert r.dimensions == 1


# ───────────────────── MockEmbeddingModel ────────────────────────────


class TestMockModel:
    def test_embed_single(self, mock_model: MockEmbeddingModel) -> None:
        results = mock_model.embed(["hello world"])
        assert len(results) == 1
        assert len(results[0]) == 8 * 4  # 8 dims * 4 bytes

    def test_embed_batch(self, mock_model: MockEmbeddingModel) -> None:
        results = mock_model.embed(["a", "b", "c"])
        assert len(results) == 3

    def test_deterministic(self, mock_model: MockEmbeddingModel) -> None:
        r1 = mock_model.embed(["test"])
        r2 = mock_model.embed(["test"])
        assert r1[0] == r2[0]

    def test_different_texts_different_vectors(self, mock_model: MockEmbeddingModel) -> None:
        results = mock_model.embed(["hello", "world"])
        assert results[0] != results[1]

    def test_normalized_output(self, mock_model: MockEmbeddingModel) -> None:
        """Mock model produces L2-normalized vectors."""
        results = mock_model.embed(["test"])
        floats = bytes_to_floats(results[0])
        norm = math.sqrt(sum(x * x for x in floats))
        assert abs(norm - 1.0) < 1e-5

    def test_model_version(self, mock_model: MockEmbeddingModel) -> None:
        assert mock_model.model_version() == "mock-v1"

    def test_dimensions(self, mock_model: MockEmbeddingModel) -> None:
        assert mock_model.dimensions() == 8

    def test_custom_dim(self) -> None:
        model = MockEmbeddingModel(dim=256)
        results = model.embed(["test"])
        assert len(results[0]) == 256 * 4


# ───────────────────── ApiEmbeddingModel ─────────────────────────────


class TestApiModel:
    def test_model_version(self) -> None:
        model = ApiEmbeddingModel(model_name="text-embedding-3-large", dim=3072)
        assert model.model_version() == "text-embedding-3-large"
        assert model.dimensions() == 3072

    def test_constructor_defaults(self) -> None:
        model = ApiEmbeddingModel()
        assert model.model_version() == "text-embedding-3-small"
        assert model.dimensions() == 1536


# ───────────────────── SimilarSection ────────────────────────────────


class TestSimilarSection:
    def test_frozen(self) -> None:
        s = SimilarSection(doc_id="d1", section_number="7.01",
                           similarity=0.95, text_hash="abc")
        with pytest.raises(AttributeError):
            s.similarity = 0.5  # type: ignore[misc]


# ───────────────────── EmbeddingManager basics ───────────────────────


class TestManagerBasics:
    def test_available_with_model(self, manager: EmbeddingManager) -> None:
        assert manager.available is True
        assert manager.model_version == "mock-v1"
        assert manager.dimensions == 8

    def test_unavailable_without_model(self) -> None:
        mgr = EmbeddingManager(model=None, store=None)
        assert mgr.available is False
        assert mgr.model_version == "none"
        assert mgr.dimensions == 0

    def test_embed_texts(self, manager: EmbeddingManager) -> None:
        results = manager.embed_texts(["hello", "world"])
        assert results is not None
        assert len(results) == 2
        assert all(isinstance(r, EmbeddingResult) for r in results)
        assert results[0].model_version == "mock-v1"
        assert results[0].dimensions == 8

    def test_embed_texts_no_model(self) -> None:
        mgr = EmbeddingManager(model=None)
        assert mgr.embed_texts(["hello"]) is None

    def test_embed_texts_model_error_returns_none(
        self,
        manager: EmbeddingManager,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        def _boom(_: list[str]) -> list[bytes]:
            raise RuntimeError("embedding backend unavailable")

        assert manager._model is not None
        monkeypatch.setattr(manager._model, "embed", _boom)
        assert manager.embed_texts(["hello"]) is None


# ───────────────────── Embed and store ───────────────────────────────


class TestEmbedAndStore:
    def test_embed_and_store(self, manager: EmbeddingManager, store: LinkStore) -> None:
        sections = [
            {"doc_id": "d1", "section_number": "7.01", "text": "Indebtedness covenant text"},
            {"doc_id": "d1", "section_number": "7.02", "text": "Liens covenant text"},
        ]
        count = manager.embed_and_store(sections)
        assert count == 2

        # Verify stored
        emb = store.get_section_embedding("d1", "7.01", "mock-v1")
        assert emb is not None
        assert len(emb) == 8 * 4

    def test_embed_and_store_no_model(self, store: LinkStore) -> None:
        mgr = EmbeddingManager(model=None, store=store)
        count = mgr.embed_and_store([{"doc_id": "d1", "section_number": "1", "text": "x"}])
        assert count == 0

    def test_embed_and_store_no_store(self, mock_model: MockEmbeddingModel) -> None:
        mgr = EmbeddingManager(model=mock_model, store=None)
        count = mgr.embed_and_store([{"doc_id": "d1", "section_number": "1", "text": "x"}])
        assert count == 0

    def test_embed_and_store_model_error_returns_zero(
        self,
        manager: EmbeddingManager,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        def _boom(_: list[str]) -> list[bytes]:
            raise RuntimeError("embedding backend unavailable")

        assert manager._model is not None
        monkeypatch.setattr(manager._model, "embed", _boom)
        count = manager.embed_and_store([{"doc_id": "d1", "section_number": "1", "text": "x"}])
        assert count == 0


# ───────────────────── Retrieval ─────────────────────────────────────


class TestRetrieval:
    def test_get_section_embedding(self, manager: EmbeddingManager) -> None:
        manager.embed_and_store([
            {"doc_id": "d1", "section_number": "7.01", "text": "Test text"},
        ])
        emb = manager.get_section_embedding("d1", "7.01")
        assert emb is not None

    def test_get_missing_embedding(self, manager: EmbeddingManager) -> None:
        assert manager.get_section_embedding("nonexistent", "1.01") is None

    def test_get_embedding_no_store(self, mock_model: MockEmbeddingModel) -> None:
        mgr = EmbeddingManager(model=mock_model, store=None)
        assert mgr.get_section_embedding("d1", "7.01") is None


# ───────────────────── Centroid computation ──────────────────────────


class TestCentroid:
    def test_compute_centroid(self, manager: EmbeddingManager) -> None:
        # First embed some sections
        manager.embed_and_store([
            {"doc_id": "d1", "section_number": "7.01", "text": "Debt covenant section one"},
            {"doc_id": "d2", "section_number": "7.01", "text": "Debt covenant section two"},
            {"doc_id": "d3", "section_number": "7.01", "text": "Debt covenant section three"},
        ])
        # Compute centroid
        centroid = manager.compute_centroid(
            "debt",
            [
                {"doc_id": "d1", "section_number": "7.01"},
                {"doc_id": "d2", "section_number": "7.01"},
                {"doc_id": "d3", "section_number": "7.01"},
            ],
        )
        assert centroid is not None
        # Centroid should be L2-normalized
        floats = bytes_to_floats(centroid)
        norm = math.sqrt(sum(x * x for x in floats))
        assert abs(norm - 1.0) < 1e-5

    def test_compute_centroid_stored(self, manager: EmbeddingManager, store: LinkStore) -> None:
        manager.embed_and_store([
            {"doc_id": "d1", "section_number": "7.01", "text": "Test"},
        ])
        manager.compute_centroid(
            "debt",
            [{"doc_id": "d1", "section_number": "7.01"}],
        )
        # Should be stored
        centroid = store.get_family_centroid("debt", "_global", "mock-v1")
        assert centroid is not None

    def test_compute_centroid_no_model(self, store: LinkStore) -> None:
        mgr = EmbeddingManager(model=None, store=store)
        assert mgr.compute_centroid("debt", []) is None

    def test_compute_centroid_no_embeddings(self, manager: EmbeddingManager) -> None:
        """No stored embeddings → returns None."""
        centroid = manager.compute_centroid(
            "debt",
            [{"doc_id": "nonexistent", "section_number": "1.01"}],
        )
        assert centroid is None

    def test_get_family_centroid(self, manager: EmbeddingManager) -> None:
        manager.embed_and_store([
            {"doc_id": "d1", "section_number": "7.01", "text": "Test"},
        ])
        manager.compute_centroid(
            "debt",
            [{"doc_id": "d1", "section_number": "7.01"}],
        )
        centroid = manager.get_family_centroid("debt")
        assert centroid is not None

    def test_get_centroid_no_store(self, mock_model: MockEmbeddingModel) -> None:
        mgr = EmbeddingManager(model=mock_model, store=None)
        assert mgr.get_family_centroid("debt") is None


# ───────────────────── Similarity search ─────────────────────────────


class TestSimilaritySearch:
    def test_find_similar(self, mock_model: MockEmbeddingModel) -> None:
        mgr = EmbeddingManager(model=mock_model)
        query = mock_model.embed(["indebtedness"])[0]
        candidates = [
            {
                "doc_id": "d1", "section_number": "7.01",
                "embedding_vector": mock_model.embed(["indebtedness"])[0],
                "text_hash": "h1",
            },
            {
                "doc_id": "d2", "section_number": "7.01",
                "embedding_vector": mock_model.embed(["liens"])[0],
                "text_hash": "h2",
            },
        ]
        results = mgr.find_similar(query, candidates, top_k=5)
        assert len(results) == 2
        # First result should be exact match
        assert results[0].doc_id == "d1"
        assert abs(results[0].similarity - 1.0) < 1e-5
        # Second should be less similar
        assert results[1].similarity < results[0].similarity

    def test_find_similar_with_threshold(self, mock_model: MockEmbeddingModel) -> None:
        mgr = EmbeddingManager(model=mock_model)
        query = mock_model.embed(["test"])[0]
        candidates = [
            {
                "doc_id": "d1", "section_number": "7.01",
                "embedding_vector": mock_model.embed(["test"])[0],
                "text_hash": "h1",
            },
            {
                "doc_id": "d2", "section_number": "7.01",
                "embedding_vector": mock_model.embed(["completely different text"])[0],
                "text_hash": "h2",
            },
        ]
        results = mgr.find_similar(query, candidates, min_similarity=0.99)
        # Only exact match should pass threshold
        assert len(results) == 1
        assert results[0].doc_id == "d1"

    def test_find_similar_top_k(self, mock_model: MockEmbeddingModel) -> None:
        mgr = EmbeddingManager(model=mock_model)
        query = mock_model.embed(["query"])[0]
        candidates = [
            {
                "doc_id": f"d{i}", "section_number": "7.01",
                "embedding_vector": mock_model.embed([f"text_{i}"])[0],
                "text_hash": f"h{i}",
            }
            for i in range(10)
        ]
        results = mgr.find_similar(query, candidates, top_k=3)
        assert len(results) == 3

    def test_find_similar_empty(self, mock_model: MockEmbeddingModel) -> None:
        mgr = EmbeddingManager(model=mock_model)
        query = mock_model.embed(["test"])[0]
        results = mgr.find_similar(query, [])
        assert results == []

    def test_find_similar_sorted_by_similarity(self, mock_model: MockEmbeddingModel) -> None:
        mgr = EmbeddingManager(model=mock_model)
        query = mock_model.embed(["test"])[0]
        candidates = [
            {
                "doc_id": f"d{i}", "section_number": "7.01",
                "embedding_vector": mock_model.embed([f"candidate_{i}"])[0],
                "text_hash": f"h{i}",
            }
            for i in range(5)
        ]
        results = mgr.find_similar(query, candidates)
        # Should be sorted descending by similarity
        for i in range(len(results) - 1):
            assert results[i].similarity >= results[i + 1].similarity


class TestSectionSimilarity:
    def test_section_similarity(self, manager: EmbeddingManager) -> None:
        manager.embed_and_store([
            {"doc_id": "d1", "section_number": "7.01", "text": "Same text"},
            {"doc_id": "d2", "section_number": "7.01", "text": "Same text"},
        ])
        sim = manager.section_similarity("d1", "7.01", "d2", "7.01")
        assert sim is not None
        assert abs(sim - 1.0) < 1e-5  # Same text → identical embeddings

    def test_section_similarity_different_text(self, manager: EmbeddingManager) -> None:
        manager.embed_and_store([
            {"doc_id": "d1", "section_number": "7.01", "text": "Indebtedness covenant"},
            {"doc_id": "d2", "section_number": "7.01", "text": "Liens and pledges"},
        ])
        sim = manager.section_similarity("d1", "7.01", "d2", "7.01")
        assert sim is not None
        assert sim < 1.0  # Different text → different similarity

    def test_section_similarity_missing(self, manager: EmbeddingManager) -> None:
        assert manager.section_similarity("x", "1", "y", "2") is None


# ───────────────────── Cache invalidation ────────────────────────────


class TestCacheInvalidation:
    def test_needs_recompute_changed(self, manager: EmbeddingManager) -> None:
        stored_hash = text_hash("original text")
        assert manager.needs_recompute("modified text", stored_hash) is True

    def test_needs_recompute_unchanged(self, manager: EmbeddingManager) -> None:
        txt = "original text"
        stored_hash = text_hash(txt)
        assert manager.needs_recompute(txt, stored_hash) is False


# ───────────────────── Coverage statistics ───────────────────────────


class TestCoverageStatistics:
    def test_complete_coverage(self, manager: EmbeddingManager) -> None:
        stats = manager.embedding_coverage(100, 100)
        assert stats["coverage_pct"] == 100.0
        assert stats["status"] == "complete"

    def test_partial_coverage(self, manager: EmbeddingManager) -> None:
        stats = manager.embedding_coverage(100, 50)
        assert stats["coverage_pct"] == 50.0
        assert stats["status"] == "partial"

    def test_no_coverage(self, manager: EmbeddingManager) -> None:
        stats = manager.embedding_coverage(100, 0)
        assert stats["coverage_pct"] == 0.0
        assert stats["status"] == "none"

    def test_empty_corpus(self, manager: EmbeddingManager) -> None:
        stats = manager.embedding_coverage(0, 0)
        assert stats["status"] == "empty"


# ───────────────────── Graceful degradation ──────────────────────────


class TestGracefulDegradation:
    """All operations must handle missing model/store without errors."""

    def test_no_model_embed(self) -> None:
        mgr = EmbeddingManager(model=None)
        assert mgr.embed_texts(["test"]) is None

    def test_no_model_embed_and_store(self, store: LinkStore) -> None:
        mgr = EmbeddingManager(model=None, store=store)
        assert mgr.embed_and_store([{"doc_id": "d1", "section_number": "1", "text": "x"}]) == 0

    def test_no_model_get_embedding(self, store: LinkStore) -> None:
        mgr = EmbeddingManager(model=None, store=store)
        assert mgr.get_section_embedding("d1", "1") is None

    def test_no_model_compute_centroid(self) -> None:
        mgr = EmbeddingManager(model=None)
        assert mgr.compute_centroid("debt", []) is None

    def test_no_model_get_centroid(self) -> None:
        mgr = EmbeddingManager(model=None)
        assert mgr.get_family_centroid("debt") is None

    def test_no_model_section_similarity(self) -> None:
        mgr = EmbeddingManager(model=None)
        assert mgr.section_similarity("d1", "1", "d2", "2") is None

    def test_no_store_embed_texts(self, mock_model: MockEmbeddingModel) -> None:
        """Can still embed without a store, just no persistence."""
        mgr = EmbeddingManager(model=mock_model, store=None)
        results = mgr.embed_texts(["test"])
        assert results is not None
        assert len(results) == 1

    def test_no_store_embed_and_store(self, mock_model: MockEmbeddingModel) -> None:
        mgr = EmbeddingManager(model=mock_model, store=None)
        assert mgr.embed_and_store([{"doc_id": "d1", "section_number": "1", "text": "x"}]) == 0

    def test_no_store_get_embedding(self, mock_model: MockEmbeddingModel) -> None:
        mgr = EmbeddingManager(model=mock_model, store=None)
        assert mgr.get_section_embedding("d1", "1") is None

    def test_no_store_compute_centroid(self, mock_model: MockEmbeddingModel) -> None:
        """Without store, centroid can't retrieve section embeddings."""
        mgr = EmbeddingManager(model=mock_model, store=None)
        centroid = mgr.compute_centroid("debt", [
            {"doc_id": "d1", "section_number": "7.01"},
        ])
        assert centroid is None
