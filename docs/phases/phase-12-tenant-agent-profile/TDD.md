# TDD — Perfil de agente por tenant

**ID:** TDD-P12-001  
**Estado:** ready  
**ADRs:** ADR-002, ADR-006, ADR-008  
**Requisitos:** RF-002, RF-004, RF-007, RNF-015, BR-002, CON-006

## Problema

`AgentConfig` declara `tone` (`src/ia_mcp/configuration/models.py:21-23`) y el compiler lo copia a `CompiledContext.policies["agent"]` (`src/ia_mcp/agent_runtime/context_compiler.py:49`). El harness construye `LLMRequest` con `instructions=compiled.core_instructions` (`src/ia_mcp/agent_runtime/harness.py:144`) y no envía `policies`. No existe `AgentConfig.instructions`. El perfil no llega al modelo. Ver estado verificado en ADR-008 §Contexto.

## Contrato de configuración

`AgentConfig` gana un campo opcional. `extra="forbid"` y `tone` obligatorio no cambian:

```python
class AgentConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tone: str
    instructions: str | None = Field(default=None, max_length=2000)
```

- `None` y `""` significan «sin instrucciones».
- No se agregan `persona`, `system_prompt`, saludo, voz, avatar ni vendor.
- `PackageConfig.agent` ya es `AgentConfig` (`src/ia_mcp/onboarding/models.py:75`). No hay tipo paralelo.
- `_draft_from_package` ya asigna `agent=package.config.agent` (`src/ia_mcp/onboarding/service.py:110`). No se agrega un mapping campo a campo.
- `schema_version` permanece en `1` (RNF-015).

## Contrato del request

`AnswerKind` no cambia (`src/ia_mcp/agent_runtime/models.py:5`). `LLMRequest` gana dos campos con default:

```python
# LLMRequest
tone: str = ""
tenant_instructions: str | None = None
```

`LLMRequest.instructions` sigue siendo Core. El perfil no se escribe en ese campo.

`FakeLLM.generate` (`src/ia_mcp/agent_runtime/ports.py:26-28`) sigue siendo válido: ignora el request.

## Compiler

`_policies` proyecta el perfil pertinente (RF-004) sin volcar `TenantConfig` completa:

```python
def _policies(skill: SkillName, config: TenantConfig) -> dict[str, object]:
    agent: dict[str, object] = {"tone": config.agent.tone}
    if config.agent.instructions:
        agent["instructions"] = config.agent.instructions
    policies: dict[str, object] = {"agent": agent}
    # ramas de skill existentes, sin cambio
    return policies
```

`compile` sigue asignando `core_instructions=CORE_INSTRUCTIONS` (`context_compiler.py:100`). El texto del tenant no se concatena a Core. `CompiledContext` no gana campos nuevos: el perfil viaja en `policies["agent"]`.

Knowledge sigue saliendo de `_evidence` (`context_compiler.py:44-45`). Es información, no personalidad.

## Harness

Cada construcción de `LLMRequest` en `handle_message` copia el perfil de la `TenantConfig` capturada para el `TenantContext` del turno (BR-002):

```python
LLMRequest(
    tenant_id=tenant.tenant_id,
    skill="faq",
    query=message.text,
    instructions=compiled.core_instructions,  # Core; no concatenar
    knowledge=compiled.knowledge,
    history=compiled.history,
    allowed_source_ids=allowed,
    tool_names=tool_names,
    tone=config.agent.tone,
    tenant_instructions=config.agent.instructions or None,
)
```

En esta rama hay un `generate` (`harness.py:139`). T02 cablea ese constructor. Si el loop de Fase 11 aterriza, cada `generate` del mismo turno usa el mismo `tone` y las mismas `tenant_instructions`. T02 no implementa el loop ni invoca el workflow engine.

## Package

`src/ia_mcp/onboarding/schemas/tenant-package.schema.json` admite `agent.instructions` opcional:

```json
"agent": {
  "type": "object",
  "additionalProperties": false,
  "required": ["tone"],
  "properties": {
    "tone": { "type": "string", "minLength": 1 },
    "instructions": { "type": ["string", "null"], "maxLength": 2000 }
  }
}
```

La fixture `tenants/fixtures/tenant-b/config.yaml` puede declarar instrucciones de política. CON-006: sin secretos en fixture, docs ni campos enviados al modelo.

## Aislamiento

- Todo boundary recibe `TenantContext`.
- El `LLMRequest` de tenant B no contiene `tone` ni `instructions` de A.
- Cero condiciones por slug o nombre de institución en compiler o harness.
- El perfil sale de la `config_version` del `TenantContext` del turno; no se relée una activación posterior a mitad del run.

## Consumidores del contrato

| Consumidor | Efecto |
|---|---|
| `src/ia_mcp/agent_runtime/ports.py:22-28` | Sin cambio; `FakeLLM` no lee el request |
| `src/ia_mcp/onboarding/models.py:75` | Sin tipo nuevo; hereda `instructions` de `AgentConfig` |
| `src/ia_mcp/onboarding/service.py:110` | Sin cambio; copia el objeto `agent` |
| `src/ia_mcp/skills/faq.py` | Sin cambio; la política sigue viendo `LLMDecision` |
| `src/ia_mcp/evals/runner.py` | Sin cambio de `AnswerKind`; `AgentConfig(tone=...)` sigue válido |
| Constructors de test `AgentConfig(tone=...)` | Sin cambio; `instructions` default `None` |

## No objetivos

- Inventar vendor LLM, `system_prompt`, persona, saludo, voz, avatar o modelo por tenant.
- Concatenar Core con texto del tenant.
- Cambiar `AnswerKind` o invocar el workflow engine.
- Retrieval real, WhatsApp real, API médica o consola `/demo`.
- Secret values en docs, fixtures, logs, traces o prompts.
