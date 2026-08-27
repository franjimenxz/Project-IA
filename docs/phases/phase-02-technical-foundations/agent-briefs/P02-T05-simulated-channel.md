# P02-T05 — Canal simulado tenant-safe

**Estado:** ready  
**Wave:** W1  
**Depends on:** P02-T02, P02-T04

Implementá envelope estricto y endpoint 202 que resuelve tenant por account. No crear conversación/agente ni aceptar tenant en body.

Casos: A válido, desconocido, extra `tenant_id`, duplicado de schema y texto spoofing. Ejecutá `pytest tests/integration/api/test_simulated_messages.py tests/security/test_foundations.py -v`.

Commit: `feat: accept tenant-safe simulated messages`.

