# Backend image: FastAPI app, risk model artefact and the embedding model.
# Runs as a non-root user; migrations run at startup when AUTO_MIGRATE=true.

FROM python:3.11.15-slim-bookworm AS build

ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /build

COPY requirements.txt .
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install -r requirements.txt

# Fetch the ONNX embedding model at build time so the container starts
# without network access and without a per-container download.
ENV FASTEMBED_CACHE_PATH=/opt/models HF_HUB_DISABLE_TELEMETRY=1
RUN /opt/venv/bin/python -c "from fastembed import TextEmbedding; \
TextEmbedding('BAAI/bge-small-en-v1.5', cache_dir='/opt/models')"


FROM python:3.11.15-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    EMBEDDING_CACHE_DIR=/opt/models HF_HUB_DISABLE_TELEMETRY=1 HF_HUB_OFFLINE=1

RUN groupadd --system --gid 10001 difflens \
    && useradd --system --uid 10001 --gid difflens --home-dir /app --shell /usr/sbin/nologin difflens

WORKDIR /app
COPY --from=build --chown=difflens:difflens /opt/venv /opt/venv
COPY --from=build --chown=difflens:difflens /opt/models /opt/models
COPY --chown=difflens:difflens alembic.ini ./
COPY --chown=difflens:difflens alembic ./alembic
COPY --chown=difflens:difflens app ./app

USER difflens
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health', timeout=4)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
