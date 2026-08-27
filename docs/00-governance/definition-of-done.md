# Definition of Done

**Estado:** ready

## Tarea

- [ ] Requisitos y criterios del brief están satisfechos.
- [ ] Se observó una prueba roja por la razón esperada.
- [ ] Implementación mínima y refactor están completos.
- [ ] Pruebas unitarias y relevantes pasan.
- [ ] Ruff, tipos y controles de seguridad aplicables pasan.
- [ ] Interfaces y errores coinciden con contratos aprobados.
- [ ] Casos negativos multi-tenant aplicables pasan.
- [ ] Logs, trazas y auditoría no exponen secretos o datos innecesarios.
- [ ] Documentación y trazabilidad están actualizadas.
- [ ] Commit autocontenido y handoff con evidencia disponibles.
- [ ] Revisiones de conformidad y calidad aceptadas.

## Vertical slice

- [ ] Recorrido end-to-end observable funciona desde canal hasta resultado.
- [ ] Happy path, alternativas, errores, timeout, retry y duplicados están cubiertos.
- [ ] Estado sobrevive a reinicio donde corresponda.
- [ ] Dos tenants de fixture demuestran aislamiento.
- [ ] Tools se filtran por tenant y skill.
- [ ] Run, workflow, tool calls y resultado se correlacionan.
- [ ] Criterios de aceptación de la slice tienen evidencia.
- [ ] Demo reproducible y rollback documentados.

## Fase

- [ ] Todos los entregables del README existen y están aceptados.
- [ ] Gate de salida satisfecho.
- [ ] Matriz de trazabilidad sin huecos para requisitos de la fase.
- [ ] Integración de todas las tareas pasa en CI limpia.
- [ ] Dependencias nuevas clasificadas y asignadas.
- [ ] ADRs y TDDs reflejan el resultado real.
- [ ] Riesgos residuales aceptados explícitamente.
- [ ] Próxima fase tiene inputs estables.

## MVP técnico

- [ ] Dos tenants tienen configuración versionada independiente.
- [ ] Dos tenants tienen Knowledge Base independiente.
- [ ] Cada tenant resuelve MCP y tools autorizadas de forma independiente.
- [ ] El Core no contiene nombres ni reglas de una institución.
- [ ] FAQ/RAG responde con fuentes y fallback seguro.
- [ ] Alta, cancelación, reprogramación y confirmación funcionan con mock MCP.
- [ ] Human handoff transfiere resumen estructurado.
- [ ] Scheduler envía recordatorio configurable e idempotente.
- [ ] Estado y workflows son persistentes.
- [ ] Tool calls y ejecuciones son auditables.
- [ ] Suite automatizada y evals básicos pasan.

## Readiness de producción

- [ ] Integración real aprobada contra sandbox.
- [ ] Autenticación, secretos, rotación y mínimo privilegio validados.
- [ ] Revisión legal/privacidad `EXT-006` satisfecha.
- [ ] SLOs, carga y capacidad `EXT-007` aprobados.
- [ ] Alertas, dashboards, runbooks y on-call ensayados.
- [ ] Backup, restore, migración y rollback ensayados.
- [ ] Retención y sanitización configuradas.
- [ ] Segundo tenant incorporado sin lógica específica en Core.
- [ ] Security review y pruebas de aislamiento aceptadas.
- [ ] Plan de activación gradual y desactivación segura aprobado.

## Evidencia inválida

No constituyen Definition of Done: captura aislada sin comando, prueba manual no reproducible, suite parcial sin justificación, mock que no cumple contrato, ausencia de errores en logs o afirmación del agente sin artefacto verificable.

