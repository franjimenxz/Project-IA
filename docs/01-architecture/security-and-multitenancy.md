# Seguridad y aislamiento multi-tenant

**Estado:** ready  
**Requisitos:** RNF-001, RNF-002, RNF-012, RF-036, RF-037

## Objetivos

- Evitar acceso cruzado a configuración, conocimiento, estado, tools, secretos y auditoría.
- Tratar el LLM y el contenido recuperado como componentes no confiables para autorización.
- Minimizar datos sensibles en prompts, telemetría y terceros.
- Fallar cerrado ante identidad, autorización o contrato ambiguo.

## Límites de confianza

1. Webhook/canal externo → Channel Gateway.
2. API administrativa → autenticación y RBAC.
3. Aplicación → LLM/embedding provider.
4. Core → MCP institucional.
5. MCP → sistema médico.
6. Aplicación → stores y observabilidad.
7. Operador humano → plataforma de handoff.

Cada límite valida autenticidad, autorización, esquema, tamaño, timeout y sanitización.

## Resolución y propagación de tenant

- El tenant se deriva de `channel + external_account_id` autenticado o del principal administrativo y produce `TenantIdentity`.
- Configuration Service captura versión activa y crea un `TenantContext`; sólo ese contexto habilita accesos de runtime.
- Headers de tenant sólo se aceptan en APIs internas autenticadas y se cotejan con scopes.
- El texto del usuario, parámetros de tool del LLM y metadata de documentos no pueden cambiar tenant.
- `TenantContext` se pasa explícitamente; no se usa un global mutable ni un UUID crudo.
- Repositorios incluyen tenant en query y claves.
- Adapters comprueban que integration y credentials reference pertenecen al tenant.
- Audit events registran tenant de autoridad.

## Autenticación y autorización

### Canal

- verificación de firma y timestamp;
- protección anti-replay;
- deduplicación por external message id;
- mapping a channel integration activa.

### Administración

- autenticación por request; hoy, token de servicio por principal validado contra una referencia `sm://` ([ADR-007](adr/ADR-007-admin-service-tokens-and-secret-resolution.md)), reemplazable por identidad federada sin cambiar los routers;
- roles `platform_admin`, `tenant_admin`, `operator`, `auditor`;
- autorización por acción y tenant;
- operaciones cross-tenant exclusivas de `platform_admin` y puertos separados;
- cambios sensibles con auditoría antes/después y motivo;
- sin configuración de identidad el plano rechaza: 401 sin identidad o con credencial inválida (indistinguibles), 403 con rol insuficiente.

### Servicios internos

- identidad de workload;
- mTLS o red privada equivalente;
- scopes mínimos;
- rotación de credenciales.

## Matriz resumida de amenazas

| Amenaza | Ejemplo | Prevención | Detección |
|---|---|---|---|
| Spoofing de tenant | Usuario pide `tenant_b` en prompt | Tenant desde canal autenticado | Audit mismatch |
| IDOR | UUID de conversación ajena | FK/query tenant-scoped + autorización | Test negativo + alerta |
| Prompt injection | PDF ordena exfiltrar secrets | Contenido delimitado como datos; tools allowlisted | Eval adversarial |
| Tool escalation | Modelo inventa tool | Registry + segunda validación | `forbidden` auditado |
| Secret leakage | Credencial entra en prompt/log | Reference + secret adapter + redactor | Secret scanning |
| SQL/vector leakage | Query sin filtro tenant | Repository API obligatoria + constraints | Query tests |
| Replay | Webhook o create duplicado | Timestamp, dedupe, idempotency key | Métrica de duplicados |
| SSRF | Endpoint MCP configurable arbitrario | Allowlist de red/host y validación | Alerta de destino |
| Supply chain | Dependencia comprometida | Lockfile, scanning, provenance | CI y alertas |
| Excessive data | Prompt incluye historia completa | Context minimization | Budget metrics/review |
| Audit tampering | Borrar tool call | Append-only + roles separados | Integrity checks |

## Defensa multi-capa

### Aplicación

- tenant no nullable en comandos;
- autorización centralizada;
- tipos distintos para IDs tenant-scoped;
- validación previa y posterior al adapter;
- errores sin enumeración cross-tenant.

### Base de datos

- claves compuestas;
- índices tenant-first;
- sesiones con tenant fijado;
- RLS como defensa adicional donde el adapter lo soporte;
- credenciales DB diferentes por workload.

### Vector/documentos

- namespace y metadata tenant-scoped;
- filtro previo al ranking;
- object keys opacas con prefix de tenant;
- URLs firmadas breves;
- verificación post-retrieval.

### MCP

- resolver valida ownership y host+scheme allowlist (fail-closed; `http` solo si explícitamente allowlisted);
- discovery vía `tools/list`; catálogo descubierto intersectado con allowlists de tenant y skill;
- auth reference resuelta fuera del modelo;
- `KNOWN_TOOLS` es alias set canónico de appointments, no deny-list de nombres institucionales;
- timeout y size limits;
- respuesta validada; invocación genérica auditada con `TenantContext`.

## Datos y privacidad

Clases iniciales:

| Clase | Ejemplos | Tratamiento |
|---|---|---|
| Pública institucional | horarios, sedes | Puede entrar a RAG publicado |
| Identificable | nombre, DNI, email | Minimizar, cifrar, acceso restringido |
| Operacional sensible | turno, cobertura | Sólo workflow/adapters necesarios |
| Secreto | tokens, passwords | Secret manager; nunca prompt/log |
| Auditoría | acciones y outcomes | Metadata sanitizada, acceso dedicado |

Antes de producción, `EXT-006` fija retención, base legal, derechos, ubicación y proveedores permitidos.

## Sanitización

Un redactor central procesa logs, spans, audit summaries y errores. Remueve:

- authorization headers y cookies;
- secret values y connection strings;
- DNI/email/teléfono cuando no son necesarios;
- contenido completo de mensajes/documentos;
- payloads crudos de API;
- prompts y completions por defecto.

Se guardan hashes o identificadores opacos cuando se necesita correlación.

## Prompt y LLM

- instrucciones Core y políticas separadas del contenido no confiable;
- documentos delimitados y rotulados como evidencia, no instrucciones;
- ninguna credencial o URL firmada;
- tools limitadas por código;
- salida estructurada validada;
- operaciones críticas requieren workflow y confirmación;
- proveedor y región aprobados antes de datos reales;
- evals adversariales para exfiltración, jailbreak e instrucciones cruzadas.

## Secretos

La configuración almacena `credentials_reference`. El adapter de secretos requiere tenant, integration id y purpose; valida ownership y devuelve el valor sólo al transport que lo necesita. El valor no aparece en excepciones ni objetos serializables.

Estado implementado ([ADR-007](adr/ADR-007-admin-service-tokens-and-secret-resolution.md)): el puerto `SecretResolver` resuelve una referencia `sm://` a un `SecretStr` o levanta `SecretResolutionError` con la referencia y sin el valor. El adapter disponible lee el entorno del proceso (`IA_MCP_SECRET_*`) y no valida ownership: el tenant lo establece la consulta tenant-scoped que produjo la referencia. La validación de ownership dentro del adapter queda pendiente del proveedor real.

## Incidentes

Una sospecha de fuga:

1. aborta la operación afectada;
2. genera evento crítico sin copiar el dato filtrado;
3. deshabilita integration/tenant mediante control autorizado si corresponde;
4. preserva evidencia de auditoría;
5. inicia runbook de incidente;
6. evalúa rotación, notificación y alcance con responsables legales/seguridad.

## Pruebas obligatorias

- A no lee config, documentos, estado, tools, secrets ni audit de B;
- parámetros o prompts no cambian TenantContext;
- IDs ajenos responden sin confirmar existencia;
- skill/tool deshabilitada falla cerrado;
- payloads con secrets/PII se redactan;
- documento con prompt injection no expande tools;
- endpoint MCP no allowlisted se rechaza;
- webhook repetido y command replay no duplican efectos;
- operador sólo accede a tenants asignados;
- audit runtime no puede borrar eventos.

## Gate de producción

Threat model revisado, suite negativa aceptada, secretos/rotación configurados, proveedor de datos aprobado, retención definida, pruebas de restore y respuesta a incidente ensayada.
