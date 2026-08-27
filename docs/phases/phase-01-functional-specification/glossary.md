# Glosario de dominio

| Término | Definición normativa |
|---|---|
| Tenant | Institución aislada que consume el Core compartido |
| TenantContext | Identidad inmutable del tenant y configuración capturada para una ejecución |
| Configuración publicada | Versión inmutable y activa del comportamiento/políticas de un tenant |
| Core | Lógica compartida sin particularidades institucionales |
| Agent Harness | Orquestador de un turno conversacional |
| Context Compiler | Componente que arma el contexto mínimo autorizado |
| Skill | Capacidad conversacional habilitable por tenant |
| Tool | Operación estructurada que el runtime puede solicitar bajo allowlist |
| Workflow | Máquina de estados persistente que gobierna una operación transaccional |
| MCP | Servidor de capacidades externas de una institución |
| MCP Resolver | Selector tenant/capability → MCP target; no implementa negocio |
| Knowledge Base | Corpus institucional aislado y versionado |
| Retrieval/RAG | Recuperación de evidencia institucional para responder |
| Conversation State | Datos necesarios para continuar el flujo actual |
| Compacted Memory | Resumen mínimo de información conversacional relevante |
| Agent Run | Ejecución correlacionable de un mensaje dentro del Harness |
| Tool Execution | Invocación individual auditada a una tool |
| Human handoff | Transferencia de ownership de conversación a un operador |
| Idempotency key | Clave que evita repetir el efecto de un comando |
| Outbox | Eventos persistidos en la misma transacción y publicados luego |
| Sandbox | Entorno externo no productivo con datos de prueba |
| Evidencia | Salida reproducible que demuestra un criterio |

