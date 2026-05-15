# Runtime State SQLite Migration Design

**Date:** 2026-05-15  
**Status:** Proposed  
**Scope:** Migrate runtime mutable JSON state into SQLite while preserving config and result artifacts as files.

## Goal

Move the remaining runtime JSON state layers that are still actively mutated by the application into SQLite so that:

- web/runtime state is transaction-safe and queryable
- local paper account state and ledger stop depending on ad hoc JSON rewrites
- worktree cleanliness improves because active runtime state is no longer tracked as evolving JSON files
- result artifacts and source configuration remain file-based where that model is still the best fit

## Non-Goals

This migration does **not** attempt to:

- move dated experiment/run/backtest artifact JSON outputs into SQLite
- move source configuration such as `strategy_blueprints.json` into SQLite
- redesign the UI, job queue, or factor experiment logic
- replace SQLite with PostgreSQL or ClickHouse

## Current Problem

The codebase still uses a split runtime persistence model:

- SQLite already stores job queue, events, run history, some market cache, and other operational state
- JSON files still store:
  - strategy execution state
  - strategy candidate registry
  - result index
  - paper automation state
  - local paper account and ledger state

This creates several problems:

1. runtime state is scattered across multiple persistence models
2. JSON rewrites are more fragile under concurrent web/worker activity
3. local paper state is harder to evolve toward richer broker semantics
4. active JSON state continues to create git noise and ambiguous runtime snapshots

## Proposed Boundary

### Migrate to SQLite

These JSON-backed runtime states will move into SQLite:

- `artifacts/web/strategy_state.json`
- `artifacts/web/strategy_registry.json`
- `artifacts/web/result_index.json`
- `artifacts/web/paper_automation_state.json`
- `artifacts/local_paper/<account>/account.json`
- `artifacts/local_paper/<account>/ledger.json`

### Keep as Files

These remain file-based by design:

- `src/stock_quantification/strategy_blueprints.json`
- dated experiment/run/backtest artifacts under `artifacts/YYYY-MM-DD/*.json`
- markdown reports and other exported artifacts

This preserves the intended architecture:

- **runtime mutable state:** SQLite
- **source configuration:** checked-in files
- **output artifacts:** immutable/semi-immutable files

## Data Model

### 1. Strategy State

Create SQLite tables for current execution strategy state, replacing `strategy_state.json`.

Responsibilities:

- current execution preset per market
- champion/challenger metadata
- updated timestamps and provenance

The existing `StrategyStateStore` remains the public interface, but its backing store becomes SQLite-first.

### 2. Strategy Registry

Create SQLite tables for registered strategy candidates, replacing `strategy_registry.json`.

Responsibilities:

- candidate metadata
- source experiment linkage
- promotion timestamps
- lifecycle state used by results/paper UI

The existing `StrategyRegistry` API remains intact where possible, but reads/writes move to SQLite.

### 3. Result Index

Create SQLite tables for result index records, replacing `result_index.json`.

Responsibilities:

- indexed experiment/run/suite records
- result metadata used by history/detail views
- artifact path references

Artifacts themselves remain file-based; SQLite stores the index and query metadata only.

### 4. Paper Automation State

Create SQLite tables for automation checkpoints, replacing `paper_automation_state.json`.

Responsibilities:

- last auto-run date/status per paper account/market
- last strategy used
- failure reason / skip reason
- idempotency guard for daily auto-runs

### 5. Local Paper Account State

Create SQLite tables for local paper broker state, replacing per-account `account.json`.

Responsibilities:

- account cash / buying power / NAV / timestamps
- current position aggregates
- account metadata and audit timestamps

### 6. Local Paper Ledger

Create SQLite tables for local paper ledger records, replacing per-account `ledger.json`.

Responsibilities:

- fills / journal entries / NAV marks
- cleanup events such as unknown-position auto-liquidation
- execution provenance
- chronological reconstruction of account state

The design should favor append-only ledger records plus derived account snapshots, rather than repeatedly overwriting one large JSON object.

## Migration Strategy

### Phase 1: Dual-read, SQLite-write

For each migrated state layer:

1. add SQLite schema and repository methods
2. make the corresponding store write to SQLite
3. keep one-time legacy JSON import as fallback/bootstrap
4. stop treating JSON as the primary source of truth

This minimizes rollout risk and preserves compatibility with existing artifact directories.

### Phase 2: Remove JSON writes

After each store is verified:

- remove JSON persistence writes
- keep read-only legacy import helpers where they still help migration/bootstrap

### Phase 3: Clean up legacy files/tests

Once all runtime paths are SQLite-backed:

- remove JSON runtime file assumptions from tests
- stop generating these runtime JSON files in normal operation
- update docs to reflect SQLite as the sole runtime state layer

## Application Integration

### Web / Runtime Layer

`web.py` should continue to use the current store abstractions. The migration should happen behind those abstractions, not by teaching view code new persistence rules.

### Strategy Layer

`strategy_state.py`, `strategy_registry.py`, and `result_index.py` should become SQLite-backed repositories with compatibility import behavior for old JSON state.

### Local Paper Layer

`local_paper.py` should move from file-backed account/ledger mutation to SQLite-backed account snapshots plus ledger entries.

This is the most behavior-sensitive migration and should preserve:

- current simulated fill semantics
- NAV/path reconstruction
- recent trade history views
- unknown position cleanup handling

## Error Handling

The migration should favor these rules:

- if SQLite state exists, use it as source of truth
- if SQLite is empty and legacy JSON exists, import once
- if legacy JSON is malformed, do not crash the app; initialize empty/default SQLite state and surface a warning where appropriate
- result artifact lookup must continue to work even though the result index metadata moves to SQLite

## Testing Strategy

The migration must include:

1. unit tests for each migrated repository/store
2. compatibility tests that import legacy JSON into SQLite
3. local paper regression tests proving account/ledger behavior remains stable
4. web tests for:
   - strategy state views
   - result history/detail pages
   - paper pages
   - automation status displays

## Rollout Order

Implement in this order:

1. `strategy_state`
2. `strategy_registry`
3. `result_index`
4. `paper_automation_state`
5. `local_paper` account state
6. `local_paper` ledger

This order migrates the lowest-risk runtime state first and leaves the most behavior-sensitive local paper migration for last.

## Expected Outcome

After this migration:

- runtime mutable state is consistently SQLite-backed
- local paper becomes closer to a real broker/account model
- active service state no longer depends on multiple mutable JSON files
- result artifacts remain file-friendly and easy to inspect/export
- future migration to PostgreSQL becomes easier because repository boundaries are clearer
