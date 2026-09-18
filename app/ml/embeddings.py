"""Text embeddings for findings.

The default backend is fastembed running BAAI/bge-small-en-v1.5 through ONNX
(384 dimensions, no PyTorch). If fastembed is not installed or the model
cannot be loaded, a hashing backend of the same dimension takes over so the
service keeps working with lexical rather than semantic similarity; the
switch is logged at error level and reported through `/api/v1/ml/status`.
"""

from __future__ import annotations

import logging
import threading
from typing import Protocol

import numpy as np

from app.config import get_settings

logger = logging.getLogger(__name__)

EMBEDDING_DIM = 384
FASTEMBED_MODEL = "BAAI/bge-small-en-v1.5"


class EmbeddingModel(Protocol):
    name: str
    dim: int

    def embed(self, texts: list[str]) -> np.ndarray:
        """Return an (n, dim) array of L2-normalised float32 vectors."""


def _normalise(matrix: np.ndarray) -> np.ndarray:
    matrix = np.asarray(matrix, dtype=np.float32)
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    return matrix / np.maximum(norms, 1e-12)


class FastEmbedModel:
    """bge-small-en-v1.5 via fastembed (ONNX runtime)."""

    def __init__(self, model_name: str = FASTEMBED_MODEL, cache_dir: str | None = None):
        from fastembed import TextEmbedding

        self.name = model_name
        self.dim = EMBEDDING_DIM
        self._model = TextEmbedding(model_name, cache_dir=cache_dir)
        self._lock = threading.Lock()

    def embed(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.dim), dtype=np.float32)
        with self._lock:
            vectors = np.array(list(self._model.embed(texts)), dtype=np.float32)
        return _normalise(vectors)


class HashingEmbeddingModel:
    """Dependency-free fallback: hashed character n-grams, L2-normalised.

    Vectors from this backend only capture lexical overlap. They share the
    dimension of the fastembed vectors but live in a different space, so the
    model name is stored with every vector and mixed corpora are re-embedded.
    """

    name = "hashing-char-ngram-v1"
    dim = EMBEDDING_DIM

    def __init__(self):
        from sklearn.feature_extraction.text import HashingVectorizer

        self._vectorizer = HashingVectorizer(
            n_features=self.dim,
            analyzer="char_wb",
            ngram_range=(3, 5),
            norm=None,
            alternate_sign=False,
            lowercase=True,
        )

    def embed(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.dim), dtype=np.float32)
        sparse = self._vectorizer.transform(texts)
        return _normalise(np.sqrt(sparse.toarray()))


_MODEL: EmbeddingModel | None = None
_LOCK = threading.Lock()
_FALLBACK_REASON: str | None = None


def get_embedding_model() -> EmbeddingModel:
    """The process-wide embedding model, created on first use."""
    global _MODEL, _FALLBACK_REASON
    with _LOCK:
        if _MODEL is not None:
            return _MODEL
        settings = get_settings()
        backend = settings.embedding_backend
        if backend == "fastembed":
            try:
                _MODEL = FastEmbedModel(settings.embedding_model, settings.embedding_cache_dir)
                logger.info("Embeddings: fastembed %s (%d dims).", _MODEL.name, _MODEL.dim)
                return _MODEL
            except Exception as exc:
                _FALLBACK_REASON = f"{type(exc).__name__}: {exc}"
                logger.error(
                    "Embeddings: fastembed model %s could not be loaded (%s); falling back "
                    "to the hashing backend. Similarity search is lexical until this is fixed.",
                    settings.embedding_model,
                    _FALLBACK_REASON,
                )
        elif backend != "hashing":
            logger.error(
                "Embeddings: unknown EMBEDDING_BACKEND %r; using the hashing backend.", backend
            )
        _MODEL = HashingEmbeddingModel()
        return _MODEL


def embedding_status() -> dict:
    model = get_embedding_model()
    return {
        "backend": "fastembed" if isinstance(model, FastEmbedModel) else "hashing",
        "model": model.name,
        "dimensions": model.dim,
        "fallback_reason": _FALLBACK_REASON,
    }


def reset_embedding_model() -> None:
    """Forget the cached model (tests switch backends)."""
    global _MODEL, _FALLBACK_REASON
    with _LOCK:
        _MODEL = None
        _FALLBACK_REASON = None
