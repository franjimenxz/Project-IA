# TDD — Cerrar el bot de runtime

**ID:** TDD-P14-001  
**Estado:** ready  
**ADRs:** ADR-002, ADR-006, ADR-007, ADR-008, ADR-010  
**Requisitos:** RF-004, RF-008, RF-009, RF-011, RF-012, RNF-001, RNF-010

## Objetivo

Cerrar el runtime de development para que `AgentHarness.handle_message` deje de devolver siempre el texto fijo de `AnswerPolicy` y pueda:

1. consultar evidencia del paquete del tenant;
2. anunciar herramientas de lectura FAQ;
3. llamar a Gemini y mapear la respuesta a `LLMDecision` o `ToolCallProposal`;
4. ejecutar esas herramientas y reentrar al bucle de Fase 11.

Hoy el harness ya copia `tone` y `tenant_instructions` (Fase 12) y ya tiene el loop (Fase 11). Nadie lee el request: `FakeLLM` hace `del request`. `EmptyKnowledgeSearch` (en `composition.py`) devuelve `()`. `FAQSkill.allowed_tools` ignora `config` y devuelve `frozenset()`. `ContextCompiler` toma el término tenant de `tenant_tools` inyectado; `build_runtime` pasa `tenant_tools={}`.

## Dependencias

- Fase 11 aceptada: `ToolCallProposal`, `tool_results` en `LLMRequest`, bucle en `AgentHarness`.
- Fase 12 aceptada: `tone` y `tenant_instructions` en cada `generate`.
- `LLMPort.generate` es `async` y **lanza** `LLMError`; no lo devuelve. El harness ya mapea esa excepción a insufficient.
- `KnowledgeSearch.search` es `async` y recibe `KnowledgeQuery`, no un `str`.
- El secreto Gemini vive fuera del repo (`sm://platform/llm/gemini` → `IA_MCP_SECRET_PLATFORM_LLM_GEMINI`). Esta fase no lo inventa ni lo escribe.

## No objetivos

- Mutaciones conversacionales (`appointments.create`, `cancel`, `reschedule`, `confirm`).
- WhatsApp Cloud, embeddings, PDF, OCR.
- Heurística local como LLM de runtime.
- Concatenar `instructions` del Core con `tenant_instructions`.
- Inventar campos médicos o APIs clínicas.
- Condiciones por `tenant_id` o slug en Core o en el adaptador Gemini.
- Editar `FakeLLM` ni borrar `EmptyKnowledgeSearch`.

## Contratos

### GeminiLLM

Implementa `LLMPort`. `generate` es `async` y lanza `LLMError("provider_unavailable")` ante HTTP no-2xx, JSON inválido, `functionCall` fuera de `tool_names` o `source_ids` que no sean subconjunto de `allowed_source_ids`.

Recibe `GeminiTransport` inyectable y `api_key: str`. No lee env ni `SecretResolver`. No registra el body ni el header `x-goog-api-key`. No incluye `tenant_id` ni slug en el body hacia Gemini.

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

Mapeo (campos separados, sin concatenar Core con tenant):

- `request.instructions` → `systemInstruction` (solo Core).
- `tone` y `tenant_instructions` → partes de usuario distintas, etiquetadas como política de tenant.
- `knowledge` → bloque EVIDENCE.
- `tool_names` → `functionDeclarations`.
- `tool_results` → `functionResponse`.
- Texto + `source_ids` ⊆ `allowed_source_ids` → `LLMDecision` (`ToolCallProposal.name` no aplica).
- `functionCall` cuyo nombre ∈ `tool_names` → `ToolCallProposal(name=..., arguments=...)`.

URL: `https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent`. Header `x-goog-api-key`. Timeout 10s en el transport por defecto (`urllib.request`).

El prompt pide citar `source_ids` del allowlist. Un `source_ids` vacío es subconjunto válido; `AnswerPolicy` ya convierte `answer` sin citas en insufficient.

### LabKnowledgeSearch

Implementa `KnowledgeSearch` (`src/ia_mcp/agent_runtime/ports.py`). Recibe `packages_dir: Path`.

```python
class LabKnowledgeSearch:
    def __init__(self, *, packages_dir: Path) -> None: ...
    async def search(
        self, tenant: TenantContext, query: KnowledgeQuery
    ) -> tuple[KnowledgeHit, ...]: ...
```

- Lee solo `{packages_dir}/{tenant.tenant_slug}/knowledge/*.txt`. El directorio del paquete es el **slug**, no el UUID.
- Si el directorio no existe, `()`.
- `source_id` = nombre de archivo (`hours-b.txt`), no path absoluto.
- `document_id` estable: `uuid5` de `tenant.tenant_id` + nombre de archivo. `document_version=1`, `page=1`.
- Ranking: substring / token overlap. Sin embeddings ni red.
- No lee el paquete de otro slug.

`EmptyKnowledgeSearch` permanece en `composition.py` hasta T04.

### FAQSkill.allowed_tools

Firma actual: `allowed_tools(self, config: TenantConfig) -> frozenset[ToolName]`.

Devuelve `config.enabled_tools ∩ {appointments.search, appointments.get}` (como `ToolName`). No incluye `appointments.create`, `appointments.cancel`, `appointments.reschedule`, `appointments.confirm`. Si `enabled_tools` está vacío, sigue `frozenset()`.

### ContextCompiler

El término tenant de `tool_registry.available` es `config.enabled_tools`, no `self._tenant_tools.get(tenant.tenant_id, ())`.

`server_tools` acepta además un `frozenset[str]` de proceso (mismo catálogo para todos los tenants). `None` o clave ausente en el mapping siguen siendo catálogo vacío (fail-closed). T04 pasa `frozenset({"appointments.search", "appointments.get"})`.

La intersección tenant ∩ skill ∩ servidor no cambia de semántica.

### build_runtime

Sigue síncrono. No llama `SecretResolver.resolve` (es async y lanza si falta). Lee `environ.get(environment_variable_for("sm://platform/llm/gemini"))`:

- valor no vacío → `GeminiLLM` con transport por defecto y esa clave;
- ausente o blank → `FakeLLM` actual (fail-closed, no lanza).

Knowledge: si `tenant_packages_dir` está definido → `LabKnowledgeSearch`; si no → `EmptyKnowledgeSearch`.

`ContextCompiler(..., server_tools=frozenset({"appointments.search", "appointments.get"}))`. El término tenant lo resuelve T03 desde `config.enabled_tools`.

Sigue exigiendo `DATABASE_URL` y `environment=="development"`.

## Pruebas

Ver [test-plan.md](test-plan.md). Cada brief cita los casos que debe escribir su implementador.
