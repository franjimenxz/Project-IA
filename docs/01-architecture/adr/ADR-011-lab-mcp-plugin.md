# ADR-011 — Plugin MCP de laboratorio y chat simulado

**Estado:** accepted  
**Fecha:** 2026-08-31  
**Supersedes:** ninguno  
**Amends:** [ADR-006](ADR-006-conversational-tool-loop.md), [ADR-009](ADR-009-operator-html-lab.md)

## Contexto

El operador necesita un bot por institución al que se le enchufa el MCP que esa sede ya opera (por ejemplo un SSE de LAN). El formulario de laboratorio exigía skills/tools canónicos a mano, el turno solo invocaba `appointments.search` / `get`, y `appointments.*` canónicos iban a `FakeAppointmentCapability` aunque hubiera un endpoint. El chat HTML ya simula el canal `simulated` con aspecto de WhatsApp; WhatsApp Cloud sigue en `EXT-004`.

ADR-005 (discovery + intersección + invoke genérico), ADR-003 (workflows para mutaciones productivas) y ADR-007 (secretos por referencia) siguen vigentes. Esta decisión no inventa el auth del MCP institucional ni un proveedor de WhatsApp.

## Decisión

1. **Enchufe de laboratorio.** En `development` y `test`, el form acepta `mcp_endpoint` (`http`/`https`, sin userinfo). La URL no entra al package (el schema no tiene `endpoint`): se persiste en `{IA_MCP_TENANT_PACKAGES_DIR}/lab_mcp_endpoints.json` keyed por `mcp_server_id` y se fusiona con `IA_MCP_MCP_ENDPOINTS`. El HTML no pinta secretos.

2. **Adaptarse al catálogo.** Al guardar, si hay endpoint, el proceso llama `tools/list` y copia los nombres descubiertos a `enabled_tools` y `mcp_capabilities`. Nombres fuera de `KNOWN_TOOLS` son válidos (ADR-005). `FAQSkill.allowed_tools` es el `enabled_tools` del tenant. El compilador de development une el catálogo de proceso con `config.enabled_tools`.

3. **Turno de laboratorio.** Si el nombre fue anunciado en `tool_names` (intersección ya hecha), es invocable en el chat, incluidas mutaciones canónicas y tools descubiertas. Si el target tiene endpoint allowlisted, el executor despacha **todas** esas tools por el transporte SSE (`tools/call`), no por el fake. Sin endpoint, `appointments.*` canónicos siguen en el fake y las mutaciones canónicas no anunciadas siguen prohibidas (ADR-006).

4. **FAQ sin knowledge.** Si el tenant tiene `enabled_tools`, el harness no corta el turno por knowledge vacío. Una respuesta `answer` posterior a una tool ok se acepta aunque no cite documentos.

5. **WhatsApp simulado.** `/admin/instituciones/{slug}/chat` es la simulación de mensajería (canal `simulated`). No es WhatsApp Business. No se agrega webhook, plantilla ni número.

6. **Auth del MCP.** El cliente no inventa un esquema. Si más adelante el operador exporta el secreto de `mcp_credentials_reference`, un adapter de P05 puede mandarlo. Hasta EXT-003, el SSE de lab se conecta sin header de auth.

## Consecuencias positivas

- El operador pega la URL del MCP de la sede y el bot anuncia esas tools.
- El chat de lab prueba esa institución sin firmar `/v1/simulated/messages`.
- Production no monta estas rutas; el package contract no gana campos institucionales.

## Consecuencias negativas

- Mutaciones en el chat de lab no pasan por workflow (acotado a no-producción).
- Un MCP que exige auth no inventada no va a responder hasta P05.
- `lab_mcp_endpoints.json` es dato de deploy de laboratorio, no de producción.

## Alternativas descartadas

- Campo URL dentro de `integrations.yaml`: rompe `additionalProperties: false`.
- WhatsApp Cloud / webhook: `EXT-004`.
- Inventar Bearer u otro header hacia el MCP de LAN: `EXT-003` / P05.
- Concatenar el catálogo MCP en las instrucciones del tenant.

## Verificación

- Form con `mcp_endpoint` acepta tools descubiertas no canónicas; el token no aparece en HTML.
- `lab_mcp_endpoints.json` mapea `server_id` → URL; allowlist deriva de esa URL (`http://host` para plaintext).
- Con endpoint, `appointments.search` y un nombre no canónico van al transporte, no al fake.
- Sin endpoint, mutaciones canónicas no anunciadas siguen `forbidden`.
- Chat HTML se presenta como simulación de WhatsApp; rutas ausentes en production.

## Rollback/sustitución

Dejar de leer `lab_mcp_endpoints.json` y revertir `FAQSkill.allowed_tools` / `invocable_on_turn` / `_dispatch`. El activate productivo y ADR-003 no cambian.
