import pytest

from ia_mcp.workflows.definition import WorkflowDefinition
from ia_mcp.workflows.ports import WorkflowError


@pytest.mark.parametrize(
    ("from_state", "event", "expected"),
    [
        ("collecting", "submit", "awaiting_confirmation"),
        ("collecting", "cancel", "cancelled"),
        ("collecting", "fail", "failed"),
        ("awaiting_confirmation", "confirm", "executing"),
        ("awaiting_confirmation", "revise", "collecting"),
        ("awaiting_confirmation", "cancel", "cancelled"),
        ("executing", "succeed", "completed"),
        ("executing", "fail", "failed"),
        ("executing", "review", "manual_review_required"),
        ("executing", "cancel", "cancelled"),
    ],
)
def test_allowed_transitions(from_state: str, event: str, expected: str) -> None:
    assert WorkflowDefinition().transition(from_state, event) == expected


@pytest.mark.parametrize(
    ("from_state", "event"),
    [
        ("collecting", "confirm"),
        ("completed", "submit"),
        ("failed", "succeed"),
        ("cancelled", "cancel"),
        ("manual_review_required", "review"),
        ("executing", "submit"),
        ("collecting_fields", "submit"),
        ("searching_slots", "select"),
    ],
)
def test_invalid_transition_fails_closed(from_state: str, event: str) -> None:
    with pytest.raises(WorkflowError) as caught:
        WorkflowDefinition().transition(from_state, event)
    assert caught.value.code == "invalid_transition"
