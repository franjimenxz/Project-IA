# ADR-006 — Loop de tool calls en el turno conversacional

**Estado:** proposed  
**Fecha:** 2026-08-29  
**Supersedes:** ninguno  
**Amends:** ninguno

## Contexto

Las Fases 3, 9 y 10 construyeron discovery MCP, autorización por intersección, invocación genérica y composition root. Nada de eso llega al turno conversacional. El estado verificado en `main` (`9380843`):

| Hecho | Evidencia |
|---|---|
| El harness es sólo FAQ | `src/ia_mcp/agent_runtime/harness.py:78` resuelve la skill literal `"faq"`; `:99` abre el run con `skill=self._faq.name`; no hay otra rama |
| Una sola llamada al modelo | `harness.py:139` `self._llm.generate(...)` se ejecuta una vez; `:165` aplica política y `:170` termina el run |
| El contrato no admite tool calls | `src/ia_mcp/agent_runtime/models.py:5` `AnswerKind = Literal["answer", "clarify", "insufficient", "handoff"]` |
| Al modelo se le anuncian tools que no puede pedir | `models.py:17` `LLMRequest.tool_names`; se llena en `harness.py:136` desde `compiled.tool_schemas` y nunca vuelve nada |
| El executor no tiene consumidor | `src/ia_mcp/api/composition.py:228` asigna `app.state.tool_executor`; ninguna ruta lo lee (`src/ia_mcp/api/routes/simulated.py` sólo lee `tenant_service`, `agent_harness`, `config_service`, `outbox`, `channel_integration_ids`) |
| `AgentHarness` no acepta executor | `harness.py:31-50`, constructor sin parámetro de tools |
| Los appointments viven en otro carril | `src/ia_mcp/skills/appointments.py:25-27` `route()` descarta el turno y devuelve `SkillResult(kind="appointments")`; los workflows sólo se instancian en tests y en `src/ia_mcp/performance/scenarios.py:160` |
| El carril de workflow ni comparte el run | `src/ia_mcp/scheduling/ingress.py:51` y `:59` pasan `run_id=uuid4()` fresco, sin relación con el turno |

Consecuencia: un usuario conversando sólo puede recibir FAQ. `tool.execute` y `mcp.resolve` están instrumentados dentro del executor (`src/ia_mcp/mcp/executor.py:183`, `:221`) pero jamás se emiten desde un turno; `agent.run` y `llm.generate` están declarados en `src/ia_mcp/observability/semconv.py:18` y `:21` y no se usan en ningún lado.

ADR-003 (contratos canónicos y workflows determinísticos para mutaciones) y ADR-005 (discovery e intersección sin catálogo cerrado) siguen vigentes. Esta decisión no los modifica: define cómo el turno consume lo que ADR-005 ya autoriza, sin romper la regla de ADR-003 de que una mutación pasa por workflow.

## Decisión

### 1. Tipo de decisión separado; `AnswerKind` no cambia

`AnswerKind` tipa tres cosas distintas: `LLMDecision.kind`, `PolicyDecision.kind` y `AgentTurnResult.kind` (`models.py:22`, `:29`, `:36`). Una propuesta de tool call sólo es válida en la primera. Agregar `"tool_call"` al alias compartido haría representable un estado inválido en las otras dos y rompería a los consumidores.

Se agrega un tipo hermano y se ensancha el retorno del puerto:

```python
@dataclass(frozen=True, slots=True)
class ToolCallProposal:
    name: str
    arguments: Mapping[str, Any]

type LLMTurnDecision = LLMDecision | ToolCallProposal
```

`LLMPort.generate` devuelve `LLMTurnDecision`. Es un ensanchamiento del retorno: toda implementación existente que devuelve `LLMDecision` sigue siendo válida sin cambios, incluida `FakeLLM` (`src/ia_mcp/agent_runtime/ports.py:22-28`).

Consumidores afectados y estrategia de compatibilidad:

| Consumidor | Uso actual | Efecto |
|---|---|---|
| `src/ia_mcp/evals/runner.py:405`, `:418` | `_outcome_from_kind` / `_skill_from_kind` con `exhaustive: Never = kind` | Sin cambio: `AnswerKind` no gana miembros, la exhaustividad estricta sigue compilando |
| `src/ia_mcp/evals/models.py:21-28` | `EvalOutcome` como `expected_outcome` del dataset | Sin cambio: no se agrega un outcome que nunca sería esperable |
| `src/ia_mcp/skills/faq.py:14-41` | `AnswerPolicy.apply` sobre `LLMDecision` | Sin cambio: la política sigue recibiendo sólo decisiones terminales; el loop resuelve la propuesta antes |
| `src/ia_mcp/agent_runtime/context_compiler.py:105` | `CompiledContext.tool_schemas` | Sin cambio de forma; pasa a alimentar además el catálogo invocable del turno |
| `src/ia_mcp/channels/outbox.py:18`, `:27` | `OutboundDelivery.kind` y `SimulatedTurnResponse.kind` son `str` | Sin cambio: el canal nunca recibe `tool_call` |
| `src/ia_mcp/evals/scorers.py:105-114` | `observed_tools` se compara contra `allowed_tools`/`forbidden_tools` | **Cambia**: hoy `observe_turn` (`runner.py:366`) construye `ObservedToolCall` desde `AgentTurnResult.tool_names`, que son tools *anunciadas*, no ejecutadas |

Por eso `AgentTurnResult` gana un campo aparte, con default, y `tool_names` conserva su significado:

```python
tool_names: tuple[str, ...] = ()      # anunciadas al modelo (sin cambio)
tool_calls: tuple[ExecutedToolCall, ...] = ()   # ejecutadas en el turno
```

`observe_turn` usa `tool_calls` cuando hay ejecuciones y `tool_names` cuando no, de modo que los datasets existentes no empiezan a fallar por `unexpected_tool`.

### 2. El loop vive en el harness, no en la skill

`Skill.route()` recibe `SkillTurn(tenant, text)` y devuelve `SkillResult(kind: str)` (`src/ia_mcp/skills/base.py:15-33`): no tiene executor, ni `run_id`, ni LLM, ni repositorio de runs. Orquestar desde la skill obligaría a inyectar ese grafo en cada skill y a duplicar por skill el ciclo de run, la auditoría y el límite de iteraciones. El harness ya es dueño del ciclo (`harness.py:95`, `:191`) y el TDD del sistema §8 le asigna «interacción con LLM» y «dispatch a knowledge/workflow/handoff». Las skills siguen declarativas: `allowed_tools` y `required_fields`.

### 3. La superficie invocable del turno es un cuarto término fail-closed

ADR-005 autoriza por `discovered ∩ tenant ∩ skill`. El turno agrega un cuarto término:

```text
invocable_en_turno = discovered ∩ tenant ∩ skill ∩ turn
```

`turn` se resuelve así, sin catálogo cerrado y sin ramificar por institución:

- Una tool canónica es invocable en el turno **si y sólo si su dispatch no exige idempotency key**. La prueba es mecánica, no de nombre: `ToolExecutor._dispatch_capability` llama `_require_idempotency_key` para `create`, `cancel`, `reschedule` y `confirm` (`executor.py:303`, `:310`, `:319`, `:326`) y no lo hace para `search` ni `get` (`:292-297`). Exigir clave de idempotencia es exactamente la marca de mutación de ADR-003.
- Una tool **descubierta no canónica** no es invocable en el turno salvo que el tenant la declare explícitamente. Core no puede conocer su semántica de mutación, y presumir lectura violaría BR-007. El default vacío es fail-closed.

Esto preserva ADR-005: `KNOWN_TOOLS` sigue sin ser deny-list de autorización; acá se usa como alias canónico de dispatch, que es el rol que ADR-005 §3 le conserva. Una tool descubierta no se rechaza «por no estar en `KNOWN_TOOLS`», se rechaza por no estar declarada por el tenant.

`TenantConfig` no puede transportar hoy esa declaración: `enabled_tools` es `frozenset[str]` sin distinción de superficie y `feature_flags` es `Mapping[str, bool]` (`src/ia_mcp/configuration/models.py:52`, `:57`). Agregar el campo es un cambio de contrato de configuración y requiere coordinación de owners (`docs/00-governance/file-map.md`). Hasta que exista, el término `turn` es el subconjunto canónico sin idempotency key, y el loop queda inerte para catálogos institucionales.

### 4. El workflow engine no se invoca desde el turno en esta decisión

El turno no llama `WorkflowEngine.start` ni `advance`. Razones:

- El TDD del sistema §7.10 y BR-007 exigen que toda mutación pase por workflow con validación y resultado tipado; una tool call propuesta por el modelo no lo es.
- `ToolCall.idempotency_key` es `str | None` (`executor.py:47`) y su ausencia devuelve `validation_error` (`executor.py:330`). Un loop que dejara al modelo elegir esa clave pondría la idempotencia en manos de un string generado. Derivarla determinísticamente es competencia del workflow, no del harness.
- Las definitions esperan `(engine, executor, tenant, workflow_id, command_id=..., run_id=...)` (por ejemplo `src/ia_mcp/workflows/appointments/create.py:366`). El turno tiene `run_id` pero no existe política de asignación de `workflow_id` ni de `command_id` desde un mensaje entrante, ni entrada HTTP que la ejerza.

En consecuencia, una intención de mutación termina el turno en `handoff` con el texto seguro existente (`SAFE_HANDOFF`, `src/ia_mcp/skills/faq.py:10`). El puente turno→workflow es una fase posterior con su propio ADR.

### 5. Límites duros del loop

| Límite | Valor | Fundamento |
|---|---|---|
| `max_tool_iterations` | 4 | La cadena de lectura más profunda hoy implementada es 2 (`appointments.get` en `workflows/appointments/reschedule.py:228` y luego `appointments.search` en `:297`); 4 deja margen para una corrección del modelo tras un `validation_error` sin permitir divergencia |
| Llamadas al modelo por turno | `max_tool_iterations + 1` = 5 | Cada iteración consume una `llm.generate`; la última produce la respuesta terminal |
| `turn_deadline_seconds` | 30.0 (techo) | `SseMcpClient` usa 10 s por llamada (`src/ia_mcp/mcp/client.py:31`); 4 iteraciones con una tool cada una admitirían 40 s sólo de transporte, así que el deadline es el límite que manda y se fija deliberadamente por debajo del producto ingenuo |
| Reintentos propios del harness | ninguno | La política de reintento vive en el transporte (`_RETRYABLE`, `client.py:25`); duplicarla en el loop violaría BR-010 |

Ambos límites son parámetros del composition root, no de `TenantConfig`: `feature_flags` es `Mapping[str, bool]` y no puede transportar enteros (`configuration/models.py:57`). Un límite por tenant exige el mismo cambio de contrato coordinado del punto 3.

Al agotarse el presupuesto el turno **no** responde parcialmente. Termina en `insufficient` con `SAFE_INSUFFICIENT` y el run se cierra `failed` con `error_code="tool_budget_exhausted"` (deadline: `"turn_deadline_exceeded"`). El repositorio ya acepta códigos de error libres en `finish` y el harness ya usa `"retrieval_unavailable"` y `"provider_unavailable"` así (`harness.py:110`, `:154`).

### 6. Realimentación del `ToolResult` como evidencia no confiable

`LLMRequest` gana un campo con default:

```python
tool_results: tuple[ToolObservation, ...] = ()
```

Cada `ToolObservation` lleva `name`, `ok`, y o bien un `value` saneado o bien `error_code` más `safe_message`. Reglas:

- El valor se sanea con `ia_mcp.mcp.audit.sanitize_summary` antes de entrar al request.
- `ToolError.upstream_reference` (`src/ia_mcp/contracts/errors.py:25`) **nunca** se realimenta al modelo.
- La observación se enmarca como evidencia no confiable, igual que un chunk de conocimiento (`context_compiler._evidence`, `context_compiler.py:44-45`), porque un `ToolResult` de un MCP institucional es un vector de inyección idéntico. `CORE_INSTRUCTIONS` ya ordena tratar los bloques de evidencia como datos y no como instrucciones (`context_compiler.py:17-20`).
- El request de la iteración N+1 se compila con el mismo `TenantContext` y la misma `config_version` del turno; una activación concurrente no cambia la configuración a mitad de loop (TDD del sistema §6).

### 7. Errores tipados y comportamiento del loop

| Condición | Código | Comportamiento del loop |
|---|---|---|
| Tool fuera de la intersección o host no allowlisted | `forbidden` | El executor ya devuelve `ToolResult(ok=False, error=_FORBIDDEN)` y audita `allowed=False` (`executor.py:206-216`, `:234-245`). Se realimenta código y mensaje seguro sin revelar qué allowlist rechazó. Dos `forbidden` en el turno terminan en `handoff` |
| Argumentos inválidos | `validation_error` | Se realimenta; el modelo puede corregir una vez. El mismo par `(name, arguments)` no se ejecuta dos veces en un turno; la repetición termina en `insufficient` |
| `not_found`, `conflict`, `contract_violation` | idem | Se realimentan como observación; consumen iteración |
| Timeout o caída del MCP | `upstream_timeout` / `upstream_unavailable` | Sin capa de retry en el harness. Se realimenta y consume iteración; agotado el presupuesto, degradación segura |
| Violación de aislamiento | `tenant_isolation_violation` | Aborto inmediato. No se realimenta nada al modelo, el run cierra `failed` y se audita como crítico, según TDD del sistema §18 |
| Proveedor LLM caído | `LLMError` | Se conserva el comportamiento actual: run `failed` con `provider_unavailable` y turno `insufficient` (`harness.py:152-164`). Como la superficie del turno es de sólo lectura, una caída a mitad de loop no deja mutación parcial que compensar |

### 8. Aislamiento por turno

El executor se construye por turno a partir del `TenantContext` del turno y nunca se cachea entre tenants. La factory ya existe con esa forma: `TenantToolExecutors.for_tenant(tenant, config, skill)` (`src/ia_mcp/api/composition.py:119-130`). El harness consume la factory, no una instancia compartida.

### 9. Observabilidad

- `agent.run` (`semconv.py:18`) pasa a ser el span raíz del turno.
- `llm.generate` (`semconv.py:21`) se emite una vez por iteración.
- `tool.execute` y `mcp.resolve` ya se emiten dentro del executor (`executor.py:183`, `:221`) y por primera vez quedan alcanzables desde un turno.
- El índice de iteración **no** es atributo de span. `ALLOWED_SPAN_ATTRIBUTES` (`semconv.py:29-47`) no lo incluye y `span_attributes` descarta en silencio cualquier clave fuera del set (`semconv.py:102`); reusar `retry_count` sería semánticamente falso. El conteo se deriva de la cardinalidad de spans hijos. Extender `semconv` requiere coordinación de owners.
- Auditoría: `ToolAuditEvent` ya transporta `run_id`, `tenant_id`, `tool`, `allowed`, `error_code` y `mcp_server_id` y se sanea en `ToolAuditAdapter` (`src/ia_mcp/mcp/audit.py:44-63`). El loop pasa el `run_id` del turno, cosa que hoy nadie hace.
- Persistencia: la vista de investigación arma `RunInvestigation.tools` leyendo filas de `workflow_transition` cuyo `event_type` empieza con `tool.` (`src/ia_mcp/observability/adapters/sqlalchemy_run_query.py:118`, `:451-472`). Una tool ejecutada por el loop no tiene workflow y hoy quedaría invisible. Cerrar ese hueco es un cambio en `src/ia_mcp/observability` con migración, de owner distinto, y se declara dependencia explícita de esta fase.

## Consecuencias positivas

- El turno conversacional puede usar la maquinaria MCP ya construida y probada de Fases 3, 9 y 10.
- `AnswerKind`, `EvalOutcome`, la política de respuesta y el contrato del canal no cambian; la extensión es aditiva y con defaults.
- La distinción entre tools anunciadas y ejecutadas vuelve verificables los scorers de tools, que hoy miden anuncio.
- Los spans `agent.run`, `llm.generate`, `tool.execute` y `mcp.resolve` dejan de ser declaraciones muertas.
- Prohibir mutaciones en el loop mantiene intactos ADR-003, BR-007 y BR-009 sin bloquear la lectura.

## Consecuencias negativas

- Los appointments siguen sin ser alcanzables conversacionalmente; se resuelve el hueco de lectura, no el de mutación.
- Con catálogos institucionales el loop queda inerte hasta que el contrato de configuración gane la declaración de superficie de turno.
- Un turno con loop no cabe en el presupuesto `agent.run` de 800 ms de `src/ia_mcp/performance/models.py:17`, donde `llm.generate` ya vale 500 ms y `tool.execute` 200 ms. El presupuesto debe renegociarse o partirse.
- El loop multiplica las llamadas al modelo y el costo por turno hasta cinco veces en el peor caso.
- Sin sink durable, las ejecuciones del loop no aparecen en la vista de investigación.

## Alternativas descartadas

- **Extender `AnswerKind` con `"tool_call"`:** haría representable un estado inválido en `PolicyDecision` y `AgentTurnResult`, rompería la exhaustividad `Never` de `evals/runner.py:414` y `:427`, y obligaría a agregar a `EvalOutcome` un miembro que ningún caso podría esperar.
- **Reusar `AgentTurnResult.tool_names` para las tools ejecutadas:** `evals/scorers.py:110-114` marcaría `unexpected_tool` sobre datasets existentes que hoy sólo declaran tools anunciadas.
- **Orquestar el loop dentro de `Skill.route()`:** `SkillTurn` y `SkillResult` no transportan executor, run ni LLM; obligaría a duplicar el ciclo de run y los límites en cada skill.
- **Permitir que el modelo pida tools mutantes:** viola BR-007 y BR-009; además dejaría la idempotencia en un string elegido por el modelo.
- **Invocar el workflow engine desde el turno en esta fase:** sin política de `workflow_id`/`command_id` desde un mensaje entrante, la decisión sería inventada. Se difiere a un ADR propio.
- **Clasificar en Core la mutabilidad de tools descubiertas:** reintroduce el catálogo cerrado que ADR-005 eliminó.
- **Loop acotado sólo por deadline, sin tope de iteraciones:** un modelo en bucle rápido consume el presupuesto de tokens y de proveedor sin cota observable.
- **Agregar una capa de retry en el harness:** duplicaría la política ya presente en el transporte y arriesgaría reintentar operaciones no clasificadas como seguras (BR-010).
- **Límites por tenant en `feature_flags`:** el tipo es `Mapping[str, bool]`; codificar un entero como flags booleanas sería un contrato encubierto.

## Verificación

- Unit: una `ToolCallProposal` produce ejecución y una segunda `llm.generate`; una `LLMDecision` terminal produce exactamente una.
- Unit: el turno se corta en `max_tool_iterations` con `insufficient` y `error_code="tool_budget_exhausted"`, nunca con respuesta parcial.
- Unit: `mypy --strict` sigue verde en `src/ia_mcp/evals/runner.py` sin tocar los chequeos `Never`.
- Unit: una tool canónica cuyo dispatch exige idempotency key no es invocable desde el turno; una descubierta no declarada tampoco.
- Seguridad: tenant A no ejecuta una tool descubierta sólo en el MCP de tenant B; ningún `ToolResult` de un tenant aparece en el `LLMRequest` de otro; todo `ToolAuditEvent` del turno lleva el `tenant_id` del `TenantContext` del turno.
- Seguridad: `upstream_reference` y valores de credencial no aparecen en `LLMRequest.tool_results`, logs ni spans.
- Observabilidad: un turno con una tool ejecutada emite `agent.run`, dos `llm.generate`, un `tool.execute` y un `mcp.resolve`.
- Regresión: la suite FAQ existente y los datasets de eval pasan sin cambios de expectativa.

## Rollback/sustitución

`max_tool_iterations = 0` desactiva el loop y restituye exactamente el turno de una sola llamada: `LLMPort` sigue pudiendo devolver `LLMDecision`, `AnswerKind` nunca cambió y los campos nuevos son opcionales con default. No hay migración que revertir. La sustitución natural es un ADR posterior que abra el puente turno→workflow y convierta el cuarto término de la intersección en dato declarado por el tenant.
