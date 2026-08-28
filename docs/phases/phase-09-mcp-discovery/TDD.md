# TDD — MCP discovery e invocación genérica

**ID:** TDD-P09-001  
**Estado:** ready  
**Requisitos:** RF-015, RF-016, RF-038, RNF-001, RNF-010, RNF-012  
**ADRs:** ADR-002, ADR-003 (amended), ADR-005

## Problema

El registry actual intersecta server/tenant/skill y luego filtra con `KNOWN_TOOLS`, rechazando nombres válidos de MCPs institucionales. El Core debe descubrir y usar tools reales sin catálogo cerrado.

## Modelos

```python
@dataclass(frozen=True, slots=True)
class DiscoveredTool:
    name: str
    description: str | None
    input_schema: Mapping[str, Any]

@dataclass(frozen=True, slots=True)
class DiscoveredToolCatalog:
    server_id: str
    tools: tuple[DiscoveredTool, ...]

@dataclass(frozen=True, slots=True)
class McpTarget:
    server_id: str
    endpoint: str
    auth_reference: str
    allowed_tools: frozenset[str]  # allowlist de tenant en config al resolver; no es el catálogo descubierto
```

`DiscoveredToolCatalog` proviene de `tools/list` y alimenta el argumento `server=` de `available()`. La política de red/host+scheme se aplica vía `HostAllowlist` inyectada en executor/cliente (fail-closed; `http` solo si el par está allowlisted), no como campo de `McpTarget`.

## Puertos

```python
class McpDiscoveryClient(Protocol):
    async def list_tools(
        self,
        tenant: TenantContext,
        target: McpTarget,
    ) -> DiscoveredToolCatalog: ...

class McpTransportClient(Protocol):
    async def call_tool(
        self,
        tenant: TenantContext,
        target: McpTarget,
        name: str,
        arguments: Mapping[str, Any],
    ) -> ToolResult: ...
```

Todo método público recibe `TenantContext`. Secret values nunca se pasan al LLM ni se loguean.

## Registry (post-discovery)

```python
def available(
    discovered: Iterable[str],
    tenant: Iterable[str],
    skill: Iterable[str],
) -> frozenset[str]:
    return frozenset(discovered) & frozenset(tenant) & frozenset(skill)
```

`KNOWN_TOOLS` permanece como alias set canónico para workflows/fakes/dispatch `appointments.*`; no participa del filtro de autorización salvo dispatch especializado en executor.

## Transporte SSE (FastMCP)

- Conectar a `{endpoint}/sse` para obtener `session_id`.
- Enviar mensajes JSON-RPC a `{endpoint}/messages/?session_id={session_id}`.
- Métodos MCP: `tools/list`, `tools/call`.
- Timeout, size limit y audit en cada llamada.

CI usa fake in-process que implementa el mismo protocolo sin red externa. E2E opcional solo si `MCP_SSE_URL` está definida (skip otherwise).

## Executor

```text
authorize(tool, discovered, tenant, skill)
→ if tool matches appointments.* canonical AND capability wired:
      dispatch AppointmentCapability / workflow path (unchanged)
  else:
      McpTransportClient.call_tool(...)
```

Resolver + host allowlist se aplican antes de discovery/invoke.

## Context compiler

El compiler intersecta allowlists usando nombres del catálogo descubierto como argumento `server=` de `available()`:

```python
authorized = sorted(
    available(
        server=discovered_names,  # tools/list o catálogo inyectado en tests
        tenant=tenant_allowlist,
        skill=skill.allowed_tools(config),
    )
)
return CompiledContext(
    ...,
    tool_schemas=tuple(ToolSchema(name=name) for name in authorized),
)
```

No usar `KNOWN_TOOLS` como `server=`; ese set es alias canónico para workflows/fakes/dispatch.

## Validators (onboarding/evals)

- No fallar un nombre solo por estar fuera de `KNOWN_TOOLS`.
- Seguir fallando: overlap allowed∩forbidden; eval allowlist vacía si la regla fail-closed ya existe.
- Validar referencias de integración y host allowlist.

## Skills

- `appointments`: `allowed_tools` desde config/discovery intersectado; no clamp a `KNOWN_TOOLS`.
- `faq`, `human_handoff`: sin tools salvo que config lo habilite explícitamente.

## Errores

| Condición | Código |
|---|---|
| Tool no en intersección | `forbidden` |
| Host/scheme no allowlisted | `forbidden` |
| Discovery timeout/unavailable | `upstream_timeout` / `upstream_unavailable` |
| Respuesta MCP inválida | `contract_violation` |

## No objetivos

- Reescribir workflows de Fases 6–8.
- Inventar API REST médica.
- Secret values en docs/fixtures.
- Condiciones por slug de tenant en Core.
