"""Tests for the similarity search module."""
from app.ml.similarity import FindingEmbedder, get_embedder

class TestFindingEmbedder:
    def setup_method(self):
        self.embedder = FindingEmbedder()

    def test_add_findings(self):
        findings = [
            {"message": "eval() is dangerous", "file_path": "a.py",
             "analyzer": "bug_risk", "severity": "critical"},
            {"message": "Function too complex", "file_path": "b.py",
             "analyzer": "complexity", "severity": "warning"},
        ]
        self.embedder.add_findings(findings, run_id="run-1")
        assert len(self.embedder._corpus) == 2
        assert len(self.embedder._corpus_texts) == 2

    def test_empty_corpus_returns_no_results(self):
        finding = {"message": "eval() detected", "analyzer": "bug_risk", "severity": "critical"}
        result = self.embedder.find_similar(finding)
        assert len(result.similar_findings) == 0
        assert result.error is not None

    def test_find_similar_with_tfidf(self):
        """Test TF-IDF based similarity (always available with scikit-learn)."""
        corpus_findings = [
            {"message": "Use of eval() is a security risk", "file_path": "a.py",
             "analyzer": "bug_risk", "severity": "critical", "suggestion": "Use ast.literal_eval"},
            {"message": "Function has high cyclomatic complexity of 15", "file_path": "b.py",
             "analyzer": "complexity", "severity": "error", "suggestion": "Refactor"},
            {"message": "Class name should use PascalCase", "file_path": "c.py",
             "analyzer": "naming", "severity": "warning", "suggestion": "Rename"},
            {"message": "Bare except clause catches all exceptions", "file_path": "d.py",
             "analyzer": "bug_risk", "severity": "warning", "suggestion": "Use specific exceptions"},
            {"message": "exec() call detected, potential security issue", "file_path": "e.py",
             "analyzer": "bug_risk", "severity": "critical", "suggestion": "Remove exec"},
        ]
        self.embedder.add_findings(corpus_findings, run_id="run-1")

        # Search for something similar to eval/exec
        query = {"message": "eval() usage found in code", "analyzer": "bug_risk", "severity": "critical"}
        result = self.embedder.find_similar(query, top_k=3, threshold=0.1)

        assert result.method in ("sbert", "tfidf")
        assert len(result.similar_findings) > 0
        # The eval/exec findings should be most similar
        top_match = result.similar_findings[0]
        assert "eval" in top_match.message.lower() or "exec" in top_match.message.lower()

    def test_clear_corpus(self):
        self.embedder.add_findings([
            {"message": "test", "file_path": "a.py", "analyzer": "x", "severity": "info"},
        ])
        assert len(self.embedder._corpus) == 1
        self.embedder.clear_corpus()
        assert len(self.embedder._corpus) == 0

    def test_result_to_dict(self):
        self.embedder.add_findings([
            {"message": "eval danger", "file_path": "a.py",
             "analyzer": "bug_risk", "severity": "critical", "suggestion": "fix it"},
        ], run_id="run-1")

        query = {"message": "eval danger", "analyzer": "bug_risk", "severity": "critical"}
        result = self.embedder.find_similar(query, threshold=0.0)
        d = result.to_dict()
        assert "query_message" in d
        assert "similar_findings" in d
        assert "method" in d
