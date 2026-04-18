# Quant Platform Single-Rollout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** In one continuous rollout, turn the current repository from a feature-rich but unstable prototype into an internally usable quant workflow with a stable core, indexed research results, a closed local-paper flow, and a usable monitoring UI.

**Architecture:** Keep the current module-first monolith. Do not introduce a database, message queue, or new deployment topology in this rollout. Consolidate around filesystem-backed artifacts, explicit result indexing, and existing CLI/Web entrypoints so the system becomes testable and reviewable before any larger platform expansion.

**Tech Stack:** Python 3, `unittest`, filesystem-backed JSON/Markdown artifacts, existing `http.server` dashboard, current `src/stock_quantification` modules.

---

## Rollout Rules

- Stay inside the current repository layout.
- Do not add new strategy families in this rollout.
- Do not introduce production-only infrastructure.
- Prefer new focused modules over growing already-large files, but preserve existing patterns where possible.
- Every checkpoint must end with runnable commands and visible artifacts.

## Checkpoints

1. **Checkpoint A: Stable core** — syntax fixed, baseline tests passing, README aligned with reality.
2. **Checkpoint B: Research + paper closed loop** — indexed outputs, paper ledger consistency, broker/local paper state visible.
3. **Checkpoint C: Usable operator UI** — dashboard surfaces research, paper, and ops state without spelunking through raw artifacts.

### Task 1: Recover Buildability and Freeze the Baseline

**Files:**
- Modify: `src/stock_quantification/pipeline.py`
- Modify: `README.md`
- Test: `tests/test_backtest.py`
- Test: `tests/test_validation.py`
- Test: `tests/test_runtime.py`
- Test: `tests/test_web.py`
- Test: `tests/test_broker.py`
- Test: `tests/test_local_paper.py`

- [ ] **Step 1: Reproduce the current hard failure**

Run:

```bash
python3 -m py_compile src/stock_quantification/pipeline.py
```

Expected: `SyntaxError` at `src/stock_quantification/pipeline.py`.

- [ ] **Step 2: Repair the syntax break in the strategy blueprint area**

Implementation target:
- Restore the malformed factor-weight mapping around the broken `trend` entry.
- Keep factor names aligned with `strategy_catalog.py` and current reporting/validation expectations.
- Do not change factor semantics yet; only recover the intended mapping structure.

- [ ] **Step 3: Re-run syntax verification**

Run:

```bash
python3 -m py_compile src/stock_quantification/pipeline.py
```

Expected: no output.

- [ ] **Step 4: Run the minimum regression set for the main chain**

Run:

```bash
PYTHONPATH=src python3 -m unittest \
  tests.test_backtest \
  tests.test_validation \
  tests.test_runtime \
  tests.test_web \
  tests.test_broker \
  tests.test_local_paper -v
```

Expected: tests complete without import-time failures.

- [ ] **Step 5: Update the repo-level truth source**

Update `README.md` so it matches what actually runs after the fix:
- keep only working commands
- mark clearly which capabilities are partial
- keep the “current range” and “not included” sections consistent with code

- [ ] **Step 6: Create the frozen baseline checkpoint**

Deliverable:
- one clean note in the plan execution log that lists:
  - commands that passed
  - commands that still fail
  - exact test modules considered baseline

### Task 2: Add a Result Index Layer for Research Outputs

**Files:**
- Create: `src/stock_quantification/result_index.py`
- Modify: `src/stock_quantification/artifacts.py`
- Modify: `src/stock_quantification/reporting.py`
- Test: `tests/test_artifacts.py`
- Test: `tests/test_reporting.py`
- Test: `tests/test_research_diagnostics.py`

- [ ] **Step 1: Define the result-index responsibilities**

Design the new module around four record types:
- research run
- validation run
- strategy suite run
- local paper run

Each record should carry:
- artifact kind
- market
- strategy or scenario identifier
- as-of or end date
- summary metrics
- file paths to JSON/Markdown outputs

- [ ] **Step 2: Write failing tests for result indexing**

Add tests that expect:
- a result record can be written after an artifact is created
- records can be listed newest-first
- filtering by kind and market works
- missing or malformed records do not crash the listing API

- [ ] **Step 3: Implement the minimal index module**

Implementation shape:
- a filesystem-backed JSON index under `artifacts/web/` or another existing artifact-backed location
- append-or-upsert behavior keyed by `artifact kind + identifier + date`
- helper functions for `record_result(...)` and `list_results(...)`

- [ ] **Step 4: Wire index recording into existing artifact writers**

Update artifact-producing paths so they can attach compact metadata when writing:
- validation results
- strategy suite results
- rolling/single backtests where available
- local paper run summaries

- [ ] **Step 5: Run the focused tests**

Run:

```bash
PYTHONPATH=src python3 -m unittest \
  tests.test_artifacts \
  tests.test_reporting \
  tests.test_research_diagnostics -v
```

Expected: new index behavior is covered and stable.

### Task 3: Normalize Validation and Strategy-Suite Summaries

**Files:**
- Modify: `scripts/run_validation_study.py`
- Modify: `scripts/run_strategy_suite.py`
- Modify: `src/stock_quantification/research_diagnostics.py`
- Modify: `src/stock_quantification/reporting.py`
- Test: `tests/test_validation.py`
- Test: `tests/test_strategy_catalog.py`

- [ ] **Step 1: Freeze the output contract**

Define one compact summary schema shared by validation and suite outputs:
- identity fields
- return / excess / drawdown metrics
- keep/review/drop style decision
- rationale text
- regime / style summary when available

- [ ] **Step 2: Write failing tests for summary compatibility**

Add tests that assert:
- validation summaries contain decision + rationale
- strategy suite summaries contain the same top-level summary keys where applicable
- missing optional diagnostics do not break serialization

- [ ] **Step 3: Implement the summary normalizer**

Keep the detailed raw payloads, but add one normalized summary block that the Web layer can consume directly without per-page custom parsing.

- [ ] **Step 4: Re-run the targeted tests**

Run:

```bash
PYTHONPATH=src python3 -m unittest \
  tests.test_validation \
  tests.test_strategy_catalog -v
```

Expected: normalized summaries are serialized consistently.

### Task 4: Close the Local Paper Ledger Loop

**Files:**
- Modify: `src/stock_quantification/local_paper.py`
- Modify: `src/stock_quantification/runtime.py`
- Modify: `src/stock_quantification/cli.py`
- Test: `tests/test_local_paper.py`
- Test: `tests/test_runtime_behavior.py`

- [ ] **Step 1: Write failing tests for ledger consistency**

Cover these scenarios:
- first run creates account + ledger + nav baseline
- second run appends trades without corrupting prior history
- no-fill runs do not create fake trades
- account snapshot, trade ledger, and nav history stay mutually consistent

- [ ] **Step 2: Tighten execution-to-ledger integration**

Implementation targets:
- one authoritative path from execution results to account snapshot updates
- nav snapshots always use the same pricing basis for a given run
- trade records skip zero-fill noise

- [ ] **Step 3: Surface paper-run metadata for later UI use**

Every local paper run should expose:
- account id
- strategy id
- trade count
- cash / buying power
- position count
- paths to generated run files

- [ ] **Step 4: Run the focused tests**

Run:

```bash
PYTHONPATH=src python3 -m unittest \
  tests.test_local_paper \
  tests.test_runtime_behavior -v
```

Expected: local paper flows are deterministic and append-safe.

### Task 5: Tighten Broker and Order-State Visibility

**Files:**
- Modify: `src/stock_quantification/broker.py`
- Modify: `src/stock_quantification/cli.py`
- Modify: `src/stock_quantification/models.py`
- Test: `tests/test_broker.py`
- Test: `tests/test_runtime.py`

- [ ] **Step 1: Write failing tests for broker state visibility**

Cover:
- unsupported market rejection
- credentials missing error path
- successful submit returns enough fields for later status inspection
- CLI output/report includes broker routing outcome cleanly

- [ ] **Step 2: Expand broker-facing order metadata only as much as needed**

Add enough state to distinguish:
- proposed order
- routed order
- accepted/pending broker status
- filled quantity and fill price when available

Do not build full reconciliation yet; keep this rollout at “paper-usable”.

- [ ] **Step 3: Run the focused tests**

Run:

```bash
PYTHONPATH=src python3 -m unittest \
  tests.test_broker \
  tests.test_runtime -v
```

Expected: routed-order outcomes are visible and serializable.

### Task 6: Expose Research Results in the Dashboard

**Files:**
- Modify: `src/stock_quantification/web.py`
- Modify: `static/styles.css`
- Test: `tests/test_web.py`

- [ ] **Step 1: Write failing Web tests for result-center views**

Cover:
- dashboard can list recent indexed research items
- selecting a result shows normalized summary fields
- empty state renders cleanly

- [ ] **Step 2: Add a minimal research/results panel**

The page should show:
- recent validation runs
- recent strategy suite runs
- recent single/rolling backtests when present
- summary cards instead of raw JSON dumps

- [ ] **Step 3: Keep the UI read-first**

Do not add editing workflows here. This page is for:
- browsing
- comparing
- opening linked artifacts

- [ ] **Step 4: Run Web tests**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_web -v
```

Expected: dashboard renders new result sections without breaking existing routes.

### Task 7: Expose Paper and Ops State in the Dashboard

**Files:**
- Modify: `src/stock_quantification/web.py`
- Modify: `src/stock_quantification/ops.py`
- Modify: `static/styles.css`
- Test: `tests/test_ops.py`
- Test: `tests/test_web.py`

- [ ] **Step 1: Write failing tests for operator views**

Cover:
- local paper account overview displays key account metrics
- recent trades are filterable by date range if provided
- ops center still shows active job, history, and audit events

- [ ] **Step 2: Implement the paper account operator panel**

The page should show:
- account overview
- recent trades
- nav history summary
- links to latest run artifacts

- [ ] **Step 3: Make ops state part of the same operator workflow**

Ensure the operator can understand:
- what last ran
- whether something is still running
- whether a run produced research outputs, paper outputs, or both

- [ ] **Step 4: Run the focused tests**

Run:

```bash
PYTHONPATH=src python3 -m unittest \
  tests.test_ops \
  tests.test_web -v
```

Expected: UI surfaces both research and runtime state coherently.

### Task 8: Final Regression, Cleanup, and Documentation Pass

**Files:**
- Modify: `README.md`
- Modify: `docs/current_gap_and_admin_console_design.md`
- Modify: `docs/quant_framework_system_design.md`
- Test: `tests/test_integration_flow.py`
- Test: `tests/test_platform.py`

- [ ] **Step 1: Run the broad regression suite**

Run:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

Expected: the repository passes or has a short explicit failure list with real blockers only.

- [ ] **Step 2: Perform a manual smoke sequence**

Run, in order:

```bash
PYTHONPATH=src python3 -m stock_quantification.cli --market CN
PYTHONPATH=src python3 scripts/run_validation_study.py --market CN --start-date 2026-01-02 --end-date 2026-03-31
PYTHONPATH=src python3 scripts/run_strategy_suite.py --market US --start-date 2026-01-02 --end-date 2026-03-31
PYTHONPATH=src python3 -m stock_quantification.web
```

Expected:
- CLI writes current-market artifacts
- validation writes indexed study outputs
- strategy suite writes indexed comparison outputs
- dashboard can display the new results

- [ ] **Step 3: Update architecture docs to reflect the new truth**

Document:
- result index layer
- current paper-closed-loop scope
- what remains intentionally out of scope after this rollout

- [ ] **Step 4: Produce the rollout closeout note**

The closeout note must list:
- what is now internally usable
- what is still prototype-grade
- next recommended milestone after this rollout

## Self-Review Notes

- This plan intentionally avoids introducing a database, scheduler framework, or approval system in the same rollout.
- The plan covers four subsystems but keeps them ordered so later tasks consume earlier stabilized outputs instead of changing everything at once.
- Remaining scope after this plan: formal data warehouse, strategy/version governance, full broker reconciliation, approval/permission system, and production deployment hardening.
