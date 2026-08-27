# TDD — {{nombre}}

**ID:** {{TDD-ID}}  
**Estado:** draft  
**Autores:** {{autores}}  
**Revisores:** {{revisores}}  
**Requisitos:** {{IDs}}  
**ADRs:** {{IDs o “ninguno”}}

> Regla: antes de cambiar a `ready`, reemplazar todos los tokens `{{...}}`, resolver ambigüedades críticas y enlazar criterios verificables.

## 1. Contexto y problema

{{hechos, usuarios afectados y motivo}}

## 2. Objetivos

- {{resultado observable}}

## 3. No objetivos

- {{exclusión explícita y destino si aplica}}

## 4. Alcance

### Incluido

- {{capacidad}}

### Excluido

- {{capacidad}}

## 5. Requisitos y aceptación

| Requisito | Criterios | Verificación |
|---|---|---|
| {{RF/RNF}} | {{AC}} | {{prueba/evidencia}} |

## 6. Arquitectura

{{diagrama Mermaid y explicación de límites}}

## 7. Componentes y responsabilidades

| Componente | Responsabilidad | Consume | Produce | Owner de datos |
|---|---|---|---|---|
| {{nombre}} | {{una responsabilidad}} | {{contrato}} | {{contrato}} | {{entidad o ninguno}} |

## 8. Flujos

{{secuencias principal, alternativas y error}}

## 9. Interfaces y contratos

{{firmas exactas, schemas, eventos y compatibilidad}}

## 10. Modelo de datos

{{entidades, constraints, índices, transacciones, retención}}

## 11. Multi-tenancy

{{autoridad del tenant, propagación, storage, pruebas negativas}}

## 12. Seguridad y privacidad

{{auth, authorization, secrets, PII, amenazas y mitigaciones}}

## 13. Fallos e idempotencia

| Fallo | Código | Retry | Estado final | UX/operación |
|---|---|---|---|---|
| {{caso}} | {{error_code}} | {{política}} | {{estado}} | {{respuesta}}

## 14. Observabilidad y auditoría

{{spans, métricas, eventos, sanitización y alertas}}

## 15. Testing y evals

{{unit, contract, integration, E2E, tenant, security, resilience, evals}}

## 16. Migración y compatibilidad

{{schema/config/API versioning y estrategia expand/contract}}

## 17. Rollout y rollback

{{feature flags, activación gradual, abort y rollback}}

## 18. Alternativas

| Alternativa | Ventaja | Desventaja | Motivo de descarte |
|---|---|---|---|
| {{nombre}} | {{valor}} | {{costo}} | {{decisión}} |

## 19. Riesgos

| Riesgo | Probabilidad/impacto | Mitigación | Evidencia |
|---|---|---|---|
| {{riesgo}} | {{clasificación}} | {{control}} | {{prueba}}

## 20. Dependencias y gates

{{documentos, tareas, EXT y condición de entrada/salida}}

## 21. Checklist de aprobación

- [ ] Tokens de plantilla resueltos.
- [ ] Requisitos y criterios trazados.
- [ ] Interfaces y ownership sin contradicciones.
- [ ] Multi-tenancy y seguridad revisados.
- [ ] Fallos, retries e idempotencia definidos.
- [ ] Pruebas y evidencia concretas.
- [ ] Rollout y rollback viables.
- [ ] Dependencias con gate explícito.

