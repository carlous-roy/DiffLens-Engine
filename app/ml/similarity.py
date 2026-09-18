"""Similar Bug Detection — embedding-based search for historically similar issues."""

import logging
from dataclasses import asdict, dataclass

import numpy as np

logger = logging.getLogger(__name__)

# Try to import sentence-transformers (heavy dependency, optional)
try:
    from sentence_transformers import SentenceTransformer

    SBERT_AVAILABLE = True
except ImportError:
    SBERT_AVAILABLE = False

# TF-IDF fallback
try:
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics.pairwise import cosine_similarity as sklearn_cosine

    SKLEARN_AVAILABLE = True
except ImportError:
    SKLEARN_AVAILABLE = False


@dataclass
class SimilarFinding:
    """A historically similar finding."""

    message: str
    file_path: str
    analyzer: str
    severity: str
    similarity_score: float
    run_id: str | None = None
    suggestion: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class SimilarityResult:
    """Result of searching for similar past findings."""

    query_message: str
    similar_findings: list[SimilarFinding]
    method: str  # "sbert", "tfidf", or "unavailable"
    error: str | None = None

    def to_dict(self) -> dict:
        return {
            "query_message": self.query_message,
            "similar_findings": [f.to_dict() for f in self.similar_findings],
            "method": self.method,
            "error": self.error,
        }


class FindingEmbedder:
    """Manages embedding computation and similarity search."""

    def __init__(self):
        self._sbert_model = None
        self._tfidf = None
        self._corpus: list[dict] = []  # stored findings with metadata
        self._corpus_texts: list[str] = []
        self._corpus_embeddings = None  # numpy array of embeddings

    def _get_sbert(self):
        """Lazy-load sentence-transformers model."""
        if self._sbert_model is None and SBERT_AVAILABLE:
            try:
                self._sbert_model = SentenceTransformer("all-MiniLM-L6-v2")
                logger.info("Loaded sentence-transformers model: all-MiniLM-L6-v2")
            except Exception as e:
                logger.warning("Failed to load sentence-transformers: %s", e)
        return self._sbert_model

    @property
    def method(self) -> str:
        if SBERT_AVAILABLE:
            return "sbert"
        elif SKLEARN_AVAILABLE:
            return "tfidf"
        return "unavailable"

    def _finding_to_text(self, finding: dict) -> str:
        """Convert a finding dict into searchable text."""
        parts = [
            finding.get("message", ""),
            finding.get("suggestion", "") or "",
            f"[{finding.get('analyzer', '')}]",
            f"[{finding.get('severity', '')}]",
        ]
        return " ".join(p for p in parts if p)

    def add_findings(self, findings: list[dict], run_id: str | None = None):
        """Add findings to the corpus for future similarity searches."""
        for f in findings:
            entry = {**f, "run_id": run_id}
            self._corpus.append(entry)
            self._corpus_texts.append(self._finding_to_text(entry))

        # Invalidate cached embeddings
        self._corpus_embeddings = None
        self._tfidf = None

    def _compute_sbert_embeddings(self, texts: list[str]) -> np.ndarray:
        """Compute embeddings using sentence-transformers."""
        model = self._get_sbert()
        if model is None:
            raise RuntimeError("sentence-transformers not available")
        return model.encode(texts, convert_to_numpy=True, show_progress_bar=False)

    def _ensure_corpus_embeddings(self):
        """Pre-compute corpus embeddings if not cached."""
        if self._corpus_embeddings is not None:
            return

        if not self._corpus_texts:
            return

        if SBERT_AVAILABLE:
            self._corpus_embeddings = self._compute_sbert_embeddings(self._corpus_texts)
        elif SKLEARN_AVAILABLE:
            self._tfidf = TfidfVectorizer(max_features=5000, stop_words="english")
            self._corpus_embeddings = self._tfidf.fit_transform(self._corpus_texts)

    def find_similar(
        self, finding: dict, top_k: int = 5, threshold: float = 0.3
    ) -> SimilarityResult:
        """Find findings similar to the given one from the stored corpus."""
        query_text = self._finding_to_text(finding)

        if not self._corpus_texts:
            return SimilarityResult(
                query_message=finding.get("message", ""),
                similar_findings=[],
                method=self.method,
                error="No historical findings in corpus.",
            )

        if self.method == "unavailable":
            return SimilarityResult(
                query_message=finding.get("message", ""),
                similar_findings=[],
                method="unavailable",
                error="Neither sentence-transformers nor scikit-learn is available.",
            )

        try:
            self._ensure_corpus_embeddings()

            if self.method == "sbert":
                query_emb = self._compute_sbert_embeddings([query_text])
                # Cosine similarity
                norms_corpus = np.linalg.norm(self._corpus_embeddings, axis=1, keepdims=True)
                norms_query = np.linalg.norm(query_emb, axis=1, keepdims=True)
                # Avoid division by zero
                norms_corpus = np.maximum(norms_corpus, 1e-10)
                norms_query = np.maximum(norms_query, 1e-10)
                similarities = (
                    (query_emb @ self._corpus_embeddings.T) / (norms_query * norms_corpus.T)
                )[0]
            else:
                # TF-IDF + cosine
                query_vec = self._tfidf.transform([query_text])
                similarities = sklearn_cosine(query_vec, self._corpus_embeddings)[0]

            # Rank results
            ranked_indices = np.argsort(similarities)[::-1]

            results = []
            for idx in ranked_indices[:top_k]:
                sim = float(similarities[idx])
                if sim < threshold:
                    break
                # Skip exact self-matches
                if sim > 0.99:
                    continue

                entry = self._corpus[idx]
                results.append(
                    SimilarFinding(
                        message=entry.get("message", ""),
                        file_path=entry.get("file_path", ""),
                        analyzer=entry.get("analyzer", ""),
                        severity=entry.get("severity", ""),
                        similarity_score=round(sim, 4),
                        run_id=entry.get("run_id"),
                        suggestion=entry.get("suggestion"),
                    )
                )

            return SimilarityResult(
                query_message=finding.get("message", ""),
                similar_findings=results,
                method=self.method,
            )

        except Exception as e:
            logger.error("Similarity search failed: %s", e)
            return SimilarityResult(
                query_message=finding.get("message", ""),
                similar_findings=[],
                method=self.method,
                error=str(e),
            )

    def clear_corpus(self):
        """Clear the stored corpus."""
        self._corpus = []
        self._corpus_texts = []
        self._corpus_embeddings = None
        self._tfidf = None


# Module-level singleton
_embedder: FindingEmbedder | None = None


def get_embedder() -> FindingEmbedder:
    global _embedder
    if _embedder is None:
        _embedder = FindingEmbedder()
    return _embedder
