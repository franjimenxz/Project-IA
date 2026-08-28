from fastapi.testclient import TestClient

from ia_mcp.api.app import create_app


def test_liveness_does_not_require_dependencies():
    response = TestClient(create_app()).get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "alive"}
