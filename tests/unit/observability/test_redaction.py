from ia_mcp.observability.redaction import redact


def test_redactor_removes_bearer_and_email():
    value = redact("Bearer secret-token for patient@example.com")
    assert "secret-token" not in value
    assert "patient@example.com" not in value
    assert value == "Bearer [REDACTED] for [EMAIL]"
