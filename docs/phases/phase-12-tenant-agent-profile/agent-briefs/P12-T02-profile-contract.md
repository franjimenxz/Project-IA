# P12-T02 — Contrato y cableado del perfil

**Estado:** accepted · **Wave:** W11 · **Depends on:** P12-T01 aceptada

Hacer que `tone` e `instructions` opcionales del tenant lleguen a cada `LLMRequest` del turno, sin concatenarlos con Core ni inventar un system prompt. Una sola tarea de implementación.

Commit: `feat: copy tenant agent profile to every LLM request`.

## Lectura obligatoria

1. `docs/README.md`
2. `docs/00-governance/delegation-protocol.md`
3. [ADR-008](../../../01-architecture/adr/ADR-008-tenant-agent-profile.md)
4. [../TDD.md](../TDD.md)
5. [../acceptance-criteria.md](../acceptance-criteria.md)
6. [../test-plan.md](../test-plan.md)
7. Código actual: `src/ia_mcp/configuration/models.py`, `src/ia_mcp/agent_runtime/models.py`, `src/ia_mcp/agent_runtime/context_compiler.py`, `src/ia_mcp/agent_runtime/harness.py`, `src/ia_mcp/agent_runtime/ports.py`, `src/ia_mcp/onboarding/models.py`, `src/ia_mcp/onboarding/schemas/tenant-package.schema.json`, `src/ia_mcp/onboarding/service.py`, `tenants/fixtures/tenant-b/config.yaml`

## Archivos exactos

**Modificar:**

- `src/ia_mcp/configuration/models.py` — `AgentConfig.instructions: str | None = Field(default=None, max_length=2000)`
- `src/ia_mcp/agent_runtime/models.py` — `LLMRequest.tone: str = ""` y `tenant_instructions: str | None = None`
- `src/ia_mcp/agent_runtime/context_compiler.py` — `_policies` incluye `instructions` en `policies["agent"]` sólo si hay texto
- `src/ia_mcp/agent_runtime/harness.py` — cada construcción de `LLMRequest` copia `tone` y `tenant_instructions`; `instructions` sigue siendo `compiled.core_instructions`
- `src/ia_mcp/onboarding/schemas/tenant-package.schema.json` — `agent.instructions` opcional, `maxLength` 2000
- `tenants/fixtures/tenant-b/config.yaml` — agregar instrucciones de política, sin secretos:
  `instructions: "No invente horarios ni especialidades que no figuren en el conocimiento recuperado."`
- `tests/unit/agent/test_context_compiler.py` — ampliar
- `tests/unit/agent/test_harness.py` — ampliar (reutilizar el `FakeLLM` que ya acumula `requests`)
- `tests/unit/onboarding/test_validator.py` — ampliar (package con y sin `instructions`; fixture tenant B)

**Crear:**

- `tests/unit/configuration/test_agent_config.py`
- `tests/unit/agent/test_models.py`
- `tests/security/test_agent_profile_isolation.py`

**No tocar:**

- `src/ia_mcp/agent_runtime/ports.py` (`FakeLLM` ya es válido sin leer los campos nuevos)
- `src/ia_mcp/onboarding/models.py` (`PackageConfig.agent` ya es `AgentConfig`)
- `src/ia_mcp/onboarding/service.py` (`_draft_from_package` ya copia el objeto `agent`)
- `src/ia_mcp/agent_runtime/context_models.py` (el perfil viaja en `policies["agent"]`)
- `AnswerKind`, skills, workflows, scheduling, evals, composition root
- `docs/00-governance/delegation-board.md`
- `docs/01-architecture/adr/README.md`, `docs/00-governance/master-roadmap.md`

## Interfaces

Produce: `AgentConfig(tone: str, instructions: str | None = None)` y `LLMRequest(..., tone: str = "", tenant_instructions: str | None = None)`.

Consume: `CORE_INSTRUCTIONS`, `compile(tenant: TenantContext, request: ContextRequest)` y `generate(self, request: LLMRequest)`.

```python
class AgentConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tone: str
    instructions: str | None = Field(default=None, max_length=2000)

# LLMRequest (aditivo)
tone: str = ""
tenant_instructions: str | None = None
```

`AnswerKind` no gana miembros. `LLMRequest.instructions` sigue siendo Core. `None` y `""` en `AgentConfig.instructions` se copian como `tenant_instructions=None` y no aparecen en `policies["agent"]`.

Si el harness de esta rama tiene un solo `generate` (`harness.py:139`), se cablea ese constructor. Si el loop de Fase 11 ya está presente, cada `generate` del turno lleva el mismo perfil. No se implementa el loop en esta tarea.

## Secuencia TDD

1. Rojo (criterio: falla por contrato ausente): `AgentConfig(tone="formal", instructions="x" * 2001)` no se rechaza; `LLMRequest` no acepta `tone` ni `tenant_instructions`.
2. Rojo: `compile` no pone `instructions` en `policies["agent"]`; el harness no copia `tone` al request.
3. Rojo: el `LLMRequest` de tenant B puede contener el canario de A.
4. Verde: implementación mínima de `AgentConfig.instructions`, campos aditivos en `LLMRequest`, `_policies` y el constructor del harness.
5. Verde: schema y fixture de tenant B; `validate_package` de la fixture sigue en verde.
6. Verde: aislamiento A/B y casos `None` / `""` / extra forbid.
7. Suite: `pytest tests/unit/configuration/test_agent_config.py tests/unit/agent/test_models.py tests/unit/agent/test_context_compiler.py tests/unit/agent/test_harness.py tests/unit/onboarding/test_validator.py tests/security/test_agent_profile_isolation.py -v`
8. Estáticos: `ruff check src tests && mypy src/ia_mcp/configuration src/ia_mcp/agent_runtime src/ia_mcp/onboarding`

## Verificación

```text
pytest tests/unit/configuration/test_agent_config.py tests/unit/agent/test_models.py tests/unit/agent/test_context_compiler.py tests/unit/agent/test_harness.py tests/unit/onboarding/test_validator.py tests/security/test_agent_profile_isolation.py -v
pytest tests/unit/agent/test_harness.py tests/integration/mvp/test_faq_turn.py -v
ruff check src tests
mypy src/ia_mcp/configuration src/ia_mcp/agent_runtime src/ia_mcp/onboarding
```

Criterios AC-P12-002, AC-P12-003, AC-P12-004, AC-P12-005, AC-P12-006, AC-P12-007, AC-P12-008.

## Exclusiones

- No concatenar `CORE_INSTRUCTIONS` con el texto del tenant.
- No inventar `persona`, `system_prompt`, saludo, voz, avatar, vendor ni modelo por tenant.
- No cambiar `AnswerKind` ni invocar el workflow engine.
- No elegir proveedor LLM ni modificar `FakeLLM`.
- No agregar ramas por slug o nombre de institución.
- No pasar secretos a fixtures, logs, traces ni al request.
- No editar el tablero ni ADRs.
