from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from ia_mcp.observability.context import current_correlation_id
from ia_mcp.shared.errors import DomainError
from tests.unit.api.observability_app import app_with_observability

CORRELATION_HEADER = "X-Correlation-ID"


def test_correlation_id_is_generated_when_missing():
    response = TestClient(app_with_observability()).get("/health/live")
    raw = response.headers[CORRELATION_HEADER]
    UUID(raw)
    payload_ok = response.json() == {"status": "alive"}
    assert payload_ok
    assert response.status_code == 200


def test_unauthenticated_request_does_not_reuse_client_correlation():
    supplied = str(uuid4())
    response = TestClient(app_with_observability()).get(
        "/health/live",
        headers={CORRELATION_HEADER: supplied},
    )
    assert response.headers[CORRELATION_HEADER] != supplied
    UUID(response.headers[CORRELATION_HEADER])


def test_problem_details_shares_generated_correlation_id():
    app = app_with_observability()

    @app.get("/_test/error")
    def boom() -> None:
        raise DomainError(
            code="processing_failed",
            safe_message="Request could not be processed",
            retryable=False,
            details={"authorization": "Bearer secret-token"},
        )

    response = TestClient(app).get("/_test/error")
    header_id = response.headers[CORRELATION_HEADER]
    UUID(header_id)
    payload = response.json()
    assert payload["correlation_id"] == header_id
    assert "secret-token" not in response.text


def test_current_correlation_id_matches_server_generated_header():
    supplied = uuid4()
    app = app_with_observability()
    seen: dict[str, UUID] = {}

    @app.get("/_test/correlation")
    def read_id() -> dict[str, str]:
        seen["id"] = current_correlation_id()
        return {"correlation_id": str(seen["id"])}

    response = TestClient(app).get(
        "/_test/correlation",
        headers={CORRELATION_HEADER: str(supplied)},
    )
    assert seen["id"] != supplied
    assert response.json()["correlation_id"] == str(seen["id"])
    assert response.headers[CORRELATION_HEADER] == str(seen["id"])
