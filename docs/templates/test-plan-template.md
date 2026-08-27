# Test Plan — {{fase/capacidad}}

**Estado:** draft  
**TDD:** {{ruta}}  
**Criterios:** {{IDs}}

> Resolver tokens `{{...}}` antes de marcar `ready`.

## Riesgos de calidad

| Riesgo | Impacto | Prueba |
|---|---|---|
| {{riesgo}} | {{impacto}} | {{caso}}

## Entornos y fixtures

{{servicios, tenants, datos, clocks, fakes y sandbox}}

## Casos

| ID | Capa | Escenario | Fixture | Oráculo | Comando | Evidencia |
|---|---|---|---|---|---|---|
| {{TEST-ID}} | {{unit/contract/...}} | {{escenario}} | {{fixture}} | {{resultado}} | `{{cmd}}` | {{artefacto}} |

## Multi-tenancy

- {{acceso positivo}}
- {{acceso cruzado negativo}}

## Seguridad

- {{auth, authorization, secrets, injection, sanitización}}

## Resiliencia

- {{timeout, retry, replay, crash/restart, estado incierto}}

## Evals

{{dataset, trajectory assertions, modelo/config, umbral}}

## Performance

{{carga, presupuesto y criterio}}

## CI y gates

{{evento, suites, salida esperada y bloqueo}}

## Exit criteria

- [ ] Casos críticos pasan.
- [ ] Criterios tienen evidencia.
- [ ] Suite tenant negativa pasa.
- [ ] Sin failures/flakiness no explicada.
- [ ] Reporte reproducible adjunto.

