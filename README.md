# DiffLens

<p>
  <a href="https://difflens.roycarlous.com"><img src="https://img.shields.io/badge/Browser_demo-difflens.roycarlous.com-22C55E?style=flat-square" alt="Browser demo" /></a>
  <img src="https://img.shields.io/badge/Python-3776AB?style=flat-square&logo=python&logoColor=white" alt="Python" />
  <img src="https://img.shields.io/badge/FastAPI-009688?style=flat-square&logo=fastapi&logoColor=white" alt="FastAPI" />
  <img src="https://img.shields.io/badge/scikit--learn-F7931E?style=flat-square&logo=scikitlearn&logoColor=white" alt="scikit-learn" />
  <img src="https://img.shields.io/badge/PostgreSQL-4169E1?style=flat-square&logo=postgresql&logoColor=white" alt="PostgreSQL" />
  <img src="https://img.shields.io/badge/Docker-2496ED?style=flat-square&logo=docker&logoColor=white" alt="Docker" />
</p>

DiffLens reviews Python and Java diffs. It parses the changed code with
Tree-sitter, measures cyclomatic complexity and nesting depth, runs naming and
bug-risk rules that only match code (never comments or strings), scores the
change with a gradient-boosting model trained on defect-inducing commits,
finds related findings from earlier runs, and posts the result on GitHub pull
requests as a commit status, a summary comment that is updated on each push,
and inline review comments at the right lines.

The browser demo at difflens.roycarlous.com is a separate JavaScript build of
the rule engine; it does not run this service or its risk model.

---

## What it does

### Static analysis

- **Parsing.** Each changed file is parsed with Tree-sitter (`tree-sitter-python`,
  `tree-sitter-java`). The analyzers see the hunks as they read after the change
  (context plus added lines) and report only on added lines. Line numbers are
  mapped back to the new file through the hunk headers, so a finding on a
  modified file points at the real line, which is what inline PR comments need.
- **Cyclomatic complexity and nesting depth** per function or method, computed
  from the syntax tree. Decision points (`if`, `elif`, loops, `except`, `case`,
  boolean operators, comprehensions, ternaries; in Java also `&&`/`||` and
  `case` groups) add to the complexity. Nesting depth counts nested control-flow
  statements; an `else if` chain is one level. A depth of four or more is
  reported as its own finding. A function is measured when its definition line
  is part of the change.
- **Bug-risk rules.** Nine Python and six Java rules (`eval()`/`exec()`, bare
  `except`, silently swallowed exceptions, mutable default arguments,
  `== None`, `global`, wildcard imports, `.equals(null)`, empty `catch`, string
  comparison with `==`, `System.out`, manual threads, TODO markers). The rules
  are line patterns, but they run over a masked copy of the source in which the
  syntax tree's comment and string-content nodes are blanked out. `eval(` in a
  comment or inside a string literal is not a finding; `eval(` inside an
  f-string `{...}` is, because that is code. TODO rules run on comment nodes
  only.
- **Naming.** Class, function, method, field, parameter and variable names are
  read from definition nodes: PEP 8 style for Python (snake_case functions,
  variables and parameters, PascalCase classes, SCREAMING_SNAKE_CASE module
  constants; CapWords type aliases are allowed) and Java style (PascalCase
  types, camelCase methods, fields and locals, SCREAMING_SNAKE_CASE for
  `static final`). Constructors are never mistaken for methods.
- **Categories.** Keyword rules sort findings into security, correctness,
  performance, maintainability and style, with a per-analyzer default.

### Change-risk score

`risk_score` in every response combines two things:

1. A calibrated probability from a `HistGradientBoostingClassifier` trained on
   ApacheJIT (Keshavarz and Nagappan, MSR 2022; 106,674 commits from 15 Apache
   projects labelled as defect-inducing or clean, CC BY 4.0). Features are the
   Kamei-style change metrics: lines added and deleted, files, directories and
   subsystems touched, entropy of the change, and, when the GitHub flow can read
   the base branch's history, the age of the changed files, their prior change
   count and the author's prior commits. Two variants ship in one artefact:
   one with the history features and a diff-only one for API submissions and
   when history is unavailable. The output is isotonic-calibrated.
2. The static findings, folded into a score with a noisy-OR over per-finding
   severity weights (critical 0.30, error 0.12, warning 0.03, info 0).

The final score is the noisy-OR of the two, `1 - (1 - p_model) * (1 - s_static)`,
with levels low / medium / high at 0.3 and 0.6. Every response reports
`model_type` (`gradient_boosting`), the model probability, the static score,
the top per-feature attributions (change in probability when a feature is reset
to its training median) and the formula. If the artefact is missing the service
logs an error at startup and reports `model_type: heuristic`.

Held-out results (newest 20% of every project's commits; test prevalence 20.0%;
a constant prediction would score Brier 0.160):

| Model | ROC-AUC | PR-AUC | Brier |
|---|---|---|---|
| full (diff + history features), calibrated | 0.800 | 0.468 | 0.134 |
| diff only, calibrated | 0.782 | 0.442 | 0.139 |

The training script, split, feature selection (including why `ndev` is
measured but not used), attributions and limitations are in
[docs/MODEL_CARD.md](docs/MODEL_CARD.md), which the script generates.

### Related findings and clusters

Each finding is embedded with `fastembed` (BAAI/bge-small-en-v1.5, ONNX, 384
dimensions) and stored with the finding. Related past findings are the nearest
neighbours by embedding (pgvector on PostgreSQL, numpy cosine on SQLite),
re-scored with TF-IDF cosine similarity for lexical overlap, at most one per
past run, reported when the combined score is at least 0.6. The corpus is
clustered at startup with agglomerative clustering (average linkage, cosine
distance, threshold 0.15, no k) and cluster ids are stored; a new finding joins
the nearest cluster within the threshold or opens one. The API, the PR comment
and the dashboard say how many times each finding was seen before. If
`fastembed` cannot load its model the service falls back to a hashing backend
(lexical only) and says so in `/api/v1/ml/status`.

### Optional LLM pass

With an Ollama (or OpenAI-compatible) endpoint configured, `/api/v1/smart-review`
and `/api/v1/analyze` with `enable_smart_review` ask the model for issues the
rules did not catch, with the static findings as context, and parse its JSON
answer into comments. The pass is off for pull requests unless
`GITHUB_ENABLE_SMART_REVIEW=true`. Model output is flattened to plain text
before it is posted to GitHub. `LLM_PROVIDER=stub` returns canned answers so the
path can be tested without a model; the quality of the real model's comments
has not been measured.

### GitHub integration

- Webhook (`pull_request` opened, synchronize, reopened; drafts skipped by
  default) with HMAC-SHA256 verification of the raw body and replay protection
  through stored delivery ids (a repeated id is answered 409).
- Commit status (pending, then success/failure by risk level), a summary comment
  with a findings table that is updated in place on later pushes, and a review
  with inline comments on error and critical findings. A high-risk review
  requests changes unless the pull request author owns the token, in which case
  it is posted as a comment (GitHub rejects the former).
- Repository-history features for the risk model from the base branch's commit
  history, bounded by `GITHUB_HISTORY_MAX_FILES`.
- Manual trigger (`POST /api/v1/github/analyze-pr`) protected by `X-API-Key`.

### Dashboard

A React dashboard to paste a diff or raw code, see findings with categories and
"seen before" badges, the risk gauge with the model's attributions, run history,
analyzed pull requests, and service status.

---

## Architecture

```
┌──────────────────┐     ┌──────────────────────────────────────────────┐
│  React dashboard │────>│  FastAPI (:8000)                             │
│  nginx (:3000)   │     │  /api/v1/analyze        static analysis,     │
└──────────────────┘     │                         risk model, clusters │
                         │  /api/v1/github/webhook PR flow              │
┌──────────────────┐     │  /api/v1/runs           history              │
│  GitHub webhooks │────>│                                              │
└──────────────────┘     └──────────┬───────────────────────────────────┘
                                    │
                    ┌───────────────┴────────────┐    ┌──────────────┐
                    │  PostgreSQL 17 + pgvector   │    │ Ollama (opt) │
                    │  (SQLite without Docker)    │    └──────────────┘
                    └────────────────────────────┘
```

Analysis and persistence run in a worker thread pool, not on the event loop.
The risk model artefact (0.8 MB, `app/ml/artifacts/`) and the embedding model
load at startup.

---

## Quick start

### With Docker Compose

```bash
git clone https://github.com/carlous-roy/DiffLens-Engine.git
cd DiffLens-Engine
cp .env.example .env
# set POSTGRES_PASSWORD (required) and API_KEY in .env
docker compose up --build -d
```

Four containers start: `difflens-db` (pgvector/pgvector 0.8.6-pg17),
`difflens-ollama` (ollama 0.18.3), `difflens-app` (FastAPI, port 8000) and
`difflens-frontend` (nginx, port 3000). Only the API and the dashboard are
published, on localhost. The app container runs the migrations at startup. The
backend image downloads the embedding model at build time, so the first build
needs network access.

Open http://localhost:3000, load the sample and click Analyze. To pull the
default LLM model: `docker compose exec ollama ollama pull codellama:7b`.

For live reload during development:

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build
```

### Without Docker

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
uvicorn app.main:app --reload --port 8000     # SQLite file, migrations run at startup
cd frontend && npm ci && npm run dev          # dashboard on :3000, proxies /api to :8000
```

The first request embeds findings, which downloads the ONNX model (about
65 MB, the quantized `qdrant/bge-small-en-v1.5-onnx-q` files) into the fastembed cache; set `EMBEDDING_BACKEND=hashing` to skip that.

```bash
curl -s http://localhost:8000/api/v1/health
curl -s -X POST http://localhost:8000/api/v1/analyze \
  -H 'Content-Type: application/json' \
  -d '{"diff": "diff --git a/x.py b/x.py\n--- /dev/null\n+++ b/x.py\n@@ -0,0 +1,2 @@\n+def f(x):\n+    return eval(x)\n"}'
```

---

## GitHub setup

1. Create a fine-grained personal access token with Pull requests: read and
   write, Commit statuses: read and write, Contents: read (Checks: read and
   write if you enable the Checks API).
2. Generate a webhook secret and an API key:
   `python3 -c "import secrets; print(secrets.token_hex(32))"`.
3. Set `GITHUB_TOKEN`, `GITHUB_WEBHOOK_SECRET` and `API_KEY` in `.env`. The
   webhook endpoint rejects unsigned deliveries, and the manual trigger is
   disabled until `API_KEY` is set.
4. Expose the API (for example `ngrok http 8000`) and add a webhook on the
   repository: payload URL `https://<public-url>/api/v1/github/webhook`, content
   type `application/json`, the secret from step 2, event "Pull requests".
5. Open a pull request. The commit status, summary comment and review appear
   within a few seconds; later pushes update the same comment.

---

## API

| Endpoint | Method | Auth | Description |
|---|---|---|---|
| `/api/v1/analyze` | POST | key only with `enable_smart_review` | Analyze a diff or raw code (max 2 MB) |
| `/api/v1/smart-review` | POST | `X-API-Key` | LLM review of a diff |
| `/api/v1/runs` | GET | – | Recent runs (`limit` 1–200) |
| `/api/v1/runs/{id}` | GET | – | Run with findings, categories, cluster ids and risk |
| `/api/v1/health` | GET | – | Database, LLM and risk model status |
| `/api/v1/ml/status` | GET | – | LLM, risk model, embeddings and index status |
| `/api/v1/github/webhook` | POST | HMAC signature | GitHub deliveries |
| `/api/v1/github/status` | GET | – | Integration configuration (token verified hourly) |
| `/api/v1/github/prs` | GET | – | Analyzed pull requests |
| `/api/v1/github/analyze-pr` | POST | `X-API-Key` | Analyze a pull request on demand |

Interactive documentation: http://localhost:8000/docs.

---

## Configuration

All settings are environment variables; `.env.example` documents every one.
The most relevant:

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | `sqlite:///./difflens.db` | SQLAlchemy URL; compose sets PostgreSQL |
| `AUTO_MIGRATE` | unset (on in development) | Run `alembic upgrade head` at startup |
| `API_KEY` | unset | Required by the routes that spend the token or the LLM |
| `MAX_DIFF_BYTES` | `2000000` | Largest diff accepted or fetched |
| `EMBEDDING_BACKEND` | `fastembed` | `fastembed` or `hashing` |
| `CLUSTER_DISTANCE_THRESHOLD` | `0.15` | Cosine distance that joins a cluster |
| `SIMILARITY_MIN_SCORE` | `0.6` | Minimum combined score for a related finding |
| `LLM_PROVIDER` | `ollama` | `ollama`, `openai` or `stub` |
| `GITHUB_TOKEN`, `GITHUB_WEBHOOK_SECRET` | unset | GitHub integration |
| `GITHUB_HISTORY_MAX_FILES` | `20` | Files whose history feeds the risk model; 0 disables |
| `GITHUB_ENABLE_SMART_REVIEW` | `false` | LLM pass on pull requests |
| `LOG_LEVEL` | `INFO` | Process log level |

---

## Development

```bash
pip install -r requirements-dev.txt
pytest --cov=app                # 285 tests in 19 files, hermetic (no network, no .env)
ruff check . && ruff format --check .
python scripts/train_risk_model.py   # downloads ApacheJIT, retrains, rewrites docs/MODEL_CARD.md
```

The suite clears `GITHUB_TOKEN`/`GH_TOKEN`, ignores `.env`, uses an in-memory
database, the hashing embedding backend and a fake GitHub API over
`httpx.MockTransport`. GitHub Actions runs ruff, the tests with coverage, the
frontend build and both Docker builds on every push.

---

## Known limitations

- Only functions whose definition line is in the diff get a complexity
  measurement, and the count covers the text visible in the diff. Edits inside
  an existing function whose `def` is outside the hunk are not measured.
- The rules are line patterns over masked source. A multi-line construct such
  as an empty `catch` block spread over several lines is not matched.
- The risk model was trained on Java-heavy Apache projects with commit-level
  labels; its probabilities are not calibrated for other ecosystems, and a
  pull request is scored as one change. ROC-AUC 0.80 ranks changes usefully
  but is not a defect detector. See the model card.
- The history features are computed from up to 20 files and one page of
  commits per file; `aexp` is capped at 500.
- Clusters of repeat findings are as good as the embeddings of short rule
  messages; different functions with the same complexity message stay apart
  only because their names differ.
- The LLM pass is unevaluated: no measurement exists of how often its comments
  are correct.
- The PostgreSQL/pgvector path is exercised by compiling its query in the test
  suite, not by running against a database in CI.
- Two languages. Adding one means writing its rules, not only adding a grammar.

---

## Project structure

```
DiffLens-Engine/
├── app/
│   ├── analysis/          syntax.py (Tree-sitter, masking), complexity.py, naming.py,
│   │                      bug_risk.py, diff_parser.py (hunk views), pipeline.py
│   ├── ml/                risk_scoring.py, change_metrics.py, embeddings.py,
│   │                      similarity.py (index, clustering), categorization.py,
│   │                      smart_review.py, llm_provider.py, artifacts/ (model + metadata)
│   ├── github/            webhook.py, client.py, history.py, pr_analyzer.py,
│   │                      formatter.py, routes.py
│   ├── api/               routes.py, schemas.py, auth.py
│   ├── db/                models.py, persist.py, migrate.py
│   ├── config/            settings
│   ├── logging_config.py
│   └── main.py
├── alembic/               migrations 001–004
├── scripts/train_risk_model.py
├── docs/MODEL_CARD.md
├── frontend/              React + Vite dashboard
├── tests/                 pytest suite, fake GitHub API
├── .github/workflows/ci.yml
├── Dockerfile, docker-compose.yml, docker-compose.dev.yml
└── requirements.txt, requirements-dev.txt
```

---

## Tech stack

| Layer | Technology |
|---|---|
| Backend | FastAPI, SQLAlchemy, Alembic, Tree-sitter, scikit-learn, fastembed (ONNX) |
| Frontend | React 18, Vite 7, Tailwind CSS, Recharts |
| Database | PostgreSQL 17 with pgvector (SQLite without Docker) |
| LLM | Ollama + CodeLlama 7B (optional) |
| Infrastructure | Docker Compose, nginx, GitHub Actions |

## License

MIT
