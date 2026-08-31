# Criterios de aceptación — Fase 15

| ID | Criterio |
|---|---|
| AC-P15-001 | ADR-011 accepted; el form admite `mcp_endpoint` y no admite `api_key` |
| AC-P15-002 | `validate_lab_mcp_endpoint` acepta `http://192.168.1.247:8001/sse` y rechaza userinfo, `file:` y host `169.254.169.254`. El valor no se escribe en el package YAML |
| AC-P15-003 | `write_lab_mcp_endpoint` deja `{root}/lab_mcp_endpoints.json` con `server_id` → URL. `load_lab_mcp_endpoints` relée ese mapa. El archivo no contiene secretos |
| AC-P15-004 | `InstitucionForm` acepta `enabled_tools={"crear_turno"}` si está en `mcp_capabilities`. Sigue rechazando tools que no estén en capabilities |
| AC-P15-005 | POST HTML de alta con `mcp_endpoint` y un `LabMcpDiscoverer` de test que devuelve `("crear_turno",)` escribe esas capabilities, el mapa de endpoints, y responde `303` a `/admin/instituciones/{slug}/chat`. El chat HTML menciona simulación de WhatsApp. El token admin no aparece en el HTML |
| AC-P15-006 | `FAQSkill.allowed_tools` con `enabled_tools={"appointments.search","appointments.create","crear_turno"}` devuelve esos tres nombres. Vacío sigue `frozenset()` |
| AC-P15-007 | Con `declared_for_turn` que incluye `appointments.create` o `crear_turno`, `invocable_on_turn` es verdadero. Sin anuncio, `appointments.create` sigue prohibido y `appointments.search` sigue permitido |
| AC-P15-008 | `ToolExecutor` con target cuyo `endpoint` está allowlisted despacha `appointments.search` y `crear_turno` al transporte, no al fake. Sin endpoint, `appointments.search` sigue en la capability. A no ve tools ni endpoint de B |

## Fuera de alcance

WhatsApp Cloud, auth MCP inventada, P05, embeddings, clave en git o HTML.
