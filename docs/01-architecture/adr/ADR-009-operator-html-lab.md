# ADR-009 — Páginas HTML de laboratorio para instituciones

**Estado:** accepted  
**Fecha:** 2026-08-31  
**Supersedes:** ninguno  
**Amends:** ninguno

## Contexto

El equipo necesita crear, listar y configurar instituciones y probar el bot desde el navegador. Hoy eso no existe: el alta es un paquete YAML + CLI/HTTP, no hay `GET` de lista, y el único HTML es `/admin/runs/{run_id}`. El canal `simulated` es un POST firmado para tests, no una pantalla. WhatsApp real está en `EXT-004`. `provision` deja el tenant `disabled` sin `active_config_version`, así que `ConfigurationService.capture` falla. El activate productivo exige preflight, que sigue fail-closed.

El spec aprobado es `docs/superpowers/specs/2026-08-31-operator-html-pages-design.md`.

ADR-002, ADR-006, ADR-007 y ADR-008 siguen vigentes.

## Decisión

En `development` y `test` se montan páginas HTML simples (sin React) para alta, edición, lista y un chat con aspecto de WhatsApp. El chat llama a `AgentHarness.handle_message` con el `TenantContext` de la institución elegida. No es WhatsApp Business.

`lab_enable` es una mutación idempotente de laboratorio: publica/activa la última config, pone `tenant.status=active` y habilita el canal `simulated` y los bindings MCP de ese tenant. No corre preflight, no afirma EXT y no se monta en producción.

El alta escribe un package bajo `IA_MCP_TENANT_PACKAGES_DIR/{slug}/` con el contrato actual (sin campos institucionales nuevos) y reutiliza `provision` + `publish`. `display_name` vive en `tenant.yaml`, no en una columna SQL.

Auth: el mismo token de ADR-007. El HTML no inventa cookies ni tokens en query.

## Consecuencias positivas

- El equipo puede recorrer alta → config → lista → chat sin CLI.
- El Core no ramifica por slug.
- El activate productivo no se debilita.

## Consecuencias negativas

- El chat de laboratorio no usa el envelope firmado de `/v1/simulated/messages`.
- `lab_enable` es un segundo camino a `status=active` (acotado a no-producción).
- El bot sigue débil (`FakeLLM`, knowledge vacío, FAQ sin tools) hasta una fase posterior.

## Alternativas descartadas

- Pegar el HTML a `/v1/simulated/messages`: obliga a firmar en el browser.
- Usar el activate de preflight: sigue fail-closed y no desbloquea la prueba.
- SPA / React / producto “consola”: fuera del pedido (HTML simple).
- Columna `display_name` en `tenant`: migración innecesaria; el package ya lo tiene.

## Verificación

- Las rutas no existen cuando `IA_MCP_ENVIRONMENT=production`.
- Chat de A no observa datos de B.
- `lab_enable` dos veces no duplica canales.
- El token admin no aparece en el HTML renderizado.
- `validate_package` del package escrito por el form es válido.

## Rollback/sustitución

Dejar de montar el router en no-producción. `lab_enable` no se llama. El activate productivo no cambia.
