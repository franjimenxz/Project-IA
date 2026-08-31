from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Mapping
from typing import Protocol

from ia_mcp.agent_runtime.models import (
    AnswerKind,
    LLMDecision,
    LLMRequest,
    LLMTurnDecision,
    ToolCallProposal,
    ToolObservation,
)
from ia_mcp.agent_runtime.ports import LLMError

DEFAULT_MODEL = "gemini-3.5-flash"
GENERATE_CONTENT_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
)
_TIMEOUT_SECONDS = 10
_UNAVAILABLE = "provider_unavailable"
_SAFE_UNAVAILABLE = "The language model is unavailable."
_OUTPUT_CONTRACT = (
    "OUTPUT_CONTRACT If you answer in text, reply with a JSON object only, "
    "no markdown: "
    '{"kind": "answer"|"clarify"|"insufficient"|"handoff", '
    '"text": "<string>", "source_ids": ["<id>", ...]}. '
    "You may instead emit a functionCall whose name is in tool_names."
)


class GeminiTransport(Protocol):
    def post_generate_content(
        self, *, url: str, api_key: str, body: dict[str, object]
    ) -> dict[str, object]: ...


class UrllibGeminiTransport:
    def post_generate_content(
        self, *, url: str, api_key: str, body: dict[str, object]
    ) -> dict[str, object]:
        request = urllib.request.Request(
            url,
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "x-goog-api-key": api_key,
            },
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=_TIMEOUT_SECONDS) as response:
            raw = response.read()
        parsed: object = json.loads(raw)
        if not isinstance(parsed, dict):
            raise json.JSONDecodeError("Gemini response must be an object", "", 0)
        return parsed


class GeminiLLM:
    def __init__(
        self,
        *,
        transport: GeminiTransport,
        api_key: str,
        model: str = DEFAULT_MODEL,
    ) -> None:
        self._transport = transport
        self._api_key = api_key
        self._model = model

    async def generate(self, request: LLMRequest) -> LLMTurnDecision:
        url = GENERATE_CONTENT_URL.format(model=self._model)
        body = _request_body(request)
        try:
            payload = self._transport.post_generate_content(
                url=url, api_key=self._api_key, body=body
            )
        except (
            urllib.error.URLError,
            json.JSONDecodeError,
            TimeoutError,
            OSError,
        ):
            raise _unavailable() from None
        return _turn_from_payload(
            payload,
            allowed_source_ids=request.allowed_source_ids,
            tool_names=request.tool_names,
        )


def _unavailable() -> LLMError:
    return LLMError(_UNAVAILABLE, _SAFE_UNAVAILABLE)


def _request_body(request: LLMRequest) -> dict[str, object]:
    parts: list[dict[str, object]] = [{"text": request.query}]
    if request.tone:
        parts.append({"text": f"TENANT_POLICY tone: {request.tone}"})
    if request.tenant_instructions:
        parts.append({"text": f"TENANT_POLICY instructions: {request.tenant_instructions}"})
    if request.knowledge:
        parts.append({"text": "EVIDENCE\n" + "\n".join(request.knowledge)})
    if request.history:
        parts.append({"text": "HISTORY\n" + "\n".join(request.history)})
    parts.append({"text": _OUTPUT_CONTRACT})
    if request.allowed_source_ids:
        parts.append(
            {
                "text": (
                    "Cite source_ids from this allowlist only: "
                    + ", ".join(request.allowed_source_ids)
                )
            }
        )
    for observation in request.tool_results:
        parts.append({"functionResponse": _function_response(observation)})
    body: dict[str, object] = {
        "systemInstruction": {"parts": [{"text": request.instructions}]},
        "contents": [{"role": "user", "parts": parts}],
    }
    if request.tool_names:
        body["tools"] = [
            {
                "functionDeclarations": [
                    {"name": name} for name in request.tool_names
                ]
            }
        ]
    return body


def _function_response(observation: ToolObservation) -> dict[str, object]:
    payload: dict[str, object] = {"ok": observation.ok}
    if observation.value is not None:
        payload["value"] = dict(observation.value)
    if observation.error_code is not None:
        payload["error_code"] = observation.error_code
    if observation.safe_message is not None:
        payload["safe_message"] = observation.safe_message
    return {"name": observation.name, "response": payload}


def _turn_from_payload(
    payload: Mapping[str, object],
    *,
    allowed_source_ids: tuple[str, ...],
    tool_names: tuple[str, ...],
) -> LLMTurnDecision:
    candidates = payload.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        raise _unavailable()
    first = candidates[0]
    if not isinstance(first, Mapping):
        raise _unavailable()
    content = first.get("content")
    if not isinstance(content, Mapping):
        raise _unavailable()
    parts = content.get("parts")
    if not isinstance(parts, list) or not parts:
        raise _unavailable()
    function_call = _first_function_call(parts)
    if function_call is not None:
        return _proposal_from_call(function_call, tool_names=tool_names)
    text = _first_text(parts)
    if text is None:
        raise _unavailable()
    return _decision_from_text(text, allowed_source_ids=allowed_source_ids)


def _first_function_call(parts: list[object]) -> Mapping[str, object] | None:
    for part in parts:
        if not isinstance(part, Mapping):
            continue
        call = part.get("functionCall")
        if isinstance(call, Mapping):
            return call
    return None


def _first_text(parts: list[object]) -> str | None:
    for part in parts:
        if not isinstance(part, Mapping):
            continue
        text = part.get("text")
        if isinstance(text, str):
            return text
    return None


def _proposal_from_call(
    call: Mapping[str, object], *, tool_names: tuple[str, ...]
) -> ToolCallProposal:
    name = call.get("name")
    if not isinstance(name, str) or name not in tool_names:
        raise _unavailable()
    raw_args = call.get("args", {})
    if raw_args is None:
        raw_args = {}
    if not isinstance(raw_args, Mapping):
        raise _unavailable()
    return ToolCallProposal(name=name, arguments=dict(raw_args))


def _decision_from_text(
    text: str, *, allowed_source_ids: tuple[str, ...]
) -> LLMDecision:
    try:
        parsed: object = json.loads(text)
    except json.JSONDecodeError as error:
        raise _unavailable() from error
    if not isinstance(parsed, Mapping):
        raise _unavailable()
    kind = _answer_kind(parsed.get("kind", "answer"))
    answer = parsed.get("text")
    if not isinstance(answer, str):
        raise _unavailable()
    raw_sources = parsed.get("source_ids", [])
    if raw_sources is None:
        raw_sources = []
    if not isinstance(raw_sources, list):
        raise _unavailable()
    source_ids: list[str] = []
    for item in raw_sources:
        if not isinstance(item, str):
            raise _unavailable()
        source_ids.append(item)
    cited = tuple(source_ids)
    if not set(cited) <= set(allowed_source_ids):
        raise _unavailable()
    return LLMDecision(kind=kind, text=answer, source_ids=cited)


def _answer_kind(value: object) -> AnswerKind:
    match value:
        case "answer" | "clarify" | "insufficient" | "handoff":
            return value
        case _:
            raise _unavailable()
