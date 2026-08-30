"""Shared test fixtures and configuration."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import app

SQLALCHEMY_TEST_URL = "sqlite://"

@pytest.fixture(scope="function")
def db_session():
    """Create a fresh in-memory database for each test."""
    engine = create_engine(
        SQLALCHEMY_TEST_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)

@pytest.fixture(scope="function")
def client(db_session):
    """FastAPI test client with overridden database dependency."""
    def override_get_db():
        try:
            yield db_session
        finally:
            pass

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
