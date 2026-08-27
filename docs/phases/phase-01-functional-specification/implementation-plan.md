# Functional Specification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Mantener una especificación funcional completa, trazable y automáticamente validada.

**Architecture:** Los requisitos viven en catálogos Markdown con IDs estables. Scripts determinísticos validan links, IDs, placeholders y cobertura sin interpretar semántica con un LLM.

**Tech Stack:** Python 3.13, Markdown, Pytest

**Spec:** `docs/phases/phase-01-functional-specification/TDD.md`

## Global Constraints

- No inventar dependencias externas.
- Preservar IDs publicados.
- Todo requisito `must` debe tener fase y método de verificación.

---

### Task 1: Validador documental

**Brief:** `agent-briefs/P01-T01-document-validator.md`

**Files:**

- Create: `scripts/check_docs.py`
- Test: `tests/docs/test_check_docs.py`

**Produces:** `check_unique_ids(paths: Sequence[Path]) -> list[str]`

- [ ] **Step 1: Write the failing test**

```python
def test_duplicate_requirement_id_is_reported(tmp_path):
    doc = tmp_path / "requirements.md"
    doc.write_text("RF-001 first\nRF-001 second\n", encoding="utf-8")
    assert check_unique_ids([doc]) == ["RF-001"]
```

- [ ] **Step 2: Verify red**

Run: `pytest tests/docs/test_check_docs.py::test_duplicate_requirement_id_is_reported -v`  
Expected: FAIL because `check_unique_ids` is unavailable.

- [ ] **Step 3: Implement ID extraction and duplicate reporting**

Implement regex `\b(?:UC|RF|RNF|BR|CON|EXT)-\d{2,3}\b`, count per namespace and return sorted duplicates.

- [ ] **Step 4: Verify green and quality**

Run: `pytest tests/docs/test_check_docs.py -v && ruff check scripts tests/docs`  
Expected: PASS and exit 0.

- [ ] **Step 5: Commit**

```bash
git add scripts/check_docs.py tests/docs/test_check_docs.py
git commit -m "test: validate documentation identifiers"
```

### Task 2: Traceability checker

**Brief:** `agent-briefs/P01-T02-traceability-checker.md`

**Files:** Create `scripts/check_traceability.py`; Test `tests/docs/test_traceability.py`.

**Produces:** `missing_must_requirements(catalog: str, matrix: str) -> set[str]`

- [ ] Write a failing test where `RF-001` is `must` but absent from matrix.
- [ ] Run `pytest tests/docs/test_traceability.py -v`; expect missing function failure.
- [ ] Implement parsing of catalog table IDs/priority and matrix ID/ranges, returning missing IDs.
- [ ] Run `pytest tests/docs/test_traceability.py -v && ruff check scripts tests/docs`; expect exit 0.
- [ ] Commit with `git commit -m "test: enforce requirement traceability"`.

### Task 3: CI documentation gate

**Brief:** `agent-briefs/P01-T03-docs-ci.md`

**Files:** Create `.github/workflows/quality.yml`; Modify `pyproject.toml`; Test `tests/docs/test_check_docs.py`.

- [ ] Add a failing subprocess test expecting `python scripts/check_docs.py --all docs` to exit 0.
- [ ] Run the test; expect failure until CLI exists.
- [ ] Add CLI flags for links, IDs/placeholders and invoke traceability; add CI job on Python 3.13.
- [ ] Run `python scripts/check_docs.py --all docs && pytest tests/docs -v`; expect exit 0.
- [ ] Commit with `git commit -m "ci: enforce documentation quality"`.

