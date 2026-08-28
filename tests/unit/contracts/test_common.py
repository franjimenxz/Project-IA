import pytest
from pydantic import TypeAdapter, ValidationError

from ia_mcp.contracts.common import NonEmptyStr, ToolResult
from ia_mcp.contracts.errors import ToolError, ToolErrorCode


def test_empty_non_empty_str_is_rejected() -> None:
    with pytest.raises(ValidationError):
        TypeAdapter(NonEmptyStr).validate_python("")


def test_tool_result_ok_requires_value_and_forbids_error() -> None:
    error = ToolError(
        code=ToolErrorCode.CONTRACT_VIOLATION,
        retryable=False,
        safe_message="Internal error.",
    )
    with pytest.raises(ValidationError):
        ToolResult[str](ok=True, value=None, error=None)
    with pytest.raises(ValidationError):
        ToolResult[str](ok=True, value="ok", error=error)


def test_tool_result_not_ok_requires_error_and_forbids_value() -> None:
    error = ToolError(
        code=ToolErrorCode.UPSTREAM_TIMEOUT,
        retryable=True,
        safe_message="The request timed out.",
    )
    with pytest.raises(ValidationError):
        ToolResult[str](ok=False, value=None, error=None)
    with pytest.raises(ValidationError):
        ToolResult[str](ok=False, value="ok", error=error)


def test_tool_result_serializes_without_secrets() -> None:
    error = ToolError(
        code=ToolErrorCode.FORBIDDEN,
        retryable=False,
        safe_message="Action is not allowed.",
        upstream_reference="ref-1",
    )
    result = ToolResult[str](ok=False, error=error)
    dumped = result.model_dump(mode="json")
    text = str(dumped)
    assert "password" not in text
    assert "secret" not in text
    assert "tenant_id" not in dumped
    assert dumped == {
        "ok": False,
        "value": None,
        "error": {
            "code": "forbidden",
            "retryable": False,
            "safe_message": "Action is not allowed.",
            "upstream_reference": "ref-1",
        },
    }
    with pytest.raises(ValidationError):
        ToolError.model_validate(
            {
                "code": "forbidden",
                "retryable": False,
                "safe_message": "Action is not allowed.",
                "credentials": "token",
            }
        )
