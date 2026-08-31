# P13-T01 — Páginas HTML de instituciones y chat de prueba

**Estado:** accepted · **Wave:** W12 · **Depends on:** Fase 12 accepted

Implementar las páginas HTML de laboratorio: alta/edición/lista de instituciones y chat tipo WhatsApp que llama al harness. Una sola tarea.

Commit: `feat: add lab HTML pages for institutions and try-chat`.

## Lectura obligatoria

1. `docs/README.md`
2. `docs/00-governance/delegation-protocol.md`
3. [ADR-002](../../../01-architecture/adr/ADR-002-tenant-context-and-isolation.md)
4. [ADR-007](../../../01-architecture/adr/ADR-007-admin-service-tokens-and-secret-resolution.md)
5. [ADR-009](../../../01-architecture/adr/ADR-009-operator-html-lab.md)
6. [../TDD.md](../TDD.md)
7. [../acceptance-criteria.md](../acceptance-criteria.md)
8. [../test-plan.md](../test-plan.md)
9. [../implementation-plan.md](../implementation-plan.md)
10. `docs/superpowers/specs/2026-08-31-operator-html-pages-design.md`
11. Código: `src/ia_mcp/api/app.py`, `src/ia_mcp/api/routes/admin_runs.py`, `src/ia_mcp/api/auth/admin.py`, `src/ia_mcp/onboarding/api.py`, `src/ia_mcp/onboarding/service.py`, `src/ia_mcp/onboarding/validator.py`, `src/ia_mcp/onboarding/models.py`, `src/ia_mcp/configuration/service.py`, `src/ia_mcp/agent_runtime/harness.py`, `src/ia_mcp/mcp/registry.py`, `tenants/fixtures/tenant-b/`

## Archivos exactos

**Crear:**

- `src/ia_mcp/onboarding/lab_package.py` — `InstitucionForm`, `write_lab_package`
- `src/ia_mcp/api/templates/instituciones.html`
- `src/ia_mcp/api/templates/institucion_chat.html`
- `src/ia_mcp/api/routes/instituciones.py` — HTML, `GET /v1/admin/tenants`, POST alta/chat
- `tests/unit/onboarding/test_lab_package.py`
- `tests/unit/onboarding/test_lab_enable.py`
- `tests/unit/api/test_instituciones_html.py`
- `tests/security/test_instituciones_isolation.py`
- `docs/phases/phase-13-operator-html-lab/evidence/P13-T01.md`

**Modificar:**

- `src/ia_mcp/onboarding/service.py` — `lab_enable`, `list_tenants` (o store equivalente)
- `src/ia_mcp/api/app.py` — montar el router sólo si el environment es `development` o `test`
- `src/ia_mcp/api/composition.py` — si hace falta exponer engine/packages dir al router; no reescribir el composition root

**No tocar:**

- `src/ia_mcp/agent_runtime/ports.py` (`FakeLLM`)
- `src/ia_mcp/agent_runtime/harness.py` (el chat lo consume; no cambia el loop)
- `src/ia_mcp/onboarding/preflight.py`, activate productivo
- `src/ia_mcp/api/routes/simulated.py`
- `alembic/`, `semconv.py`, `docs/00-governance/delegation-board.md`
- WhatsApp real, vendor LLM, campos institucionales nuevos

## Interfaces

```python
class InstitucionForm(BaseModel):
    model_config = ConfigDict(extra="forbid")
    slug: str
    display_name: str
    tone: str
    instructions: str | None = Field(default=None, max_length=2000)
    enabled_skills: frozenset[SkillName] = Field(default_factory=frozenset)
    enabled_tools: frozenset[str] = Field(default_factory=frozenset)
    mcp_server_id: str
    mcp_capabilities: frozenset[str] = Field(default_factory=frozenset)
    mcp_credentials_reference: str
    knowledge_text: str | None = None

def write_lab_package(root: Path, form: InstitucionForm) -> Path: ...

async def lab_enable(self, admin: TenantAdminContext) -> ProvisionedTenant: ...

async def list_tenants(self, principal: Principal) -> tuple[TenantListItem, ...]: ...
```

`write_lab_package` debe pasar `validate_package`. `lab_enable` es idempotente. El chat usa `ConfigurationService.capture` + `AgentHarness.handle_message` con `TenantContext` del slug. `channel_integration_id` se lee en el request desde SQL, no del mapa de startup.

## Secuencia TDD

1. Rojo: `write_lab_package` / `lab_enable` / `/admin/instituciones` no existen.
2. Verde: package válido; provision + lab_enable; HTML lista y chat.
3. Verde: aislamiento A/B, 401, production sin rutas.
4. Suite y estáticos del test-plan.
5. Evidencia en `evidence/P13-T01.md`.

## Verificación

```text
pytest tests/unit/onboarding/test_lab_package.py tests/unit/onboarding/test_lab_enable.py tests/unit/api/test_instituciones_html.py tests/security/test_instituciones_isolation.py -v
ruff check src/ia_mcp/api src/ia_mcp/onboarding tests/unit/api/test_instituciones_html.py tests/unit/onboarding/test_lab_package.py tests/unit/onboarding/test_lab_enable.py tests/security/test_instituciones_isolation.py
mypy src/ia_mcp/api src/ia_mcp/onboarding
```

Criterios AC-P13-002 a AC-P13-008.

## Exclusiones

- No modificar `FakeLLM` ni elegir vendor.
- No desbloquear preflight productivo ni P05.
- No agregar columnas ni migraciones.
- No pasar secretos al HTML ni al LLM.
- No editar el tablero.
