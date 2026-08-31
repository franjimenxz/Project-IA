from __future__ import annotations

import pytest
from pydantic import ValidationError

from ia_mcp.configuration.models import AgentConfig


def test_tone_only_constructor_defaults_instructions_to_none() -> None:
    config = AgentConfig(tone="formal")
    assert config.tone == "formal"
    assert config.instructions is None


def test_none_instructions_are_valid() -> None:
    config = AgentConfig(tone="formal", instructions=None)
    assert config.instructions is None


def test_blank_instructions_are_valid_and_mean_absent() -> None:
    config = AgentConfig(tone="formal", instructions="")
    assert config.instructions in (None, "")


def test_instructions_of_2000_characters_are_accepted() -> None:
    text = "x" * 2000
    config = AgentConfig(tone="formal", instructions=text)
    assert config.instructions == text


def test_instructions_over_2000_characters_are_rejected() -> None:
    with pytest.raises(ValidationError) as refused:
        AgentConfig(tone="formal", instructions="x" * 2001)
    assert any(error["type"] == "string_too_long" for error in refused.value.errors())


@pytest.mark.parametrize("field", ["persona", "system_prompt", "greeting"])
def test_undeclared_agent_fields_are_forbidden(field: str) -> None:
    with pytest.raises(ValidationError) as refused:
        AgentConfig(tone="formal", **{field: "nope"})
    assert any("extra" in error["type"] for error in refused.value.errors())


def test_tone_is_required() -> None:
    with pytest.raises(ValidationError):
        AgentConfig()  # type: ignore[call-arg]
