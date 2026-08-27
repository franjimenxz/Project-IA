# Criterios de aceptación — Fase 1

```gherkin
Scenario: AC-P01-001 — Todos los casos de uso están completos
  Given el plan maestro y los actores ACT-01 a ACT-05
  When se revisan UC-01 a UC-10
  Then cada caso declara actor, precondiciones, trigger, flujo, alternativas, errores, resultado y sistemas
```

```gherkin
Scenario: AC-P01-002 — Los requisitos son trazables
  Given el catálogo de requisitos
  When se selecciona cualquier RF o RNF de prioridad must
  Then existe una fase responsable, método de verificación y entrada en la matriz de trazabilidad
```

```gherkin
Scenario: AC-P01-003 — Los vacíos no se convierten en invenciones
  Given que faltan API médica, sandbox, proveedor de canal y política legal
  When se inspecciona la especificación
  Then cada vacío aparece como EXT con condición de resolución y gate
  And no aparecen endpoints, credenciales o reglas no confirmadas
```

```gherkin
Scenario: AC-P01-004 — Multi-tenancy es transversal
  Given cualquier capacidad que accede a datos, tools o integraciones
  When se revisan sus requisitos y verificación
  Then el tenant de autoridad y una prueba negativa están definidos
```

```gherkin
Scenario: AC-P01-005 — El MVP tiene Definition of Done observable
  Given los entregables funcionales
  When se revisa la Definition of Done
  Then FAQ, turnos, handoff, scheduler, persistencia, auditoría, dos tenants y evals tienen checks separados
```

```gherkin
Scenario: AC-P01-006 — Las mutaciones no quedan a decisión libre del LLM
  Given UC-04 a UC-07
  When se revisan reglas y resultados
  Then cada mutación exige workflow, validación, idempotencia y resultado tipado
```

```gherkin
Scenario: AC-P01-007 — Una respuesta informativa sin evidencia es segura
  Given UC-08 y retrieval insuficiente
  When se aplica la configuración del tenant
  Then el resultado reconoce el límite, pide aclaración o deriva
  And no inventa información institucional
```

```gherkin
Scenario: AC-P01-008 — El segundo tenant valida la arquitectura
  Given un primer tenant implementado
  When se incorpora el segundo tenant
  Then la aceptación exige no agregar lógica por nombre de institución en Core
```

