# ADR-010 — Gemini como LLM de runtime

**Estado:** accepted  
**Fecha:** 2026-08-31  
**Supersedes:** ninguno  
**Amends:** ninguno

## Contexto

El harness de development usa `FakeLLM` que ignora el `LLMRequest` y `EmptyKnowledgeSearch`. El perfil (ADR-008) llega al request y no se usa. El responsable del producto eligió **Gemini** (Google AI / `generativelanguage.googleapis.com`) como vendor. No hay secret manager: ADR-007 ya mapea `sm://` → `IA_MCP_SECRET_*`.

`gemini-2.0-flash` está apagado (junio 2026). El modelo de runtime es `gemini-3.5-flash` vía `generateContent`.

ADR-002, ADR-006, ADR-007 y ADR-008 siguen vigentes. Esta decisión no abre mutaciones en el turno ni concatena texto de tenant con Core.

## Decisión

1. `GeminiLLM` implementa `LLMPort.generate`. Tests siguen usando `FakeLLM`.
2. Transporte: `POST https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash:generateContent` con header `x-goog-api-key`. Sin SDK obligatorio; `urllib.request` o un puerto `GeminiTransport` inyectable.
3. Clave: `sm://platform/llm/gemini` → `IA_MCP_SECRET_PLATFORM_LLM_GEMINI`. Nunca en repo, HTML, logs, traces ni fixtures. Si no resuelve, el adapter no se construye (fail-closed); T04 deja `FakeLLM`.
4. Mapeo del request (campos separados, sin concatenar Core con tenant):
   - `LLMRequest.instructions` → `systemInstruction` (Core).
   - `tone` y `tenant_instructions` → parte aparte etiquetada como política de tenant.
   - `knowledge` → contenido EVIDENCE.
   - `tool_names` → `functionDeclarations`.
   - `tool_results` → partes `functionResponse`.
5. Respuesta: texto + `source_ids` citados ⊆ `allowed_source_ids` → `LLMDecision`; `functionCall` cuyo nombre está en `tool_names` → `ToolCallProposal(name=..., arguments=...)`; otro caso o error de red → **lanzar** `LLMError` con `code="provider_unavailable"`. El harness ya captura esa excepción y mapea a insufficient. `generate` es `async` y no devuelve `LLMError`.
6. Cero ramas por slug. El mismo adapter sirve a todos los tenants.

## Consecuencias positivas

- El runtime puede responder con un modelo real.
- La clave sigue el plano de secretos existente.

## Consecuencias negativas

- Dependencia de red y cuota Gemini.
- Sin clave, el proceso sigue en FakeLLM (bot débil).

## Alternativas descartadas

- LabLLM heurístico: el producto eligió Gemini.
- OpenAI/Anthropic: no decididos.
- Concatenar tenant + Core: viola ADR-008.
- Clave en `IA_MCP_GEMINI_API_KEY` suelta sin `sm://`: rompe el patrón ADR-007.

## Verificación

- Tests del adapter con transporte fake: nunca una clave real.
- Aislamiento: el body hacia Gemini de B no contiene canarios de A.
- Error HTTP → se lanza `LLMError`; harness `insufficient`.
- `FakeLLM` de `ports.py` intacto.

## Rollback/sustitución

Dejar de inyectar `GeminiLLM` en composition. El harness vuelve a `FakeLLM`.
