"""DiffLens FastAPI entrypoint."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.config import get_settings
from app.github.routes import github_router
from app.logging_config import configure_logging
from app.ml.risk_scoring import load_risk_model
from app.ml.similarity import get_finding_index

settings = get_settings()
configure_logging(settings.log_level)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Startup work: load the risk model artefact and the similarity corpus."""
    if load_risk_model() is None:
        logger.error("Risk scoring is running on the heuristic fallback.")
    get_finding_index().load_from_db()
    yield


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description=(
        "Code review for Python and Java diffs: Tree-sitter static analysis, "
        "change-risk scoring and GitHub pull request integration."
    ),
    lifespan=lifespan,
)

allowed_origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix="/api/v1")
app.include_router(github_router, prefix="/api/v1")


@app.get("/")
def root():
    return {
        "name": settings.app_name,
        "version": settings.app_version,
        "docs": "/docs",
        "dashboard": settings.dashboard_url,
        "github_webhook": "/api/v1/github/webhook",
        "github_configured": bool(settings.github_token),
    }
