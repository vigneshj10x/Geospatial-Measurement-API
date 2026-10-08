"""Tests for the Leaflet interactive map viewer endpoint at GET /viewer."""

from starlette.testclient import TestClient


def test_get_viewer_endpoint_returns_html(client: TestClient) -> None:
    """GET /viewer must return HTTP 200 with HTML content containing Leaflet and uploader."""
    response = client.get("/viewer")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    content = response.text
    assert "leaflet.js" in content
    assert "leaflet.css" in content
    assert "Geospatial Engine" in content
    assert "?format=geojson" in content
    assert "area-unit-group" in content
    assert "badge-ok" in content
    assert "badge-skipped" in content
    assert "badge-error" in content


def test_root_endpoint_lists_viewer_url(client: TestClient) -> None:
    """GET / lists the viewer URL."""
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert "viewer_url" in data
    assert data["viewer_url"] == "/viewer"
