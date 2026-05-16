# EvoQuant MVP v1 Design

## Purpose

Build a multi-market, self-evolving quant research platform that can generate candidate strategies, backtest them, validate robustness, register strategy versions, run paper trading, and expose the whole loop through a simple admin console.

The first version optimizes for reproducibility and operational control. It must make every strategy candidate traceable from data version to strategy parameters, validation metrics, approval decisions, paper-trading performance, and retirement history.

## Decisions Confirmed

- The platform is multi-market by design, not hard-coded for A-shares, US equities, or crypto.
- MVP v1 prioritizes the research evolution loop, with paper trading included earlier than originally proposed.
- Real live trading is explicitly out of scope for v1. Execution adapters should exist as interfaces only.
- The admin console should be a working research operations tool, not a decorative dashboard.
- Strategy pages must show performance and risk metrics, including CAGR, Sharpe, max drawdown, Calmar, turnover, validation state, and paper decay.

## MVP Scope

### Build in v1

- Data Hub
  - Multi-market data adapter interface.
  - Bars, instrument metadata, calendar references, and dataset versions.
  - Data quality checks for freshness, missing bars, duplicates, and price anomalies.
  - Initial storage can use local files and SQLite metadata; the schema should remain Postgres-friendly.

- Strategy Factory
  - Strategy templates with explicit parameter spaces.
  - Candidate generation through deterministic template expansion and parameter search.
  - No unrestricted LLM-written production strategy code in v1.

- Backtest Runner
  - Job-based backtest execution.
  - Cost model, slippage model, position constraints, and rebalance frequency.
  - Metrics output: CAGR, volatility, Sharpe, Sortino, max drawdown, Calmar, turnover, hit rate, payoff ratio, and exposure summary.

- Robustness Gate
  - Out-of-sample validation.
  - Walk-forward validation.
  - Parameter stability checks.
  - Cost sensitivity checks.
  - Correlation checks against already-approved strategies.

- Strategy Registry
  - Strategy id, name, version, market scope, asset class, template, parameters, code hash, dataset version, status, metrics, and audit trail.
  - Statuses: `research`, `candidate`, `paper`, `small-live-ready`, `production-ready`, `retired`.
  - v1 can use `small-live-ready` and `production-ready` as approval states only; they must not trigger real live orders.

- Paper Trading
  - Paper account with cash, equity, realized PnL, unrealized PnL, and net asset value.
  - Paper portfolio with positions, average cost, market value, and per-position PnL.
  - Paper orders with order intent, simulated fills, fill price, fees, and timestamps.
  - Paper performance comparison against backtest metrics to detect strategy decay.

- Risk Gate
  - Global mode: `research-only`, `paper-only`, `paused`.
  - Strategy-level pause and retire actions.
  - Candidate promotion requires validation gate results and manual approval.
  - Live trading remains disabled in v1.

- Admin Console
  - Overview.
  - Strategies.
  - Backtests.
  - Evolution.
  - Paper Trading.
  - Data Health.
  - Risk.
  - Audit Log.

### Explicitly Not v1

- Real broker or exchange live order submission.
- Unrestricted LLM strategy generation that writes directly to the registry.
- Reinforcement-learning production strategies.
- Full RBAC or organization-level permissions.
- Large distributed training/search infrastructure.
- Direct dependency on a single trading engine such as NautilusTrader, LEAN, vn.py, or Freqtrade.

## Architecture

The platform should use clear boundaries so each subsystem can be tested and replaced independently.

```text
Data Adapters
  -> Data Hub
  -> Dataset Registry
  -> Strategy Factory
  -> Backtest Runner
  -> Robustness Gate
  -> Strategy Registry
  -> Admin Approval
  -> Paper Trading
  -> Feedback Loop
```

The feedback loop writes paper performance, validation failures, and retirement reasons back into the registry. These records become inputs for later candidate generation and parameter search.

## Multi-Market Model

Market-specific rules belong in adapters and rule objects, not in strategy or registry code.

Core abstractions:

- `Market`: identifies a trading venue or asset domain such as `US`, `CN`, or `CRYPTO`.
- `Instrument`: symbol, market, asset class, currency, exchange, lot size, and tradability metadata.
- `Calendar`: sessions, holidays, trading hours, and settlement assumptions.
- `FeeModel`: commission, tax, spread, funding, and borrow assumptions.
- `SlippageModel`: price impact and fill assumptions.
- `PositionRule`: lot size, long-only/shortable constraints, leverage, concentration, and market-specific restrictions.
- `Bar`: timestamp, open, high, low, close, volume, adjustment flags, and source metadata.

The same strategy template should be able to run on different markets when supplied compatible adapters and rules.

## Admin Console

The console should be dense, operational, and built for repeated use.

### Overview

- Strategy counts by status.
- Active jobs.
- Candidate gate pass/fail counts.
- Paper account summary.
- Global risk mode.
- Recent audit events.

### Strategies

List columns:

- Strategy name and version.
- Market and asset class.
- Status.
- CAGR.
- Sharpe.
- Max drawdown.
- Calmar.
- Turnover.
- Validation state.
- Paper decay.
- Actions: approve for paper, pause, retire, open detail.

Detail view:

- Equity curve.
- Drawdown curve.
- Monthly and yearly returns.
- Train, validation, test, and paper segment metrics.
- Parameters, template id, code hash, dataset version, and audit history.

### Backtests

- Submit backtest jobs.
- View queued, running, succeeded, and failed jobs.
- Compare result metrics across strategy versions.
- Open generated reports and validation diagnostics.

### Evolution

- Configure objective function.
- Configure strategy templates and parameter spaces.
- Limit maximum candidates.
- Review generated candidates before registry promotion.

### Paper Trading

- Paper account NAV, cash, equity, realized PnL, and unrealized PnL.
- Holdings table.
- Orders and simulated fills.
- Paper vs backtest metric comparison.
- Paper decay warnings.

### Data Health

- Data source freshness.
- Missing bar counts.
- Duplicate bar counts.
- Price anomaly counts.
- Dataset versions and quality reports.

### Risk

- Global pause.
- Paper-only mode.
- Strategy-level pause.
- Promotion gate configuration.

### Audit Log

- Immutable events for strategy creation, status changes, backtest submissions, validation results, paper orders, risk mode changes, and approvals.

## Data Storage

MVP storage can be SQLite plus local files, with clean repository interfaces so Postgres and object storage can replace them later.

Suggested persistent records:

- `datasets`
- `instruments`
- `bars_metadata`
- `strategies`
- `strategy_versions`
- `strategy_metrics`
- `jobs`
- `validation_reports`
- `paper_accounts`
- `paper_positions`
- `paper_orders`
- `paper_fills`
- `risk_state`
- `audit_events`

Time-series bar data can start as Parquet or CSV files referenced by dataset metadata.

## API Surface

Initial API groups:

- `/api/dashboard`
- `/api/strategies`
- `/api/strategies/{id}`
- `/api/strategies/{id}/status`
- `/api/backtests`
- `/api/evolution`
- `/api/paper/accounts`
- `/api/paper/orders`
- `/api/data-health`
- `/api/risk`
- `/api/audit-events`

Every mutating endpoint should write an audit event.

## Job Model

Jobs should be explicit records, even if v1 runs them locally.

Job kinds:

- `backtest`
- `validation`
- `evolution`
- `paper_rebalance`
- `data_quality_check`

Job statuses:

- `queued`
- `running`
- `success`
- `failed`
- `cancelled`

The job table should store request payload, result payload, error message, timestamps, and related entity ids.

## Safety Rules

- Live trading is disabled in v1.
- Paper trading is the only execution mode that can produce simulated fills.
- Candidate promotion requires manual approval.
- No strategy can move to paper without validation records.
- All status transitions and risk changes must be audited.
- Missing or stale data should fail loudly for research jobs instead of silently degrading.

## Technical Direction

- Backend: FastAPI.
- Storage: SQLite for MVP, repository interfaces compatible with later Postgres migration.
- Workers: local database-backed job runner for MVP, replaceable by Celery, RQ, or Ray.
- Frontend: React admin console with tables, detail views, and charts.
- Charting: lightweight chart library for equity, drawdown, and return views.
- Tests: pytest with service-level and API-level coverage.

## Implementation Notes

The repository currently contains an early implementation spike created before this design was finalized. Treat it as disposable scaffolding. The implementation plan should decide which files to keep, rewrite, or delete, and no behavior from that spike should be assumed approved unless it appears in this spec.

## Acceptance Criteria

- A user can create or import a strategy template candidate.
- A user can run a backtest job and inspect performance metrics.
- A validation gate can pass or fail a strategy based on configured robustness rules.
- A passed strategy can be manually promoted to paper.
- A paper account can simulate holdings, orders, fills, and NAV.
- The admin console shows strategy returns, risk metrics, validation status, paper decay, jobs, data health, risk state, and audit events.
- Every important mutation writes an audit event.
- The system starts with live trading disabled.
