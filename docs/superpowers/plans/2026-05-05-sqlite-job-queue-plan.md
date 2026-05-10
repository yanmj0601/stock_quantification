# SQLite Job Queue Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the JSON-backed single active-job lock with a SQLite-backed persistent job queue and history store for the dashboard.

**Architecture:** Introduce a focused SQLite state store for jobs, job events, run history, and lightweight key-value state. Keep the existing execution logic largely intact, but change task submission from “run immediately if lock free” to “enqueue, then consume with a single worker”.

**Tech Stack:** Python stdlib `sqlite3`, existing threaded web server, unittest

---

### Task 1: Add failing storage tests

**Files:**
- Create: `tests/test_sqlite_state.py`
- Test: `tests/test_ops.py`

- [ ] **Step 1: Write failing SQLite store tests**

Add tests for:
- queueing a job
- claiming the oldest queued job
- finishing a job
- importing legacy JSON state
- appending and listing run history

- [ ] **Step 2: Run targeted tests to verify failure**

Run: `PYTHONPATH=src python3 -m unittest tests.test_sqlite_state -v`

Expected: FAIL because the SQLite store does not exist yet.

### Task 2: Implement SQLite state store

**Files:**
- Create: `src/stock_quantification/sqlite_state.py`
- Modify: `src/stock_quantification/__init__.py`
- Test: `tests/test_sqlite_state.py`

- [ ] **Step 1: Implement schema and migration helpers**
- [ ] **Step 2: Implement job queue CRUD**
- [ ] **Step 3: Implement event and run-history persistence**
- [ ] **Step 4: Run targeted tests**

Run: `PYTHONPATH=src python3 -m unittest tests.test_sqlite_state -v`

Expected: PASS

### Task 3: Refactor ProjectOpsStore onto SQLite

**Files:**
- Modify: `src/stock_quantification/ops.py`
- Modify: `tests/test_ops.py`

- [ ] **Step 1: Update ops tests for queue semantics**
- [ ] **Step 2: Verify tests fail against old JSON-only behavior**

Run: `PYTHONPATH=src python3 -m unittest tests.test_ops -v`

Expected: FAIL on queue-specific expectations.

- [ ] **Step 3: Reimplement ProjectOpsStore using the SQLite store**
- [ ] **Step 4: Re-run ops tests**

Run: `PYTHONPATH=src python3 -m unittest tests.test_ops -v`

Expected: PASS

### Task 4: Move web task logs and run history to SQLite

**Files:**
- Modify: `src/stock_quantification/web.py`
- Modify: `tests/test_web.py`

- [ ] **Step 1: Add failing web tests for SQLite-backed history/status**
- [ ] **Step 2: Run focused web tests to verify failure**

Run: `PYTHONPATH=src python3 -m unittest tests.test_web.WebTests.test_home_page_run_history_view_reads_persisted_history tests.test_web.WebTests.test_home_page_run_history_view_shows_blocked_runtime_events -v`

Expected: FAIL because history still reads JSON directly.

- [ ] **Step 3: Switch `_load_task_logs`, `_load_run_history`, `_append_run_history_records`, and status aggregation to SQLite-backed helpers**
- [ ] **Step 4: Re-run focused web tests**

Run: `PYTHONPATH=src python3 -m unittest tests.test_web.WebTests.test_home_page_run_history_view_reads_persisted_history tests.test_web.WebTests.test_home_page_run_history_view_shows_blocked_runtime_events -v`

Expected: PASS

### Task 5: Add queued execution worker

**Files:**
- Modify: `src/stock_quantification/web.py`
- Modify: `tests/test_web.py`

- [ ] **Step 1: Add failing tests for enqueue-on-submit behavior**
- [ ] **Step 2: Run focused tests to verify failure**

Run: `PYTHONPATH=src python3 -m unittest tests.test_web -k queue -v`

Expected: FAIL or no matching tests before implementation.

- [ ] **Step 3: Add a single background worker that claims queued jobs and dispatches the correct executor**
- [ ] **Step 4: Change `handle_run` and `handle_factor_backtest` to enqueue payloads instead of blocking on an active lock**
- [ ] **Step 5: Re-run focused web tests**

Run: `PYTHONPATH=src python3 -m unittest tests.test_web -v`

Expected: PASS for the new queue behavior.

### Task 6: End-to-end verification

**Files:**
- Modify: `src/stock_quantification/web.py`
- Modify: `src/stock_quantification/ops.py`
- Modify: `tests/test_web.py`
- Modify: `tests/test_ops.py`
- Modify: `tests/test_sqlite_state.py`

- [ ] **Step 1: Run compile checks**

Run: `python3 -m py_compile src/stock_quantification/sqlite_state.py src/stock_quantification/ops.py src/stock_quantification/web.py tests/test_sqlite_state.py tests/test_ops.py tests/test_web.py`

Expected: no output

- [ ] **Step 2: Run the full targeted test suite**

Run: `PYTHONPATH=src python3 -m unittest tests.test_sqlite_state tests.test_ops tests.test_web -v`

Expected: PASS

- [ ] **Step 3: Restart local web service and verify status endpoint**

Run: `curl -s http://127.0.0.1:8000/api/project/status`

Expected: JSON with queue-aware `active_job` and `job_history`.
