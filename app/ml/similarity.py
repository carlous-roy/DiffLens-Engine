"""Related past findings and clusters of repeat findings.

Every persisted finding carries an embedding (see `app.ml.embeddings`) and a
cluster id. At startup `FindingIndex.load_from_db` reads the corpus from the
database, re-embeds anything produced by a different model, and clusters it
with agglomerative clustering (average linkage, cosine distance, a fixed
distance threshold, no k). New findings are compared with the corpus:

- related findings: nearest neighbours by embedding cosine similarity, run
  through pgvector on PostgreSQL and through numpy elsewhere, re-scored with
  TF-IDF cosine similarity for lexical overlap, at most one hit per past run;
- clusters: a new finding joins the nearest existing cluster whose centroid
  is within the distance threshold, otherwise it starts a new one, and
  `times_seen_before` counts the corpus members of that cluster.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import asdict, dataclass, field

import numpy as np

from app.config import get_settings
from app.ml.embeddings import EmbeddingModel, get_embedding_model

logger = logging.getLogger(__name__)

TOP_K = 3
CANDIDATE_MULTIPLIER = 4


@dataclass
class SimilarFinding:
    """A related finding from an earlier run."""

    message: str
    file_path: str
    analyzer: str
    severity: str
    similarity_score: float  # embedding cosine similarity
    lexical_score: float  # TF-IDF cosine similarity
    combined_score: float  # mean of the two
    run_id: str | None = None
    finding_id: str | None = None
    cluster_id: int | None = None
    suggestion: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class SimilarityResult:
    """Related past findings for one query finding."""

    query_message: str
    similar_findings: list[SimilarFinding]
    method: str
    cluster_id: int | None = None
    times_seen_before: int = 0
    error: str | None = None

    def to_dict(self) -> dict:
        return {
            "query_message": self.query_message,
            "similar_findings": [f.to_dict() for f in self.similar_findings],
            "method": self.method,
            "cluster_id": self.cluster_id,
            "times_seen_before": self.times_seen_before,
            "error": self.error,
        }


@dataclass
class _Entry:
    finding_id: str | None
    run_id: str | None
    cluster_id: int | None
    text: str
    meta: dict = field(default_factory=dict)


def finding_text(finding: dict) -> str:
    """The text that is embedded for a finding: what the issue is, not where."""
    parts = [f"{finding.get('analyzer', '')}: {finding.get('message', '')}".strip(": ")]
    if finding.get("suggestion"):
        parts.append(str(finding["suggestion"]))
    return " ".join(parts)


class FindingIndex:
    """In-memory corpus of embedded findings, with cluster centroids."""

    def __init__(
        self,
        model: EmbeddingModel,
        distance_threshold: float,
        session_factory=None,
    ):
        self.model = model
        self.distance_threshold = float(distance_threshold)
        self._session_factory = session_factory
        self._lock = threading.RLock()
        self._entries: list[_Entry] = []
        self._vectors = np.zeros((0, model.dim), dtype=np.float32)
        self._centroid_sums: dict[int, np.ndarray] = {}
        self._cluster_sizes: dict[int, int] = {}
        self._next_cluster_id = 1
        self._tfidf = None
        self._tfidf_matrix = None
        self.loaded_from_db = False

    # ------------------------------------------------------------ state ----

    def __len__(self) -> int:
        return len(self._entries)

    @property
    def method(self) -> str:
        backend = "fastembed" if self.model.name.startswith("BAAI/") else "hashing"
        return f"{backend}+tfidf"

    def stats(self) -> dict:
        with self._lock:
            return {
                "findings": len(self._entries),
                "clusters": len(self._cluster_sizes),
                "embedding_model": self.model.name,
                "distance_threshold": self.distance_threshold,
                "loaded_from_db": self.loaded_from_db,
                "search_backend": "pgvector" if self._uses_pgvector() else "numpy",
            }

    def _uses_pgvector(self) -> bool:
        if self._session_factory is None:
            return False
        bind = getattr(self._session_factory, "kw", {}).get("bind")
        return bind is not None and bind.dialect.name == "postgresql"

    # --------------------------------------------------------- embedding ----

    def embed(self, findings: list[dict]) -> np.ndarray:
        return self.model.embed([finding_text(f) for f in findings])

    # ------------------------------------------------------------- load ----

    def load_from_db(self) -> None:
        """Read the persisted corpus, re-embed stale rows and (re)cluster.

        Tolerates a database without the tables (fresh clone before the
        migrations ran): the index simply starts empty.
        """
        if self._session_factory is None:
            return
        from sqlalchemy.exc import SQLAlchemyError

        from app.db.models import AnalysisFinding, AnalysisRun

        settings = get_settings()
        session = self._session_factory()
        try:
            rows = (
                session.query(AnalysisFinding)
                .join(AnalysisRun, AnalysisRun.id == AnalysisFinding.run_id)
                .filter(AnalysisFinding.embedding.isnot(None))
                .order_by(AnalysisRun.created_at.desc())
                .limit(settings.similarity_corpus_limit)
                .all()
            )
            stale = [r for r in rows if r.embedding_model != self.model.name]
            if stale:
                logger.info("Re-embedding %d findings stored with another model.", len(stale))
                vectors = self.model.embed([finding_text(_row_dict(r)) for r in stale])
                for row, vec in zip(stale, vectors, strict=True):
                    row.embedding = vec
                    row.embedding_model = self.model.name
                session.commit()

            with self._lock:
                self._reset()
                if rows:
                    self._vectors = np.vstack(
                        [np.asarray(r.embedding, dtype=np.float32) for r in rows]
                    )
                    self._entries = [
                        _Entry(
                            str(r.id),
                            str(r.run_id),
                            r.cluster_id,
                            finding_text(_row_dict(r)),
                            meta=_row_dict(r),
                        )
                        for r in rows
                    ]
                needs_clustering = any(e.cluster_id is None for e in self._entries)
                if self._entries and (
                    needs_clustering or len(self._entries) <= settings.similarity_recluster_limit
                ):
                    changed = self.recluster()
                    if changed:
                        by_id = {e.finding_id: e.cluster_id for e in self._entries}
                        for row in rows:
                            new_id = by_id.get(str(row.id))
                            if new_id != row.cluster_id:
                                row.cluster_id = new_id
                        session.commit()
                else:
                    self._rebuild_centroids()
                self.loaded_from_db = True
            logger.info(
                "Similarity index loaded: %d findings in %d clusters (%s).",
                len(self._entries),
                len(self._cluster_sizes),
                self.model.name,
            )
        except SQLAlchemyError as exc:
            session.rollback()
            logger.warning(
                "Similarity index could not load the corpus (%s); starting empty. "
                "Run the migrations if the tables are missing.",
                exc.__class__.__name__,
            )
        finally:
            session.close()

    def _reset(self) -> None:
        self._entries = []
        self._vectors = np.zeros((0, self.model.dim), dtype=np.float32)
        self._centroid_sums = {}
        self._cluster_sizes = {}
        self._next_cluster_id = 1
        self._tfidf = None
        self._tfidf_matrix = None

    # ------------------------------------------------------- clustering ----

    def recluster(self) -> bool:
        """Cluster the whole corpus; returns True when any cluster id changed.

        Agglomerative clustering with average linkage over cosine distance and
        a distance threshold: deterministic for a given corpus and no choice
        of k. Ids are renumbered from 1 in order of first appearance so they
        stay stable across restarts for an unchanged corpus.
        """
        with self._lock:
            n = len(self._entries)
            if n == 0:
                return False
            if n == 1:
                labels = np.array([0])
            else:
                from sklearn.cluster import AgglomerativeClustering

                clustering = AgglomerativeClustering(
                    n_clusters=None,
                    distance_threshold=self.distance_threshold,
                    metric="cosine",
                    linkage="average",
                )
                labels = clustering.fit_predict(self._vectors)
            renumber: dict[int, int] = {}
            changed = False
            for entry, label in zip(self._entries, labels, strict=True):
                cluster_id = renumber.setdefault(int(label), len(renumber) + 1)
                if entry.cluster_id != cluster_id:
                    changed = True
                entry.cluster_id = cluster_id
            self._rebuild_centroids()
            return changed

    def _rebuild_centroids(self) -> None:
        self._centroid_sums = {}
        self._cluster_sizes = {}
        for entry, vec in zip(self._entries, self._vectors, strict=True):
            if entry.cluster_id is None:
                continue
            self._centroid_sums[entry.cluster_id] = (
                self._centroid_sums.get(entry.cluster_id, 0) + vec
            )
            self._cluster_sizes[entry.cluster_id] = self._cluster_sizes.get(entry.cluster_id, 0) + 1
        self._next_cluster_id = max(self._cluster_sizes, default=0) + 1

    def assign_cluster(self, vector: np.ndarray) -> tuple[int, int]:
        """Return (cluster id, members already in that cluster) for a vector.

        The nearest centroid within the distance threshold wins; otherwise a
        new id is allocated. The corpus is not modified: `add_run` records
        the assignment once the finding is persisted.
        """
        with self._lock:
            if self._cluster_sizes:
                ids = list(self._cluster_sizes)
                centroids = np.vstack(
                    [self._centroid_sums[c] / self._cluster_sizes[c] for c in ids]
                )
                norms = np.linalg.norm(centroids, axis=1)
                sims = centroids @ vector / np.maximum(norms, 1e-12)
                best = int(np.argmax(sims))
                if 1.0 - float(sims[best]) <= self.distance_threshold:
                    return ids[best], self._cluster_sizes[ids[best]]
            cluster_id = self._next_cluster_id
            self._next_cluster_id += 1
            return cluster_id, 0

    # ----------------------------------------------------------- search ----

    def search(self, vector: np.ndarray, top_k: int = TOP_K) -> list[tuple[int, float]]:
        """Indices into the corpus and cosine similarities, best first."""
        with self._lock:
            if len(self._entries) == 0:
                return []
            if self._uses_pgvector():
                hits = self._search_pgvector(vector, top_k * CANDIDATE_MULTIPLIER)
                if hits is not None:
                    return hits
            sims = self._vectors @ vector
            order = np.argsort(-sims)[: top_k * CANDIDATE_MULTIPLIER]
            return [(int(i), float(sims[i])) for i in order]

    def _search_pgvector(self, vector: np.ndarray, limit: int) -> list[tuple[int, float]] | None:
        """Nearest neighbours through pgvector's `<=>` cosine distance operator."""
        try:
            from app.db.models import AnalysisFinding

            positions = {e.finding_id: i for i, e in enumerate(self._entries)}
            hits: list[tuple[int, float]] = []
            session = self._session_factory()
            try:
                for row_id, distance in pgvector_neighbours(
                    session, AnalysisFinding, vector, self.model.name, limit
                ):
                    position = positions.get(str(row_id))
                    if position is None:
                        continue
                    hits.append((position, 1.0 - float(distance)))
            finally:
                session.close()
            return hits
        except Exception as exc:  # fall back to numpy rather than fail the analysis
            logger.warning("pgvector search failed (%s); using numpy.", exc)
            return None

    def lexical_scores(self, query_text: str, indices: list[int]) -> list[float]:
        """TF-IDF cosine similarity between the query and the given corpus rows."""
        with self._lock:
            if not indices:
                return []
            self._ensure_tfidf()
            from sklearn.metrics.pairwise import cosine_similarity

            query = self._tfidf.transform([query_text])
            sims = cosine_similarity(query, self._tfidf_matrix[indices])[0]
            return [float(s) for s in sims]

    def _ensure_tfidf(self) -> None:
        if self._tfidf is not None:
            return
        from sklearn.feature_extraction.text import TfidfVectorizer

        self._tfidf = TfidfVectorizer(max_features=5000)
        self._tfidf_matrix = self._tfidf.fit_transform([e.text for e in self._entries])

    # -------------------------------------------------------------- add ----

    def add_run(
        self,
        run_id: str,
        findings: list[dict],
        vectors: np.ndarray,
        cluster_ids: list[int],
        finding_ids: list[str] | None = None,
    ) -> None:
        """Record a persisted run's findings in the corpus."""
        if len(findings) == 0:
            return
        with self._lock:
            for i, (finding, vec, cluster_id) in enumerate(
                zip(findings, vectors, cluster_ids, strict=True)
            ):
                self._entries.append(
                    _Entry(
                        finding_ids[i] if finding_ids else None,
                        run_id,
                        cluster_id,
                        finding_text(finding),
                        meta={
                            "message": finding.get("message", ""),
                            "file_path": finding.get("file_path", ""),
                            "analyzer": finding.get("analyzer", ""),
                            "severity": finding.get("severity", ""),
                            "suggestion": finding.get("suggestion"),
                        },
                    )
                )
                self._centroid_sums[cluster_id] = self._centroid_sums.get(cluster_id, 0) + vec
                self._cluster_sizes[cluster_id] = self._cluster_sizes.get(cluster_id, 0) + 1
                self._next_cluster_id = max(self._next_cluster_id, cluster_id + 1)
            self._vectors = np.vstack([self._vectors, np.asarray(vectors, dtype=np.float32)])
            self._tfidf = None
            self._tfidf_matrix = None

    def entry(self, index: int) -> _Entry:
        return self._entries[index]


def pgvector_neighbours(session, model_cls, vector: np.ndarray, model_name: str, limit: int):
    """Query (id, cosine distance) of the nearest stored findings on PostgreSQL."""
    import sqlalchemy as sa
    from pgvector.sqlalchemy import Vector

    from app.db.models import EMBEDDING_DIM

    query_vec = sa.bindparam("query_vec", [float(x) for x in vector], type_=Vector(EMBEDDING_DIM))
    distance = model_cls.embedding.op("<=>")(query_vec).label("distance")
    stmt = (
        sa.select(model_cls.id, distance)
        .where(model_cls.embedding_model == model_name)
        .where(model_cls.embedding.isnot(None))
        .order_by(distance)
        .limit(limit)
    )
    return session.execute(stmt).all()


def _row_dict(row) -> dict:
    return {
        "analyzer": row.analyzer,
        "message": row.message,
        "suggestion": row.suggestion,
        "file_path": row.file_path,
        "severity": row.severity.value if row.severity else "",
    }


# ------------------------------------------------------------ analysis ----


@dataclass
class SimilarityAnalysis:
    """Per-finding similarity results plus what persistence needs to store."""

    results: list[SimilarityResult]
    vectors: np.ndarray
    cluster_ids: list[int]
    times_seen_before: list[int]


def analyze_findings(findings: list[dict], index: FindingIndex | None = None) -> SimilarityAnalysis:
    """Embed the run's findings, find related past findings and assign clusters.

    Findings of the same run that fall in one new cluster share its id, so
    a repeated issue within one diff is one cluster from the start.
    """
    index = index or get_finding_index()
    settings = get_settings()
    if not findings:
        return SimilarityAnalysis([], np.zeros((0, index.model.dim), dtype=np.float32), [], [])

    vectors = index.embed(findings)
    results: list[SimilarityResult] = []
    cluster_ids: list[int] = []
    seen_counts: list[int] = []
    new_clusters: list[tuple[int, np.ndarray]] = []  # (id, vector) allocated for this run

    for finding, vector in zip(findings, vectors, strict=True):
        query_text = finding_text(finding)
        hits = index.search(vector, TOP_K)
        candidate_idx = [i for i, _ in hits]
        lexical = index.lexical_scores(query_text, candidate_idx)
        related: list[SimilarFinding] = []
        seen_runs: set[str | None] = set()
        for (idx, semantic), lex in zip(hits, lexical, strict=True):
            entry = index.entry(idx)
            if entry.run_id in seen_runs:
                continue  # one hit per past run
            combined = round((semantic + lex) / 2, 4)
            if combined < settings.similarity_min_score:
                continue
            seen_runs.add(entry.run_id)
            meta = entry.meta
            related.append(
                SimilarFinding(
                    message=meta.get("message", entry.text),
                    file_path=meta.get("file_path", ""),
                    analyzer=meta.get("analyzer", ""),
                    severity=meta.get("severity", ""),
                    similarity_score=round(float(semantic), 4),
                    lexical_score=round(float(lex), 4),
                    combined_score=combined,
                    run_id=entry.run_id,
                    finding_id=entry.finding_id,
                    cluster_id=entry.cluster_id,
                    suggestion=meta.get("suggestion"),
                )
            )
            if len(related) >= TOP_K:
                break
        related.sort(key=lambda f: -f.combined_score)

        cluster_id, seen = index.assign_cluster(vector)
        if seen == 0:
            # Newly allocated: reuse it for near-identical findings in this run.
            for existing_id, existing_vec in new_clusters:
                if 1.0 - float(existing_vec @ vector) <= index.distance_threshold:
                    cluster_id = existing_id
                    break
            else:
                new_clusters.append((cluster_id, vector))
        cluster_ids.append(cluster_id)
        seen_counts.append(seen)
        results.append(
            SimilarityResult(
                query_message=finding.get("message", ""),
                similar_findings=related,
                method=index.method,
                cluster_id=cluster_id,
                times_seen_before=seen,
            )
        )

    return SimilarityAnalysis(results, vectors, cluster_ids, seen_counts)


# ----------------------------------------------------------- singleton ----

_INDEX: FindingIndex | None = None
_INDEX_LOCK = threading.Lock()


def get_finding_index() -> FindingIndex:
    """The process-wide index; created lazily and empty until `load_from_db`."""
    global _INDEX
    with _INDEX_LOCK:
        if _INDEX is None:
            settings = get_settings()
            try:
                from app.db import SessionLocal
            except Exception:  # pragma: no cover - database layer unavailable
                SessionLocal = None
            _INDEX = FindingIndex(
                get_embedding_model(), settings.cluster_distance_threshold, SessionLocal
            )
        return _INDEX


def set_finding_index(index: FindingIndex | None) -> None:
    """Replace the process-wide index (tests bind one to their database)."""
    global _INDEX
    with _INDEX_LOCK:
        _INDEX = index


def reset_finding_index() -> None:
    set_finding_index(None)
