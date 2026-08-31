# Diseño: páginas HTML de instituciones y chat de prueba

**Estado:** Listo para revisión  
**Fecha:** 2026-08-31  
**Secuencia:** primero estas páginas; el bot débil se mejora en una fase posterior.  
**Ambiente:** sólo `development` y `test` (`IA_MCP_ENVIRONMENT`). En producción estas rutas no se montan.

## 1. Propósito

Dar al equipo una **página web HTML simple** (mismo estilo que `/admin/runs/{run_id}`) para:

1. crear una institución;
2. configurarla (tono, instrucciones, skills, tools, MCP, texto de conocimiento);
3. ver la lista;
4. seleccionar una y probarla en un chat con aspecto de WhatsApp.

No es un producto “consola”. No es WhatsApp Business (`EXT-004`). No mejora `FakeLLM` ni el retrieval en esta entrega.

## 2. Fuera de alcance (esta entrega)

- Adapter LLM real; `FakeLLM` no se toca y sigue ignorando el request.
- Knowledge embeddings / PDFs (`EXT-008`).
- API médica (`EXT-001`–`EXT-003`).
- WhatsApp real, webhooks, plantillas, números.
- Mutaciones conversacionales (ADR-006 §4).
- Campos institucionales no existentes (CUIT, logo, especialidades libres, saludo, avatar, vendor).
- Condiciones por slug en Core.
- Secretos en HTML, logs, traces, fixtures o repositorio.
- Activación productiva por preflight (sigue fail-closed). `lab_enable` no la reemplaza en producción.
- Cambiar `semconv.py`, alembic existente, o el envelope `/v1/simulated/messages`.

## 3. Páginas

Dos templates HTML servidos por FastAPI, sin React. CSS mínimo en el mismo archivo. Un script corto solo para guardar el token admin en `sessionStorage` y mandar `Authorization` (ADR-007). El token no se refleja en el HTML de respuesta.

### 3.1 `/admin/instituciones`

- Tabla: `slug`, `display_name`, `status`, `config_version`.
- Formulario de alta / edición (mismos campos; si `slug` ya existe, es edición).
- Enlace “Probar” → `/admin/instituciones/{slug}/chat`.

Campos del formulario (contrato actual, `extra=forbid`):

| Campo | Origen |
|---|---|
| `slug` | `tenant.yaml` (`^[a-z0-9]+(?:-[a-z0-9]+)*$`) |
| `display_name` | `tenant.yaml` |
| `tone` | `AgentConfig.tone` |
| `instructions` | `AgentConfig.instructions`, opcional, máx. 2000; `""` se guarda como ausente |
| `enabled_skills` | `faq`, `appointments`, `human_handoff` |
| `enabled_tools` | solo nombres de `KNOWN_TOOLS` / tools del package (p. ej. `appointments.search`, `.get`, `.create`, `.cancel`, `.reschedule`, `.confirm`) |
| `mcp.server_id` | `config.yaml` y binding `kind: mcp` |
| `mcp.capabilities` | `integrations.yaml` |
| `mcp.credentials_reference` | URI `sm://…` u otro esquema ya aceptado; nunca el valor del secreto |
| `knowledge_text` | opcional; un `.txt` del package |

Generados por el servidor, no por el operador:

- `schema_version: 1`
- canal `simulated`, `external_account_id: {slug}-simulated`, `secret_reference: sm://{slug}/channel/simulated`
- `knowledge.namespace == slug`
- un `policies/{skill}.yaml` por cada skill habilitada (`schema_version: 1`, `skill`)
- `evals.jsonl` vacío (el validador lo admite)
- `feature_flags.simulated_channel: true`

### 3.2 `/admin/instituciones/{slug}/chat`

- Cabecera con `display_name` (estilo WhatsApp).
- Lista de burbujas (usuario / bot) en el request actual; no hay persistencia extra de UI.
- Input + enviar.
- POST del texto al mismo path. El servidor **no** usa `/v1/simulated/messages` ni la firma del canal simulado.
- Resuelve el tenant por `slug` con `TenantContext` de **esa** institución (no el `tenant_id` del principal).
- `ConfigurationService.capture` + `AgentHarness.handle_message`.
- `InboundMessage.channel = "simulated"`; `channel_integration_id` se lee **en el request** desde la fila SQL de ese tenant (no el mapa `channel_integration_ids` cargado al startup).
- Respuesta: misma página con el historial del POST (texto del usuario + `kind`/`text`/`source_ids` del `AgentTurnResult`).
- Si no hay config activa: mensaje seguro ya existente (`Active configuration is not available.`), sin inventar hechos.

## 4. API y mutaciones

Auth: el mismo `get_principal` / token de servicio (ADR-007). Crear, listar y `lab_enable` requieren `platform_admin`. El chat requiere principal autenticado con `platform_admin` o rol que ya pueda operar ese slug vía `admin_context_for`.

Rutas nuevas (sólo no-producción):

| Método | Path | Efecto |
|---|---|---|
| `GET` | `/v1/admin/tenants` | Lista `{slug, display_name, status, config_version}` visibles al principal. `slug`/`status`/`config_version` salen de SQL. `display_name` se lee de `IA_MCP_TENANT_PACKAGES_DIR/{slug}/tenant.yaml`; si el archivo no existe, la lista muestra el `slug`. No se agrega columna ni migración. |
| `POST` | `/v1/admin/instituciones` | Escribe package bajo `IA_MCP_TENANT_PACKAGES_DIR/{slug}/`, `validate_package`, `provision`. Si el slug existe, no recrea (idempotente: replay de `provision`). Luego `publish` de la edición si el form cambió config. Luego `lab_enable`. |
| `POST` | `/v1/admin/tenants/{slug}/lab-enable` | Ver §5. Idempotente. |
| `GET`/`POST` | `/admin/instituciones` | HTML de §3.1 |
| `GET`/`POST` | `/admin/instituciones/{slug}/chat` | HTML de §3.2 |

Se reutilizan sin cambiar contrato: `POST /v1/admin/tenants/provision`, `GET /v1/admin/tenants/{slug}`, `ConfigurationService.publish` / `activate` (versión).

`TenantContext` es obligatorio en todo boundary tenant-scoped (capture, harness, list-by-tenant).

## 5. `lab_enable` (no es activate de producción)

`provision` deja `tenant.status=disabled`, config `draft` y `active_config_version=None`. Sin esto el chat no puede hacer `capture()`.

`lab_enable` (idempotente, audit `lab_enable`):

1. Rechaza si `IA_MCP_ENVIRONMENT` no es `development` ni `test`.
2. Toma la última versión de config del tenant; si está `draft`, la trata como publicable (o publica un `TenantConfigDraft` equivalente).
3. Setea `active_config_version`, `tenant.status=active`.
4. Activa solo el canal `simulated` y los bindings MCP de ese `tenant_id`.
5. No corre preflight, no afirma EXT, no escribe secretos.

No se monta en producción. No desbloquea P05.

## 6. Aislamiento y seguridad

- El chat de A no puede `capture` ni ejecutar tools de B.
- Ampliar el allowlist de A no cambia el de B (ya cubierto por el loop; las pruebas HTML no lo debilitan).
- El formulario rechaza keys extra y literales de secreto (mismas reglas que el validador de package).
- `credentials_reference` / `secret_reference` son URI; el HTML nunca pide el secreto.
- Listar no revela tenants ajenos: `platform_admin` ve todos; un `tenant_admin` sólo el propio (404 en el resto, igual que `GET /{slug}`).

## 7. Pruebas exigidas

Rojo primero.

- HTML de lista renderiza slugs de dos tenants y no cruza datos.
- Alta con `tone` + `instructions` + `server_id` escribe package válido (`validate_package` verde) y `provision` idempotente.
- `instructions=""` no aparece en `policies["agent"]`; `tenant_instructions` del próximo generate (cuando el bot se mejore) sigue siendo `None` — esta entrega no cambia el harness.
- `lab_enable` dos veces no duplica canales; segunda llamada no error.
- Chat POST de tenant A no incluye `tenant_id` ni texto de B.
- Sin `Authorization`: 401, mismo mensaje que el resto del admin.
- En `IA_MCP_ENVIRONMENT=production` las rutas de esta spec no existen.
- El token no aparece en el HTML renderizado ni en `RunInvestigation`.

No se exige que el texto del bot use las instrucciones (owner: fase del bot).

## 8. Fase del bot (después)

Fuera de este spec. Candidatos, en orden, cuando se abra esa fase:

1. Un `LLMPort` de laboratorio que lea `tone` y `tenant_instructions` sin concatenarlos a Core, **o** un adapter real (vendor = ADR aparte).
2. Allowlist de lectura en FAQ / superficie de turno para que el loop no esté inerte.
3. Retrieval que no sea `EmptyKnowledgeSearch`.

Hasta entonces el chat muestra lo que el harness ya hace (`FakeLLM` + knowledge vacío + FAQ sin tools).

## 9. Archivos previstos

- `src/ia_mcp/api/templates/instituciones.html`
- `src/ia_mcp/api/templates/institucion_chat.html`
- `src/ia_mcp/api/routes/instituciones.py` (HTML + list + lab_enable + package writer)
- `src/ia_mcp/onboarding/lab_enable.py` o método en el store existente
- `tests/unit/api/test_instituciones_html.py`
- `tests/security/test_instituciones_isolation.py`

No editar `delegation-board.md` desde el implementador. El coordinador abre Fase 13 y desbloquea tareas después de este spec.

## 10. Criterio de hecho

Un operador con token `platform_admin` en development abre `/admin/instituciones`, crea o elige un slug, guarda tono/instrucciones/MCP, abre el chat, envía un mensaje y ve una respuesta del harness de **ese** tenant. El bot puede ser débil. WhatsApp real no interviene.
