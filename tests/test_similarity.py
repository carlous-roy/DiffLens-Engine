"""Tests for related-finding search, clustering and the SQLite/numpy fallback."""

import numpy as np
import pytest
from sqlalchemy.dialects import postgresql

from app.analysis.pipeline import run_analysis
from app.config import get_settings
from app.db.models import AnalysisFinding
from app.db.persist import persist_run
from app.ml.embeddings import HashingEmbeddingModel, get_embedding_model
from app.ml.similarity import (
    FindingIndex,
    analyze_findings,
    finding_text,
    pgvector_neighbours,
    set_finding_index,
)
from tests.conftest import SAMPLE_JAVA_DIFF, SAMPLE_PYTHON_DIFF

EVAL = {
    "message": "Use of eval()/exec() is a security risk.",
    "suggestion": "Use ast.literal_eval() for safe evaluation.",
    "analyzer": "bug_risk",
    "severity": "critical",
    "file_path": "a.py",
}
EXCEPT = {
    "message": "Bare except clause catches all exceptions.",
    "suggestion": "Catch specific exceptions.",
    "analyzer": "bug_risk",
    "severity": "warning",
    "file_path": "b.py",
}
NAMING = {
    "message": "Class 'dataProcessor' should use PascalCase.",
    "suggestion": "Rename to 'DataProcessor'.",
    "analyzer": "naming",
    "severity": "warning",
    "file_path": "c.py",
}


def _index(session_factory=None, threshold=None) -> FindingIndex:
    threshold = get_settings().cluster_distance_threshold if threshold is None else threshold
    return FindingIndex(HashingEmbeddingModel(), threshold, session_factory)


def _seed(index: FindingIndex, run_id: str, findings: list[dict]) -> None:
    """Add a past run to the corpus and re-cluster, as a startup load would."""
    vectors = index.embed(findings)
    cluster_ids = [index.assign_cluster(v)[0] for v in vectors]
    index.add_run(run_id, findings, vectors, cluster_ids)
    index.recluster()


class TestFindingText:
    def test_describes_the_issue_not_the_location(self):
        text = finding_text(EVAL)
        assert text.startswith("bug_risk: Use of eval()/exec()")
        assert "ast.literal_eval" in text
        assert "a.py" not in text


class TestSearch:
    def test_exact_repeat_in_another_file_is_returned(self):
        """The same rule firing again is the point of the search; identical
        messages are not skipped as self-matches."""
        index = _index()
        _seed(index, "run-1", [EVAL, EXCEPT])
        query = {**EVAL, "file_path": "other.py"}
        analysis = analyze_findings([query], index)
        hits = analysis.results[0].similar_findings
        assert hits, "an identical past finding must be reported"
        assert hits[0].file_path == "a.py"
        assert hits[0].run_id == "run-1"
        assert hits[0].similarity_score == pytest.approx(1.0, abs=1e-5)
        assert hits[0].lexical_score == pytest.approx(1.0, abs=1e-5)
        assert hits[0].combined_score == pytest.approx(1.0, abs=1e-4)

    def test_at_most_one_hit_per_past_run(self):
        index = _index()
        _seed(index, "run-1", [EVAL, {**EVAL, "file_path": "x.py"}, {**EVAL, "file_path": "y.py"}])
        _seed(index, "run-2", [EVAL])
        analysis = analyze_findings([EVAL], index)
        run_ids = [h.run_id for h in analysis.results[0].similar_findings]
        assert sorted(run_ids) == ["run-1", "run-2"]

    def test_unrelated_findings_are_not_reported(self):
        index = _index()
        _seed(index, "run-1", [NAMING])
        analysis = analyze_findings([EVAL], index)
        assert analysis.results[0].similar_findings == []

    def test_results_carry_both_scores_and_method(self):
        index = _index()
        _seed(index, "run-1", [EVAL])
        result = analyze_findings([EVAL], index).results[0].to_dict()
        hit = result["similar_findings"][0]
        assert {"similarity_score", "lexical_score", "combined_score", "cluster_id"} <= set(hit)
        assert result["method"] == "hashing+tfidf"

    def test_empty_corpus(self):
        analysis = analyze_findings([EVAL], _index())
        assert analysis.results[0].similar_findings == []
        assert analysis.results[0].times_seen_before == 0
        assert analysis.cluster_ids == [1]


class TestClustering:
    def test_recluster_groups_repeats_and_separates_different_rules(self):
        index = _index()
        _seed(index, "run-1", [EVAL, EXCEPT, NAMING])
        _seed(index, "run-2", [{**EVAL, "file_path": "z.py"}, NAMING])
        index.recluster()
        clusters = [index.entry(i).cluster_id for i in range(len(index))]
        assert clusters[0] == clusters[3]  # eval twice
        assert clusters[2] == clusters[4]  # naming twice
        assert len({clusters[0], clusters[1], clusters[2]}) == 3
        assert sorted(set(clusters)) == [1, 2, 3]  # renumbered from 1

    def test_recluster_is_deterministic(self):
        a, b = _index(), _index()
        for idx in (a, b):
            _seed(idx, "run-1", [EVAL, EXCEPT, NAMING, {**EVAL, "file_path": "q.py"}])
            idx.recluster()
        assert [a.entry(i).cluster_id for i in range(4)] == [
            b.entry(i).cluster_id for i in range(4)
        ]

    def test_new_finding_joins_existing_cluster_and_counts_repeats(self):
        index = _index()
        _seed(index, "run-1", [EVAL, EVAL, EXCEPT])
        analysis = analyze_findings([{**EVAL, "file_path": "new.py"}, NAMING], index)
        eval_result, naming_result = analysis.results
        assert eval_result.times_seen_before == 2
        assert eval_result.cluster_id == index.entry(0).cluster_id
        assert naming_result.times_seen_before == 0
        assert naming_result.cluster_id not in {e.cluster_id for e in index._entries}

    def test_identical_findings_in_one_run_share_a_new_cluster(self):
        index = _index()
        analysis = analyze_findings([EVAL, {**EVAL, "file_path": "b.py"}, NAMING], index)
        assert analysis.cluster_ids[0] == analysis.cluster_ids[1]
        assert analysis.cluster_ids[2] != analysis.cluster_ids[0]

    def test_threshold_controls_grouping(self):
        strict = _index(threshold=0.01)
        _seed(strict, "run-1", [EVAL, {**EVAL, "message": EVAL["message"] + " Really."}])
        strict.recluster()
        assert strict.entry(0).cluster_id != strict.entry(1).cluster_id

        loose = _index(threshold=0.9)
        _seed(loose, "run-1", [EVAL, {**EVAL, "message": EVAL["message"] + " Really."}])
        loose.recluster()
        assert loose.entry(0).cluster_id == loose.entry(1).cluster_id


class TestSqliteFallback:
    """On SQLite the corpus lives in memory and search is numpy cosine."""

    def test_corpus_loads_from_database_and_cluster_ids_are_persisted(
        self, session_factory, db_session
    ):
        writer = _index(session_factory)
        set_finding_index(writer)
        result = run_analysis(SAMPLE_PYTHON_DIFF, enable_ml=True)
        run = persist_run(db_session, result, source="test")
        result2 = run_analysis(SAMPLE_JAVA_DIFF, enable_ml=True)
        persist_run(db_session, result2, source="test")

        stored = db_session.query(AnalysisFinding).all()
        assert stored and all(f.embedding is not None for f in stored)
        assert all(f.embedding_model == "hashing-char-ngram-v1" for f in stored)
        assert all(f.cluster_id is not None for f in stored)
        assert all(f.category is not None for f in stored)
        assert stored[0].embedding.shape == (384,)

        # A fresh process: the index is rebuilt from the database.
        fresh = _index(session_factory)
        fresh.load_from_db()
        assert fresh.loaded_from_db is True
        assert len(fresh) == len(stored)
        assert fresh.stats()["search_backend"] == "numpy"
        assert fresh.stats()["clusters"] >= 2

        # Re-clustering on load writes the ids back; identical findings share one.
        by_message = {}
        for f in db_session.query(AnalysisFinding).all():
            by_message.setdefault(f.message, set()).add(f.cluster_id)
        assert all(len(ids) == 1 for ids in by_message.values())

        # The rebuilt corpus answers a repeat of the first run's findings.
        analysis = analyze_findings(result.all_findings()[:1], fresh)
        assert analysis.results[0].times_seen_before >= 1
        assert analysis.results[0].similar_findings[0].run_id == str(run.id)

    def test_rows_from_another_model_are_re_embedded(self, session_factory, db_session):
        set_finding_index(_index(session_factory))
        result = run_analysis(SAMPLE_PYTHON_DIFF, enable_ml=True)
        persist_run(db_session, result, source="test")
        db_session.query(AnalysisFinding).update({"embedding_model": "old-model"})
        db_session.commit()

        fresh = _index(session_factory)
        fresh.load_from_db()
        models = {f.embedding_model for f in db_session.query(AnalysisFinding).all()}
        assert models == {"hashing-char-ngram-v1"}
        assert len(fresh) > 0

    def test_missing_tables_leave_the_index_empty(self, caplog):
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker

        engine = create_engine("sqlite://")
        index = _index(sessionmaker(bind=engine))
        with caplog.at_level("WARNING"):
            index.load_from_db()
        assert len(index) == 0
        assert "could not load the corpus" in caplog.text


class TestPgvectorQuery:
    def test_neighbour_query_uses_the_cosine_operator(self):
        """The PostgreSQL path is a `<=>` ordered query; compile it for that dialect."""
        captured = {}

        class FakeSession:
            def execute(self, stmt):
                captured["sql"] = str(stmt.compile(dialect=postgresql.dialect()))

                class Result:
                    def all(self_inner):
                        return []

                return Result()

        rows = pgvector_neighbours(
            FakeSession(), AnalysisFinding, np.zeros(384, dtype=np.float32), "BAAI/x", 5
        )
        assert rows == []
        sql = captured["sql"]
        assert "<=>" in sql
        assert "embedding_model" in sql
        assert "ORDER BY" in sql and "LIMIT" in sql


class TestEmbeddings:
    def test_hashing_vectors_are_normalised_and_deterministic(self):
        model = HashingEmbeddingModel()
        vectors = model.embed(["eval is unsafe", "eval is unsafe", "naming"])
        assert vectors.shape == (3, 384)
        assert np.allclose(np.linalg.norm(vectors, axis=1), 1.0)
        assert np.allclose(vectors[0], vectors[1])
        assert vectors[0] @ vectors[2] < 0.5

    def test_tests_run_on_the_hashing_backend(self):
        assert get_embedding_model().name == "hashing-char-ngram-v1"

    def test_fastembed_failure_falls_back_loudly(self, monkeypatch, caplog):
        from app.ml import embeddings

        monkeypatch.setenv("EMBEDDING_BACKEND", "fastembed")
        get_settings.cache_clear()
        embeddings.reset_embedding_model()

        def boom(self, *args, **kwargs):
            raise RuntimeError("no network")

        monkeypatch.setattr(embeddings.FastEmbedModel, "__init__", boom)
        try:
            with caplog.at_level("ERROR"):
                model = embeddings.get_embedding_model()
            assert isinstance(model, HashingEmbeddingModel)
            status = embeddings.embedding_status()
            assert status["backend"] == "hashing"
            assert "no network" in status["fallback_reason"]
            assert "falling back" in caplog.text
        finally:
            get_settings.cache_clear()
            embeddings.reset_embedding_model()


class TestApiSurface:
    def test_repeat_analysis_reports_seen_before(self, client):
        first = client.post("/api/v1/analyze", json={"diff": SAMPLE_PYTHON_DIFF}).json()
        assert first["summary"]["findings_seen_before"] == 0
        assert all(f["times_seen_before"] == 0 for f in first["bug_risk_findings"])

        second = client.post("/api/v1/analyze", json={"diff": SAMPLE_PYTHON_DIFF}).json()
        assert second["summary"]["findings_seen_before"] == second["summary"]["total_findings"]
        assert all(f["times_seen_before"] >= 1 for f in second["bug_risk_findings"])
        assert second["similar_findings"], "related past findings are surfaced"
        hit = second["similar_findings"][0]["similar_findings"][0]
        assert hit["run_id"] == first["run_id"]

        detail = client.get(f"/api/v1/runs/{second['run_id']}").json()
        assert detail["risk_score"]["model_type"] == "gradient_boosting"
        assert all(f["cluster_id"] is not None for f in detail["findings"])
        assert all(f["category"] for f in detail["findings"])

    def test_ml_status_reports_index_and_embeddings(self, client):
        status = client.get("/api/v1/ml/status").json()
        assert status["embeddings"]["backend"] == "hashing"
        assert status["similarity_index"]["search_backend"] == "numpy"
        assert status["similarity_index"]["loaded_from_db"] is True
