# P02-T05 — Canal simulado tenant-safe

**Estado:** ready  
**Wave:** W1  
**Depends on:** P02-T02, P02-T04

## Lectura obligatoria

System TDD Channel Gateway, security TDD, `../TDD.md`, AC-P02-002/003/012 y Task 5.

## Archivos exactos

Crear `src/ia_mcp/channels/models.py`, `channels/simulated_auth.py`, `api/routes/simulated.py`, tests API/security; modificar app routing por environment. No crear conversation/agent.

Implementá body estricto y endpoint 202 sólo test/development. La cuenta proviene de headers HMAC firmados con timestamp+body; validar freshness/replay antes de resolver. No crear conversación/agente ni aceptar tenant/account en body, ni montar la ruta en producción.

Casos: A válido, firma/body/account manipulado, timestamp viejo, replay, cuenta desconocida, extra `tenant_id/account_id` y texto spoofing. Ejecutá `pytest tests/integration/api/test_simulated_messages.py tests/security/test_foundations.py -v`.

Commit: `feat: accept tenant-safe simulated messages`.

Secuencia TDD: request firmado válido primero en rojo; luego tamper/stale/replay y production-route absence; verde con comando de verificación indicado.
