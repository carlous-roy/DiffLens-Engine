# DiffLens

<p>
  <a href="https://difflens.roycarlous.com"><img src="https://img.shields.io/badge/Live_demo-difflens.roycarlous.com-22C55E?style=flat-square" alt="Live demo" /></a>
  <img src="https://img.shields.io/badge/Python-3776AB?style=flat-square&logo=python&logoColor=white" alt="Python" />
  <img src="https://img.shields.io/badge/FastAPI-009688?style=flat-square&logo=fastapi&logoColor=white" alt="FastAPI" />
  <img src="https://img.shields.io/badge/scikit--learn-F7931E?style=flat-square&logo=scikitlearn&logoColor=white" alt="scikit-learn" />
  <img src="https://img.shields.io/badge/PostgreSQL-4169E1?style=flat-square&logo=postgresql&logoColor=white" alt="PostgreSQL" />
  <img src="https://img.shields.io/badge/Docker-2496ED?style=flat-square&logo=docker&logoColor=white" alt="Docker" />
</p>

A code review engine that parses the code rather than pattern-matching the text.

Many review tools match patterns against source text. DiffLens parses Python and Java into
**Tree-sitter ASTs** first, so "this function has a cyclomatic complexity of 19" is a measurement
rather than an estimate. On top of that sits a **weighted risk score** built from diff size, severity
distribution and complexity signals, **keyword-rule categorization** that sorts findings into
security, correctness, performance, maintainability and style, and **TF-IDF similarity search** that
surfaces issues this codebase has already seen.

An optional local **CodeLlama** pass rewrites findings as review comments, and GitHub webhooks run
the analysis on every pull request: commit status, a summary comment with a findings table, and
inline comments on the high-severity findings.

The AST layer is what makes the findings usable. A regex can tell you the word `eval` appears; it
cannot tell you whether that is inside a comment, a string literal, or a code path reachable from
user input. The parse tree can. Every finding is anchored to a node, which is also how the inline PR
comments land on the correct line.

[Live demo](https://difflens.roycarlous.com) · [Portfolio](https://roycarlous.com)

---

## Features

### Static Analysis
- **Cyclomatic Complexity**: Tree-sitter AST parsing detects overly complex functions and deep nesting in Python and Java code.
- **Naming Conventions**: validates PEP 8 (Python) and Java naming standards for classes, functions, variables, and constants.
- **Bug Risk Detection**: 15 rules (9 Python, 6 Java) identify common anti-patterns: bare excepts, `eval()` / `exec()` usage, mutable default arguments, wildcard imports, `global` state, `.equals(null)`, empty catch blocks, string comparison with `==`, and leftover TODO/FIXME markers.

### Scoring and Classification
- **Risk Scoring**: a weighted heuristic scores overall change risk (low / medium / high) over a 15-feature vector extracted from the diff and its findings: diff size, severity distribution, max and average complexity, churn ratio, naming violations, bug-risk density, and security-sensitive patterns. Every score ships with the contributing factors that produced it, so the number is explainable rather than opaque.
- **Auto-Categorization**: regex keyword rules classify findings into security, correctness, performance, maintainability, and style, falling back to a per-analyzer default when no rule matches.
- **Similarity Search**: TF-IDF vectors and cosine similarity find historically similar findings to surface recurring issues across your codebase. A sentence-transformers path is wired in and used automatically if that optional dependency is installed.
- **Smart Review**: optional LLM-powered narrative review via Ollama / CodeLlama that rewrites findings as prose review comments.

### GitHub Integration
- **Webhook Listener**: automatically analyzes pull requests when they are opened, synchronized, or reopened.
- **Commit Statuses**: sets pending/success/failure status on the PR head commit.
- **Summary Comments**: posts a detailed Markdown comment with findings table, risk score, severity breakdown, and category analysis.
- **Inline Review Comments**: adds code-level annotations on high-severity findings.
- **Check Run Annotations**: optional Checks API integration for inline annotations in the Files Changed tab.
- **Manual Trigger**: analyze any PR on demand via the dashboard or REST API.

### Dashboard
- **Analyze Page**: paste a unified diff or raw code for instant analysis with visualizations.
- **GitHub Page**: view analyzed PRs, trigger manual analysis, see integration status.
- **History Page**: browse all past analysis runs with source filtering (API / GitHub).
- **Run Detail Page**: deep dive into findings grouped by file with severity breakdown.
- **Status Page**: real-time health checks for all services (DB, LLM, ML features).

### Raw Code Auto-Detection
Paste plain Python or Java code (not just diffs), the engine auto-detects the language, wraps it into a synthetic diff, and runs the full analysis pipeline.

---

## Architecture

```
┌──────────────────┐     ┌──────────────────────────────────────────────┐
│  React Dashboard │────>│  FastAPI Backend (:8000)                     │
│  (:3000)         │     │                                              │
└──────────────────┘     │  /api/v1/analyze        -> Analysis pipeline │
                         │  /api/v1/github/webhook -> PR auto-analysis  │
┌──────────────────┐     │  /api/v1/runs           -> History & details │
│  GitHub          │────>│  /api/v1/github/status  -> Integration health│
│  Webhooks        │     └──────────┬───────────────────────────────────┘
└──────────────────┘                │
                         ┌──────────▼──────────┐    ┌──────────────┐
                         │  PostgreSQL (:5432)  │    │ Ollama (opt) │
                         └─────────────────────┘    └──────────────┘
```

---

## Quick Start

### Prerequisites

- [Docker](https://docs.docker.com/get-docker/) and Docker Compose
- (Optional) [Ollama](https://ollama.com) for LLM-powered smart reviews

### 1. Clone the repository

```bash
git clone https://github.com/carlous-roy/DiffLens-Engine.git
cd DiffLens-Engine
```

### 2. Configure environment

```bash
cp .env.example .env
# Default values work for local development. No edits needed.
# To enable GitHub integration, add your token and webhook secret.
```

### 3. Start the stack

```bash
docker compose up --build -d
```

This starts four containers:

| Container | Port | Description |
|-----------|------|-------------|
| `difflens-app` | 8000 | FastAPI backend with Uvicorn |
| `difflens-frontend` | 3000 | React dashboard served via Nginx |
| `difflens-db` | 5432 | PostgreSQL 15 |
| `difflens-ollama` | 11434 | Ollama LLM server (optional) |

### 4. Open the dashboard

Visit **http://localhost:3000**, paste code or load the sample diff and click Analyze.

### 5. Verify everything is running

```bash
docker compose ps
docker compose logs app --tail 20
curl http://localhost:8000/api/v1/health
```

---

## GitHub Webhook Setup

### 1. Generate a Personal Access Token

Go to [github.com/settings/tokens?type=beta](https://github.com/settings/tokens?type=beta) and create a fine-grained token with:
- Pull requests: Read and write
- Commit statuses: Read and write
- Contents: Read
- Checks: Read and write (optional)

### 2. Generate a webhook secret

```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

### 3. Update `.env`

```env
GITHUB_TOKEN=REPLACE_WITH_YOUR_GITHUB_TOKEN
GITHUB_WEBHOOK_SECRET=REPLACE_WITH_YOUR_WEBHOOK_SECRET
```

### 4. Expose DiffLens to the internet

```bash
ngrok http 8000
```

### 5. Configure the webhook on GitHub

Go to your repo, then Settings, Webhooks, Add webhook:
- Payload URL: `https://your-ngrok-url/api/v1/github/webhook`
- Content type: `application/json`
- Secret: paste your webhook secret
- Events: select Pull requests only

### 6. Test it

Open a pull request, DiffLens will automatically analyze it and post results.

---

## API Reference

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/v1/analyze` | POST | Analyze a diff or raw code |
| `/api/v1/smart-review` | POST | Standalone LLM code review |
| `/api/v1/runs` | GET | List recent analysis runs |
| `/api/v1/runs/{id}` | GET | Get run details with findings |
| `/api/v1/health` | GET | Service health check |
| `/api/v1/ml/status` | GET | ML feature availability |
| `/api/v1/github/webhook` | POST | Receive GitHub webhook events |
| `/api/v1/github/status` | GET | GitHub integration health |
| `/api/v1/github/prs` | GET | List analyzed PRs |
| `/api/v1/github/analyze-pr` | POST | Manually trigger PR analysis |

Interactive docs available at http://localhost:8000/docs (Swagger UI).

---

## Project Structure

```
DiffLens-Engine/
├── app/
│   ├── analysis/              # Static analyzers
│   │   ├── diff_parser.py         # Unified diff parser + raw code auto-detect
│   │   ├── complexity.py          # Cyclomatic complexity via Tree-sitter
│   │   ├── naming.py              # PEP 8 / Java naming conventions
│   │   ├── bug_risk.py            # Bug risk pattern detection
│   │   └── pipeline.py            # Orchestrates analyzers + ML modules
│   ├── ml/                    # Machine learning modules
│   │   ├── risk_scoring.py        # Weighted-heuristic risk scoring
│   │   ├── categorization.py      # Keyword-rule finding categorization
│   │   ├── similarity.py          # TF-IDF + cosine similarity search
│   │   ├── smart_review.py        # LLM-powered narrative review
│   │   └── llm_provider.py        # Pluggable LLM provider abstraction
│   ├── github/                # GitHub integration
│   │   ├── webhook.py             # HMAC signature verification + event dispatch
│   │   ├── client.py              # Async GitHub REST API client
│   │   ├── pr_analyzer.py         # Full PR analysis orchestration
│   │   ├── formatter.py           # Markdown formatting for GitHub output
│   │   └── routes.py              # Webhook endpoint + manual trigger
│   ├── api/                   # Core REST API
│   │   ├── routes.py              # /analyze, /runs, /health, /ml/status
│   │   └── schemas.py             # Pydantic request/response models
│   ├── db/                    # Database layer
│   │   ├── models.py              # SQLAlchemy models (runs, findings, PRs)
│   │   └── __init__.py            # Engine + session factory
│   ├── config/                # Environment-based configuration
│   └── main.py                # FastAPI app entrypoint
├── frontend/                  # React dashboard
│   └── src/
│       ├── pages/                 # Analyze, GitHub, History, RunDetail, Status
│       ├── components/            # Badges, Charts, RiskGauge, FindingsList
│       ├── api.js                 # Backend API client
│       └── index.css              # Tailwind + custom design system
├── alembic/                   # Database migrations
├── tests/                     # 14 test files covering all modules
├── docker-compose.yml         # Full stack orchestration
├── Dockerfile                 # Backend container
├── .env.example               # Documented environment variables
├── requirements.txt           # Python dependencies
└── README.md
```

---

## Configuration

All settings are controlled via environment variables. See `.env.example` for the full list with descriptions.

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `postgresql://...` | PostgreSQL connection string |
| `ML_ENABLE_SMART_REVIEW` | `true` | Enable LLM-powered code review |
| `ML_ENABLE_RISK_SCORING` | `true` | Enable risk score prediction |
| `ML_ENABLE_SIMILARITY` | `true` | Enable similar finding search |
| `ML_ENABLE_CATEGORIZATION` | `true` | Enable auto-categorization |
| `DASHBOARD_URL` | `http://localhost:3000` | Frontend URL reported by the API root |
| `CORS_ORIGINS` | `http://localhost:3000,http://127.0.0.1:3000` | Comma-separated origins allowed to call the API |
| `GITHUB_TOKEN` | _(unset)_ | GitHub PAT for posting results |
| `GITHUB_WEBHOOK_SECRET` | _(unset)_ | HMAC secret for webhook verification. Required: the webhook endpoint rejects unsigned deliveries. |
| `GITHUB_POST_COMMENT` | `true` | Post summary comments on PRs |
| `GITHUB_POST_REVIEW` | `true` | Post inline review comments |
| `GITHUB_USE_CHECKS_API` | `false` | Use Checks API for annotations |

---

## Development

### Running without Docker

```bash
# Backend
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000

# Frontend
cd frontend && npm install && npm run dev

# Database: point DATABASE_URL to a local Postgres instance
```

### Running tests

```bash
pytest -v
```

Tests use SQLite in-memory and mock external services (GitHub API, Ollama).

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | FastAPI, SQLAlchemy, Alembic, Tree-sitter, scikit-learn |
| Frontend | React 18, Vite, Tailwind CSS, Recharts, Lucide Icons |
| Database | PostgreSQL 15 |
| LLM | Ollama + CodeLlama 7B (optional) |
| Infrastructure | Docker Compose, Nginx |

---

## What I'd do differently

- **Risk scoring is a weighted heuristic, not a learned model.** The weights are hand-tuned over the
  extracted feature vector, because there is no corpus of "this PR caused an incident" to train
  against. The feature extraction is built so a model can take over — `TrainedRiskModel` already
  wraps the scikit-learn fit/predict path — but nothing is trained today, and calling the output a
  *prediction* would be overselling it. Real labels would come from linking merged PRs to subsequent
  reverts or incident tickets.
- **Two languages only.** Tree-sitter has grammars for dozens; the analysis rules are what is
  Python- and Java-specific. Adding a language means writing its complexity and bug-risk rules, not
  just dropping in a grammar.
- **Similarity search is a flat scan.** Every query re-scores the whole corpus. Fine at this size,
  wrong past a few thousand findings. The fix is a vector index — pgvector, with real embeddings in
  place of TF-IDF — rather than a rewrite of the search itself.
- **The LLM pass is unevaluated.** It produces comments that read well, and I have no measurement of
  whether they are *correct* more often than they are fluent. That gap is exactly the one worth
  closing next, and it needs a golden set with published numbers rather than a demo.

## License

MIT
