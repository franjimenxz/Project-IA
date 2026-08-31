# P15-T02 — Form de laboratorio, endpoint MCP y chat simulado

**Estado:** ready · **Wave:** W14 · **Depends on:** P15-T01 accepted

Crear el mapa de endpoints de lab, el campo `mcp_endpoint` y presentar el chat como simulación de WhatsApp. Discovery al guardar con un puerto inyectable. Sin tocar el loop ni el executor.

Commit: `feat: plug lab MCP endpoint from institution form (P15-T02)`

## Lectura obligatoria

1. `docs/README.md`
2. `docs/00-governance/delegation-protocol.md`
3. [ADR-011](../../../01-architecture/adr/ADR-011-lab-mcp-plugin.md)
4. [../TDD.md](../TDD.md)
5. [../acceptance-criteria.md](../acceptance-criteria.md) (AC-P15-001 a AC-P15-005)
6. [../test-plan.md](../test-plan.md)
7. Código: `src/ia_mcp/onboarding/lab_package.py`, `src/ia_mcp/api/routes/instituciones.py`, `src/ia_mcp/api/templates/instituciones.html`, `src/ia_mcp/api/templates/institucion_chat.html`, `src/ia_mcp/mcp/client.py` (`list_tools` existente; no cambiar firma salvo que T03 ya esté merged — no lo asumas)

## Archivos permitidos

**Crear:**

- `src/ia_mcp/onboarding/lab_mcp.py`
- `tests/unit/onboarding/test_lab_mcp.py`

**Modificar:**

- `src/ia_mcp/onboarding/lab_package.py`
- `src/ia_mcp/api/routes/instituciones.py`
- `src/ia_mcp/api/templates/instituciones.html`
- `src/ia_mcp/api/templates/institucion_chat.html`
- `tests/unit/onboarding/test_lab_package.py`
- `tests/unit/api/test_instituciones_html.py`
- `tests/security/test_instituciones_isolation.py` solo si el HTML nuevo lo exige (token ausente, A/B)

**No tocar:**

- `src/ia_mcp/agent_runtime/`
- `src/ia_mcp/mcp/executor.py`
- `src/ia_mcp/mcp/client.py`
- `src/ia_mcp/skills/faq.py`
- `src/ia_mcp/api/composition.py`
- `docs/00-governance/delegation-board.md`
- secretos, WhatsApp Cloud, P05

## Interfaces

```python
LAB_ENDPOINTS_FILE = "lab_mcp_endpoints.json"

class LabMcpDiscoverer(Protocol):
    async def list_names(self, endpoint: str) -> tuple[str, ...]: ...

def validate_lab_mcp_endpoint(value: str) -> str: ...
def allowlist_entry_for(endpoint: str) -> str: ...
def load_lab_mcp_endpoints(root: Path) -> dict[str, str]: ...
def write_lab_mcp_endpoint(root: Path, server_id: str, endpoint: str) -> Path: ...

class SseLabMcpDiscoverer:
    async def list_names(self, endpoint: str) -> tuple[str, ...]: ...
```

`SseLabMcpDiscoverer` puede devolver `()` si el cliente actual filtra por `allowed_tools` vacío (T03 agrega `intersect_allowed=False`). El POST de alta **debe** usar `getattr(request.app.state, "lab_mcp_discoverer", None)` y, si no hay discoverer, no inventar red en tests.

`InstitucionForm.mcp_endpoint: str | None`. Validar con `validate_lab_mcp_endpoint` o omitir si blank. Quitar el reject de nombres fuera de `KNOWN_TOOLS`; mantener ⊆ capabilities y prefix `appointments.` → skill `appointments`.

Alta HTML: si hay endpoint, escribir mapa, intentar discovery, unir nombres, `faq` siempre, `appointments` si hay `appointments.*`. Redirect `303` a `/admin/instituciones/{slug}/chat`. Chat: copy de “Simular WhatsApp” / canal simulado. Token nunca en HTML.

Campo visible `mcp_endpoint` en el form. Skills/tools pueden quedar en un `<details>` avanzado. No agregar `cuit`, `api_key` ni URL de WhatsApp.

## TDD

1. Rojo: `lab_mcp` y `mcp_endpoint` no existen; tools `crear_turno` las rechaza el form.
2. Verde: URL válida, JSON en root, form acepta `crear_turno` ⊆ capabilities, POST con discoverer stub, 303, chat menciona WhatsApp, token ausente.
3. Isolation: token y secretos no se pinta.

## Verificación

```text
pytest tests/unit/onboarding/test_lab_mcp.py tests/unit/onboarding/test_lab_package.py tests/unit/api/test_instituciones_html.py tests/security/test_instituciones_isolation.py -v
ruff check src/ia_mcp/onboarding/lab_mcp.py src/ia_mcp/onboarding/lab_package.py src/ia_mcp/api/routes/instituciones.py tests/unit/onboarding/test_lab_mcp.py tests/unit/onboarding/test_lab_package.py tests/unit/api/test_instituciones_html.py
```

Criterios: AC-P15-001 a AC-P15-005.

## Exclusiones

- No cablear composition ni el harness.
- No inventar `Authorization` hacia el MCP.
- No editar el tablero.
