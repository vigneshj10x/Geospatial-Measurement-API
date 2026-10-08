"""Basic pytest test for GET /health using TestClient."""

from starlette.testclient import TestClient


def test_health_check_endpoint(client: TestClient) -> None:
    """Verify that GET /health returns 200 OK and expected payload."""
    response = client.get("/health")
    assert response.status_code == 200

    data = response.json()
    assert data["status"] == "ok"
    assert "app" in data
    assert "version" in data


def test_root_endpoint(client: TestClient) -> None:
    """Verify that GET / returns 200 OK and metadata."""
    response = client.get("/")
    assert response.status_code == 200

    data = response.json()
    assert "name" in data
    assert "version" in data
    assert "docs_url" in data
