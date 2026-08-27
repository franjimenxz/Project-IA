# Casos de uso

## UC-01 — Iniciar conversación

**Actor:** Paciente.  
**Precondiciones:** cuenta de canal autenticada y tenant activo.  
**Trigger:** llega un mensaje no procesado.  
**Flujo principal:** verificar mensaje → resolver tenant → deduplicar → crear/retomar conversación → capturar config → iniciar run → responder/encaminar.  
**Alternativas:** conversación `human_owned` se entrega al operador; tenant suspendido devuelve indisponibilidad segura.  
**Errores:** firma inválida, cuenta desconocida, duplicado, persistencia no disponible.  
**Resultado:** mensaje asociado a un único tenant/conversación y run auditado, o rechazo seguro.  
**Sistemas:** Channel Gateway, Tenant Resolver, Conversation Service, Agent Harness.

## UC-02 — Solicitar turno

**Actor:** Paciente.  
**Precondiciones:** skill appointments habilitada.  
**Trigger:** intención de obtener turno.  
**Flujo principal:** detectar intención → iniciar workflow → solicitar campos configurados → validar progresivamente → continuar a disponibilidad.  
**Alternativas:** campo opcional omitido; paciente cambia especialidad/fecha; solicita persona.  
**Errores:** datos inválidos, skill deshabilitada, estado conflictivo.  
**Resultado:** workflow persistente listo para consultar disponibilidad o handoff.  
**Sistemas:** Harness, Appointment Skill, Workflow Engine.

## UC-03 — Consultar disponibilidad

**Actor:** Paciente.  
**Precondiciones:** especialidad y rango válidos; MCP capability habilitada.  
**Trigger:** workflow dispone de datos mínimos.  
**Flujo principal:** crear request canónico → resolver MCP → buscar → validar response → presentar alternativas.  
**Alternativas:** sin slots, ampliar rango o cambiar profesional/sede.  
**Errores:** timeout, rate limit, contract violation, integración deshabilitada.  
**Resultado:** slots vigentes y normalizados o fallback/handoff seguro.  
**Sistemas:** Workflow, MCP Resolver/Client, Agenda.

## UC-04 — Crear turno

**Actor:** Paciente.  
**Precondiciones:** slot seleccionado, datos válidos y confirmación requerida obtenida.  
**Trigger:** paciente confirma creación.  
**Flujo principal:** revalidar slot → emitir command idempotente → crear mediante MCP → persistir resultado/outbox → confirmar.  
**Alternativas:** slot dejó de estar disponible y se ofrecen nuevas opciones.  
**Errores:** conflicto, timeout con estado incierto, rechazo de validación.  
**Resultado:** un único turno creado o estado `manual_review_required`, nunca éxito inventado.  
**Sistemas:** Workflow, MCP, Agenda, Audit.

## UC-05 — Cancelar turno

**Actor:** Paciente.  
**Precondiciones:** turno localizable y cancelación permitida.  
**Trigger:** solicitud de cancelación.  
**Flujo principal:** identificar/validar turno → mostrar resumen → confirmar → cancelar idempotentemente → informar.  
**Alternativas:** turno ya cancelado se trata como resultado idempotente; política exige handoff.  
**Errores:** no encontrado, no autorizado, fuera de plazo, upstream caído.  
**Resultado:** cancelado, sin cambios con explicación o manual review.  
**Sistemas:** Harness, Workflow, MCP, Agenda.

## UC-06 — Reprogramar turno

**Actor:** Paciente.  
**Precondiciones:** turno reprogramable y datos de búsqueda válidos.  
**Trigger:** solicitud de cambio.  
**Flujo principal:** cargar turno → buscar alternativas → seleccionar → revalidar → reprogramar atómicamente según contrato → informar.  
**Alternativas:** API sólo permite cancelar+crear; se requiere estrategia aprobada y compensación.  
**Errores:** slot perdido, estado incierto, operación parcial.  
**Resultado:** turno en nuevo slot o escalamiento explícito sin ocultar inconsistencia.  
**Sistemas:** Workflow, MCP, Agenda, Handoff.

## UC-07 — Confirmar turno

**Actor:** Paciente.  
**Precondiciones:** turno pendiente de confirmación.  
**Trigger:** respuesta manual o a recordatorio.  
**Flujo principal:** identificar turno → validar respuesta → confirmar idempotentemente → cancelar jobs redundantes → informar.  
**Alternativas:** ya confirmado devuelve éxito idempotente; rechazo inicia cancelación sólo si política lo permite.  
**Errores:** turno ambiguo, expirado, upstream indisponible.  
**Resultado:** confirmación persistida o handoff.  
**Sistemas:** Channel, Harness, Workflow, MCP, Scheduler.

## UC-08 — Consultar información

**Actor:** Paciente.  
**Precondiciones:** FAQ habilitada y corpus publicado.  
**Trigger:** pregunta institucional.  
**Flujo principal:** normalizar pregunta → retrieval tenant-scoped → validar soporte → generar respuesta con fuentes.  
**Alternativas:** evidencia insuficiente pide aclaración, reconoce límite o deriva según config.  
**Errores:** documento corrupto, retrieval caído, contenido no publicado.  
**Resultado:** respuesta sustentada o fallback; nunca contenido de otro tenant.  
**Sistemas:** Harness, Context Compiler, Knowledge Service, LLM.

## UC-09 — Derivar a operador

**Actor:** Paciente y operador.  
**Precondiciones:** handoff habilitado o política crítica.  
**Trigger:** solicitud explícita, baja confianza, fuera de alcance o error persistente.  
**Flujo principal:** resumir datos/acciones → crear caso → cambiar ownership → notificar paciente/operador.  
**Alternativas:** provider no disponible crea cola durable y mensaje seguro.  
**Errores:** rechazo del provider, payload inválido, duplicado.  
**Resultado:** conversación `human_owned` con transferencia auditada o retry/handoff local pendiente.  
**Sistemas:** Harness, Handoff Service, Operator Adapter.

## UC-10 — Recordatorio automático

**Actor:** Scheduler como sistema; paciente responde.  
**Precondiciones:** turno elegible, política activa y canal disponible.  
**Trigger:** alcanza `scheduled_for`, inicialmente 48 horas antes.  
**Flujo principal:** claim job → consultar estado → omitir si no elegible → outbox/send → procesar respuesta por UC-07.  
**Alternativas:** horario configurable o canal temporalmente no disponible.  
**Errores:** duplicado, timeout, turno ya confirmado/cancelado.  
**Resultado:** un recordatorio máximo por business key o skip auditado.  
**Sistemas:** Scheduler, DB/Outbox, Channel, MCP, Workflow.

