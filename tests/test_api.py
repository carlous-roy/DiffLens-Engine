"""Tests for the API endpoints."""
from tests.conftest import SAMPLE_PYTHON_DIFF, MINIMAL_PYTHON_DIFF

def test_root(client):
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "DiffLens"
    assert "version" in data

def test_health(client):
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] in ("healthy", "degraded")
    assert "version" in data
    assert "database" in data

def test_analyze_python(client):
    response = client.post("/api/v1/analyze", json={
        "diff": SAMPLE_PYTHON_DIFF,
        "source": "test",
    })
    assert response.status_code == 200
    data = response.json()

    assert "run_id" in data
    assert data["summary"]["files_analyzed"] == 1
    assert data["summary"]["total_findings"] > 0
    assert len(data["complexity_findings"]) > 0
    assert len(data["naming_findings"]) > 0
    assert len(data["bug_risk_findings"]) > 0

def test_analyze_clean_code(client):
    response = client.post("/api/v1/analyze", json={
        "diff": MINIMAL_PYTHON_DIFF,
    })
    assert response.status_code == 200
    data = response.json()
    assert data["summary"]["total_findings"] >= 0
    assert len(data["bug_risk_findings"]) == 0
    assert len(data["naming_findings"]) == 0

def test_analyze_empty_diff_rejected(client):
    response = client.post("/api/v1/analyze", json={"diff": ""})
    assert response.status_code == 422  # validation error

def test_list_runs(client):
    # Create a run first
    client.post("/api/v1/analyze", json={"diff": MINIMAL_PYTHON_DIFF})

    response = client.get("/api/v1/runs")
    assert response.status_code == 200
    data = response.json()
    assert len(data) >= 1
    assert "id" in data[0]
    assert "summary" in data[0]

def test_get_run_detail(client):
    # Create a run
    create_resp = client.post("/api/v1/analyze", json={"diff": SAMPLE_PYTHON_DIFF})
    run_id = create_resp.json()["run_id"]

    # Fetch it
    response = client.get(f"/api/v1/runs/{run_id}")
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == run_id
    assert len(data["findings"]) > 0

def test_get_run_not_found(client):
    response = client.get("/api/v1/runs/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404
