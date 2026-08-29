# Roadmap maestro

**Estado:** ready  
**Objetivo:** ordenar entregas verticales, dependencias, paralelización y gates del MVP.

## Mapa de fases

```mermaid
flowchart LR
    P1[Fase 1\nEspecificación funcional] --> P2[Fase 2\nFundaciones técnicas]
    P2 --> P3[Fase 3\nContratos internos]
    P3 --> S41[Slice 4.1\nFAQ multi-tenant]
    P3 --> S42[Slice 4.2\nCrear turno]
    S42 --> S43[Slice 4.3\nCiclo de turno]
    S42 --> S44[Slice 4.4\nHandoff]
    S43 --> S45[Slice 4.5\nScheduler]
    S41 --> P6[Fase 6\nVerificación y evals]
    S43 --> P6
    S44 --> P6
    S45 --> P6
    S43 --> P5[Fase 5\nIntegración real]
    EXT[Documentación API + sandbox] --> P5
    S41 --> P7[Fase 7\nOperabilidad]
    S42 --> P7
    P5 --> P8[Fase 8\nSegundo tenant]
    P6 --> P8
    P7 --> P8
    P8 --> P9[Fase 9\nMCP discovery]
    P9 --> P10[Fase 10\nComposition root]
    P10 --> P11[Fase 11\nLoop de tool calls]
```

## Estrategia de entrega

La arquitectura y los contratos se estabilizan primero. A continuación se implementan slices completas. Testing, seguridad y observabilidad acompañan cada tarea; las fases 6 y 7 consolidan evidencia transversal y capacidades operativas, no introducen esas disciplinas por primera vez.

## Waves de trabajo

| Wave | Trabajo | Dependencia | Hito demostrable |
|---|---|---|---|
| W0 | Fase 1: dominio, requisitos y aceptación | Plan maestro | Backlog verificable y sin ambigüedades críticas |
| W1 | Fase 2: arquitectura, datos, amenazas y ADRs | W0 aceptada | Diseño coherente y revisado |
| W2 | Fase 3: contratos, errores, tools y fakes | W1 aceptada | Contract tests ejecutables |
| W3 | Slice 4.1 y base de Slice 4.2 | W2 aceptada | FAQ aislada y workflow de alta con mock |
| W4 | Slices 4.3 y 4.4 | Slice 4.2 aceptada | Ciclo de turnos y handoff |
| W5 | Slice 4.5, pruebas de resiliencia y operabilidad | W4 integrada | Recordatorios y reconstrucción de runs |
| W6-intake | P05-T01; en paralelo Fases 6 y 7 | P03-T05/P04-T10 aceptadas y `EXT-001` | Mapping institucional aprobado |
| W6-build | P05-T02 y P05-T03 | P05-T01 aceptada y `EXT-003` | Adapter contract-compliant |
| W6-sandbox | P05-T04 | P05-T03 aceptada y `EXT-002` | Sandbox real, canary y rollback |
| W7-prep | Fase 8 package/provision disabled | Fase 4 aceptada | Segundo package validado sin activar |
| W7-activate | Fase 8 preflight/activación/prueba final | Fases 5, 6 y 7 aceptadas | Segundo tenant sin cambios específicos en Core |
| W8 | Fase 9 MCP discovery e invocación genérica | Fase 8 aceptada (P08-T04); ADR-005 aceptado | Instituciones usan catálogo MCP propio vía `tools/list`; Core sin catálogo cerrado |
| W9 | Fase 10 composition root | Fase 9 aceptada (P09-T04) | Un proceso real deja listos los collaborators que hoy sólo inyectan los tests |
| W10 | Fase 11 loop de tool calls en el turno | P10-T01 aceptada; ADR-006 aceptado | El modelo ejecuta una tool de lectura ya autorizada y su resultado vuelve en la iteración siguiente |

## Gates globales

### G0 — Requisitos listos

- actores y UC-01 a UC-10 definidos;
- RF, RNF, BR, CON y EXT identificados;
- criterios de aceptación observables;
- datos desconocidos clasificados.

### G1 — Arquitectura lista

- componentes y ownership definidos;
- modelo de datos y límites transaccionales definidos;
- tenant context obligatorio en toda interfaz sensible;
- amenazas críticas con mitigación;
- ADRs fundacionales aceptados.

### G2 — Contratos listos

- modelos canónicos versionados;
- errores tipados;
- tools allowlisted por tenant;
- fakes y contract tests compartidos;
- compatibilidad documentada.

### G3 — Slice lista

- criterios de la slice pasan;
- pruebas negativas multi-tenant pasan;
- trazas y auditoría correlacionables;
- fallos y duplicados cubiertos;
- documentación y evidencia actualizadas.

### G4 — Integración real lista

G4 es el gate de salida de Fase 5. Su entrada requiere G2, las Slices 4.2–4.3 aceptadas y las dependencias externas indicadas.

- `EXT-001`, `EXT-002` y `EXT-003` satisfechos;
- contract tests contra adaptador real;
- sandbox end-to-end;
- secretos fuera del modelo y del repositorio;
- rollout y rollback ensayados.

### G5 — MVP listo

- Definition of Done del MVP satisfecha;
- suites funcional, seguridad, aislamiento, resiliencia y evals aceptadas;
- SLOs y alertas operables;
- segundo tenant incorporado sin lógica específica en Core.

### G6 — MCP discovery listo

Gate de salida de Fase 9. Entrada: G5 y P08-T04 aceptada.

- discovery `tools/list` operativo con fake in-process en CI;
- autorización por intersección discovered ∩ tenant ∩ skill sin catálogo cerrado en Core;
- invocación genérica `tools/call` con host/scheme allowlist fail-closed;
- dispatch canónico `appointments.*` preservado (ADR-003);
- AC-P09-001–AC-P09-012 aceptados.

### Fases 10 y 11

No agregan gate global. Cierran contra sus propios criterios: `AC-P10-001`–`AC-P10-006` y `AC-P11-001`–`AC-P11-012`, según declaran sus README. G6 sigue siendo el último gate global del roadmap.

## Política de replanificación

Se actualiza el roadmap cuando cambia un contrato compartido, aparece una nueva dependencia bloqueante, falla un gate por diseño o una tarea supera su boundary. La replanificación debe preservar identificadores existentes y marcar como `superseded` lo reemplazado.

## Camino crítico

Fase 1 → Fase 2 → Fase 3 → Slice 4.2 → Slice 4.3 → Fase 5 → Fase 8.

La Fase 5 puede permanecer bloqueada sin impedir validar el MVP contra mocks. No puede considerarse lista para producción sin documentación oficial y sandbox.
