# Changelog

Dates are the dates of the commits on the `main` branch.

## Unreleased

### Static analysis
- Rules run over a copy of the source in which Tree-sitter comment and string
  nodes are blanked, so nothing matches inside comments or string literals.
- Naming checks read names from definition nodes; variables, parameters,
  fields and locals are checked; constructors are no longer taken for methods.
- Nesting depth per function, computed from the tree, reported from depth 4.
- Findings on modified files carry real new-file line numbers, mapped through
  the hunk headers; inline PR comments now land.
- Iterative tree walks; deeply nested input no longer exhausts the stack.
- Complexity findings are categorised as maintainability, not performance.

### Risk scoring
- A `HistGradientBoostingClassifier` trained on ApacheJIT with isotonic
  calibration replaces the hand-weighted heuristic; `model_type` reports
  `gradient_boosting`, with per-feature attributions and a documented
  noisy-OR combination with the static findings. Training script, artefact and
  generated model card (`docs/MODEL_CARD.md`) are committed. The heuristic
  remains only as a loudly logged fallback when the artefact is missing.
- The `ML_ENABLE_*` flags switch their modules off instead of being reported only.

### Similarity and clustering
- Findings are embedded with fastembed (BAAI/bge-small-en-v1.5) and stored with
  a cluster id; pgvector on PostgreSQL, numpy on SQLite; TF-IDF kept for lexical
  similarity. Exact repeats are reported (the `> 0.99` skip is gone), at most
  one hit per past run, and the corpus is loaded from the database at startup.
- Agglomerative clustering of repeat findings; "seen N times before" in the
  API, the PR comment, inline reviews and the dashboard.

### GitHub
- `X-API-Key` required on the manual PR trigger, the LLM review and `/analyze`
  with the LLM pass; owner, repo, SHA and number validation; diff size and
  `limit` bounds; 404 for malformed run ids; non-ASCII signatures rejected
  cleanly; webhook replay protection through stored delivery ids.
- The summary comment is updated in place on later pushes; high-risk reviews on
  the token owner's own pull requests are posted as comments.
- Repository-history features for the risk model from the base branch.
- The pull request flow is tested end to end against a fake GitHub API.

### Operations
- Migrations run at startup in development (`AUTO_MIGRATE`), so a fresh clone
  works; logging follows `LOG_LEVEL`; analysis runs off the event loop.
- Non-root images on pinned base tags, `.dockerignore`, unpublished database
  and Ollama ports, localhost binding by default, a development override file.
- Dependencies upgraded (FastAPI 0.141, Starlette 1.6, scikit-learn 1.9,
  Vite 7, React Router 7); development requirements split; frontend lockfile
  committed; GitHub Actions CI (ruff, pytest with coverage, frontend and
  Docker builds); hermetic test suite.

## 1.0.0 (2026-03-15; README and migration fixes on 2026-08-30)

- Static analysis pipeline: cyclomatic complexity via Tree-sitter, naming
  convention checks, bug-risk patterns.
- Weighted-heuristic risk score, keyword categorisation, TF-IDF similarity
  search over an in-memory corpus.
- Optional Ollama/CodeLlama review pass.
- GitHub webhook integration: commit statuses, summary comment, review
  comments, optional check runs; manual trigger.
- React dashboard, Docker Compose stack, Alembic migrations, 14-file test suite.
