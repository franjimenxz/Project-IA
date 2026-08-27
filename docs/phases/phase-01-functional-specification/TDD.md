# TDD — Modelo de especificación funcional

**ID:** TDD-P01-001  
**Estado:** accepted  
**Requisitos:** UC-01–UC-10, RF-001–RF-045, RNF-001–RNF-015

## Decisión

La especificación se normaliza en cinco catálogos: casos de uso, requisitos, reglas, restricciones y dependencias. Cada entrada recibe un ID estable y un método de verificación. Los criterios observables viven por fase y la matriz global conecta requisito, diseño, tarea, prueba y evidencia.

## Boundary

Fase 1 describe comportamiento y resultados; no define endpoints externos, proveedor LLM, UI de operador ni implementación interna. Decisiones técnicas se toman en Fase 2 y contratos en Fase 3.

## Calidad del requisito

Una entrada está lista cuando es singular, inequívoca, verificable, priorizada, trazable y no contiene una solución innecesaria. Un dato externo desconocido se registra como `EXT`, no como requisito ficticio.

## Ownership

- Producto acepta UC, RF y reglas de negocio.
- Arquitectura acepta RNF, restricciones y TDDs.
- Seguridad acepta privacidad y threat model.
- QA acepta verificabilidad y evidencia.

## Cambio

Cambios conservan IDs y actualizan impacto. Un requisito eliminado pasa a `superseded`; no se renumera. Cambios en contrato o arquitectura requieren ADR/TDD y revalidación de trazabilidad.

## Gate

`G0` se satisface con catálogo, use cases, criterios y dependencias completas, y una revisión sin contradicciones críticas.

