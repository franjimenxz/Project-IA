# Plan de prueba — Fase 15

**Estado:** ready

## Unitaria

- `tests/unit/onboarding/test_lab_mcp.py` — URL, mapa JSON, rechazo de userinfo y link-local.
- `tests/unit/onboarding/test_lab_package.py` — tools no canónicas ⊆ capabilities.
- `tests/unit/api/test_instituciones_html.py` — `mcp_endpoint`, 303 al chat, texto WhatsApp simulado, token ausente.
- `tests/unit/skills/test_faq.py` — `allowed_tools` = `enabled_tools`.
- `tests/unit/agent/test_turn_tool_surface.py` — `declared_for_turn` habilita create / `crear_turno`.
- `tests/unit/mcp/test_executor.py` — transporte cuando hay endpoint allowlisted.
- `tests/unit/api/test_composition.py` — merge de `lab_mcp_endpoints.json` con env.

## Seguridad

- `tests/security/test_instituciones_isolation.py` — A no ve el chat ni el mapa de B; token no se pinta.
- Isolation de tools: tenant A no ejecuta el catálogo de B.

## Fuera

Sin red al MCP de LAN en CI. El discoverer de test es un stub. Sin WhatsApp Cloud.
