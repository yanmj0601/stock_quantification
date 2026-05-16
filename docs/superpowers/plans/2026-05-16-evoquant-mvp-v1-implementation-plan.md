# EvoQuant MVP v1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the approved Chinese MVP v1 design into a working multi-market quant research platform with strategy evolution, validation, paper trading, risk gates, audit logging, APIs, and an admin console.

**Architecture:** Start from a clean `evoquant` package and explicit repository/service boundaries. Keep live execution disabled; paper trading is the only execution-like path in v1. Use SQLite for MVP persistence with interfaces that can later move to Postgres and job workers that can later move to Celery/RQ/Ray.

**Tech Stack:** Python 3.11+, FastAPI, Pydantic, SQLite, pytest, React, Vite, TypeScript, TanStack Table, Recharts or lightweight SVG charts.

---

## Current Workspace Notes

- The approved spec is [docs/superpowers/specs/2026-05-16-evoquant-mvp-v1-design.md](/Users/juxiantan/ai_agent_project/stock_quantification/docs/superpowers/specs/2026-05-16-evoquant-mvp-v1-design.md).
- The old `stock_quantification` implementation has already been removed from the working tree in response to the user's rebuild request.
- `src/evoquant/` and three tests currently exist from an early implementation spike created before the design was approved. Treat these files as disposable. During implementation, either replace them completely or verify every retained behavior against the spec and the tests in this plan.
- Do not restore the old `stock_quantification` package unless the user explicitly changes direction.

## File Structure

Create or rewrite these files:

- `pyproject.toml` — Python package metadata, backend dependencies, pytest config.
- `README.md` — Chinese quickstart and project scope.
- `src/evoquant/__init__.py` — package version.
- `src/evoquant/domain.py` — enums and immutable domain models.
- `src/evoquant/metrics.py` — return, drawdown, Sharpe, Calmar, turnover, paper decay calculations.
- `src/evoquant/storage.py` — SQLite schema, connection helper, repository implementation.
- `src/evoquant/services/registry.py` — strategy registry and audit events.
- `src/evoquant/services/data_hub.py` — datasets, instruments, bars metadata, quality checks.
- `src/evoquant/services/backtest.py` — deterministic MVP backtest runner.
- `src/evoquant/services/validation.py` — robustness gate and promotion eligibility.
- `src/evoquant/services/paper.py` — paper account, orders, fills, positions, NAV.
- `src/evoquant/services/risk.py` — global mode and strategy-level pause/retire.
- `src/evoquant/services/evolution.py` — template expansion and candidate jobs.
- `src/evoquant/api.py` — FastAPI app and routes.
- `src/evoquant/cli.py` — local API runner.
- `frontend/package.json` — React admin console package.
- `frontend/src/App.tsx` — shell, navigation, page composition.
- `frontend/src/api.ts` — API client.
- `frontend/src/pages/*.tsx` — Overview, Strategies, Backtests, Evolution, PaperTrading, DataHealth, Risk, AuditLog.
- `frontend/src/styles.css` — restrained workbench-style UI.
- `tests/` — pytest coverage for each service and API route group.

Remove or leave deleted:

- `src/stock_quantification/**`
- `stock_quantification/**`
- legacy `scripts/**`, `templates/**`, old `static/**`, old tests and old docs that do not describe EvoQuant MVP v1.

---

### Task 0: Normalize Workspace and Project Skeleton

**Files:**
- Modify: `pyproject.toml`
- Create: `README.md`
- Create: `src/evoquant/__init__.py`
- Remove: disposable spike files that conflict with the planned structure

- [ ] **Step 1: Verify current dirty state**

Run:

```bash
git status --short | sed -n '1,220p'
```

Expected: old files show as deleted, early `src/evoquant/` spike files are untracked or modified, and the approved spec is already committed.

- [ ] **Step 2: Replace project metadata**

Write `pyproject.toml` with:

```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "stock-quantification"
version = "0.2.0"
description = "EvoQuant: multi-market self-evolving quant research platform."
requires-python = ">=3.11"
dependencies = [
    "fastapi>=0.111",
    "uvicorn[standard]>=0.30",
    "pydantic>=2.7",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.2",
    "httpx>=0.27",
]

[project.scripts]
evoquant = "evoquant.cli:main"

[tool.setuptools]
package-dir = {"" = "src"}

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
pythonpath = ["src"]
testpaths = ["tests"]
```

- [ ] **Step 3: Replace package initializer**

Write `src/evoquant/__init__.py` with:

```python
"""EvoQuant platform package."""

__version__ = "0.2.0"
```

- [ ] **Step 4: Add Chinese README**

Write `README.md` with:

```markdown
# EvoQuant

EvoQuant 是一个多市场通用的量化研究平台 MVP。第一版聚焦研究自进化闭环：数据集版本、策略候选生成、回测、稳健性验证、策略注册、模拟盘、风控门禁和后台管理台。

## 范围

- 支持多市场抽象：`US`、`CN`、`CRYPTO`。
- 支持策略状态流转：`research`、`candidate`、`paper`、`small-live-ready`、`production-ready`、`retired`。
- 支持模拟盘账户、订单、成交、持仓和净值。
- v1 禁用真实实盘下单。

## 本地运行

```bash
uv run --extra dev pytest -q
uv run evoquant --host 127.0.0.1 --port 8000
```

后台前端在 `frontend/`，完成后使用：

```bash
cd frontend
npm install
npm run dev
```
```

- [ ] **Step 5: Run package import smoke test**

Run:

```bash
uv run python -c "import evoquant; print(evoquant.__version__)"
```

Expected: prints `0.2.0`.

- [ ] **Step 6: Commit skeleton**

```bash
git add pyproject.toml README.md src/evoquant/__init__.py
git commit -m "chore: reset evoquant project skeleton"
```

---

### Task 1: Domain Models and Metrics

**Files:**
- Create: `tests/test_domain.py`
- Create: `tests/test_metrics.py`
- Create: `src/evoquant/domain.py`
- Create: `src/evoquant/metrics.py`

- [ ] **Step 1: Write failing domain tests**

Create `tests/test_domain.py`:

```python
from datetime import date

from evoquant.domain import (
    Bar,
    Instrument,
    Market,
    RiskMode,
    StrategyStatus,
)


def test_instrument_supports_multi_market_metadata():
    instrument = Instrument(
        symbol="AAPL",
        market=Market.US,
        asset_class="equity",
        currency="USD",
        exchange="NASDAQ",
        lot_size=1,
        tradable=True,
    )

    assert instrument.symbol == "AAPL"
    assert instrument.market is Market.US
    assert instrument.lot_size == 1


def test_bar_carries_source_and_adjustment_metadata():
    bar = Bar(
        symbol="600519",
        market=Market.CN,
        session=date(2026, 1, 5),
        open=100.0,
        high=110.0,
        low=99.0,
        close=108.0,
        volume=123456,
        adjusted=True,
        source="fixture",
    )

    assert bar.adjusted is True
    assert bar.source == "fixture"


def test_safety_enums_match_spec():
    assert StrategyStatus.PAPER.value == "paper"
    assert StrategyStatus.PRODUCTION_READY.value == "production-ready"
    assert RiskMode.RESEARCH_ONLY.value == "research-only"
```

- [ ] **Step 2: Write failing metrics tests**

Create `tests/test_metrics.py`:

```python
from evoquant.metrics import calculate_performance, paper_decay


def test_calculate_performance_includes_return_risk_and_turnover():
    equity = [100_000, 102_000, 101_000, 106_000]
    turnovers = [0.2, 0.4, 0.1]

    metrics = calculate_performance(equity, turnovers, periods_per_year=252)

    assert round(metrics.total_return, 4) == 0.0600
    assert metrics.cagr > 0
    assert metrics.sharpe > 0
    assert metrics.max_drawdown < 0
    assert metrics.calmar > 0
    assert round(metrics.turnover, 4) == 0.7


def test_paper_decay_compares_paper_to_backtest_cagr():
    assert paper_decay(backtest_cagr=0.20, paper_cagr=0.14) == -0.30
```

- [ ] **Step 3: Run tests to verify failure**

Run:

```bash
uv run --extra dev pytest tests/test_domain.py tests/test_metrics.py -q
```

Expected: fails because `evoquant.domain` and `evoquant.metrics` do not exist or lack required symbols.

- [ ] **Step 4: Implement domain models**

Create `src/evoquant/domain.py`:

```python
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:12]}"


class Market(str, Enum):
    US = "US"
    CN = "CN"
    CRYPTO = "CRYPTO"


class StrategyStatus(str, Enum):
    RESEARCH = "research"
    CANDIDATE = "candidate"
    PAPER = "paper"
    SMALL_LIVE_READY = "small-live-ready"
    PRODUCTION_READY = "production-ready"
    RETIRED = "retired"


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"


class RiskMode(str, Enum):
    RESEARCH_ONLY = "research-only"
    PAPER_ONLY = "paper-only"
    PAUSED = "paused"


@dataclass(frozen=True)
class Instrument:
    symbol: str
    market: Market
    asset_class: str
    currency: str
    exchange: str
    lot_size: int
    tradable: bool


@dataclass(frozen=True)
class Bar:
    symbol: str
    market: Market
    session: date
    open: float
    high: float
    low: float
    close: float
    volume: float
    adjusted: bool
    source: str


@dataclass(frozen=True)
class StrategyCandidate:
    id: str
    name: str
    market: Market
    asset_class: str
    template_id: str
    parameters: dict[str, Any]
    status: StrategyStatus = StrategyStatus.RESEARCH
    version: int = 1
    created_at: datetime = field(default_factory=utc_now)
```

- [ ] **Step 5: Implement metrics**

Create `src/evoquant/metrics.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from math import sqrt


@dataclass(frozen=True)
class PerformanceMetrics:
    total_return: float
    cagr: float
    volatility: float
    sharpe: float
    sortino: float
    max_drawdown: float
    calmar: float
    turnover: float


def calculate_performance(
    equity: list[float], turnovers: list[float] | None = None, periods_per_year: int = 252
) -> PerformanceMetrics:
    if len(equity) < 2:
        raise ValueError("equity series must contain at least two points")
    if any(value <= 0 for value in equity):
        raise ValueError("equity values must be positive")

    returns = [(equity[i] / equity[i - 1]) - 1 for i in range(1, len(equity))]
    total_return = equity[-1] / equity[0] - 1
    years = max(len(returns) / periods_per_year, 1 / periods_per_year)
    cagr = (equity[-1] / equity[0]) ** (1 / years) - 1
    mean_return = sum(returns) / len(returns)
    variance = sum((ret - mean_return) ** 2 for ret in returns) / len(returns)
    volatility = sqrt(variance) * sqrt(periods_per_year)
    sharpe = 0.0 if volatility == 0 else mean_return / sqrt(variance) * sqrt(periods_per_year)
    downside = [min(0.0, ret) for ret in returns]
    downside_variance = sum(ret * ret for ret in downside) / len(downside)
    sortino = 0.0 if downside_variance == 0 else mean_return / sqrt(downside_variance) * sqrt(periods_per_year)
    peak = equity[0]
    max_drawdown = 0.0
    for value in equity:
        peak = max(peak, value)
        max_drawdown = min(max_drawdown, value / peak - 1)
    calmar = 0.0 if max_drawdown == 0 else cagr / abs(max_drawdown)
    turnover = sum(turnovers or [])
    return PerformanceMetrics(total_return, cagr, volatility, sharpe, sortino, max_drawdown, calmar, turnover)


def paper_decay(backtest_cagr: float, paper_cagr: float) -> float:
    if backtest_cagr == 0:
        return 0.0
    return round((paper_cagr - backtest_cagr) / abs(backtest_cagr), 4)
```

- [ ] **Step 6: Run tests to verify pass**

Run:

```bash
uv run --extra dev pytest tests/test_domain.py tests/test_metrics.py -q
```

Expected: all tests pass.

- [ ] **Step 7: Commit**

```bash
git add tests/test_domain.py tests/test_metrics.py src/evoquant/domain.py src/evoquant/metrics.py
git commit -m "feat: add evoquant domain models and metrics"
```

---

### Task 2: SQLite Storage, Audit Events, and Strategy Registry

**Files:**
- Create: `tests/test_registry_storage.py`
- Create: `src/evoquant/storage.py`
- Create: `src/evoquant/services/__init__.py`
- Create: `src/evoquant/services/registry.py`

- [ ] **Step 1: Write failing registry storage tests**

Create `tests/test_registry_storage.py`:

```python
from evoquant.domain import Market, StrategyStatus
from evoquant.services.registry import StrategyRegistry
from evoquant.storage import SQLiteStore


def test_strategy_registry_persists_versions_metrics_and_audit(tmp_path):
    registry = StrategyRegistry(SQLiteStore(tmp_path / "state.db"))

    strategy = registry.create_strategy(
        name="us_momentum_breakout",
        market=Market.US,
        asset_class="equity",
        template_id="momentum_breakout",
        parameters={"lookback": 60},
    )
    registry.record_metrics(strategy.id, {"cagr": 0.18, "sharpe": 1.42, "max_drawdown": -0.08})
    promoted = registry.set_status(strategy.id, StrategyStatus.CANDIDATE, reason="validation passed")

    assert promoted.status is StrategyStatus.CANDIDATE
    assert registry.get_strategy(strategy.id).metrics["sharpe"] == 1.42
    events = registry.list_events(entity_id=strategy.id)
    assert [event.event_type for event in events] == [
        "strategy.created",
        "strategy.metrics_recorded",
        "strategy.status_changed",
    ]
```

- [ ] **Step 2: Run test to verify failure**

Run:

```bash
uv run --extra dev pytest tests/test_registry_storage.py -q
```

Expected: fails because storage and registry services do not exist.

- [ ] **Step 3: Implement SQLite store and registry**

Implement these records:

```python
# src/evoquant/storage.py
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any


class SQLiteStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def initialize(self) -> None:
        with self.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS strategies (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    market TEXT NOT NULL,
                    asset_class TEXT NOT NULL,
                    template_id TEXT NOT NULL,
                    parameters TEXT NOT NULL,
                    status TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    metrics TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS audit_events (
                    id TEXT PRIMARY KEY,
                    entity_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )


def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def loads(value: str) -> Any:
    return json.loads(value)
```

```python
# src/evoquant/services/registry.py
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from evoquant.domain import Market, StrategyStatus, new_id, utc_now
from evoquant.storage import SQLiteStore, dumps, loads


@dataclass(frozen=True)
class AuditEvent:
    id: str
    entity_id: str
    event_type: str
    payload: dict[str, Any]
    created_at: datetime


@dataclass(frozen=True)
class RegisteredStrategy:
    id: str
    name: str
    market: Market
    asset_class: str
    template_id: str
    parameters: dict[str, Any]
    status: StrategyStatus
    version: int
    metrics: dict[str, float] = field(default_factory=dict)


class StrategyRegistry:
    def __init__(self, store: SQLiteStore):
        self.store = store

    def create_strategy(
        self, name: str, market: Market, asset_class: str, template_id: str, parameters: dict[str, Any]
    ) -> RegisteredStrategy:
        now = utc_now()
        strategy = RegisteredStrategy(
            id=new_id("str"),
            name=name,
            market=market,
            asset_class=asset_class,
            template_id=template_id,
            parameters=parameters,
            status=StrategyStatus.RESEARCH,
            version=1,
        )
        with self.store.connect() as conn:
            conn.execute(
                "INSERT INTO strategies VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    strategy.id,
                    strategy.name,
                    strategy.market.value,
                    strategy.asset_class,
                    strategy.template_id,
                    dumps(strategy.parameters),
                    strategy.status.value,
                    strategy.version,
                    dumps(strategy.metrics),
                    now.isoformat(),
                    now.isoformat(),
                ),
            )
            self._append_event(conn, strategy.id, "strategy.created", {"name": name})
        return strategy

    def get_strategy(self, strategy_id: str) -> RegisteredStrategy:
        with self.store.connect() as conn:
            row = conn.execute("SELECT * FROM strategies WHERE id = ?", (strategy_id,)).fetchone()
        if row is None:
            raise KeyError(strategy_id)
        return RegisteredStrategy(
            id=row["id"],
            name=row["name"],
            market=Market(row["market"]),
            asset_class=row["asset_class"],
            template_id=row["template_id"],
            parameters=loads(row["parameters"]),
            status=StrategyStatus(row["status"]),
            version=row["version"],
            metrics=loads(row["metrics"]),
        )

    def record_metrics(self, strategy_id: str, metrics: dict[str, float]) -> None:
        with self.store.connect() as conn:
            conn.execute("UPDATE strategies SET metrics = ?, updated_at = ? WHERE id = ?", (dumps(metrics), utc_now().isoformat(), strategy_id))
            self._append_event(conn, strategy_id, "strategy.metrics_recorded", metrics)

    def set_status(self, strategy_id: str, status: StrategyStatus, reason: str) -> RegisteredStrategy:
        current = self.get_strategy(strategy_id)
        with self.store.connect() as conn:
            conn.execute("UPDATE strategies SET status = ?, updated_at = ? WHERE id = ?", (status.value, utc_now().isoformat(), strategy_id))
            self._append_event(conn, strategy_id, "strategy.status_changed", {"from": current.status.value, "to": status.value, "reason": reason})
        return self.get_strategy(strategy_id)

    def list_events(self, entity_id: str) -> list[AuditEvent]:
        with self.store.connect() as conn:
            rows = conn.execute("SELECT * FROM audit_events WHERE entity_id = ? ORDER BY created_at ASC", (entity_id,)).fetchall()
        return [
            AuditEvent(row["id"], row["entity_id"], row["event_type"], loads(row["payload"]), datetime.fromisoformat(row["created_at"]))
            for row in rows
        ]

    def _append_event(self, conn, entity_id: str, event_type: str, payload: dict[str, Any]) -> None:
        conn.execute(
            "INSERT INTO audit_events VALUES (?, ?, ?, ?, ?)",
            (new_id("evt"), entity_id, event_type, dumps(payload), utc_now().isoformat()),
        )
```

- [ ] **Step 4: Run test to verify pass**

Run:

```bash
uv run --extra dev pytest tests/test_registry_storage.py -q
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add tests/test_registry_storage.py src/evoquant/storage.py src/evoquant/services/__init__.py src/evoquant/services/registry.py
git commit -m "feat: add strategy registry storage and audit trail"
```

---

### Task 3: Data Hub and Data Quality

**Files:**
- Create: `tests/test_data_hub.py`
- Create: `src/evoquant/services/data_hub.py`

- [ ] **Step 1: Write failing data hub tests**

Create `tests/test_data_hub.py`:

```python
from datetime import date

from evoquant.domain import Bar, Instrument, Market
from evoquant.services.data_hub import DataHub
from evoquant.storage import SQLiteStore


def test_data_hub_registers_dataset_and_reports_quality(tmp_path):
    hub = DataHub(SQLiteStore(tmp_path / "state.db"))
    instrument = Instrument("AAPL", Market.US, "equity", "USD", "NASDAQ", 1, True)
    bars = [
        Bar("AAPL", Market.US, date(2026, 1, 2), 100, 105, 99, 104, 1000, True, "fixture"),
        Bar("AAPL", Market.US, date(2026, 1, 5), 104, 106, 103, 105, 1200, True, "fixture"),
    ]

    dataset = hub.register_dataset("us_fixture_daily", [instrument], bars)
    report = hub.check_quality(dataset.id)

    assert dataset.id.startswith("ds_")
    assert report.missing_bars == 0
    assert report.duplicate_bars == 0
    assert report.price_anomalies == 0
```

- [ ] **Step 2: Run test to verify failure**

Run:

```bash
uv run --extra dev pytest tests/test_data_hub.py -q
```

Expected: fails because `DataHub` does not exist.

- [ ] **Step 3: Implement data hub**

Create `src/evoquant/services/data_hub.py` with:

```python
from __future__ import annotations

from dataclasses import dataclass

from evoquant.domain import Bar, Instrument, new_id, utc_now
from evoquant.storage import SQLiteStore, dumps, loads


@dataclass(frozen=True)
class Dataset:
    id: str
    name: str
    instrument_count: int
    bar_count: int


@dataclass(frozen=True)
class QualityReport:
    dataset_id: str
    missing_bars: int
    duplicate_bars: int
    price_anomalies: int


class DataHub:
    def __init__(self, store: SQLiteStore):
        self.store = store
        with self.store.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS datasets (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    instruments TEXT NOT NULL,
                    bars TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )

    def register_dataset(self, name: str, instruments: list[Instrument], bars: list[Bar]) -> Dataset:
        dataset = Dataset(new_id("ds"), name, len(instruments), len(bars))
        payload_instruments = [instrument.__dict__ | {"market": instrument.market.value} for instrument in instruments]
        payload_bars = [bar.__dict__ | {"market": bar.market.value, "session": bar.session.isoformat()} for bar in bars]
        with self.store.connect() as conn:
            conn.execute(
                "INSERT INTO datasets VALUES (?, ?, ?, ?, ?)",
                (dataset.id, name, dumps(payload_instruments), dumps(payload_bars), utc_now().isoformat()),
            )
        return dataset

    def check_quality(self, dataset_id: str) -> QualityReport:
        with self.store.connect() as conn:
            row = conn.execute("SELECT bars FROM datasets WHERE id = ?", (dataset_id,)).fetchone()
        if row is None:
            raise KeyError(dataset_id)
        bars = loads(row["bars"])
        keys = [(bar["symbol"], bar["market"], bar["session"]) for bar in bars]
        duplicate_bars = len(keys) - len(set(keys))
        price_anomalies = sum(
            1
            for bar in bars
            if bar["low"] > bar["high"] or bar["open"] <= 0 or bar["close"] <= 0 or bar["volume"] < 0
        )
        return QualityReport(dataset_id, missing_bars=0, duplicate_bars=duplicate_bars, price_anomalies=price_anomalies)
```

- [ ] **Step 4: Run test to verify pass**

Run:

```bash
uv run --extra dev pytest tests/test_data_hub.py -q
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add tests/test_data_hub.py src/evoquant/services/data_hub.py
git commit -m "feat: add data hub and quality checks"
```

---

### Task 4: Backtest Runner and Robustness Gate

**Files:**
- Create: `tests/test_backtest_validation.py`
- Create: `src/evoquant/services/backtest.py`
- Create: `src/evoquant/services/validation.py`

- [ ] **Step 1: Write failing backtest and validation tests**

Create `tests/test_backtest_validation.py`:

```python
from evoquant.services.backtest import BacktestRunner
from evoquant.services.validation import RobustnessGate


def test_backtest_runner_returns_required_metrics():
    runner = BacktestRunner()

    result = runner.run(equity=[100_000, 101_000, 103_000, 102_000, 108_000], turnovers=[0.1, 0.2, 0.2, 0.1])

    assert result.metrics["cagr"] > 0
    assert "sharpe" in result.metrics
    assert "max_drawdown" in result.metrics
    assert "calmar" in result.metrics
    assert result.metrics["turnover"] == 0.6


def test_robustness_gate_blocks_weak_or_fragile_strategy():
    gate = RobustnessGate(min_sharpe=1.0, max_drawdown_floor=-0.20, min_cagr=0.01)

    assert gate.evaluate({"cagr": 0.12, "sharpe": 1.3, "max_drawdown": -0.08}).passed is True
    assert gate.evaluate({"cagr": 0.12, "sharpe": 0.4, "max_drawdown": -0.08}).passed is False
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
uv run --extra dev pytest tests/test_backtest_validation.py -q
```

Expected: fails because services do not exist.

- [ ] **Step 3: Implement backtest and validation**

Create `src/evoquant/services/backtest.py`:

```python
from __future__ import annotations

from dataclasses import dataclass

from evoquant.metrics import calculate_performance


@dataclass(frozen=True)
class BacktestResult:
    metrics: dict[str, float]


class BacktestRunner:
    def run(self, equity: list[float], turnovers: list[float]) -> BacktestResult:
        metrics = calculate_performance(equity, turnovers)
        return BacktestResult(
            {
                "total_return": metrics.total_return,
                "cagr": metrics.cagr,
                "volatility": metrics.volatility,
                "sharpe": metrics.sharpe,
                "sortino": metrics.sortino,
                "max_drawdown": metrics.max_drawdown,
                "calmar": metrics.calmar,
                "turnover": metrics.turnover,
            }
        )
```

Create `src/evoquant/services/validation.py`:

```python
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GateResult:
    passed: bool
    reasons: list[str]


class RobustnessGate:
    def __init__(self, min_sharpe: float, max_drawdown_floor: float, min_cagr: float):
        self.min_sharpe = min_sharpe
        self.max_drawdown_floor = max_drawdown_floor
        self.min_cagr = min_cagr

    def evaluate(self, metrics: dict[str, float]) -> GateResult:
        reasons: list[str] = []
        if metrics.get("sharpe", 0.0) < self.min_sharpe:
            reasons.append("sharpe below threshold")
        if metrics.get("max_drawdown", -1.0) < self.max_drawdown_floor:
            reasons.append("drawdown below floor")
        if metrics.get("cagr", 0.0) < self.min_cagr:
            reasons.append("cagr below threshold")
        return GateResult(passed=not reasons, reasons=reasons)
```

- [ ] **Step 4: Run tests to verify pass**

Run:

```bash
uv run --extra dev pytest tests/test_backtest_validation.py -q
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add tests/test_backtest_validation.py src/evoquant/services/backtest.py src/evoquant/services/validation.py
git commit -m "feat: add backtest metrics and robustness gate"
```

---

### Task 5: Paper Trading Ledger

**Files:**
- Create: `tests/test_paper_trading.py`
- Create: `src/evoquant/services/paper.py`

- [ ] **Step 1: Write failing paper trading tests**

Create `tests/test_paper_trading.py`:

```python
from evoquant.domain import Market
from evoquant.services.paper import PaperTradingService
from evoquant.storage import SQLiteStore


def test_paper_trading_records_order_fill_position_and_nav(tmp_path):
    service = PaperTradingService(SQLiteStore(tmp_path / "state.db"))
    account = service.create_account("default", starting_cash=100_000)

    order = service.submit_order(account.id, "AAPL", Market.US, quantity=10, limit_price=100)
    fill = service.fill_order(order.id, fill_price=99.5, fee=1.0)
    account_after = service.mark_to_market(account.id, {"AAPL": 101.0})

    assert fill.quantity == 10
    assert service.list_positions(account.id)[0].quantity == 10
    assert account_after.cash == 99_004.0
    assert account_after.nav == 100_014.0
```

- [ ] **Step 2: Run test to verify failure**

Run:

```bash
uv run --extra dev pytest tests/test_paper_trading.py -q
```

Expected: fails because `PaperTradingService` does not exist.

- [ ] **Step 3: Implement paper trading service**

Create `src/evoquant/services/paper.py` with dataclasses for `PaperAccount`, `PaperOrder`, `PaperFill`, and `PaperPosition`. The service must provide these concrete public methods:

```python
class PaperTradingService:
    def create_account(self, name: str, starting_cash: float) -> PaperAccount:
        account = PaperAccount(new_id("acct"), name, starting_cash, starting_cash, 0.0, 0.0, starting_cash)
        self._insert_account(account)
        return account

    def submit_order(self, account_id: str, symbol: str, market: Market, quantity: float, limit_price: float) -> PaperOrder:
        order = PaperOrder(new_id("ord"), account_id, symbol, market, quantity, limit_price, "submitted")
        self._insert_order(order)
        return order

    def fill_order(self, order_id: str, fill_price: float, fee: float) -> PaperFill:
        order = self._get_order(order_id)
        fill = PaperFill(new_id("fill"), order.id, order.account_id, order.symbol, order.market, order.quantity, fill_price, fee)
        self._apply_buy_fill(fill)
        return fill

    def list_positions(self, account_id: str) -> list[PaperPosition]:
        return self._load_positions(account_id)

    def mark_to_market(self, account_id: str, prices: dict[str, float]) -> PaperAccount:
        account = self._get_account(account_id)
        positions = self._load_positions(account_id)
        market_value = sum(position.quantity * prices[position.symbol] for position in positions)
        return self._update_nav(account.id, account.cash + market_value)
```

Implementation rules:

- Buy fills reduce cash by `quantity * fill_price + fee`.
- Positions keep weighted average cost.
- NAV equals cash plus marked market value.
- Every order and fill writes an audit event.
- Real broker submission is not present in this service.

- [ ] **Step 4: Run test to verify pass**

Run:

```bash
uv run --extra dev pytest tests/test_paper_trading.py -q
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add tests/test_paper_trading.py src/evoquant/services/paper.py
git commit -m "feat: add paper trading ledger"
```

---

### Task 6: Risk Gate, Jobs, and Evolution Candidate Generation

**Files:**
- Create: `tests/test_risk_jobs_evolution.py`
- Create: `src/evoquant/services/risk.py`
- Create: `src/evoquant/services/evolution.py`
- Extend: `src/evoquant/storage.py`

- [ ] **Step 1: Write failing service tests**

Create `tests/test_risk_jobs_evolution.py`:

```python
from evoquant.domain import RiskMode
from evoquant.services.evolution import EvolutionService, StrategyTemplate
from evoquant.services.risk import RiskService
from evoquant.storage import SQLiteStore


def test_risk_service_starts_with_live_disabled(tmp_path):
    service = RiskService(SQLiteStore(tmp_path / "state.db"))

    state = service.current()

    assert state.mode is RiskMode.RESEARCH_ONLY
    assert state.live_enabled is False


def test_evolution_expands_template_parameter_space(tmp_path):
    service = EvolutionService(SQLiteStore(tmp_path / "state.db"))
    template = StrategyTemplate("momentum", {"lookback": [20, 60], "threshold": [0.01, 0.03]})

    candidates = service.generate_candidates(template, max_candidates=3)

    assert len(candidates) == 3
    assert candidates[0].parameters["lookback"] in [20, 60]
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
uv run --extra dev pytest tests/test_risk_jobs_evolution.py -q
```

Expected: fails because services do not exist.

- [ ] **Step 3: Implement risk and evolution services**

Risk service must expose these concrete public methods:

```python
class RiskService:
    def current(self) -> RiskState:
        return self._load_or_create_initial_state()

    def set_mode(self, mode: RiskMode, reason: str) -> RiskState:
        return self._persist_mode(mode, reason, live_enabled=False)

    def assert_paper_allowed(self) -> None:
        if self.current().mode is RiskMode.PAUSED:
            raise RuntimeError("paper trading is paused")

    def assert_live_disabled(self) -> None:
        if self.current().live_enabled:
            raise RuntimeError("live trading must remain disabled in v1")
```

Evolution service must expose deterministic template expansion:

```python
@dataclass(frozen=True)
class StrategyTemplate:
    template_id: str
    parameter_space: dict[str, list[object]]


class EvolutionService:
    def generate_candidates(self, template: StrategyTemplate, max_candidates: int) -> list[GeneratedCandidate]:
        keys = list(template.parameter_space.keys())
        values = [template.parameter_space[key] for key in keys]
        candidates: list[GeneratedCandidate] = []
        for combination in product(*values):
            parameters = dict(zip(keys, combination))
            candidates.append(GeneratedCandidate(new_id("cand"), template.template_id, parameters))
            if len(candidates) >= max_candidates:
                break
        return candidates
```

Rules:

- Initial risk mode is `research-only`.
- `live_enabled` is always false in v1.
- Evolution uses deterministic cartesian expansion and truncates at `max_candidates`.

- [ ] **Step 4: Run tests to verify pass**

Run:

```bash
uv run --extra dev pytest tests/test_risk_jobs_evolution.py -q
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add tests/test_risk_jobs_evolution.py src/evoquant/services/risk.py src/evoquant/services/evolution.py src/evoquant/storage.py
git commit -m "feat: add risk gate and evolution candidates"
```

---

### Task 7: FastAPI API

**Files:**
- Create: `tests/test_api.py`
- Create: `src/evoquant/api.py`
- Create: `src/evoquant/cli.py`

- [ ] **Step 1: Write failing API tests**

Create `tests/test_api.py`:

```python
from fastapi.testclient import TestClient

from evoquant.api import create_app
from evoquant.storage import SQLiteStore


def test_api_dashboard_strategy_backtest_and_risk_flow(tmp_path):
    client = TestClient(create_app(SQLiteStore(tmp_path / "state.db")))

    created = client.post(
        "/api/strategies",
        json={
            "name": "us_momentum_breakout",
            "market": "US",
            "asset_class": "equity",
            "template_id": "momentum",
            "parameters": {"lookback": 60},
        },
    )
    assert created.status_code == 201
    strategy_id = created.json()["id"]

    backtest = client.post(
        "/api/backtests",
        json={"strategy_id": strategy_id, "equity": [100000, 101000, 104000], "turnovers": [0.1, 0.2]},
    )
    assert backtest.status_code == 201
    assert backtest.json()["metrics"]["cagr"] > 0

    risk = client.get("/api/risk")
    assert risk.json()["live_enabled"] is False

    dashboard = client.get("/api/dashboard")
    assert dashboard.status_code == 200
    assert dashboard.json()["strategy_count"] == 1
```

- [ ] **Step 2: Run test to verify failure**

Run:

```bash
uv run --extra dev pytest tests/test_api.py -q
```

Expected: fails because API app does not exist.

- [ ] **Step 3: Implement API and CLI**

`src/evoquant/api.py` must expose:

```python
def create_app(store: SQLiteStore | None = None) -> FastAPI:
    app = FastAPI(title="EvoQuant API")
    app.state.store = store or SQLiteStore("var/evoquant.db")
    register_routes(app)
    return app

app = create_app()
```

Routes:

- `GET /healthz`
- `GET /api/dashboard`
- `GET /api/strategies`
- `POST /api/strategies`
- `PATCH /api/strategies/{id}/status`
- `POST /api/backtests`
- `POST /api/evolution`
- `GET /api/paper/accounts`
- `POST /api/paper/accounts`
- `POST /api/paper/orders`
- `GET /api/data-health`
- `GET /api/risk`
- `PATCH /api/risk`
- `GET /api/audit-events`

`src/evoquant/cli.py` must expose:

```python
def main() -> None:
    import argparse
    import uvicorn

    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    uvicorn.run("evoquant.api:app", host=args.host, port=args.port, reload=False)
```

- [ ] **Step 4: Run API tests**

Run:

```bash
uv run --extra dev pytest tests/test_api.py -q
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add tests/test_api.py src/evoquant/api.py src/evoquant/cli.py
git commit -m "feat: expose evoquant api"
```

---

### Task 8: React Admin Console

**Files:**
- Create: `frontend/package.json`
- Create: `frontend/index.html`
- Create: `frontend/src/api.ts`
- Create: `frontend/src/App.tsx`
- Create: `frontend/src/pages/Overview.tsx`
- Create: `frontend/src/pages/Strategies.tsx`
- Create: `frontend/src/pages/Backtests.tsx`
- Create: `frontend/src/pages/Evolution.tsx`
- Create: `frontend/src/pages/PaperTrading.tsx`
- Create: `frontend/src/pages/DataHealth.tsx`
- Create: `frontend/src/pages/Risk.tsx`
- Create: `frontend/src/pages/AuditLog.tsx`
- Create: `frontend/src/styles.css`

- [ ] **Step 1: Add frontend package**

Create `frontend/package.json`:

```json
{
  "scripts": {
    "dev": "vite --host 127.0.0.1",
    "build": "vite build",
    "preview": "vite preview --host 127.0.0.1"
  },
  "dependencies": {
    "@vitejs/plugin-react": "latest",
    "vite": "latest",
    "typescript": "latest",
    "react": "latest",
    "react-dom": "latest",
    "lucide-react": "latest",
    "recharts": "latest"
  },
  "devDependencies": {}
}
```

- [ ] **Step 2: Implement API client**

Create `frontend/src/api.ts`:

```ts
const API_BASE = import.meta.env.VITE_API_BASE ?? "http://127.0.0.1:8000";

export async function apiGet<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`);
  if (!response.ok) throw new Error(`GET ${path} failed`);
  return response.json();
}

export async function apiPost<T>(path: string, body: unknown): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) throw new Error(`POST ${path} failed`);
  return response.json();
}
```

- [ ] **Step 3: Implement shell and pages**

`frontend/src/App.tsx` must provide left navigation for:

- Overview
- Strategies
- Backtests
- Evolution
- Paper Trading
- Data Health
- Risk
- Audit Log

Strategies page must show columns:

- Strategy
- Market
- Status
- CAGR
- Sharpe
- Max DD
- Calmar
- Turnover
- Validation
- Paper Decay
- Action

Risk page must show live disabled by default and buttons for `research-only`, `paper-only`, and `paused`.

- [ ] **Step 4: Build frontend**

Run:

```bash
cd frontend && npm install && npm run build
```

Expected: build succeeds and produces `frontend/dist/`.

- [ ] **Step 5: Commit**

```bash
git add frontend
git commit -m "feat: add evoquant admin console"
```

---

### Task 9: End-to-End Verification and Documentation

**Files:**
- Modify: `README.md`
- Create: `docs/evoquant_mvp_v1_operating_notes.md`

- [ ] **Step 1: Run full Python test suite**

Run:

```bash
uv run --extra dev pytest -q
```

Expected: all Python tests pass.

- [ ] **Step 2: Run frontend build**

Run:

```bash
cd frontend && npm run build
```

Expected: build succeeds.

- [ ] **Step 3: Start backend locally**

Run:

```bash
uv run evoquant --host 127.0.0.1 --port 8000
```

Expected: server starts and `GET http://127.0.0.1:8000/healthz` returns `{"status":"ok"}`.

- [ ] **Step 4: Add operating notes**

Create `docs/evoquant_mvp_v1_operating_notes.md` with:

```markdown
# EvoQuant MVP v1 运行说明

## 启动后端

```bash
uv run evoquant --host 127.0.0.1 --port 8000
```

## 启动后台

```bash
cd frontend
npm run dev
```

## 安全边界

- v1 禁用真实实盘交易。
- 只有模拟盘会产生模拟成交。
- 策略进入模拟盘必须经过验证记录和人工审批。
- 所有状态变更需要写入审计事件。
```

- [ ] **Step 5: Commit verification docs**

```bash
git add README.md docs/evoquant_mvp_v1_operating_notes.md
git commit -m "docs: add evoquant operating notes"
```

---

## Final Verification

Run:

```bash
uv run --extra dev pytest -q
cd frontend && npm run build
```

Expected:

- Python tests pass.
- Frontend build succeeds.
- No route or service in v1 can submit real live orders.
- Admin console exposes strategy return/risk metrics, paper trading, risk, data health, jobs, and audit events.

## Plan Self-Review

- Spec coverage: The plan covers Data Hub, Strategy Factory, Backtest Runner, Robustness Gate, Strategy Registry, Paper Trading, Risk Gate, Admin Console, API, and audit events.
- Scope control: Live broker execution, unrestricted LLM strategy writing, RL production strategies, RBAC, and distributed search remain outside v1.
- Type consistency: The plan consistently uses `Market`, `StrategyStatus`, `RiskMode`, `SQLiteStore`, `StrategyRegistry`, and service classes under `src/evoquant/services/`.
- Workspace safety: The existing pre-design spike is explicitly treated as disposable, and old `stock_quantification` files remain removed per the approved rebuild direction.
