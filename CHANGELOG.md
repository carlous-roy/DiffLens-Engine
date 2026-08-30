# Changelog

## [1.0.0] — 2025-03-04

### Features
- Static analysis pipeline: cyclomatic complexity (Tree-sitter AST), naming convention checks (PEP 8, Java), bug risk pattern detection.
- Risk scoring via a weighted heuristic over a 15-feature vector extracted from the diff and its findings, reported with its contributing factors.
- Auto-categorization of findings into security, correctness, performance, maintainability, and style via regex keyword rules.
- Similarity search using TF-IDF vectors and cosine similarity to find historically similar findings.
- Smart review via Ollama / CodeLlama for LLM-powered narrative code review.
- GitHub webhook integration: automatic PR analysis on open/sync/reopen, commit statuses, summary comments, inline review comments, and check run annotations.
- Manual PR analysis trigger via dashboard and REST API.
- Raw code auto-detection: accepts plain Python/Java code in addition to unified diffs.
- React dashboard with analysis visualization, GitHub integration page, run history, and system status.
- Full Docker Compose deployment with PostgreSQL, Nginx, and optional Ollama.
- Comprehensive test suite (14 test files).
- Database migrations via Alembic.
