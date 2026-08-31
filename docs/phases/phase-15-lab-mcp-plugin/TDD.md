# TDD — Plugin MCP de laboratorio

**ID:** TDD-P15-001  
**Estado:** ready  
**ADRs:** ADR-002, ADR-005, ADR-006 (amended), ADR-007, ADR-009 (amended), ADR-011  
**Requisitos:** RF-002, RF-004, RF-024–RF-027, RF-037, RNF-001, CON-006

## Objetivo

El laboratorio trata cada institución como un bot. El operador declara perfil (`tone`, `instructions`) y enchufa un MCP por URL SSE. El Core descubre el catálogo y el chat simulado (`simulated`, aspecto WhatsApp) puede invocar las tools descubiertas.

## Contratos

### Persistencia del endpoint (no es campo de package)

`integrations.yaml` sigue sin `endpoint` (`additionalProperties: false`). El mapa vive en:

`{IA_MCP_TENANT_PACKAGES_DIR}/lab_mcp_endpoints.json`

```json
{"soloturnos": "http://192.168.1.247:8001/sse"}
```

Clave = `mcp_server_id`. Valor = URL `http`/`https` sin userinfo. Nunca un secreto.

```python
def validate_lab_mcp_endpoint(value: str) -> str: ...
def allowlist_entry_for(endpoint: str) -> str: ...
def load_lab_mcp_endpoints(root: Path) -> dict[str, str]: ...
def write_lab_mcp_endpoint(root: Path, server_id: str, endpoint: str) -> Path: ...

class LabMcpDiscoverer(Protocol):
    async def list_names(self, endpoint: str) -> tuple[str, ...]: ...
```

`allowlist_entry_for`: `https` → hostname; `http` → `http://hostname` (ADR-005).

### InstitucionForm

Campo nuevo opcional `mcp_endpoint: str | None`. `enabled_tools` admite nombres descubiertos fuera de `KNOWN_TOOLS` (no vacíos). Sigue valiendo `enabled_tools ⊆ mcp_capabilities` y `appointments.*` exige skill `appointments`.

Si `mcp_endpoint` viene informado: validar URL, `write_lab_mcp_endpoint`, `tools/list` (`intersect_allowed=False`). Los nombres descubiertos se unen a `enabled_tools` y `mcp_capabilities`. Skill `faq` siempre; `appointments` si algún nombre empieza con `appointments.`. Si `tools/list` falla, se guarda el package igual y el HTML muestra un mensaje seguro, sin el body upstream.

`mcp_server_id` vacío se sustituye por el `slug`. `mcp_credentials_reference` `sm://slug/mcp/appointments` se sustituye por `sm://{slug}/mcp/appointments`.

### Chat

`/admin/instituciones/{slug}/chat` se presenta como simulación de WhatsApp. Sigue siendo canal `simulated`. Tras un POST de alta HTML exitoso, redirigir a ese chat (`303`).

### Runtime (T03)

- `FAQSkill.allowed_tools` = `config.enabled_tools` (amenda AC-P14-006 en lab).
- `invocable_on_turn(name, declared_for_turn=frozenset(tool_names))`: si `name` está en `declared_for_turn`, es invocable. Sin anuncio, se mantiene la regla canónica de lectura.
- `ContextCompiler`: `server = _server_catalog | config.enabled_tools` cuando `mirror_tenant_tools=True` (solo `build_runtime`).
- `build_runtime` fusiona `load_lab_mcp_endpoints(packages_dir)` con `IA_MCP_MCP_ENDPOINTS` (env gana).
- `ToolExecutor._dispatch`: si `target.endpoint` está allowlisted, **todas** las tools van al transporte SSE, también `appointments.*`. Sin endpoint, el fake canónico no cambia.
- Host vacío o no allowlisted con endpoint presente: `forbidden` (no caer al fake).
- Sin hits de knowledge y con `enabled_tools`: no cortar el turno. `answer` con texto tras una tool `ok` se acepta aunque no cite documentos.
- `SseMcpClient.list_tools(..., intersect_allowed=True)` por defecto. `False` no filtra por `target.allowed_tools`.
- Cero auth inventada hacia el MCP.

## No objetivos

WhatsApp Cloud, auth MCP inventada, API médica, embeddings, secretos en HTML, ramas por slug, workflows productivos desde el turno fuera de development/test.
