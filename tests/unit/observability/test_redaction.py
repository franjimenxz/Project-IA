from ia_mcp.observability.redaction import redact


def test_redactor_removes_bearer_and_email():
    value = redact("Bearer secret-token for patient@example.com")
    assert "secret-token" not in value
    assert "patient@example.com" not in value
    assert value == "Bearer [REDACTED] for [EMAIL]"


def test_redactor_removes_basic_auth_api_key_dni_and_phone():
    value = redact(
        "Basic dXNlcjpwYXNz api_key=sk-live-secret DNI 30111222 +54 11 4444-5555"
    )
    assert "dXNlcjpwYXNz" not in value
    assert "sk-live-secret" not in value
    assert "30111222" not in value
    assert "4444-5555" not in value
    assert "Basic [REDACTED]" in value
    assert "DNI [REDACTED]" in value
