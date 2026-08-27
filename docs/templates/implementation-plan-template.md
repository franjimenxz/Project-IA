# {{Feature Name}} Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** {{una oración}}

**Architecture:** {{dos o tres oraciones}}

**Tech Stack:** Python 3.13, FastAPI, Pydantic v2, SQLAlchemy 2, PostgreSQL, Pytest

**Spec:** {{ruta exacta al TDD aprobado}}

## Global Constraints

- TenantContext es obligatorio en toda interfaz tenant-scoped.
- El Core no contiene lógica o credenciales institucionales.
- Mutaciones pasan por workflows idempotentes.
- Toda tarea sigue prueba roja, implementación mínima y prueba verde.
- Los tokens `{{...}}` deben resolverse antes de marcar el plan `ready`.

---

## File map

| Ruta | Responsabilidad |
|---|---|
| `{{path}}` | {{responsabilidad única}} |

## Dependency DAG

```mermaid
flowchart LR
    {{TASK_A}} --> {{TASK_B}}
```

### Task {{N}}: {{Component Name}}

**Brief:** `{{ruta al brief}}`

**Requirements:** {{IDs}}

**Files:**

- Create: `{{exact/path.py}}`
- Modify: `{{exact/existing.py}}`
- Test: `{{tests/exact/test_path.py}}`

**Interfaces:**

- Consumes: `{{exact signature}}`
- Produces: `{{exact signature}}`

- [ ] **Step 1: Write the failing test**

```python
{{test completo}}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest {{exact node id}} -v`  
Expected: FAIL with `{{razón exacta}}`.

- [ ] **Step 3: Write minimal implementation**

```python
{{implementación mínima completa}}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest {{exact node id}} -v`  
Expected: PASS.

- [ ] **Step 5: Run relevant quality gates**

Run: `ruff check {{paths}} && mypy {{paths}} && pytest {{suite}} -v`  
Expected: exit code 0.

- [ ] **Step 6: Commit**

```bash
git add {{exact paths}}
git commit -m "{{type: outcome}}"
```

## Plan self-review

- [ ] Cada requisito del TDD tiene tarea.
- [ ] No hay tokens `{{...}}`.
- [ ] Firmas y tipos coinciden entre tareas.
- [ ] Cada paso de código contiene contenido ejecutable.
- [ ] Cada tarea termina en evidencia y commit independiente.

