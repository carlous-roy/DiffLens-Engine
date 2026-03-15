# DiffLens

**ML-powered code review intelligence.** Static analysis, risk scoring, auto-categorization, and GitHub integration — all in a containerized stack you can run locally in minutes.

**[Try the Live Demo](https://difflens.roycarlous.com)**

---

## Features

### Static Analysis
- **Cyclomatic Complexity** — Tree-sitter AST parsing detects overly complex functions and deep nesting in Python and Java code.
- **Naming Conventions** — Validates PEP 8 (Python) and Java naming standards for classes, functions, variables, and constants.
- **Bug Risk Detection** — Pattern matching identifies common anti-patterns: bare excepts, `eval()` usage, mutable default arguments, wildcard imports, hardcoded credentials, and more.

### ML-Powered Intelligence
- **Risk Scoring** — A scikit-learn gradient boosting model predicts overall change risk (low / medium / high) based on extracted features like diff size, severity distribution, and complexity.
- **Auto-Categorization** — TF-IDF keyword matching classifies findings into security, correctness, performance, maintainability, and style.
- **Similarity Search** — Lightweight embeddings find historically similar findings to surface recurring issues across your codebase.
- **Smart Review** — Optional LLM-powered narrative review via Ollama / CodeLlama that produces human-quality review comments.

### GitHub Integration
- **Webhook Listener** — Automatically analyzes pull requests when they are opened, synchronized, or reopened.
- **Commit Statuses** — Sets pending/success/failure status on the PR head commit.
- **Summary Comments** — Posts a detailed Markdown comment with findings table, risk score, severity breakdown, and category analysis.
- **Inline Review Comments** — Adds code-level annotations on high-severity findings.
- **Check Run Annotations** — Optional Checks API integration for inline annotations in the Files Changed tab.
- **Manual Trigger** — Analyze any PR on demand via the dashboard or REST API.

### Dashboard
- **Analyze Page** — Paste a unified diff or raw code for instant analysis with visualizations.
- **GitHub Page** — View analyzed PRs, trigger manual analysis, see integration status.
- **History Page** — Browse all past analysis runs with source filtering (API / GitHub).
- **Run Detail Page** — Deep dive into findings grouped by file with severity breakdown.
- **Status Page** — Real-time health checks for all services (DB, LLM, ML features).

### Raw Code Auto-Detection
Paste plain Python or Java code (not just diffs) — the engine auto-detects the language, wraps it into a synthetic diff, and runs the full analysis pipeline.

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
# Default values work for local development — no edits needed.
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

Visit **http://localhost:3000** — paste code or load the sample diff and click Analyze.

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

Open a pull request — DiffLens will automatically analyze it and post results.

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
│   │   ├── risk_scoring.py        # Gradient boosting risk prediction
│   │   ├── categorization.py      # TF-IDF finding categorization
│   │   ├── similarity.py          # Embedding-based similar finding search
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
| `GITHUB_TOKEN` | — | GitHub PAT for posting results |
| `GITHUB_WEBHOOK_SECRET` | — | HMAC secret for webhook verification |
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

# Database — point DATABASE_URL to a local Postgres instance
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
| Infrastructure | Docker Compose, Nginx, GitHub Actions |

---

## License

MIT — see [LICENSE](LICENSE).

---

Built by [Roy Carlous Christudass](https://roycarlous.com) | [Live Demo](https://difflens.roycarlous.com)
