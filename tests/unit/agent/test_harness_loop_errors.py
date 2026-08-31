from __future__ import annotations

from dataclasses import asdict, fields

import pytest

from ia_mcp.agent_runtime.models import ToolCallProposal
from ia_mcp.agent_runtime.ports import LLMError
from ia_mcp.contracts.errors import ToolErrorCode
from ia_mcp.skills.faq import SAFE_HANDOFF, SAFE_INSUFFICIENT
from tests.unit.agent.test_harness import inbound, tenant_a
from tests.unit.agent.test_harness_loop import (
    ANSWER,
    SEARCH_ARGS,
    SEARCH_PROPOSAL,
    UPSTREAM_REF,
    RecordingExecutor,
    RecordingFactory,
    ScriptedLLM,
    error_result,
    make_loop_harness,
)

FEEDBACK_ERRORS = (
    (ToolErrorCode.VALIDATION_ERROR, "The request is invalid.", False),
    (ToolErrorCode.NOT_FOUND, "The requested resource was not found.", False),
    (ToolErrorCode.CONFLICT, "The requested slot is not available.", False),
    (ToolErrorCode.CONTRACT_VIOLATION, "Upstream response was invalid.", False),
    (ToolErrorCode.UPSTREAM_TIMEOUT, "The request timed out.", True),
    (ToolErrorCode.UPSTREAM_UNAVAILABLE, "The service is unavailable.", True),
)


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("code", "message", "retryable"),
    FEEDBACK_ERRORS,
)
async def test_typed_errors_feed_back_without_harness_retry(
    code: ToolErrorCode, message: str, retryable: bool
) -> None:
    executor = RecordingExecutor(
        error_result(
            code,
            message,
            retryable=retryable,
            upstream_reference=UPSTREAM_REF,
        )
    )
    llm = ScriptedLLM(SEARCH_PROPOSAL, ANSWER)
    harness, _knowledge, _llm, _runs = make_loop_harness(
        llm=llm, executors=RecordingFactory(executor)
    )

    result = await harness.handle_message(tenant_a(), inbound("hours"))

    assert len(executor.calls) == 1
    assert len(llm.requests) == 2
    observation = llm.requests[1].tool_results[0]
    assert observation.ok is False
    assert observation.error_code == code.value
    assert observation.safe_message == message
    blob = " ".join(str(getattr(observation, item.name)) for item in fields(observation))
    blob = f"{blob} {observation!r} {asdict(observation)!s} {llm.requests[1]!r}"
    assert UPSTREAM_REF not in blob
    assert "upstream_reference" not in blob
    assert result.tool_calls[0].ok is False
    assert result.tool_calls[0].error_code == code.value


@pytest.mark.anyio
async def test_two_forbidden_observations_finish_as_handoff() -> None:
    llm = ScriptedLLM(
        ToolCallProposal(name="appointments.create", arguments={"slot_id": "s-1"}),
        ToolCallProposal(name="appointments.cancel", arguments={"appointment_id": "apt-1"}),
        ANSWER,
    )
    executor = RecordingExecutor()
    harness, _knowledge, _llm, runs = make_loop_harness(
        llm=llm, executors=RecordingFactory(executor)
    )

    result = await harness.handle_message(tenant_a(), inbound("book"))

    assert executor.calls == []
    assert result.kind == "handoff"
    assert result.text == SAFE_HANDOFF
    assert "Hours are 8 to 16" not in result.text
    assert len(llm.requests) == 2
    assert [call.error_code for call in result.tool_calls] == ["forbidden", "forbidden"]
    assert runs.finished and runs.finished[0][1] == "handed_off"


@pytest.mark.anyio
async def test_repeated_name_and_arguments_is_insufficient() -> None:
    first_args = {
        "specialty": "cardiologia",
        "date_from": "2026-09-01",
        "date_to": "2026-09-01",
    }
    second_args = {
        "date_to": "2026-09-01",
        "specialty": "cardiologia",
        "date_from": "2026-09-01",
    }
    llm = ScriptedLLM(
        ToolCallProposal(name="appointments.search", arguments=first_args),
        ToolCallProposal(name="appointments.search", arguments=second_args),
        ANSWER,
    )
    executor = RecordingExecutor()
    harness, _knowledge, _llm, runs = make_loop_harness(
        llm=llm, executors=RecordingFactory(executor)
    )

    result = await harness.handle_message(tenant_a(), inbound("hours"))

    assert len(executor.calls) == 1
    assert result.kind == "insufficient"
    assert result.text == SAFE_INSUFFICIENT
    assert "Hours are 8 to 16" not in result.text
    assert runs.finished and runs.finished[0][1] == "failed"
    assert runs.error_codes == ["tool_call_repeated"]


@pytest.mark.anyio
async def test_tenant_isolation_violation_aborts_without_second_generate() -> None:
    executor = RecordingExecutor(
        error_result(
            ToolErrorCode.TENANT_ISOLATION_VIOLATION,
            "An internal error occurred.",
            upstream_reference=UPSTREAM_REF,
        )
    )
    llm = ScriptedLLM(SEARCH_PROPOSAL, ANSWER)
    harness, _knowledge, _llm, runs = make_loop_harness(
        llm=llm, executors=RecordingFactory(executor)
    )

    result = await harness.handle_message(tenant_a(), inbound("hours"))

    assert len(llm.requests) == 1
    assert llm.requests[0].tool_results == ()
    assert result.kind == "insufficient"
    assert result.text == SAFE_INSUFFICIENT
    assert "Hours are 8 to 16" not in result.text
    assert runs.finished and runs.finished[0][1] == "failed"
    assert runs.error_codes == ["tenant_isolation_violation"]
    blob = f"{result!r} {result.text} {llm.requests!r}"
    assert UPSTREAM_REF not in blob


@pytest.mark.anyio
async def test_llm_error_on_second_generate_is_provider_unavailable() -> None:
    executor = RecordingExecutor()
    llm = ScriptedLLM(
        SEARCH_PROPOSAL,
        LLMError("provider_unavailable", "LLM is unavailable."),
    )
    harness, _knowledge, _llm, runs = make_loop_harness(
        llm=llm, executors=RecordingFactory(executor)
    )

    result = await harness.handle_message(tenant_a(), inbound("hours"))

    assert len(executor.calls) == 1
    assert len(llm.requests) == 2
    assert llm.requests[1].tool_results[0].ok is True
    assert result.kind == "insufficient"
    assert result.text == SAFE_INSUFFICIENT
    assert "Hours are 8 to 16" not in result.text
    assert runs.finished and runs.finished[0][1] == "failed"
    assert runs.error_codes == ["provider_unavailable"]


@pytest.mark.anyio
async def test_forbidden_from_executor_counts_toward_handoff() -> None:
    executor = RecordingExecutor(
        error_result(ToolErrorCode.FORBIDDEN, "Action is not allowed.")
    )
    llm = ScriptedLLM(
        SEARCH_PROPOSAL,
        ToolCallProposal(
            name="appointments.search",
            arguments={**SEARCH_ARGS, "location": "other"},
        ),
        ANSWER,
    )
    harness, _knowledge, _llm, runs = make_loop_harness(
        llm=llm, executors=RecordingFactory(executor)
    )

    result = await harness.handle_message(tenant_a(), inbound("hours"))

    assert len(executor.calls) == 2
    assert result.kind == "handoff"
    assert result.text == SAFE_HANDOFF
    assert len(llm.requests) == 2
    assert runs.finished and runs.finished[0][1] == "handed_off"
