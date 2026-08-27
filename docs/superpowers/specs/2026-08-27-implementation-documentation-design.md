# Diseño del paquete documental para implementación multiagente

**Estado:** Listo para revisión  
**Fecha:** 2026-08-27  
**Fuente primaria:** Plan maestro provisto por el responsable del producto  
**Stack base confirmado:** Python con FastAPI  

## 1. Propósito

Este documento define cómo transformar el plan maestro de la plataforma de agentes médicos multi-tenant en un paquete completo de especificaciones y planes ejecutables por agentes de desarrollo.

El paquete debe permitir que cada agente:

1. comprenda exactamente qué resultado debe producir;
2. conozca sus dependencias de entrada y sus contratos de salida;
3. trabaje sin reinterpretar el plan maestro completo;
4. aplique desarrollo guiado por pruebas;
5. demuestre el cumplimiento con evidencia reproducible;
6. no introduzca decisiones incompatibles con otros frentes;
7. entregue trabajo revisable e integrable en incrementos pequeños.

El término **TDD** se utiliza exclusivamente como **Technical Design Document**. El enfoque de implementación, por su parte, también aplicará el ciclo de pruebas primero: rojo, verde y refactorización.

## 2. Resultado esperado

La documentación final estará compuesta por cinco capas coordinadas:

1. **Gobernanza:** roadmap, requisitos, decisiones, dependencias, trazabilidad y reglas de delegación.
2. **Arquitectura transversal:** diseño del sistema, datos, seguridad, multi-tenancy, testing y observabilidad.
3. **Paquetes de fase:** alcance, TDD, aceptación, pruebas, implementación y briefs delegables.
4. **Plantillas normativas:** formatos reutilizables para TDD, ADR, planes, pruebas y handoffs.
5. **Evidencia:** resultados de pruebas, revisiones, decisiones y gates de salida.

Los documentos no reemplazarán al código como fuente de verdad de contratos ejecutables. Los esquemas Pydantic, OpenAPI, migraciones y pruebas de contrato deberán mantenerse sincronizados con la documentación mediante validaciones automáticas.

## 3. Principios rectores

### 3.1 Separación de responsabilidades

- La configuración determina cómo se comporta el agente.
- La Knowledge Base determina qué sabe el agente.
- MCP determina qué puede hacer el agente.
- El Core compartido no contiene condiciones, credenciales, prompts ni integraciones específicas de una institución.
- Las operaciones transaccionales pasan por workflows determinísticos; el LLM no ejecuta libremente acciones críticas.

### 3.2 Vertical slices antes que capas aisladas

Cada incremento técnico debe demostrar un recorrido observable de extremo a extremo. Los componentes transversales se agregan cuando son necesarios para habilitar una slice concreta, sin construir infraestructura especulativa.

### 3.3 Contratos antes que integraciones

Las capacidades internas se expresan con contratos canónicos independientes de proveedores. Las APIs institucionales se incorporan mediante adaptadores y MCPs que traducen esos contratos.

### 3.4 Aislamiento verificable

Toda funcionalidad que lea configuración, estado, documentos, secretos, tools o auditoría debe incluir al menos una prueba positiva para el tenant correcto y una prueba negativa que demuestre que otro tenant no puede acceder al recurso.

### 3.5 Decisiones explícitas

Los datos desconocidos se clasifican como dependencia externa o decisión arquitectónica. Ningún agente puede completar un vacío inventando endpoints, credenciales, autenticación, requisitos legales o campos clínicos.

### 3.6 Entregas reproducibles

Cada tarea debe declarar comandos de prueba, resultados esperados, archivos afectados, criterios de aceptación y evidencia. “Funciona localmente” no constituye evidencia suficiente.

## 4. Jerarquía de fuentes de verdad

Ante una contradicción, se aplicará este orden:

1. requisitos aprobados y restricciones explícitas del responsable del producto;
2. ADRs aceptados;
3. TDD transversal del sistema;
4. TDD de la fase activa;
5. contratos ejecutables y esquemas versionados;
6. plan de implementación;
7. brief de tarea del agente;
8. comentarios y notas no normativas.

Un agente que detecte una contradicción debe detener la parte afectada, registrar la discrepancia y solicitar una decisión. No puede resolverla silenciosamente alterando una fuente de nivel superior.

## 5. Estructura documental objetivo

```text
docs/
├── README.md
├── 00-governance/
│   ├── master-roadmap.md
│   ├── requirements-catalog.md
│   ├── assumptions-decisions-dependencies.md
│   ├── traceability-matrix.md
│   ├── delegation-protocol.md
│   └── definition-of-done.md
├── 01-architecture/
│   ├── system-tdd.md
│   ├── component-model.md
│   ├── sequence-diagrams.md
│   ├── data-model.md
│   ├── security-and-multitenancy.md
│   ├── testing-strategy.md
│   ├── observability-strategy.md
│   └── adr/
│       ├── README.md
│       └── ADR-template.md
├── phases/
│   ├── phase-01-functional-specification/
│   ├── phase-02-technical-foundations/
│   ├── phase-03-internal-contracts/
│   ├── phase-04-mvp-vertical-slices/
│   ├── phase-05-real-integration/
│   ├── phase-06-verification-and-evals/
│   ├── phase-07-operability-and-observability/
│   └── phase-08-second-tenant-onboarding/
└── templates/
    ├── TDD-template.md
    ├── implementation-plan-template.md
    ├── agent-task-brief-template.md
    ├── ADR-template.md
    ├── test-plan-template.md
    └── evidence-report-template.md
```

Cada directorio de fase tendrá esta forma:

```text
phase-NN-name/
├── README.md
├── TDD.md
├── acceptance-criteria.md
├── test-plan.md
├── implementation-plan.md
├── agent-briefs/
│   └── PNN-TNN-short-name.md
└── evidence/
    └── README.md
```

Los archivos `implementation-plan.md` y `agent-briefs/` se generan después de aprobar el TDD correspondiente. El directorio `evidence/` comienza con instrucciones y recibe únicamente artefactos reproducibles o referencias a ejecuciones automatizadas.

## 6. Documentos de gobernanza

### 6.1 Índice documental

`docs/README.md` explicará el orden de lectura, el estado de cada documento, la convención de identificadores y el camino recomendado para producto, arquitectura, implementación, QA y operaciones.

### 6.2 Roadmap maestro

`master-roadmap.md` contendrá:

- fases y slices;
- dependencias entre fases;
- gates de entrada y salida;
- trabajo paralelizable;
- hitos demostrables;
- dependencias externas bloqueantes;
- criterio para replanificar.

### 6.3 Catálogo de requisitos

`requirements-catalog.md` normalizará:

- actores;
- casos de uso `UC-NN`;
- requisitos funcionales `RF-NNN`;
- requisitos no funcionales `RNF-NNN`;
- reglas de negocio `BR-NNN`;
- restricciones `CON-NNN`;
- dependencias externas `EXT-NNN`.

Cada requisito tendrá descripción, fuente, prioridad, método de verificación, fases responsables y estado.

### 6.4 Registro de supuestos, decisiones y dependencias

`assumptions-decisions-dependencies.md` separará estrictamente:

- **Confirmado:** requisito explícito aprobado.
- **Supuesto de diseño:** reversible, documentado y verificable.
- **Decisión:** resolución tomada mediante TDD o ADR.
- **Dependencia externa:** información o sistema fuera del control del equipo.

No se usarán entradas sin responsable, condición de resolución ni impacto.

### 6.5 Matriz de trazabilidad

`traceability-matrix.md` mantendrá el recorrido:

```text
Requisito → decisión/ADR → TDD → tarea → prueba → evidencia
```

Una fase no puede cerrarse si alguno de sus requisitos carece de prueba o evidencia asociada, salvo que se encuentre explícitamente diferido a una fase posterior en el roadmap.

### 6.6 Protocolo de delegación

`delegation-protocol.md` definirá:

- cómo seleccionar una tarea lista;
- qué documentos debe leer el agente;
- cómo reservar archivos e interfaces;
- cómo reportar bloqueos;
- cómo entregar resultados;
- revisiones obligatorias;
- límites para cambios fuera de alcance;
- política de commits;
- criterio de reintento y reasignación.

### 6.7 Definition of Done

`definition-of-done.md` tendrá niveles de finalización para tarea, slice, fase y MVP. Ningún nivel podrá declararse terminado sólo porque el código compila o porque una demostración manual tuvo éxito.

## 7. Baseline técnico que documentará el TDD del sistema

### 7.1 Forma de despliegue inicial

Se adoptará un **monolito modular** en Python con procesos desplegables separados cuando su ciclo operativo lo requiera:

- API FastAPI para canales, administración y callbacks;
- worker para tareas asíncronas y scheduling;
- runtime del agente;
- MCP servers por institución construidos sobre una librería compartida;
- herramientas de ingestión de conocimiento.

Los límites se definirán mediante módulos, puertos y contratos. No se dividirá prematuramente el MVP en microservicios, pero ningún módulo dependerá de detalles internos de otro módulo cuando exista un contrato público.

### 7.2 Tecnologías base

- Python 3.13.
- FastAPI y Pydantic v2 para APIs y contratos.
- SQLAlchemy 2 y Alembic para persistencia y migraciones.
- PostgreSQL como almacenamiento transaccional autoritativo.
- pgvector como primera implementación de búsqueda vectorial, encapsulada detrás de un puerto reemplazable.
- Redis para cola, caché acotada y coordinación distribuida; nunca como única fuente de estado transaccional.
- Almacenamiento de objetos compatible con S3 para documentos originales, detrás de una interfaz.
- OpenTelemetry para trazas, métricas y correlación.
- Pytest para pruebas; Ruff y un verificador de tipos configurado en modo estricto para calidad estática.
- Contenedores para el entorno reproducible de desarrollo y CI.

Las versiones exactas de dependencias se fijarán en el lockfile del bootstrap y se actualizarán mediante un proceso controlado. El diseño no dependerá de una plataforma cloud específica.

### 7.3 Estructura lógica del código

El TDD técnico detallará una estructura equivalente a:

```text
src/platform/
├── api/
├── tenancy/
├── configuration/
├── agent_runtime/
├── context_compiler/
├── skills/
├── knowledge/
├── workflows/
├── mcp/
├── integrations/
├── handoff/
├── scheduling/
├── observability/
└── shared/
```

`shared/` sólo contendrá primitivas verdaderamente transversales. No se utilizará como depósito de lógica sin propietario.

### 7.4 Puertos obligatorios

El diseño deberá definir, como mínimo, interfaces reemplazables para:

- modelo LLM;
- embeddings;
- repositorio de configuración;
- repositorio de conversaciones y workflows;
- Knowledge Base y retrieval;
- secretos;
- mensajería/canal;
- MCP client y resolución de servidores;
- scheduler;
- handoff;
- auditoría y telemetría;
- almacenamiento de documentos.

## 8. Descomposición de fases

### 8.1 Fase 1 — Especificación funcional

**Objetivo:** convertir la visión en comportamiento verificable sin decidir detalles internos innecesarios.

**Entregables principales:**

- glosario de dominio;
- actores y límites del sistema;
- UC-01 a UC-10 completos;
- catálogo RF, RNF, BR, CON y EXT;
- criterios de aceptación de producto;
- matriz inicial de trazabilidad;
- inventario de datos sensibles;
- decisiones y dependencias explícitas.

**Gate de salida:** todos los comportamientos del MVP tienen actor, precondición, trigger, flujo principal, alternativas, errores, resultado y método de verificación.

### 8.2 Fase 2 — Fundaciones técnicas

**Objetivo:** fijar la arquitectura compartida que permite implementar slices sin redefinir límites.

**Entregables principales:**

- TDD del sistema;
- diagrama de componentes;
- secuencias para consulta, alta, cancelación, reprogramación, confirmación, handoff y error externo;
- modelo de datos con clasificación persistente/efímero;
- estrategia de configuración versionada;
- estrategia de aislamiento multi-tenant;
- modelo de seguridad, secretos, sanitización y retención;
- taxonomía de errores;
- estrategia de idempotencia;
- ADRs fundacionales.

**Gate de salida:** cada componente tiene responsabilidad, interfaz, dependencias, datos, fallos y estrategia de prueba; no existe lógica institucional dentro del Core.

### 8.3 Fase 3 — Contratos internos

**Objetivo:** crear contratos canónicos ejecutables antes de integrar sistemas reales.

**Entregables principales:**

- modelos Pydantic para tenant, configuración, agente, conocimiento, workflows y MCP;
- contratos `AppointmentSearchRequest`, `AppointmentSlot`, `AppointmentCreateRequest`, `Appointment`, `Patient`, `ToolResult` y `ToolError`;
- convenciones de versionado y compatibilidad;
- catálogo de tools MCP;
- esquema común de errores;
- OpenAPI y ejemplos;
- contract tests y fixtures canónicas.

**Gate de salida:** los contratos tienen campos, tipos, obligatoriedad, validaciones, errores y ejemplos; los mocks cumplen las mismas pruebas que deberá cumplir una integración real.

### 8.4 Fase 4 — MVP por vertical slices

La fase se divide en slices que se aceptan individualmente:

#### Slice 4.1 — FAQ multi-tenant

Canal simulado → Tenant Resolver → Agent Harness → Context Compiler → FAQ Skill → Knowledge Service → respuesta con fuentes.

Demuestra aislamiento entre dos tenants, respuesta basada en documentación y comportamiento seguro cuando falta información.

#### Slice 4.2 — Creación de turno

Canal simulado → Appointment Skill → workflow persistente → MCP Resolver → mock MCP → mock agenda.

Demuestra recolección de datos configurables, consulta de disponibilidad, selección, revalidación, idempotencia y creación.

#### Slice 4.3 — Ciclo de vida del turno

Agrega consulta, cancelación, reprogramación y confirmación con autorización, validaciones, errores y reintentos seguros.

#### Slice 4.4 — Human handoff

Agrega triggers, resumen estructurado, transferencia, suspensión segura de automatización y reanudación definida.

#### Slice 4.5 — Scheduler y recordatorio

Agrega recordatorios configurables, inicialmente 48 horas antes, entrega idempotente y workflow de confirmación.

**Gate de salida de fase:** dos tenants ejecutan las slices habilitadas sin compartir configuración, documentos, estado, tools, credenciales ni auditoría.

### 8.5 Fase 5 — Primera integración real

**Objetivo:** reemplazar el mock de agenda por el MCP institucional sin cambiar contratos del Core.

**Gate de entrada bloqueante:** documentación oficial de API, acceso a sandbox, mecanismo de autenticación y reglas de uso entregados por la institución.

**Entregables principales:**

- informe de compatibilidad API/contratos;
- adaptador institucional;
- autenticación y secretos;
- transformaciones de request y response;
- timeouts, errores, rate limits y retries seguros;
- idempotencia;
- contract tests compartidos;
- pruebas de sandbox y end-to-end;
- plan de activación y rollback.

Mientras el gate no se cumpla, la fase permanecerá explícitamente bloqueada y el desarrollo continuará contra mocks contractuales; no se inventarán detalles.

### 8.6 Fase 6 — Verificación, seguridad y evals

**Objetivo:** consolidar evidencia de corrección funcional, aislamiento y comportamiento del agente.

Testing no comienza en esta fase: cada tarea anterior incluye pruebas. Esta fase completa suites cruzadas, pruebas de seguridad, carga, resiliencia y evals del recorrido completo.

**Gate de salida:** no hay requisitos críticos sin evidencia; las pruebas multi-tenant obligatorias pasan; los umbrales de evals y performance definidos en los requisitos no funcionales se cumplen.

### 8.7 Fase 7 — Operabilidad y observabilidad

**Objetivo:** hacer investigable, medible y operable cada conversación y operación.

La instrumentación básica se incorpora desde la primera slice. Esta fase agrega vistas de investigación, alertas, SLOs, runbooks, retención, sanitización, capacity planning y procedimientos de incidente.

**Gate de salida:** un operador puede reconstruir una ejecución mediante `run_id`, `tenant_id`, `conversation_id`, `config_version`, skill, workflow, MCP, tools y resultado sin depender sólo de logs de texto.

### 8.8 Fase 8 — Segundo tenant y readiness

**Objetivo:** demostrar que una nueva institución se incorpora por configuración, conocimiento y MCP, sin modificar el Core.

**Entregables principales:**

- runbook de onboarding;
- segundo tenant completo;
- suite de regresión multi-tenant;
- evals por tenant;
- validación de feature flags y skills;
- checklist de activación/desactivación;
- informe de cambios requeridos en el Core.

**Gate de salida:** el segundo tenant se activa sin condiciones específicas en módulos compartidos. Cualquier cambio del Core debe justificarse como capacidad genérica mediante ADR.

## 9. Formato normativo de cada TDD

Cada `TDD.md` deberá incluir:

1. metadata: identificador, estado, autores, revisores y documentos relacionados;
2. contexto y problema;
3. objetivos y no objetivos;
4. alcance y exclusiones;
5. requisitos y criterios cubiertos;
6. arquitectura y responsabilidades;
7. flujos y diagramas de secuencia;
8. interfaces, APIs, eventos y contratos;
9. modelo de datos, ownership y ciclo de vida;
10. aislamiento multi-tenant;
11. seguridad, privacidad y secretos;
12. errores, timeouts, retries e idempotencia;
13. observabilidad, auditoría y sanitización;
14. estrategia de testing y evals;
15. migración y compatibilidad;
16. rollout, feature flags y rollback;
17. alternativas descartadas y consecuencias;
18. riesgos con mitigaciones;
19. dependencias y gates;
20. checklist de aprobación.

Un TDD no puede aprobarse con requisitos ambiguos que afecten contratos, seguridad o aceptación. Las dependencias externas sí pueden permanecer sin resolver cuando exista un mock contractual y un gate explícito que impida activar la integración real.

## 10. Criterios de aceptación

Los criterios funcionales utilizarán identificadores `AC-PNN-NNN` y formato Given/When/Then. Cada criterio deberá declarar:

- requisito origen;
- prioridad;
- precondiciones y fixture;
- comportamiento observable;
- resultado esperado;
- tipo de prueba;
- evidencia requerida.

Ejemplo normativo:

```gherkin
Scenario: AC-P04-001 — El tenant A no recupera documentos del tenant B
  Given los tenants A y B tienen documentos indexados con contenido distinguible
  And la conversación pertenece al tenant A
  When la FAQ Skill ejecuta una búsqueda de conocimiento
  Then todos los resultados pertenecen al namespace del tenant A
  And la respuesta no contiene fragmentos ni metadatos del tenant B
  And la traza registra tenant_id=A sin almacenar contenido sensible innecesario
```

Los RNF tendrán criterios cuantitativos o un procedimiento reproducible. Los valores de performance y disponibilidad que requieran información de negocio se fijarán antes del gate de producción; el MVP utilizará presupuestos explícitos aprobados en el catálogo de RNF.

## 11. Estrategia de pruebas

### 11.1 Ciclo obligatorio por tarea

1. escribir una prueba que falle por la ausencia del comportamiento;
2. ejecutar y registrar el fallo esperado;
3. implementar el cambio mínimo;
4. ejecutar la prueba y confirmar que pasa;
5. refactorizar sin cambiar comportamiento;
6. ejecutar la suite relevante y controles estáticos;
7. adjuntar evidencia y realizar un commit autocontenido.

### 11.2 Capas

- **Unitarias:** configuración, resolución de tenant, compiler, filtros, validaciones, estados y políticas.
- **Contrato:** modelos, tools MCP, adaptadores, compatibilidad y errores.
- **Integración:** PostgreSQL, pgvector, Redis, almacenamiento de objetos, scheduler y handoff.
- **End-to-end:** recorridos verticales con proveedores simulados o sandbox.
- **Multi-tenant:** accesos positivos y negativos para configuración, KB, estado, tools, secretos y auditoría.
- **Seguridad:** autenticación, autorización, inyección de tenant, prompt injection, fuga de datos y sanitización.
- **Resiliencia:** timeouts, duplicados, caídas, retries, operaciones incompletas y recuperación.
- **Evals del agente:** intención, skill, tool, retrieval, políticas, handoff, alucinación y resultado final.
- **Performance:** latencia, concurrencia, colas, retrieval y consumo de recursos.

### 11.3 Determinismo

Los tests funcionales no dependerán de llamadas no controladas a un LLM real. Se usarán puertos, fakes, respuestas grabadas o proveedores configurados para evals. Las evals probabilísticas tendrán datasets versionados, semilla cuando aplique, umbrales y reporte de regresiones.

## 12. Planes de implementación

Cada plan se derivará de un TDD aprobado y comenzará con:

- objetivo;
- arquitectura resumida;
- stack;
- referencia al TDD;
- restricciones globales;
- mapa de archivos y responsabilidades;
- DAG de tareas.

Cada tarea será la menor unidad que justifique una revisión independiente y contendrá:

- identificador y objetivo;
- requisitos y criterios cubiertos;
- archivos exactos a crear o modificar;
- interfaces consumidas y producidas con firmas;
- pasos de prueba primero;
- comando exacto y fallo esperado;
- implementación mínima esperada;
- comando de verificación y resultado esperado;
- controles estáticos;
- evidencia;
- commit sugerido;
- condiciones de handoff.

No se admitirán instrucciones como “agregar pruebas”, “manejar errores” o “implementar lo anterior” sin casos, contratos, comandos y resultados concretos.

## 13. Briefs para agentes

Cada brief `PNN-TNN-short-name.md` será autocontenido y tendrá:

1. objetivo único;
2. resultado demostrable;
3. documentos obligatorios de lectura;
4. dependencias ya disponibles;
5. alcance incluido y excluido;
6. archivos permitidos y archivos reservados por otros frentes;
7. interfaces exactas consumidas y producidas;
8. pasos de implementación y pruebas;
9. criterios de aceptación asociados;
10. comandos de verificación;
11. evidencia que debe devolver;
12. restricciones de seguridad y multi-tenancy;
13. procedimiento de bloqueo;
14. formato del handoff;
15. mensaje de commit sugerido.

Un brief no habilita al agente a modificar decisiones de arquitectura. Si el contrato no permite completar la tarea, debe elevar una solicitud de cambio con impacto y alternativas.

## 14. Paralelización y ownership

El roadmap organizará tareas en waves:

- tareas de una wave no dependen entre sí;
- una interfaz tiene un único owner durante cada wave;
- los consumidores usan contratos ya aprobados o fakes versionados;
- dos agentes no editan el mismo archivo de manera simultánea;
- contratos compartidos se estabilizan antes de abrir fan-out;
- cada wave termina con revisión de especificación, calidad y suite integrada.

La paralelización prioritaria será:

1. documentación funcional, amenazas y modelo de datos después de fijar el glosario;
2. puertos y contratos después de aprobar el TDD del sistema;
3. implementaciones de adaptadores y fakes después de congelar contratos;
4. slices independientes sólo cuando comparten una base integrada estable;
5. pruebas cruzadas y revisión una vez fusionadas las entregas de la wave.

## 15. Revisiones y gates

Cada entrega tendrá dos revisiones:

1. **Conformidad:** verifica requisitos, TDD, alcance, contratos y criterios.
2. **Calidad:** verifica diseño, legibilidad, seguridad, pruebas, mantenibilidad y evidencia.

Orden de gates:

```text
Requisitos aprobados
→ TDD aprobado
→ plan y briefs aprobados
→ prueba roja observada
→ implementación y prueba verde
→ revisión de conformidad
→ revisión de calidad
→ suite integrada
→ evidencia registrada
→ cierre de tarea/slice/fase
```

## 16. Evidencia y estado

La evidencia mínima por tarea incluirá:

- hash de commit;
- comandos ejecutados;
- resultados y cantidad de pruebas;
- controles estáticos;
- criterios de aceptación cubiertos;
- migraciones o contratos generados;
- riesgos o desviaciones;
- enlaces o rutas a artefactos.

Los estados permitidos serán: `draft`, `ready`, `in_progress`, `blocked`, `in_review`, `accepted` y `superseded`. `blocked` requiere causa, impacto, responsable externo o decisión requerida y condición de desbloqueo.

## 17. Restricciones y dependencias externas conocidas

- La API médica real no está documentada: se usarán contratos y mocks hasta cumplir el gate de Fase 5.
- El proveedor de WhatsApp no está confirmado: Channel Gateway se diseñará como puerto y el MVP usará un canal simulado.
- La plataforma de handoff no está confirmada: se definirá un contrato y un adaptador simulado.
- El proveedor LLM no está confirmado: el runtime dependerá de un puerto neutral.
- La infraestructura cloud no está confirmada: los componentes se describirán por capacidad, no por producto propietario.
- Los requisitos legales específicos requieren validación especializada antes de producción: el MVP aplicará minimización, separación, auditoría y políticas configurables, sin afirmar certificaciones no verificadas.
- Los campos de paciente serán configurables; no se impondrán campos institucionales no confirmados.

## 18. Riesgos y mitigaciones

| Riesgo | Mitigación documental y técnica |
|---|---|
| Los agentes interpretan distinto el plan | Jerarquía normativa, contratos ejecutables y briefs autocontenidos |
| Se construyen capas sin flujo usable | Planificación por vertical slices y demos por gate |
| Fuga entre tenants | Tenant context obligatorio, filtros en repositorios y pruebas negativas |
| El LLM gobierna operaciones críticas | Workflow persistente, validaciones y confirmaciones determinísticas |
| Contratos cambian durante trabajo paralelo | Owner único, versionado y gates antes del fan-out |
| Se inventa la API institucional | Dependencia bloqueante, mock contractual y fase separada |
| La documentación queda obsoleta | Trazabilidad, generación desde esquemas y checks de CI |
| Se difiere observabilidad hasta el final | Correlación y auditoría desde la primera slice |
| Se sobrearquitecta el MVP | Monolito modular, puertos explícitos y ADR para nuevas piezas |
| Las evals sólo miran la respuesta final | Dataset de trayectorias y evaluación de contexto, skill, tool y workflow |

## 19. Criterios de completitud del paquete documental

El paquete se considerará completo cuando:

- todos los requisitos del plan maestro estén catalogados;
- todos los UC, RF, RNF, BR, CON y EXT tengan identificador;
- exista trazabilidad desde requisito hasta evidencia;
- la arquitectura, datos, seguridad, testing y observabilidad estén especificados;
- cada fase tenga alcance, TDD, aceptación, pruebas y gate;
- cada tarea implementable tenga plan y brief autocontenido;
- las dependencias externas estén explicitadas y no convertidas en supuestos;
- las slices incluyan pruebas multi-tenant y de errores;
- los templates impidan placeholders y handoffs ambiguos;
- el roadmap muestre dependencias y trabajo paralelizable;
- el segundo tenant sirva como validación de reutilización del Core;
- una revisión de consistencia no encuentre contradicciones críticas.

## 20. No objetivos de esta etapa documental

- implementar el producto;
- seleccionar un proveedor cloud definitivo;
- seleccionar una API médica sin documentación;
- declarar cumplimiento legal o regulatorio;
- diseñar una interfaz de operador no requerida para validar handoff;
- optimizar para escalas no respaldadas por requisitos;
- reemplazar esquemas ejecutables por descripciones narrativas.

## 21. Secuencia de producción de documentos

Después de aprobar esta especificación:

1. crear gobernanza, catálogo y plantillas;
2. escribir la especificación funcional y sus criterios;
3. escribir los TDDs transversales y ADRs;
4. definir contratos y estrategia de verificación;
5. construir el roadmap con DAG y waves;
6. generar un plan detallado por fase;
7. derivar briefs por tarea;
8. ejecutar revisión de cobertura, placeholders, consistencia de tipos e interfaces;
9. entregar un índice navegable con orden de delegación.

La generación de planes y briefs no comenzará hasta que esta especificación rectora sea aprobada, porque todos ellos argumentan desde sus decisiones y límites.
