from fastapi import status
from fastapi.testclient import TestClient


def test_health_endpoint_root(client: TestClient) -> None:
    """Test that GET /health returns HTTP 200 with status ok."""
    response = client.get("/health")
    assert response.status_code == status.HTTP_200_OK
    assert response.json() == {"status": "ok"}


def test_health_endpoint_v1(client: TestClient) -> None:
    """Test that GET /api/v1/health returns HTTP 200 with status ok."""
    response = client.get("/api/v1/health")
    assert response.status_code == status.HTTP_200_OK
    assert response.json() == {"status": "ok"}
