# Verification and Evals Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Crear gates reproducibles para trayectoria del agente, seguridad, resiliencia y performance.

**Architecture:** Dataset y observaciones usan schemas tipados; scorers determinísticos gobiernan propiedades críticas y reportes comparan baseline.

**Tech Stack:** Python 3.13, Pydantic v2, Pytest, OpenTelemetry artifacts

**Spec:** `docs/phases/phase-06-verification-and-evals/TDD.md`

## Global Constraints

- Sólo fixtures sintéticas.
- Fallo crítico no se promedia.
- No guardar reasoning privado/prompts completos.
- Repetibilidad por hashes/versiones.

---

### Task 1: Schema y dataset

**Brief:** `agent-briefs/P06-T01-eval-dataset.md`

**Files:** Create `src/ia_mcp/evals/models.py`, `evals/datasets/mvp.jsonl`, validator and tests.

- [ ] Write failing test for duplicate case id/forbidden source intersection.
- [ ] Run unit test; expect missing validator.
- [ ] Implement strict EvalCase models and dataset validation.
- [ ] Add at least one case per UC plus cross-tenant/adversarial cases.
- [ ] Run validator/tests and commit `test: define versioned agent eval dataset`.

### Task 2: Runner, scorers y comparison

**Brief:** `agent-briefs/P06-T02-eval-runner.md`

**Files:** Create eval runner/scorers/report/CLI and tests.

- [ ] **Write failing test**

```python
def test_forbidden_tool_fails_critical_case():
    score = score_trajectory(case(forbidden_tools={"patients.get"}), observed(tools={"patients.get"}))
    assert score.passed is False
    assert score.critical_failures == ("forbidden_tool:patients.get",)
```

- [ ] Run test; expect missing scorer.
- [ ] Implement deterministic scorers, runner over Harness and JSON/Markdown report.
- [ ] Implement baseline comparison and non-zero exit on regression/critical failure.
- [ ] Run fake smoke and commit `feat: evaluate complete agent trajectories`.

### Task 3: Security/isolation suite

**Brief:** `agent-briefs/P06-T03-security-suite.md`

**Files:** Extend `tests/security/*`, create fixture matrix.

- [ ] Parameterize failing matrix over config, KB, secret, tool, conversation, job and audit stores.
- [ ] Run matrix and record uncovered boundary failures.
- [ ] Add boundary tests and only scoped control fixes; no blanket exception swallowing.
- [ ] Run SAST/dependency/secret scans and suite.
- [ ] Commit `test: enforce cross-tenant security boundaries`.

### Task 4: Resilience suite

**Brief:** `agent-briefs/P06-T04-resilience.md`

**Files:** Create fault injector and `tests/resilience/*`.

- [ ] Write failure scenarios for each dependency and before/after mutation outcomes.
- [ ] Run tests; expect missing fault hooks or incorrect states.
- [ ] Implement deterministic fault plans in fakes and assert retry/manual review/recovery.
- [ ] Run crash/restart/replay suite.
- [ ] Commit `test: verify workflow resilience and recovery`.

### Task 5: Performance baseline y release report

**Brief:** `agent-briefs/P06-T05-performance-report.md`

**Files:** Create performance scenarios/CLI, quality report aggregator and CI scheduled job.

- [ ] Add failing parser test for missing latency/error/queue metrics.
- [ ] Implement baseline scenarios and report schema.
- [ ] Run controlled baseline, store summarized approved baseline, compare regression.
- [ ] Wire scheduled/release gates.
- [ ] Commit `ci: gate releases on quality evidence`.

