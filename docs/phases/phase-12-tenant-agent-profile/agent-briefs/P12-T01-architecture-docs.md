# P12-T01 — ADR-008 y documentación de fase

**Estado:** accepted · **Wave:** W11 · **Depends on:** Fase 11 accepted en tablero; P10-T01 accepted

Documentar que el perfil de agente del tenant (tono + instrucciones opcionales) es configuración versionada y llega a cada `LLMRequest` del turno, sin reemplazar Core ni abrir un system prompt libre. Tarea sin código de producción.

Commit: `docs: define tenant agent profile and its path to the model`.

## Lectura obligatoria

1. `docs/README.md`
2. `docs/00-governance/delegation-protocol.md`
3. `docs/00-governance/requirements-catalog.md` (RF-002, RF-004, RF-007, CON-006, RNF-015, BR-002)
4. [ADR-002](../../../01-architecture/adr/ADR-002-tenant-context-and-isolation.md), [ADR-006](../../../01-architecture/adr/ADR-006-conversational-tool-loop.md), [ADR-007](../../../01-architecture/adr/ADR-007-admin-service-tokens-and-secret-resolution.md)
5. `docs/templates/ADR-template.md`
6. Fase 11 como molde: `docs/phases/phase-11-agent-loop/` (README, TDD, acceptance-criteria, implementation-plan, test-plan, briefs)
7. Código actual (citar archivo y línea en el ADR):
   - `src/ia_mcp/configuration/models.py` (`AgentConfig`)
   - `src/ia_mcp/agent_runtime/context_compiler.py` (`CORE_INSTRUCTIONS`, `_policies`, `compile`)
   - `src/ia_mcp/agent_runtime/models.py` (`LLMRequest`)
   - `src/ia_mcp/agent_runtime/harness.py` (construcción de `LLMRequest`)
   - `src/ia_mcp/agent_runtime/ports.py` (`FakeLLM`)
   - `src/ia_mcp/onboarding/models.py` (`PackageConfig.agent`)
   - `src/ia_mcp/onboarding/schemas/tenant-package.schema.json`
   - `src/ia_mcp/onboarding/service.py` (`_draft_from_package`)
   - `tenants/fixtures/tenant-b/config.yaml`

## Archivos exactos e interfaces

**Crear o completar:**

- `docs/01-architecture/adr/ADR-008-tenant-agent-profile.md`
- `docs/phases/phase-12-tenant-agent-profile/TDD.md`
- `docs/phases/phase-12-tenant-agent-profile/acceptance-criteria.md`
- `docs/phases/phase-12-tenant-agent-profile/implementation-plan.md`
- `docs/phases/phase-12-tenant-agent-profile/test-plan.md`
- `docs/phases/phase-12-tenant-agent-profile/agent-briefs/P12-T02-profile-contract.md`
- `docs/phases/phase-12-tenant-agent-profile/evidence/README.md`
- actualizar el README de fase y el README de briefs para listar T02 con su enlace

**Se puede ampliar, no reescribir el problema:**

- `docs/phases/phase-12-tenant-agent-profile/README.md`
- `docs/phases/phase-12-tenant-agent-profile/agent-briefs/P12-T01-architecture-docs.md` (solo si hace falta alinear IDs de criterios)

**No tocar:**

- `src/**`, `tests/**`, `scripts/**`, `.github/**`, `tenants/**`
- `docs/00-governance/delegation-board.md`
- `docs/01-architecture/adr/README.md` y `docs/00-governance/master-roadmap.md` (índice y roadmap los actualiza el coordinador)
- ADR-002, ADR-006, ADR-007: esta decisión no los enmienda
- `docs/00-governance/traceability-matrix.md` (el coordinador la actualiza al aceptar T01 si los AC citan RF existentes)

## Interfaces documentadas

El ADR fija estas firmas. T02 las implementa sin desviarse. Defaults aditivos: ningún constructor existente se rompe.

```python
class AgentConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tone: str
    instructions: str | None = None

# LLMRequest (campos nuevos con default)
tone: str = ""
tenant_instructions: str | None = None
```

Reglas que el ADR debe dejar normativas, no opcionales:

1. `tone` ya existe y es obligatorio. T02 lo copia a `LLMRequest.tone` en cada `generate` del turno (uno o varios si el loop de Fase 11 está presente).
2. `instructions` es texto de política del tenant, opcional, máximo 2000 caracteres. `None` y string vacío son equivalentes a “sin instrucciones”.
3. `CORE_INSTRUCTIONS` sigue siendo de Core y no se concatena con el texto del tenant. El modelo recibe Core en `LLMRequest.instructions` y el perfil en `tone` / `tenant_instructions`.
4. `CompiledContext.policies["agent"]` incluye `tone` y, si hay, `instructions`. Eso no sustituye copiarlos al `LLMRequest`: hoy el harness no envía `policies`.
5. Knowledge sigue siendo información recuperable, no personalidad. No se inventa un campo `persona`, `system_prompt`, saludo, voz, avatar ni vendor.
6. `FakeLLM` sigue válido sin leer los campos nuevos.
7. `TenantContext` en todo boundary. Cero ramas por slug. Fixtures y docs sin secretos (CON-006).
8. El package schema permite `agent.instructions` opcional. `AgentConfig` es el tipo de `PackageConfig.agent`; no hace falta un tipo paralelo.
9. Isolation: el `LLMRequest` de tenant B no contiene `tone` ni `instructions` de A.

`AnswerKind` no cambia. No se invoca el workflow engine. No se elige proveedor LLM.

## Verificación

Ejecutar y adjuntar salida real:

```text
python scripts/check_docs.py --all docs
python scripts/check_traceability.py
pytest tests/docs -q
ruff check scripts tests/docs
```

Cada afirmación de estado actual del ADR cita archivo y línea verificables en el commit base de esta rama. El brief de T02 debe tener las secciones exigidas por `check_docs.py --briefs`: Lectura obligatoria, Archivos, Interfaces/TDD, Verificación, Commit.

T01 cubre AC-P12-001. T01 define AC-P12-001–AC-P12-008. T02 cubre AC-P12-002–AC-P12-008.

## Exclusiones

- No inventar API, credenciales, autenticación, vendors, requisitos legales ni campos institucionales.
- No prometer retrieval real, WhatsApp real ni mutaciones desde el turno.
- No editar el tablero ni estados de tareas ajenas.
- No resolver EXT. Marcar dependencias abiertas.
