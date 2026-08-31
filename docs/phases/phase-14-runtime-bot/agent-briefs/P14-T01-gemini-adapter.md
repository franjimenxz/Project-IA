# P14-T01 — Adaptador Gemini

**Estado:** accepted · **Wave:** W13 · **Depends on:** Fase 12 accepted; ADR-010 accepted

Crear `GeminiLLM` que implementa `LLMPort` contra Gemini 3.5 Flash vía transport inyectable. Sin red real en tests. Sin tocar `composition.py`.

Commit: `feat: add Gemini LLM adapter (P14-T01)`

## Lectura obligatoria

1. `docs/README.md`
2. `docs/00-governance/delegation-protocol.md`
3. [ADR-010](../../../01-architecture/adr/ADR-010-gemini-runtime-llm.md)
4. [../TDD.md](../TDD.md)
5. [../acceptance-criteria.md](../acceptance-criteria.md) (AC-P14-001 a AC-P14-004, AC-P14-010)
6. [../test-plan.md](../test-plan.md)
7. Código: `src/ia_mcp/agent_runtime/ports.py` (`LLMPort`, `LLMError`, `FakeLLM`), `src/ia_mcp/agent_runtime/models.py` (`LLMRequest`, `LLMDecision`, `ToolCallProposal`, `LLMTurnDecision`, `ToolObservation`)

## Archivos permitidos

**Crear:**

- `src/ia_mcp/llm/gemini.py`
- `src/ia_mcp/llm/__init__.py` si no existe
- `tests/unit/llm/test_gemini.py`
- `tests/security/test_gemini_tenant_isolation.py`

**No tocar:**

- `src/ia_mcp/api/composition.py`
- `src/ia_mcp/agent_runtime/ports.py` (`FakeLLM` intacto)
- `src/ia_mcp/agent_runtime/harness.py`
- secretos, HTML, `docs/00-governance/delegation-board.md`

## Interfaces

```python
class GeminiTransport(Protocol):
    def post_generate_content(
        self, *, url: str, api_key: str, body: dict[str, object]
    ) -> dict[str, object]: ...

class GeminiLLM:
    def __init__(
        self,
        *,
        transport: GeminiTransport,
        api_key: str,
        model: str = "gemini-3.5-flash",
    ) -> None: ...
    async def generate(self, request: LLMRequest) -> LLMTurnDecision: ...
```

`generate` es `async` (el harness hace `await self._llm.generate`). Ante fallo lanza `LLMError` con `code="provider_unavailable"`; no lo devuelve. El transport por defecto usa `urllib.request`. Los tests inyectan un transport fake. Timeout 10s.

URL: `https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent`.  
Header: `x-goog-api-key`.

Mapeo:

- `request.instructions` → `systemInstruction` (solo Core).
- `tone` y `tenant_instructions` → partes de usuario distintas, sin concatenar con Core.
- `knowledge` → bloque EVIDENCE.
- `tool_names` → `functionDeclarations`.
- `tool_results` → `functionResponse`.
- Texto + `source_ids` ⊆ `allowed_source_ids` → `LLMDecision`.
- `functionCall` cuyo nombre ∈ `tool_names` → `ToolCallProposal(name=..., arguments=...)`.
- HTTP no-2xx, JSON inválido, tool o source fuera de allowlist → `raise LLMError(...)`.

No ramificar por `tenant_id` ni slug. No poner esos campos en el body. No loguear `api_key` ni el body. Tests con `api_key="test-not-a-secret"`.

## TDD

1. Rojo: `test_gemini.py` — decision, proposal, `LLMError`, no-concat.
2. Implementar `GeminiLLM` + transport por defecto.
3. Verde. Isolation: dos tenants distintos producen el mismo mapeo de campos (el adaptador no lee el slug).

## Verificación

```text
pytest tests/unit/llm/test_gemini.py tests/security/test_gemini_tenant_isolation.py -v
ruff check src/ia_mcp/llm tests/unit/llm tests/security/test_gemini_tenant_isolation.py
```

Criterios: AC-P14-001, AC-P14-002, AC-P14-003, AC-P14-004, AC-P14-010.

## Exclusiones

- No cablear composition (T04).
- No llamar a `generativelanguage.googleapis.com` desde un test.
- No editar el tablero.
