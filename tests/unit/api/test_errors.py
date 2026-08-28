from fastapi.testclient import TestClient

from ia_mcp.api.app import create_app
from ia_mcp.shared.errors import DomainError, TenantIsolationViolation


def test_problem_details_omits_nested_sensitive_details():
    app = create_app()

    @app.get("/_test/error")
    def boom() -> None:
        raise DomainError(
            code="processing_failed",
            safe_message="Request could not be processed",
            retryable=False,
            details={
                "authorization": "Bearer secret-token",
                "contact": {"email": "patient@example.com"},
            },
        )

    response = TestClient(app).get("/_test/error")
    body = response.text
    assert "secret-token" not in body
    assert "patient@example.com" not in body
    payload = response.json()
    assert "details" not in payload
    assert payload["detail"] == "Request could not be processed"
    assert response.status_code == 400
    assert response.headers["content-type"].startswith("application/problem+json")


def test_unhandled_error_hides_stack():
    app = create_app()

    @app.get("/_test/crash")
    def crash() -> None:
        raise RuntimeError("secret-token TRACEBACK_MARKER patient@example.com")

    response = TestClient(app, raise_server_exceptions=False).get("/_test/crash")
    body = response.text
    assert "TRACEBACK_MARKER" not in body
    assert "secret-token" not in body
    assert "patient@example.com" not in body
    assert "Traceback" not in body
    assert response.status_code == 500
    payload = response.json()
    assert "details" not in payload
    assert payload["status"] == 500
    assert response.headers["content-type"].startswith("application/problem+json")


def test_error_log_redacts_token_and_email(caplog):
    app = create_app()

    @app.get("/_test/error")
    def boom() -> None:
        raise DomainError(
            code="processing_failed",
            safe_message="Request could not be processed",
            retryable=False,
            details={
                "authorization": "Bearer secret-token",
                "contact": {"email": "patient@example.com"},
            },
        )

    TestClient(app).get("/_test/error")
    assert "secret-token" not in caplog.text
    assert "patient@example.com" not in caplog.text
    assert "[REDACTED]" in caplog.text
    assert "[EMAIL]" in caplog.text


def test_tenant_isolation_violation_hides_foreign_resource():
    app = create_app()

    @app.get("/_test/isolation")
    def boom() -> None:
        raise TenantIsolationViolation(details={"resource_id": "foreign-resource-b"})

    response = TestClient(app).get("/_test/isolation")
    assert response.status_code == 404
    assert "foreign-resource-b" not in response.text
    payload = response.json()
    assert "details" not in payload
    assert payload["detail"] == "Resource not found"
