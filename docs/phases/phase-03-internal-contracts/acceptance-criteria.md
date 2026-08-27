# Criterios de aceptación — Fase 3

```gherkin
Scenario: AC-P03-001 — Search request válido
  Given specialty y rango donde date_from no supera date_to
  When se valida AppointmentSearchRequest
  Then el schema acepta el payload y normaliza tipos
```

```gherkin
Scenario: AC-P03-002 — Campos extra rechazados
  Given un payload con tenant_id o credentials
  When se valida cualquier tool request
  Then la validación falla por campo extra
```

```gherkin
Scenario: AC-P03-003 — Slot requiere timezone
  Given starts_at sin offset
  When se valida AppointmentSlot
  Then la validación falla
```

```gherkin
Scenario: AC-P03-004 — ToolResult es consistente
  Given ok=true con error o sin value
  When se valida ToolResult
  Then la validación falla
```

```gherkin
Scenario: AC-P03-005 — Tool deshabilitada falla cerrado
  Given una tool presente en MCP pero no en config
  When el executor recibe la llamada
  Then no invoca MCP y devuelve forbidden
```

```gherkin
Scenario: AC-P03-006 — Tenant no aparece en schema del modelo
  Given el JSON schema expuesto al LLM
  When se inspeccionan properties
  Then no contiene tenant_id, endpoint ni credentials_reference
```

```gherkin
Scenario: AC-P03-007 — Fake cumple búsqueda y mutaciones
  Given la contract suite
  When se ejecuta contra FakeAppointmentCapability
  Then search/get/create/cancel/reschedule/confirm pasan
```

```gherkin
Scenario: AC-P03-008 — Replay de create es idempotente
  Given dos create con la misma idempotency key
  When fake procesa ambos
  Then devuelve el mismo appointment
  And existe una sola creación
```

```gherkin
Scenario: AC-P03-009 — Error externo se normaliza
  Given timeout o respuesta malformada simulada
  When se invoca la capability
  Then retorna ToolError tipado sin payload sensible
```

```gherkin
Scenario: AC-P03-010 — Contract suite es reutilizable
  Given un objeto que implementa AppointmentCapability
  When se parametriza la suite con ese objeto
  Then no importa clases concretas del fake
```

