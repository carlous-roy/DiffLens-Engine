# Changelog

## [1.0.0] — 2025-03-04

### Features
- Static analysis pipeline: cyclomatic complexity (Tree-sitter AST), naming convention checks (PEP 8, Java), bug risk pattern detection.
- ML-powered risk scoring using scikit-learn gradient boosting.
- Auto-categorization of findings into security, correctness, performance, maintainability, and style via TF-IDF.
- Similarity search using lightweight embeddings to find historically similar findings.
- Smart review via Ollama / CodeLlama for LLM-powered narrative code review.
- GitHub webhook integration: automatic PR analysis on open/sync/reopen, commit statuses, summary comments, inline review comments, and check run annotations.
- Manual PR analysis trigger via dashboard and REST API.
- Raw code auto-detection: accepts plain Python/Java code in addition to unified diffs.
- React dashboard with analysis visualization, GitHub integration page, run history, and system status.
- Full Docker Compose deployment with PostgreSQL, Nginx, and optional Ollama.
- Comprehensive test suite (14 test files).
- Database migrations via Alembic.
