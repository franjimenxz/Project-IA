# TDD — Loop de tool calls en el turno

**ID:** TDD-P11-001  
**Estado:** draft  
**ADRs:** ADR-002, ADR-003, ADR-005, ADR-006  
**Requisitos:** RF-004, RF-008, RF-023, RF-034, RF-044, RNF-001, RNF-004, RNF-009, RNF-011

## Problema

El turno llama al modelo una vez y no tiene rama de ejecución de tools. El contrato de decisión no admite una tool call, el executor cableado en Fase 10 no tiene consumidor y los appointments corren por un carril de workflow sin vínculo con el turno. Ver estado verificado en ADR-006 §Contexto.

## Contrato de decisión

`AnswerKind` no cambia. Se agrega un tipo hermano y se ensancha el retorno del puerto:

```python
@dataclass(frozen=True, slots=True)
class ToolCallProposal:
    name: str
    arguments: Mapping[str, Any]

type LLMTurnDecision = LLMDecision | ToolCallProposal

class LLMPort(Protocol):
    async def generate(self, request: LLMRequest) -> LLMTurnDecision: ...
```

Ensanchar el retorno es compatible con toda implementación existente: `FakeLLM` (`src/ia_mcp/agent_runtime/ports.py:22-28`) sigue devolviendo `LLMDecision`, que es miembro de la unión.

## Realimentación

`LLMRequest` gana un campo con default, de modo que ningún constructor existente se rompe:

```python
@dataclass(frozen=True, slots=True)
class ToolObservation:
    name: str
    ok: bool
    value: Mapping[str, object] | None = None
    error_code: str | None = None
    safe_message: str | None = None

# LLMRequest
tool_results: tuple[ToolObservation, ...] = ()
```

Reglas de construcción de la observación:

- `value` sale de `ia_mcp.mcp.audit.sanitize_summary` sobre el `value` del `ToolResult`.
- `error_code` y `safe_message` salen de `ToolError`; `upstream_reference` (`src/ia_mcp/contracts/errors.py:25`) nunca se copia.
- La observación se enmarca como evidencia no confiable, con el mismo criterio que `context_compiler._evidence` (`src/ia_mcp/agent_runtime/context_compiler.py:44-45`) y bajo `CORE_INSTRUCTIONS` (`context_compiler.py:17-20`).
- La iteración N+1 se compila con el mismo `TenantContext` y la misma `config_version` del turno.

## Resultado del turno

```python
# AgentTurnResult
tool_names: tuple[str, ...] = ()                 # anunciadas (significado actual, sin cambio)
tool_calls: tuple[ExecutedToolCall, ...] = ()    # ejecutadas en este turno
```

`ExecutedToolCall` lleva `name`, `ok` y `error_code | None`. Los argumentos no se copian al resultado del turno.

## Superficie invocable

```text
invocable_en_turno = discovered ∩ tenant ∩ skill ∩ turn
```

`turn` se deriva sin catálogo cerrado:

| Caso | Regla | Fundamento mecánico |
|---|---|---|
| Tool canónica sin idempotency key | invocable | `_dispatch_capability` no llama `_require_idempotency_key` para `search` ni `get` (`src/ia_mcp/mcp/executor.py:292-297`) |
| Tool canónica con idempotency key | no invocable | Sí lo llama para `create`, `cancel`, `reschedule`, `confirm` (`executor.py:303`, `:310`, `:319`, `:326`); exigir clave es la marca de mutación de ADR-003 |
| Tool descubierta no canónica | no invocable | Core no conoce su semántica; presumir lectura violaría BR-007. Fail-closed hasta que el tenant lo declare |

`KNOWN_TOOLS` se usa aquí como alias canónico de dispatch, el rol que ADR-005 §3 le conserva; no vuelve a ser deny-list de autorización.

## Loop

```text
compile → generate
  while iteración < max_tool_iterations y deadline no vencido:
      decision = generate(request con tool_results acumuladas)
      si decision es terminal: policy.apply → finish
      si decision es ToolCallProposal:
          si (name, arguments) ya ejecutado en este turno: finish insufficient
          si name no está en invocable_en_turno: observación forbidden; iteración += 1
          si no: executor.execute(tenant, run_id, ToolCall(...)) → observación; iteración += 1
  presupuesto agotado → finish insufficient
```

El executor se obtiene por turno desde la factory ya existente `TenantToolExecutors.for_tenant(tenant, config, skill)` (`src/ia_mcp/api/composition.py:119-130`). No se cachea entre tenants ni entre turnos.

## Límites

| Parámetro | Valor | Fundamento |
|---|---|---|
| `max_tool_iterations` | 4 | Cadena de lectura más profunda hoy implementada: 2 (`appointments.get` en `src/ia_mcp/workflows/appointments/reschedule.py:228`, luego `appointments.search` en `:297`), más margen para una corrección tras `validation_error` |
| Llamadas al modelo | hasta 5 | Una por iteración más la terminal |
| `turn_deadline_seconds` | 30.0 | `SseMcpClient` usa 10 s por llamada (`src/ia_mcp/mcp/client.py:31`); el deadline se fija por debajo del producto de 4 iteraciones |
| Retries en el harness | ninguno | La política vive en el transporte (`_RETRYABLE`, `client.py:25`); duplicarla violaría BR-010 |

Ambos son parámetros del composition root. `TenantConfig.feature_flags` es `Mapping[str, bool]` (`src/ia_mcp/configuration/models.py:57`) y no puede transportar enteros; un límite por tenant exige cambio de contrato coordinado.

## Agotamiento y errores

| Condición | Resultado del turno | `error_code` del run |
|---|---|---|
| Iteraciones agotadas | `insufficient` con `SAFE_INSUFFICIENT` | `tool_budget_exhausted` |
| Deadline vencido | `insufficient` con `SAFE_INSUFFICIENT` | `turn_deadline_exceeded` |
| Par `(name, arguments)` repetido | `insufficient` | `tool_call_repeated` |
| Dos `forbidden` en el turno | `handoff` con `SAFE_HANDOFF` | run `handed_off` |
| `LLMError` | `insufficient` | `provider_unavailable`, sin cambio (`src/ia_mcp/agent_runtime/harness.py:152-164`) |
| `tenant_isolation_violation` | aborto, sin realimentar nada | run `failed`, auditoría crítica |

`AgentRunRepository.finish` acepta `error_code: str | None` (`src/ia_mcp/agent_runtime/ports.py:49-58`); estos códigos siguen la convención ya usada por el harness.

Códigos realimentados al modelo como observación, sin capa de retry propia: `validation_error`, `forbidden`, `not_found`, `conflict`, `contract_violation`, `upstream_timeout`, `upstream_unavailable`.

## Aislamiento

- Todo boundary del loop recibe `TenantContext`; el `run_id` del turno se propaga a cada `ToolExecutor.execute`.
- El executor se construye desde el `TenantContext` del turno; no hay instancia compartida entre tenants.
- Ninguna observación de un tenant entra al `LLMRequest` de otro.
- Cero condiciones por slug o nombre de institución en harness, executor o compiler.

## Observabilidad

| Span | Estado hoy | En esta fase |
|---|---|---|
| `agent.run` | declarado sin uso (`src/ia_mcp/observability/semconv.py:18`) | span raíz del turno |
| `llm.generate` | declarado sin uso (`semconv.py:21`) | uno por iteración |
| `tool.execute` | emitido dentro del executor (`src/ia_mcp/mcp/executor.py:183`) | alcanzable desde un turno por primera vez |
| `mcp.resolve` | emitido dentro del executor (`executor.py:221`) | idem |

El índice de iteración no es atributo de span: `ALLOWED_SPAN_ATTRIBUTES` no lo incluye y `span_attributes` descarta claves fuera del set (`semconv.py:29-47`, `:102`). Se deriva de la cardinalidad de spans hijos.

Auditoría: el loop pasa el `run_id` del turno a `ToolExecutor.execute`, de modo que `ToolAuditEvent` (`src/ia_mcp/mcp/executor.py:72-79`) queda correlacionado. La persistencia durable es dependencia abierta: `RunInvestigation.tools` se arma hoy desde filas de `workflow_transition` con `event_type` prefijado `tool.` (`src/ia_mcp/observability/adapters/sqlalchemy_run_query.py:118`, `:451-472`), y una tool del loop no tiene workflow.

## Consumidores del contrato

| Consumidor | Efecto |
|---|---|
| `src/ia_mcp/evals/runner.py:405`, `:418` | Sin cambio; `AnswerKind` intacto y la exhaustividad `Never` sigue compilando |
| `src/ia_mcp/evals/runner.py:366` | `observe_turn` usa `tool_calls` cuando hay ejecuciones y `tool_names` cuando no |
| `src/ia_mcp/evals/scorers.py:105-114` | Deja de medir anuncio y pasa a medir ejecución sin invalidar datasets existentes |
| `src/ia_mcp/skills/faq.py:14-41` | Sin cambio; la política sólo ve decisiones terminales |
| `src/ia_mcp/channels/outbox.py:18`, `:27` | Sin cambio; `kind` es `str` y nunca recibe `tool_call` |
| `src/ia_mcp/api/routes/simulated.py:130` | Sin cambio de firma; el turno puede tardar más |

## No objetivos

- Invocar el workflow engine desde el turno.
- Cambiar `AnswerKind`, `EvalOutcome` o el contrato del canal.
- Inventar API médica, credenciales, autenticación, vendor de LLM o campos institucionales.
- Secret values en docs, fixtures, logs, traces o prompts.
