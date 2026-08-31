# TDD — Páginas HTML de laboratorio

**ID:** TDD-P13-001  
**Estado:** ready  
**ADRs:** ADR-002, ADR-006, ADR-007, ADR-008, ADR-009  
**Requisitos:** RF-002, RF-037, RNF-001, BR-002, CON-006

## Problema

No existe UI de instituciones. `provision` deja el tenant sin config activa. El chat de prueba no puede usar `capture()` ni el harness con `TenantContext` de la institución elegida.

## Contratos

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

`write_lab_package` escribe el árbol exigido por `validate_package` bajo `{root}/{slug}/`. Genera canal `simulated` / `{slug}-simulated` / `sm://{slug}/channel/simulated`. `knowledge.namespace == slug`. Un `policies/{skill}.yaml` por skill habilitada. `evals.jsonl` vacío. `instructions=""` se omite. `enabled_tools` ⊆ `KNOWN_TOOLS` y ⊆ `mcp_capabilities`. `mcp_credentials_reference` es URI, no un secreto.

`lab_enable` es idempotente, audit `lab_enable`, solo si el proceso no es production. Setea config activa, `tenant.status=active`, canal `simulated` y bindings MCP de ese `tenant_id`.

El chat no usa `/v1/simulated/messages`. Resuelve `channel_integration_id` en el request desde SQL. `InboundMessage.channel = "simulated"`. Historial: campo `history` del POST (pares user/bot, máx. 20), sin secretos.

Rutas HTML y `lab_enable` no se montan en production. Auth: `get_principal` (ADR-007). Alta/lista/`lab_enable`: `platform_admin`. Chat: `admin_context_for` del slug.

## Verificación

```text
pytest tests/unit/onboarding/test_lab_package.py tests/unit/onboarding/test_lab_enable.py tests/unit/api/test_instituciones_html.py tests/security/test_instituciones_isolation.py -v
ruff check src/ia_mcp/api src/ia_mcp/onboarding tests/unit/api/test_instituciones_html.py tests/unit/onboarding/test_lab_package.py tests/unit/onboarding/test_lab_enable.py tests/security/test_instituciones_isolation.py
mypy src/ia_mcp/api src/ia_mcp/onboarding
```
