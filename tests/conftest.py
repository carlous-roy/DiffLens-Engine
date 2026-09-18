"""Shared test fixtures and configuration.

The suite is hermetic: it never reads a developer's `.env` or ambient GitHub
credentials, and it never opens a network connection. Anything that would
talk to GitHub or an LLM is replaced with a stub below.
"""

import os

# Must run before `app` is imported: settings are read once at import time.
for _var in ("GITHUB_TOKEN", "GH_TOKEN", "GITHUB_WEBHOOK_SECRET"):
    os.environ.pop(_var, None)
os.environ["DIFFLENS_ENV_FILE"] = ""
# The application engine points at an in-memory database so nothing on disk
# is touched; routes get a per-test session through a dependency override.
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
# No model download during tests: the hashing backend is deterministic.
os.environ["EMBEDDING_BACKEND"] = "hashing"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.db import Base, get_db  # noqa: E402
from app.github import client as github_client  # noqa: E402
from app.main import app  # noqa: E402
from app.ml.embeddings import get_embedding_model  # noqa: E402
from app.ml.similarity import FindingIndex, reset_finding_index, set_finding_index  # noqa: E402

SQLALCHEMY_TEST_URL = "sqlite://"


@pytest.fixture(autouse=True)
def _fresh_similarity_index():
    """Every test starts with an empty in-memory similarity corpus."""
    reset_finding_index()
    yield
    reset_finding_index()


@pytest.fixture(autouse=True)
def _no_github_network(monkeypatch):
    """Never let a test reach api.github.com.

    `verify_token` is the one call the status endpoint makes on its own; the
    rest of the client is exercised through an explicit mocked transport in
    the PR-flow tests.
    """

    async def _fake_verify_token(self):
        return {"login": "difflens-test-bot", "id": 1}

    monkeypatch.setattr(github_client.GitHubClient, "verify_token", _fake_verify_token)
    yield


@pytest.fixture(scope="function")
def session_factory():
    """A session factory on a fresh in-memory database with the schema created."""
    engine = create_engine(
        SQLALCHEMY_TEST_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    try:
        yield factory
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


@pytest.fixture(scope="function")
def db_session(session_factory):
    """A session on the per-test database."""
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture(scope="function")
def client(db_session, session_factory):
    """FastAPI test client with the database dependency and the similarity
    index bound to the per-test database."""

    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    set_finding_index(
        FindingIndex(
            get_embedding_model(), get_settings().cluster_distance_threshold, session_factory
        )
    )
    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


SAMPLE_PYTHON_DIFF = """diff --git a/utils/helpers.py b/utils/helpers.py
new file mode 100644
--- /dev/null
+++ b/utils/helpers.py
@@ -0,0 +1,35 @@
+import os
+from typing import Optional
+
+MAX_RETRIES = 3
+
+class dataProcessor:
+    \"\"\"Processes data.\"\"\"
+
+    def ProcessData(self, data, cache={}):
+        \"\"\"Process the given data.\"\"\"
+        if data is None:
+            return None
+        if data == None:
+            return None
+        try:
+            result = eval(data)
+        except:
+            pass
+        for item in data:
+            if item > 0:
+                if item > 10:
+                    if item > 100:
+                        result = item * 2
+                    else:
+                        result = item * 3
+                else:
+                    result = item
+            else:
+                result = 0
+        # TODO: add better error handling
+        return result
+
+    def __init__(self):
+        self.data = []
+        global SHARED_STATE
"""

SAMPLE_JAVA_DIFF = """diff --git a/src/Main.java b/src/Main.java
new file mode 100644
--- /dev/null
+++ b/src/Main.java
@@ -0,0 +1,15 @@
+public class dataHandler {
+    public static final int max_retries = 3;
+
+    public boolean checkName(String name) {
+        if (name.equals(null)) {
+            return false;
+        }
+        if (name == "admin") {
+            System.out.println("admin user");
+            return true;
+        }
+        // TODO: handle other roles
+        return false;
+    }
+}
"""

MINIMAL_PYTHON_DIFF = """diff --git a/clean.py b/clean.py
new file mode 100644
--- /dev/null
+++ b/clean.py
@@ -0,0 +1,5 @@
+def add(a, b):
+    return a + b
+
+def subtract(a, b):
+    return a - b
"""
