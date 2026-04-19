# Quant Closed-Loop Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the first foundation modules needed to turn the current research-heavy quant repository into a system that can continuously evaluate factors, monitor data quality, and learn from execution feedback.

**Architecture:** Keep the current filesystem-first, module-first monolith. Add three small, focused foundation modules under `src/stock_quantification/` with matching unit tests, and avoid touching the current strategy runtime more than necessary. Treat this rollout as infrastructure for later UI, scheduling, and productionization work rather than a full end-to-end product launch.

**Tech Stack:** Python 3, `unittest`, dataclasses, existing `src/stock_quantification` package exports, existing test suite conventions.

---

## P0 / P1 / P2 Roadmap

### P0: Must-have closed-loop modules

1. Factor and experiment registry
2. Data snapshot and quality diagnostics
3. Execution feedback and reconciliation primitives
4. Broker order-state machine and replay-safe sync
5. Account-level risk budget and capital allocation

### P1: Strong leverage after P0

1. Strategy versioning and champion/challenger workflow
2. Task scheduling, alerting, and anomaly detection
3. Research result center with side-by-side comparisons
4. Portfolio optimizer and exposure budget center

### P2: Later platform upgrades

1. Web admin center for research governance
2. Multi-broker execution adapters
3. Historical warehouse and metadata lineage
4. API surface for external tooling

## Task 1: Add Factor and Experiment Registry

**Files:**
- Create: `src/stock_quantification/factor_registry.py`
- Modify: `src/stock_quantification/__init__.py`
- Test: `tests/test_factor_registry.py`

- [ ] **Step 1: Write the failing tests**

Add tests that cover:
- registering a factor definition and new factor version
- rejecting duplicate factor-version pairs
- recording experiment runs that reference factor versions
- ranking experiment summaries newest-first and best-score-first

- [ ] **Step 2: Run the targeted test file**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_factor_registry -v
```

Expected: import or attribute failures because the module does not exist yet.

- [ ] **Step 3: Implement the minimal registry**

Implementation scope:
- `FactorDefinition`
- `FactorVersion`
- `ExperimentRun`
- `InMemoryFactorRegistry`
- helpers for factor registration, version registration, experiment recording, and leaderboard-style listing

- [ ] **Step 4: Export the new module surface**

Update `src/stock_quantification/__init__.py` so the new types are importable from the package root.

- [ ] **Step 5: Re-run the focused test**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_factor_registry -v
```

Expected: PASS.

## Task 2: Add Data Snapshot and Quality Diagnostics

**Files:**
- Create: `src/stock_quantification/data_quality.py`
- Modify: `src/stock_quantification/__init__.py`
- Test: `tests/test_data_quality.py`

- [ ] **Step 1: Write the failing tests**

Add tests that cover:
- building a dataset snapshot summary from row counts and freshness timestamps
- generating quality findings for stale, missing, or zero-row datasets
- summarizing the worst dataset status for dashboard consumption

- [ ] **Step 2: Run the targeted test file**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_data_quality -v
```

Expected: import or attribute failures because the module does not exist yet.

- [ ] **Step 3: Implement the minimal diagnostics module**

Implementation scope:
- `DatasetSnapshot`
- `DataQualityFinding`
- `DataQualityReport`
- helpers for freshness checks, row-count checks, and overall severity summarization

- [ ] **Step 4: Export the new module surface**

Update `src/stock_quantification/__init__.py` so the new types are importable from the package root.

- [ ] **Step 5: Re-run the focused test**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_data_quality -v
```

Expected: PASS.

## Task 3: Add Execution Feedback and Reconciliation Primitives

**Files:**
- Create: `src/stock_quantification/execution_feedback.py`
- Modify: `src/stock_quantification/__init__.py`
- Test: `tests/test_execution_feedback.py`

- [ ] **Step 1: Write the failing tests**

Add tests that cover:
- computing fill-rate and slippage summaries from order attempts
- flagging a broker/account mismatch between intended and observed positions
- summarizing execution health for later strategy feedback loops

- [ ] **Step 2: Run the targeted test file**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_execution_feedback -v
```

Expected: import or attribute failures because the module does not exist yet.

- [ ] **Step 3: Implement the minimal feedback module**

Implementation scope:
- `ExecutionAttempt`
- `ExecutionFeedbackSummary`
- `ReconciliationDifference`
- helpers for aggregate fill-rate, average slippage, and position reconciliation

- [ ] **Step 4: Export the new module surface**

Update `src/stock_quantification/__init__.py` so the new types are importable from the package root.

- [ ] **Step 5: Re-run the focused test**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_execution_feedback -v
```

Expected: PASS.

## Task 4: Run the Combined Foundation Regression

**Files:**
- Modify: `src/stock_quantification/__init__.py`
- Test: `tests/test_factor_registry.py`
- Test: `tests/test_data_quality.py`
- Test: `tests/test_execution_feedback.py`
- Test: `tests/test_platform.py`

- [ ] **Step 1: Run the foundation modules together**

Run:

```bash
PYTHONPATH=src python3 -m unittest \
  tests.test_factor_registry \
  tests.test_data_quality \
  tests.test_execution_feedback \
  tests.test_platform -v
```

Expected: PASS.

- [ ] **Step 2: Record follow-up integration targets**

Capture these next integration points in the final summary:
- wire factor registry into validation and strategy-suite outputs
- wire data quality report into ops/dashboard status
- wire execution feedback into broker/local-paper reconciliation flows
