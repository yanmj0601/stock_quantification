# Experiment Evolution Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a minimal self-evolving strategy experiment loop that auto-derives and requeues the next factor backtest after each successful experiment.

**Architecture:** Extend `factor_backtest` jobs with lineage metadata, add a focused evolution helper to derive the next experiment payload from attribution output, and surface lineage/mutation details in optimize history/detail views.

**Tech Stack:** Python, existing SQLite job queue, dashboard web UI, unittest

---

### Task 1: Add evolution payload and UI inputs

**Files:**
- Modify: `src/stock_quantification/web.py`
- Test: `tests/test_web.py`

### Task 2: Implement minimal evolution derivation helper

**Files:**
- Create: `src/stock_quantification/experiment_evolution.py`
- Test: `tests/test_experiment_evolution.py`

### Task 3: Auto-enqueue next generation after successful experiment

**Files:**
- Modify: `src/stock_quantification/web.py`
- Test: `tests/test_web.py`

### Task 4: Expose lineage and mutation details in history/detail

**Files:**
- Modify: `src/stock_quantification/web.py`
- Test: `tests/test_web.py`

### Task 5: Verify end-to-end behavior

**Files:**
- Modify: `tests/test_web.py`
- Modify: `tests/test_experiment_evolution.py`
