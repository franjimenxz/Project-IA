# Catálogo de requisitos

**Estado:** ready  
**Fuente:** plan maestro aprobado  
**Prioridades:** `must`, `should`, `could`

## Actores

| ID | Actor | Responsabilidad |
|---|---|---|
| ACT-01 | Paciente | Consulta información y gestiona turnos |
| ACT-02 | Operador humano | Recibe y continúa conversaciones derivadas |
| ACT-03 | Administrador de institución | Configura tenant, políticas, skills, conocimiento e integraciones |
| ACT-04 | Sistema externo | Provee capacidades institucionales mediante API/MCP |
| ACT-05 | Administrador de plataforma | Opera el Core, seguridad, observabilidad y onboarding |

## Casos de uso

| ID | Nombre | Actor principal | Resultado |
|---|---|---|---|
| UC-01 | Iniciar conversación | ACT-01 | Tenant resuelto y conversación creada o retomada |
| UC-02 | Solicitar turno | ACT-01 | Workflow de turno iniciado con datos configurables |
| UC-03 | Consultar disponibilidad | ACT-01 | Alternativas vigentes presentadas |
| UC-04 | Crear turno | ACT-01 | Turno creado una sola vez y auditado |
| UC-05 | Cancelar turno | ACT-01 | Turno cancelado con validación y confirmación |
| UC-06 | Reprogramar turno | ACT-01 | Turno movido de manera consistente |
| UC-07 | Confirmar turno | ACT-01 | Estado de confirmación actualizado idempotentemente |
| UC-08 | Consultar información | ACT-01 | Respuesta institucional con fuentes o fallback seguro |
| UC-09 | Derivar a operador | ACT-01/ACT-02 | Contexto estructurado transferido y automatización suspendida |
| UC-10 | Recordatorio automático | Sistema | Paciente contactado según política configurable |

## Requisitos funcionales

| ID | Requisito | Prioridad | Verificación | Fase |
|---|---|---|---|---|
| RF-001 | Resolver un `tenant_id` confiable desde el canal antes de procesar contenido | must | Integración + seguridad | 4.1 |
| RF-002 | Cargar configuración activa estructurada y versionada por tenant | must | Unitario + integración | 4.1 |
| RF-003 | Permitir rollback de configuración conservando historial | must | Integración | 4.1 |
| RF-004 | Construir contexto con sólo configuración, políticas, memoria, conocimiento y tools pertinentes | must | Unitario + snapshot semántico | 4.1 |
| RF-005 | Mantener estado conversacional persistente fuera de la ventana del LLM | must | Integración | 4.2 |
| RF-006 | Registrar cada ejecución con `run_id`, tenant, conversación, config, skill, workflow, MCP y resultado | must | Integración | 4.1 |
| RF-007 | Habilitar skills por configuración de tenant | must | Unitario + aislamiento | 4.1 |
| RF-008 | Exponer al modelo sólo tools autorizadas para tenant y skill | must | Unitario + seguridad | 4.2 |
| RF-009 | Consultar Knowledge Base aislada por tenant | must | Integración + aislamiento | 4.1 |
| RF-010 | Ingerir PDFs y conservar procedencia, versión y estado | must | Integración | 4.1 |
| RF-011 | Responder consultas institucionales priorizando conocimiento recuperado | must | Eval | 4.1 |
| RF-012 | No inventar información cuando retrieval sea insuficiente | must | Eval | 4.1 |
| RF-013 | Aplicar fallback configurable: aclarar, pedir datos o handoff | must | Eval + integración | 4.1/4.4 |
| RF-014 | Interpretar intención y activar un workflow para operaciones críticas | must | Unitario + eval | 4.2 |
| RF-015 | Recolectar campos de turno definidos por configuración | must | Unitario + E2E | 4.2 |
| RF-016 | Consultar disponibilidad mediante contrato canónico | must | Contrato + E2E | 4.2 |
| RF-017 | Revalidar disponibilidad antes de crear o reprogramar | must | E2E + concurrencia | 4.2/4.3 |
| RF-018 | Crear turno con confirmación explícita e idempotencia | must | E2E + resiliencia | 4.2 |
| RF-019 | Cancelar turno mediante workflow validado | must | E2E | 4.3 |
| RF-020 | Reprogramar turno sin dejar estados parciales silenciosos | must | E2E + resiliencia | 4.3 |
| RF-021 | Confirmar turno manual o automáticamente de forma idempotente | must | E2E | 4.3/4.5 |
| RF-022 | Persistir y recuperar workflows incompletos | must | Integración + resiliencia | 4.2 |
| RF-023 | Aplicar timeouts, retries seguros y errores tipados a integraciones | must | Contrato + resiliencia | 4.2/5 |
| RF-024 | Resolver MCP por tenant sin lógica de negocio en el resolver | must | Unitario + aislamiento | 4.2 |
| RF-025 | Permitir MCP por institución construido con capacidades reutilizables | must | Arquitectura + contrato | 3/5 |
| RF-026 | Mantener nombres y respuestas canónicas para tools comunes | must | Contract tests | 3 |
| RF-027 | Traducir contratos canónicos a la API institucional en un adaptador | must | Contract tests | 5 |
| RF-028 | Derivar a operador por solicitud, política, baja confianza o error persistente | must | E2E + eval | 4.4 |
| RF-029 | Entregar al operador paciente, motivo, resumen, datos y acciones | must | Contrato + E2E | 4.4 |
| RF-030 | Suspender acciones automáticas mientras el handoff está activo | must | Integración | 4.4 |
| RF-031 | Programar recordatorios con anticipación configurable, inicialmente 48 horas | must | Integración con reloj falso | 4.5 |
| RF-032 | Evitar recordatorios duplicados y omitir turnos ya confirmados | must | Integración + idempotencia | 4.5 |
| RF-033 | Procesar la respuesta al recordatorio mediante workflow de confirmación | must | E2E | 4.5 |
| RF-034 | Auditar retrievals, tool calls, MCP, errores, handoffs, latencia y uso de modelo | must | Integración | 4-7 |
| RF-035 | Permitir reconstruir una ejecución sin depender sólo de logs de texto | must | Prueba operativa | 7 |
| RF-036 | Sanitizar datos sensibles antes de logs y telemetría | must | Seguridad | 4-7 |
| RF-037 | Referenciar secretos sin exponerlos al modelo ni a configuración legible | must | Seguridad | 2/5 |
| RF-038 | Activar/desactivar tenant y capacidades mediante configuración | must | Integración | 4/8 |
| RF-039 | Incorporar un segundo tenant sin modificar lógica compartida | must | E2E + diff arquitectónico | 8 |
| RF-040 | Ejecutar evals versionadas sobre trayectoria completa del agente | must | Pipeline de evals | 6 |
| RF-041 | Simular WhatsApp detrás de un Channel Gateway reemplazable | must | Integración | 4.1 |
| RF-042 | Incorporar proveedor real de WhatsApp sin cambiar el Agent Harness | should | Contract tests | Posterior al MVP técnico |
| RF-043 | Gestionar conocimiento por namespace, versión y estado de publicación | must | Integración | 4.1 |
| RF-044 | Correlacionar mensajes, runs, workflows, tools y auditoría | must | Integración | 4-7 |
| RF-045 | Desactivar de forma segura una integración o tenant sin perder auditoría | must | E2E operativa | 8 |

## Requisitos no funcionales

| ID | Requisito | Prioridad | Método de verificación |
|---|---|---|---|
| RNF-001 | Aislamiento multi-tenant en todas las capas | must | Suite negativa, revisión de queries y threat model |
| RNF-002 | Seguridad por defecto y mínimo privilegio | must | SAST, tests de autorización y revisión |
| RNF-003 | Auditoría íntegra y correlacionable | must | Reconstrucción de runs y controles de acceso |
| RNF-004 | Disponibilidad con degradación segura | must | Pruebas de fallos y SLO aprobado antes de producción |
| RNF-005 | Escalabilidad horizontal de API y workers sin estado local autoritativo | should | Prueba de concurrencia y diseño |
| RNF-006 | Observabilidad con trazas, métricas y logs estructurados | must | Prueba operativa y dashboards |
| RNF-007 | Performance con presupuestos por etapa | must | Carga; presupuestos fijados en Fase 2 |
| RNF-008 | Trazabilidad requisito-código-prueba-evidencia | must | Matriz y checks documentales |
| RNF-009 | Mantenibilidad mediante módulos pequeños y contratos tipados | must | Revisión, complejidad y type checking |
| RNF-010 | Extensibilidad de skills, LLM, almacenamiento, canal y MCP | must | Segundo adapter/tenant sin cambios en Core |
| RNF-011 | Idempotencia de operaciones mutables y jobs | must | Duplicados y replay tests |
| RNF-012 | Privacidad y minimización de datos | must | Inventario, sanitización y revisión especializada |
| RNF-013 | Recuperabilidad de workflows y operaciones incompletas | must | Crash/restart tests |
| RNF-014 | Reproducibilidad de entorno, builds y pruebas | must | CI limpia desde checkout |
| RNF-015 | Compatibilidad versionada de configuración y contratos | must | Migración y contract tests |

## Reglas de negocio

| ID | Regla |
|---|---|
| BR-001 | El `tenant_id` de autoridad proviene del canal autenticado, no del texto del usuario |
| BR-002 | Una ejecución usa una única versión de configuración inmutable |
| BR-003 | Una skill deshabilitada no se carga ni expone sus tools |
| BR-004 | Knowledge retrieval siempre requiere tenant explícito |
| BR-005 | La respuesta institucional cita procedencia cuando utiliza conocimiento |
| BR-006 | Si no hay evidencia suficiente, el agente no completa la respuesta por conocimiento general |
| BR-007 | Toda mutación requiere workflow, validación y resultado tipado |
| BR-008 | Crear o reprogramar requiere revalidación del slot |
| BR-009 | El mismo idempotency key no produce dos mutaciones |
| BR-010 | Retries automáticos sólo aplican a operaciones clasificadas como seguras |
| BR-011 | El MCP Resolver sólo selecciona endpoint/capacidades; no transforma negocio |
| BR-012 | Credenciales se resuelven fuera del contexto del modelo |
| BR-013 | Un handoff activo impide nuevas mutaciones automáticas |
| BR-014 | Un turno confirmado o cancelado no recibe recordatorio de confirmación |
| BR-015 | Los campos de paciente/turno son configurables por tenant |
| BR-016 | Cada tool call registra tenant, run, input sanitizado, estado, latencia y error tipado |
| BR-017 | Configuraciones publicadas son inmutables; un cambio crea nueva versión |
| BR-018 | Documentos no publicados no participan del retrieval productivo |
| BR-019 | El segundo tenant no justifica condiciones por nombre dentro del Core |
| BR-020 | Datos clínicos o administrativos no necesarios no se copian a logs, prompts ni métricas |

## Restricciones

| ID | Restricción |
|---|---|
| CON-001 | Backend en Python 3.13 y FastAPI |
| CON-002 | Proveedores externos se aíslan detrás de puertos/adaptadores |
| CON-003 | El MVP utiliza monolito modular, no microservicios por defecto |
| CON-004 | PostgreSQL es la fuente autoritativa de estado transaccional |
| CON-005 | El LLM es reemplazable y no constituye el workflow engine |
| CON-006 | No se almacenan secretos en repositorio, prompts o configuración expuesta al modelo |
| CON-007 | No se inventan contratos de la API médica |
| CON-008 | Cada cambio funcional incluye pruebas antes de aceptarse |
| CON-009 | Documentación, contratos y migraciones se versionan junto con el código |
| CON-010 | Las obligaciones legales se validan con especialistas antes de producción |

## Dependencias externas

| ID | Dependencia | Bloquea | Condición de resolución |
|---|---|---|---|
| EXT-001 | Documentación oficial de API médica | Adaptador real | Especificación completa y versionada recibida |
| EXT-002 | Acceso a sandbox médico | E2E real | Credenciales no productivas y datos de prueba disponibles |
| EXT-003 | Método de autenticación y límites de API | Seguridad del adapter | Flujo, scopes, expiración y rate limits confirmados |
| EXT-004 | Proveedor real de WhatsApp | Canal productivo | Contrato, webhook, seguridad y sandbox definidos |
| EXT-005 | Plataforma de handoff | Handoff productivo | API/eventos y ownership operativo confirmados |
| EXT-006 | Política legal y de retención | Producción | Revisión legal y privacy sign-off |
| EXT-007 | Objetivos de carga y disponibilidad | Capacity/SLO final | Volumen, horarios y criticidad aprobados |
| EXT-008 | PDFs institucionales reales | Calidad RAG del tenant | Corpus, permisos y responsables provistos |

