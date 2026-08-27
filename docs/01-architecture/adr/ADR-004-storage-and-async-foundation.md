# ADR-004 — PostgreSQL autoritativo, pgvector y Redis coordinador

**Estado:** accepted  
**Fecha:** 2026-08-27

## Contexto

El MVP necesita estado transaccional, configuración, auditoría, vectores, jobs y coordinación. Multiplicar stores autoritativos aumenta fallos distribuidos.

## Decisión

Usar PostgreSQL como fuente autoritativa. Usar pgvector para retrieval inicial detrás de un puerto. Usar Redis para cola, caché y locks reconstruibles, nunca como única copia de conversación/workflow. Usar object storage S3-compatible para documentos originales.

Side effects se publican mediante transactional outbox. Jobs persistentes conservan estado en PostgreSQL aunque Redis se pierda.

## Consecuencias positivas

- Consistencia y operación inicial simplificadas.
- Backup/restore unificado para estado crítico.
- Retrieval inicial sin otro cluster.
- Reemplazo posterior posible por puertos.

## Consecuencias negativas

- Carga vectorial y transaccional comparte base inicialmente.
- Redis sigue siendo dependencia operativa para throughput.
- Jobs requieren dispatcher/outbox propio o librería compatible.

## Alternativas descartadas

- Vector DB propietaria desde el inicio: decisión sin benchmark.
- Redis como workflow store: durabilidad insuficiente para negocio.
- Broker y scheduler independientes desde día uno: mayor superficie operativa.

## Verificación

- pérdida de Redis no pierde workflow/job;
- outbox evita commit sin publicación permanente;
- benchmark define cuándo extraer vector search;
- adapters de stores cumplen contract tests.

