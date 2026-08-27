# Criterios de aceptación — Fase 2

```gherkin
Scenario: AC-P02-001 — Checkout reproducible
  Given un checkout limpio con Python 3.13 y contenedores
  When se ejecuta el comando de bootstrap y la suite rápida
  Then dependencias se instalan desde lockfile
  And lint, tipos y unit tests finalizan con exit code 0
```

```gherkin
Scenario: AC-P02-002 — Tenant resuelto desde cuenta autenticada
  Given una channel integration del tenant A y headers simulados con HMAC válido
  When llega un envelope con account id autenticado fuera del body
  Then el resolver devuelve tenant A
  And un tenant incluido en el contenido no altera el resultado
```

```gherkin
Scenario: AC-P02-003 — Cuenta desconocida falla cerrado
  Given un account id no registrado
  When se intenta resolver tenant
  Then se devuelve error seguro
  And no se crea conversación ni run
```

```gherkin
Scenario: AC-P02-012 — Identidad simulada manipulada falla antes del tenant
  Given body o account/timestamp modificados después de firmar
  When llega el request simulado
  Then la firma se rechaza
  And no se invoca Tenant Resolver
  And la ruta no existe en configuración de producción
```

```gherkin
Scenario: AC-P02-004 — Config publicada es inmutable
  Given config A v1 publicada
  When se propone un cambio
  Then se crea v2
  And v1 conserva payload y hash originales
```

```gherkin
Scenario: AC-P02-005 — Run captura versión
  Given config v1 activa al iniciar un request
  When v2 se activa durante el procesamiento
  Then el request conserva v1 hasta finalizar
  And ningún repositorio de runtime acepta sólo tenant_id como UUID
```

```gherkin
Scenario: AC-P02-006 — Rollback atómico
  Given v1 y v2 publicadas con v2 activa
  When un administrador autorizado activa v1
  Then nuevas ejecuciones usan v1
  And la acción queda auditada
```

```gherkin
Scenario: AC-P02-007 — Repositorio rechaza acceso cruzado
  Given config perteneciente a tenant B
  When un repositorio recibe TenantContext A y el identificador de B
  Then no devuelve la config
  And registra una violación sin contenido sensible
```

```gherkin
Scenario: AC-P02-008 — Secrets son referencias
  Given una config validada
  When se serializa para el Agent Harness
  Then sólo contiene credentials_reference
  And ningún secret value aparece
```

```gherkin
Scenario: AC-P02-009 — Correlación de request
  Given un request sin correlation header
  When FastAPI lo procesa
  Then genera correlation_id
  And response, trace y audit comparten el ID
```

```gherkin
Scenario: AC-P02-010 — Error sanitizado
  Given una excepción con token y email
  When el handler produce Problem Details y log
  Then la respuesta no contiene details internas
  And token/email están redactados
```

```gherkin
Scenario: AC-P02-011 — Ciclo de contexto es explícito
  Given una cuenta autenticada y config v1 activa
  When Tenant Resolver y Configuration Service procesan el ingreso
  Then el primero produce TenantIdentity
  And el segundo produce TenantContext con config_version=1
  And una activación concurrente de v2 no muta el contexto existente
```
