from ia_mcp.workflows.models import WorkflowState
from ia_mcp.workflows.ports import WorkflowError

_TRANSITIONS: dict[tuple[str, str], WorkflowState] = {
    ("collecting", "submit"): "awaiting_confirmation",
    ("collecting", "cancel"): "cancelled",
    ("collecting", "fail"): "failed",
    ("awaiting_confirmation", "confirm"): "executing",
    ("awaiting_confirmation", "revise"): "collecting",
    ("awaiting_confirmation", "cancel"): "cancelled",
    ("executing", "succeed"): "completed",
    ("executing", "fail"): "failed",
    ("executing", "review"): "manual_review_required",
    ("executing", "cancel"): "cancelled",
}


class WorkflowDefinition:
    def transition(self, from_state: str, event: str) -> WorkflowState:
        nxt = _TRANSITIONS.get((from_state, event))
        if nxt is None:
            raise WorkflowError("invalid_transition", "Transition is not allowed.")
        return nxt
