# EvoQuant MVP v2 真实信号闭环 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 构建真实数据驱动的美股/A股多市场信号闭环：免费数据源同步、本地缓存、横截面动量信号、扫描快照、模拟盘订单草稿、真实回测和后台 Signals 页面。

**Architecture:** 在现有 v1 基础上增加清晰边界的服务模块：`market_data` 负责 provider 与缓存，`market_rules` 负责市场交易规则，`strategies` 输出标准信号，`signals` 负责扫描快照，`drafts` 负责模拟盘订单草稿，`backtest` 从样例 equity 扩展到真实 bars。FastAPI 只编排服务，不承载策略逻辑；前端继续保持运营台风格，新增 Signals 页面并增强 Data Health、Backtests、Paper Trading。

**Tech Stack:** Python 3.11+、FastAPI、Pydantic、SQLite、pytest、yfinance、AKShare、React、Vite、TypeScript、Recharts。

---

## File Structure

新增或修改的主要文件：

- Modify: `pyproject.toml` — 增加 `market-data` optional extra，包含 yfinance、akshare、pandas。
- Modify: `src/evoquant/domain.py` — 增加 `SignalSide`、`OrderDraftStatus`、`TimeFrame` 等枚举。
- Create: `src/evoquant/services/instruments.py` — instrument master 存储、CSV 中文名覆盖、指数成分缓存。
- Create: `src/evoquant/services/market_rules.py` — 美股/A股交易成本、滑点、A 股 T+1、lot size、涨跌停规则。
- Create: `src/evoquant/services/market_data.py` — bars schema、本地缓存、同步 job、覆盖率、质量报告。
- Create: `src/evoquant/providers/base.py` — `MarketDataProvider` 协议和 provider 数据结构。
- Create: `src/evoquant/providers/csv.py` — CSV provider，供测试和本地导入使用。
- Create: `src/evoquant/providers/yahoo.py` — yfinance provider。
- Create: `src/evoquant/providers/akshare.py` — AKShare provider。
- Create: `src/evoquant/services/strategies.py` — 策略接口、`cross_sectional_momentum`、score/risk reason。
- Create: `src/evoquant/services/signals.py` — scan 执行、scan snapshot、scan results 查询。
- Create: `src/evoquant/services/drafts.py` — 从 signals 生成模拟盘订单草稿、approve/cancel/submit lifecycle。
- Modify: `src/evoquant/services/backtest.py` — 保留现有 equity metrics，同时增加真实 bar/signal 回测入口。
- Create: `src/evoquant/services/scheduler.py` — 本地轻量 schedule 配置和下一次运行时间计算。
- Modify: `src/evoquant/api.py` — 增加 data sync、signals、drafts、real backtest、schedule API。
- Create: `tests/test_market_data.py`
- Create: `tests/test_market_rules.py`
- Create: `tests/test_strategies_signals.py`
- Create: `tests/test_order_drafts.py`
- Create: `tests/test_real_backtest.py`
- Modify: `tests/test_api.py`
- Modify: `frontend/src/App.tsx` — 增加 Signals 导航。
- Create: `frontend/src/pages/Signals.tsx`
- Modify: `frontend/src/pages/DataHealth.tsx`
- Modify: `frontend/src/pages/Backtests.tsx`
- Modify: `frontend/src/pages/PaperTrading.tsx`
- Modify: `frontend/src/api.ts`
- Modify: `frontend/src/styles.css`
- Modify: `README.md`
- Modify: `docs/evoquant_mvp_v1_operating_notes.md`
- Create: `docs/evoquant_mvp_v2_data_sources.md`

---

### Task 1: Dependencies, Domain Types, and Storage Foundations

**Files:**
- Modify: `pyproject.toml`
- Modify: `src/evoquant/domain.py`
- Modify: `src/evoquant/storage.py`
- Create: `tests/test_domain_v2.py`
- Create: `tests/test_storage_v2.py`

- [ ] **Step 1: Write failing domain tests**

Create `tests/test_domain_v2.py`:

```python
from evoquant.domain import Market, OrderDraftStatus, SignalSide, TimeFrame


def test_v2_signal_and_draft_enums_are_stable():
    assert SignalSide.BUY.value == "buy"
    assert SignalSide.HOLD.value == "hold"
    assert SignalSide.SELL.value == "sell"
    assert OrderDraftStatus.DRAFT.value == "draft"
    assert OrderDraftStatus.BLOCKED.value == "blocked"
    assert TimeFrame.DAILY.value == "1d"


def test_existing_markets_remain_supported():
    assert {market.value for market in Market} == {"US", "CN", "CRYPTO"}
```

- [ ] **Step 2: Write failing storage schema tests**

Create `tests/test_storage_v2.py`:

```python
from evoquant.storage import SQLiteStore


def test_v2_tables_are_initialized(tmp_path):
    store = SQLiteStore(tmp_path / "state.db")

    with store.connection() as conn:
        rows = conn.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table'
            ORDER BY name
            """
        ).fetchall()

    table_names = {row["name"] for row in rows}
    assert {
        "instruments",
        "market_bars",
        "market_sync_jobs",
        "market_quality_reports",
        "signal_scans",
        "signal_results",
        "paper_order_drafts",
        "schedule_configs",
    }.issubset(table_names)
```

- [ ] **Step 3: Run tests and verify they fail**

Run:

```bash
uv run --extra dev pytest tests/test_domain_v2.py tests/test_storage_v2.py -q
```

Expected: fails because enums and v2 tables do not exist.

- [ ] **Step 4: Add optional market-data dependencies**

Modify `pyproject.toml`:

```toml
[project.optional-dependencies]
dev = [
    "pytest>=8.2",
    "httpx>=0.27",
]
market-data = [
    "yfinance>=0.2",
    "akshare>=1.16",
    "pandas>=2.2",
]
```

Keep the existing `dev` extra and add `market-data` without forcing network libraries into the default install.

- [ ] **Step 5: Add v2 enums**

Modify `src/evoquant/domain.py`:

```python
class SignalSide(str, Enum):
    BUY = "buy"
    HOLD = "hold"
    SELL = "sell"


class OrderDraftStatus(str, Enum):
    DRAFT = "draft"
    APPROVED = "approved"
    CANCELLED = "cancelled"
    SUBMITTED = "submitted"
    BLOCKED = "blocked"


class TimeFrame(str, Enum):
    DAILY = "1d"
```

- [ ] **Step 6: Add v2 SQLite tables**

Extend `SQLiteStore.initialize()` in `src/evoquant/storage.py` with these tables:

```sql
CREATE TABLE IF NOT EXISTS instruments (
    symbol TEXT NOT NULL,
    market TEXT NOT NULL,
    name TEXT NOT NULL,
    name_zh TEXT NOT NULL,
    exchange TEXT NOT NULL,
    currency TEXT NOT NULL,
    sector TEXT NOT NULL,
    index_membership TEXT NOT NULL,
    tradable INTEGER NOT NULL,
    lot_size INTEGER NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (symbol, market)
);
CREATE TABLE IF NOT EXISTS market_bars (
    symbol TEXT NOT NULL,
    market TEXT NOT NULL,
    session TEXT NOT NULL,
    open REAL NOT NULL,
    high REAL NOT NULL,
    low REAL NOT NULL,
    close REAL NOT NULL,
    volume REAL NOT NULL,
    amount REAL NOT NULL,
    adjusted INTEGER NOT NULL,
    suspended INTEGER NOT NULL,
    limit_up INTEGER NOT NULL,
    limit_down INTEGER NOT NULL,
    source TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (symbol, market, session)
);
CREATE TABLE IF NOT EXISTS market_sync_jobs (
    id TEXT PRIMARY KEY,
    market TEXT NOT NULL,
    provider TEXT NOT NULL,
    status TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    total_symbols INTEGER NOT NULL,
    success_symbols INTEGER NOT NULL,
    failed_symbols INTEGER NOT NULL,
    coverage REAL NOT NULL,
    failures TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS market_quality_reports (
    id TEXT PRIMARY KEY,
    sync_job_id TEXT NOT NULL,
    market TEXT NOT NULL,
    missing_bars INTEGER NOT NULL,
    duplicate_bars INTEGER NOT NULL,
    price_anomalies INTEGER NOT NULL,
    suspended_count INTEGER NOT NULL,
    limit_up_count INTEGER NOT NULL,
    limit_down_count INTEGER NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS signal_scans (
    id TEXT PRIMARY KEY,
    strategy_template TEXT NOT NULL,
    parameters TEXT NOT NULL,
    market_scope TEXT NOT NULL,
    as_of_date TEXT NOT NULL,
    coverage TEXT NOT NULL,
    status TEXT NOT NULL,
    error_message TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS signal_results (
    scan_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    market TEXT NOT NULL,
    name TEXT NOT NULL,
    name_zh TEXT NOT NULL,
    close REAL NOT NULL,
    signal TEXT NOT NULL,
    score REAL NOT NULL,
    target_weight REAL NOT NULL,
    reason TEXT NOT NULL,
    risk_flags TEXT NOT NULL,
    as_of_date TEXT NOT NULL,
    rank INTEGER NOT NULL,
    PRIMARY KEY (scan_id, symbol, market)
);
CREATE TABLE IF NOT EXISTS paper_order_drafts (
    id TEXT PRIMARY KEY,
    scan_id TEXT NOT NULL,
    account_id TEXT NOT NULL,
    strategy_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    market TEXT NOT NULL,
    side TEXT NOT NULL,
    target_weight REAL NOT NULL,
    current_weight REAL NOT NULL,
    estimated_quantity REAL NOT NULL,
    reference_price REAL NOT NULL,
    reason TEXT NOT NULL,
    risk_flags TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS schedule_configs (
    id TEXT PRIMARY KEY,
    market TEXT NOT NULL,
    enabled INTEGER NOT NULL,
    timezone TEXT NOT NULL,
    run_time TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
```

- [ ] **Step 7: Run focused tests**

Run:

```bash
uv run --extra dev pytest tests/test_domain_v2.py tests/test_storage_v2.py -q
```

Expected: passes.

- [ ] **Step 8: Commit**

```bash
git add pyproject.toml src/evoquant/domain.py src/evoquant/storage.py tests/test_domain_v2.py tests/test_storage_v2.py
git commit -m "feat: add v2 domain and storage foundations"
```

---

### Task 2: Instrument Master and Market Data Providers

**Files:**
- Create: `src/evoquant/providers/__init__.py`
- Create: `src/evoquant/providers/base.py`
- Create: `src/evoquant/providers/csv.py`
- Create: `src/evoquant/providers/yahoo.py`
- Create: `src/evoquant/providers/akshare.py`
- Create: `src/evoquant/services/instruments.py`
- Create: `tests/test_instruments_providers.py`

- [ ] **Step 1: Write failing provider and instrument tests**

Create `tests/test_instruments_providers.py`:

```python
from datetime import date
from pathlib import Path

from evoquant.domain import Market
from evoquant.providers.csv import CsvMarketDataProvider
from evoquant.services.instruments import InstrumentMaster, InstrumentRecord
from evoquant.storage import SQLiteStore


def test_instrument_master_upserts_and_prefers_chinese_name(tmp_path):
    store = SQLiteStore(tmp_path / "state.db")
    master = InstrumentMaster(store)

    master.upsert_many([
        InstrumentRecord(
            symbol="AAPL",
            market=Market.US,
            name="Apple Inc.",
            name_zh="苹果公司",
            exchange="NASDAQ",
            currency="USD",
            sector="Technology",
            index_membership="SP500",
            tradable=True,
            lot_size=1,
        )
    ])

    listed = master.list_by_market(Market.US)

    assert len(listed) == 1
    assert listed[0].symbol == "AAPL"
    assert listed[0].name_zh == "苹果公司"


def test_csv_market_data_provider_reads_instruments_and_bars(tmp_path):
    instruments = tmp_path / "instruments.csv"
    bars = tmp_path / "bars.csv"
    instruments.write_text(
        "symbol,market,name,name_zh,exchange,currency,sector,index_membership,tradable,lot_size\n"
        "AAPL,US,Apple Inc.,苹果公司,NASDAQ,USD,Technology,SP500,true,1\n",
        encoding="utf-8",
    )
    bars.write_text(
        "symbol,market,date,open,high,low,close,volume,amount,adjusted,suspended,limit_up,limit_down\n"
        "AAPL,US,2026-01-02,100,105,99,104,1000000,104000000,true,false,false,false\n",
        encoding="utf-8",
    )

    provider = CsvMarketDataProvider(instruments_path=instruments, bars_path=bars)

    loaded_instruments = provider.sync_instruments("SP500")
    loaded_bars = provider.sync_bars(["AAPL"], Market.US, date(2026, 1, 1), date(2026, 1, 31))

    assert loaded_instruments[0].name_zh == "苹果公司"
    assert loaded_bars[0].close == 104.0
    assert loaded_bars[0].amount == 104000000.0
```

- [ ] **Step 2: Run test and verify it fails**

Run:

```bash
uv run --extra dev pytest tests/test_instruments_providers.py -q
```

Expected: fails because provider and instrument modules do not exist.

- [ ] **Step 3: Add provider data structures**

Create `src/evoquant/providers/base.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Protocol

from evoquant.domain import Market


@dataclass(frozen=True)
class ProviderInstrument:
    symbol: str
    market: Market
    name: str
    name_zh: str
    exchange: str
    currency: str
    sector: str
    index_membership: str
    tradable: bool
    lot_size: int


@dataclass(frozen=True)
class ProviderBar:
    symbol: str
    market: Market
    session: date
    open: float
    high: float
    low: float
    close: float
    volume: float
    amount: float
    adjusted: bool
    suspended: bool
    limit_up: bool
    limit_down: bool
    source: str


class MarketDataProvider(Protocol):
    name: str

    def sync_instruments(self, index_id: str) -> list[ProviderInstrument]:
        raise NotImplementedError

    def sync_bars(
        self, symbols: list[str], market: Market, start: date, end: date, timeframe: str = "1d"
    ) -> list[ProviderBar]:
        raise NotImplementedError
```

Create `src/evoquant/providers/__init__.py` that exports these names.

- [ ] **Step 4: Implement InstrumentMaster**

Create `src/evoquant/services/instruments.py` with:

```python
from __future__ import annotations

from dataclasses import dataclass

from evoquant.domain import Market, utc_now
from evoquant.storage import SQLiteStore


@dataclass(frozen=True)
class InstrumentRecord:
    symbol: str
    market: Market
    name: str
    name_zh: str
    exchange: str
    currency: str
    sector: str
    index_membership: str
    tradable: bool
    lot_size: int


class InstrumentMaster:
    def __init__(self, store: SQLiteStore):
        self.store = store

    def upsert_many(self, instruments: list[InstrumentRecord]) -> None:
        now = utc_now().isoformat()
        with self.store.connection() as conn:
            conn.executemany(
                """
                INSERT INTO instruments (
                    symbol, market, name, name_zh, exchange, currency, sector,
                    index_membership, tradable, lot_size, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol, market) DO UPDATE SET
                    name = excluded.name,
                    name_zh = excluded.name_zh,
                    exchange = excluded.exchange,
                    currency = excluded.currency,
                    sector = excluded.sector,
                    index_membership = excluded.index_membership,
                    tradable = excluded.tradable,
                    lot_size = excluded.lot_size,
                    updated_at = excluded.updated_at
                """,
                [
                    (
                        item.symbol,
                        item.market.value,
                        item.name,
                        item.name_zh,
                        item.exchange,
                        item.currency,
                        item.sector,
                        item.index_membership,
                        1 if item.tradable else 0,
                        item.lot_size,
                        now,
                    )
                    for item in instruments
                ],
            )

    def list_by_market(self, market: Market) -> list[InstrumentRecord]:
        with self.store.connection() as conn:
            rows = conn.execute(
                """
                SELECT symbol, market, name, name_zh, exchange, currency, sector,
                       index_membership, tradable, lot_size
                FROM instruments
                WHERE market = ?
                ORDER BY symbol ASC
                """,
                (market.value,),
            ).fetchall()
        return [
            InstrumentRecord(
                symbol=row["symbol"],
                market=Market(row["market"]),
                name=row["name"],
                name_zh=row["name_zh"],
                exchange=row["exchange"],
                currency=row["currency"],
                sector=row["sector"],
                index_membership=row["index_membership"],
                tradable=bool(row["tradable"]),
                lot_size=int(row["lot_size"]),
            )
            for row in rows
        ]
```

- [ ] **Step 5: Implement CsvMarketDataProvider**

Create `src/evoquant/providers/csv.py` with `csv.DictReader`, parse booleans from `true/false/1/0/yes/no`, and return `ProviderInstrument` and `ProviderBar`. Filter bars by symbol, market, start, and end.

- [ ] **Step 6: Add yfinance and AKShare provider shells**

Create `src/evoquant/providers/yahoo.py`:

```python
from __future__ import annotations

from datetime import date

from evoquant.domain import Market
from evoquant.providers.base import ProviderBar, ProviderInstrument


class YahooFinanceProvider:
    name = "yfinance"

    def sync_instruments(self, index_id: str) -> list[ProviderInstrument]:
        raise NotImplementedError("S&P 500 instrument sync is implemented in Task 3")

    def sync_bars(
        self, symbols: list[str], market: Market, start: date, end: date, timeframe: str = "1d"
    ) -> list[ProviderBar]:
        raise NotImplementedError("Yahoo bar sync is implemented in Task 3")
```

Create `src/evoquant/providers/akshare.py` with the same shell class `AkshareProvider`.

- [ ] **Step 7: Run focused tests**

Run:

```bash
uv run --extra dev pytest tests/test_instruments_providers.py -q
```

Expected: passes.

- [ ] **Step 8: Commit**

```bash
git add src/evoquant/providers src/evoquant/services/instruments.py tests/test_instruments_providers.py
git commit -m "feat: add instrument master and provider interfaces"
```

---

### Task 3: Market Data Cache, Incremental Sync, and Quality Reports

**Files:**
- Create: `src/evoquant/services/market_data.py`
- Modify: `src/evoquant/providers/yahoo.py`
- Modify: `src/evoquant/providers/akshare.py`
- Create: `tests/test_market_data.py`

- [ ] **Step 1: Write failing market data cache tests**

Create `tests/test_market_data.py`:

```python
from datetime import date

from evoquant.domain import Market
from evoquant.providers.base import ProviderBar, ProviderInstrument
from evoquant.services.market_data import MarketDataService
from evoquant.storage import SQLiteStore


class FakeProvider:
    name = "fake"

    def __init__(self, bars: list[ProviderBar], instruments: list[ProviderInstrument] | None = None):
        self.bars = bars
        self.instruments = instruments or []
        self.calls = []

    def sync_instruments(self, index_id: str) -> list[ProviderInstrument]:
        return self.instruments

    def sync_bars(self, symbols, market, start, end, timeframe="1d"):
        self.calls.append((tuple(symbols), market, start, end, timeframe))
        return [
            bar
            for bar in self.bars
            if bar.symbol in symbols and bar.market is market and start <= bar.session <= end
        ]


def _bar(symbol: str, session: date, close: float = 10.0) -> ProviderBar:
    return ProviderBar(
        symbol=symbol,
        market=Market.US,
        session=session,
        open=close - 1,
        high=close + 1,
        low=close - 2,
        close=close,
        volume=1000,
        amount=close * 1000,
        adjusted=True,
        suspended=False,
        limit_up=False,
        limit_down=False,
        source="fake",
    )


def test_sync_bars_records_coverage_and_persists_bars(tmp_path):
    service = MarketDataService(SQLiteStore(tmp_path / "state.db"))
    provider = FakeProvider([_bar("AAPL", date(2026, 1, 2))])

    job = service.sync_bars(provider, ["AAPL", "MSFT"], Market.US, date(2026, 1, 1), date(2026, 1, 5))
    bars = service.list_bars(Market.US, ["AAPL"], date(2026, 1, 1), date(2026, 1, 5))

    assert job.total_symbols == 2
    assert job.success_symbols == 1
    assert job.failed_symbols == 1
    assert job.coverage == 0.5
    assert bars[0].symbol == "AAPL"
    assert bars[0].close == 10.0


def test_incremental_sync_starts_after_latest_cached_date(tmp_path):
    service = MarketDataService(SQLiteStore(tmp_path / "state.db"))
    initial_provider = FakeProvider([_bar("AAPL", date(2026, 1, 2))])
    update_provider = FakeProvider([_bar("AAPL", date(2026, 1, 3), close=11.0)])

    service.sync_bars(initial_provider, ["AAPL"], Market.US, date(2026, 1, 1), date(2026, 1, 2))
    service.incremental_sync(update_provider, ["AAPL"], Market.US, end=date(2026, 1, 3))

    assert update_provider.calls[0][2] == date(2026, 1, 3)
    bars = service.list_bars(Market.US, ["AAPL"], date(2026, 1, 1), date(2026, 1, 3))
    assert [bar.close for bar in bars] == [10.0, 11.0]
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
uv run --extra dev pytest tests/test_market_data.py -q
```

Expected: fails because `MarketDataService` does not exist.

- [ ] **Step 3: Implement market data dataclasses and sync service**

Create `src/evoquant/services/market_data.py` with:

- `MarketBar`
- `SyncJob`
- `QualitySummary`
- `MarketDataService.sync_bars()`
- `MarketDataService.incremental_sync()`
- `MarketDataService.list_bars()`
- `MarketDataService.latest_session()`
- `MarketDataService.quality_report()`

Implementation requirements:

- Upsert bars by `(symbol, market, session)`.
- Compute success by distinct symbols with at least one returned bar.
- Failures are requested symbols without returned bars.
- Coverage is `success_symbols / total_symbols`, or `0.0` when no symbols.
- Incremental sync starts from latest cached date + 1 calendar day. Trading-calendar precision comes later; missing sessions are handled by quality reports.
- Quality report counts duplicate rows as 0 because table primary key prevents duplicates; count OHLC anomalies, suspended rows, limit up rows, limit down rows from cached bars.

- [ ] **Step 4: Implement real provider adapters behind optional imports**

Modify `src/evoquant/providers/yahoo.py`:

- Import yfinance inside methods, not at module import time.
- Convert yfinance daily OHLCV rows into `ProviderBar`.
- `amount` is `close * volume` when provider does not return amount.
- Only support `Market.US`; raise `ValueError` for other markets.

Modify `src/evoquant/providers/akshare.py`:

- Import akshare inside methods, not at module import time.
- Implement 沪深300成分同步 using AKShare `index_stock_cons_csindex(symbol="000300")` when available; if the installed AKShare build does not expose that function, raise a clear `RuntimeError` that names the missing function.
- Implement A 股日线 sync using adjusted daily data.
- Convert A 股 symbols into the local symbol convention used by instruments.
- Set `limit_up`, `limit_down`, and `suspended` from available provider fields when present; default to `False` when unavailable and record this limitation in docs later.

Tests for these methods must use fake monkeypatched modules or fake clients and must not hit network.

- [ ] **Step 5: Run focused tests**

Run:

```bash
uv run --extra dev pytest tests/test_market_data.py -q
```

Expected: passes.

- [ ] **Step 6: Commit**

```bash
git add src/evoquant/services/market_data.py src/evoquant/providers/yahoo.py src/evoquant/providers/akshare.py tests/test_market_data.py
git commit -m "feat: add market data cache and sync jobs"
```

---

### Task 4: Market Rules and Order Sizing

**Files:**
- Create: `src/evoquant/services/market_rules.py`
- Create: `tests/test_market_rules.py`

- [ ] **Step 1: Write failing market rule tests**

Create `tests/test_market_rules.py`:

```python
from datetime import date

from evoquant.domain import Market, SignalSide
from evoquant.services.market_rules import MarketRulesService


def test_cn_rounds_buy_quantity_to_lot_size():
    rules = MarketRulesService.defaults()

    quantity = rules.estimate_quantity(Market.CN, cash=123456, price=25.3, side=SignalSide.BUY)

    assert quantity % 100 == 0
    assert quantity == 4800


def test_cn_t_plus_one_blocks_same_day_sell():
    rules = MarketRulesService.defaults()

    allowed = rules.can_sell(
        Market.CN,
        quantity=100,
        acquired_session=date(2026, 1, 2),
        trade_session=date(2026, 1, 2),
        limit_down=False,
        suspended=False,
    )

    assert allowed is False


def test_us_allows_same_day_sell_when_not_suspended():
    rules = MarketRulesService.defaults()

    allowed = rules.can_sell(
        Market.US,
        quantity=1,
        acquired_session=date(2026, 1, 2),
        trade_session=date(2026, 1, 2),
        limit_down=False,
        suspended=False,
    )

    assert allowed is True


def test_limit_up_blocks_new_cn_buy():
    rules = MarketRulesService.defaults()

    assert rules.can_buy(Market.CN, limit_up=True, suspended=False) is False
    assert rules.can_buy(Market.CN, limit_up=False, suspended=False) is True
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
uv run --extra dev pytest tests/test_market_rules.py -q
```

Expected: fails because `market_rules.py` does not exist.

- [ ] **Step 3: Implement market rules**

Create `src/evoquant/services/market_rules.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from evoquant.domain import Market, SignalSide


@dataclass(frozen=True)
class MarketRule:
    commission_rate: float
    tax_rate_sell: float
    slippage_rate: float
    min_fee: float
    lot_size: int
    t_plus_one: bool


class MarketRulesService:
    def __init__(self, rules: dict[Market, MarketRule]):
        self.rules = rules

    @classmethod
    def defaults(cls) -> "MarketRulesService":
        return cls(
            {
                Market.US: MarketRule(0.0005, 0.0, 0.0005, 0.0, 1, False),
                Market.CN: MarketRule(0.0003, 0.0005, 0.0005, 5.0, 100, True),
                Market.CRYPTO: MarketRule(0.001, 0.0, 0.001, 0.0, 1, False),
            }
        )

    def can_buy(self, market: Market, *, limit_up: bool, suspended: bool) -> bool:
        if suspended:
            return False
        if market is Market.CN and limit_up:
            return False
        return True

    def can_sell(
        self,
        market: Market,
        *,
        quantity: float,
        acquired_session: date,
        trade_session: date,
        limit_down: bool,
        suspended: bool,
    ) -> bool:
        if quantity <= 0 or suspended:
            return False
        rule = self.rules[market]
        if market is Market.CN and limit_down:
            return False
        if rule.t_plus_one and acquired_session >= trade_session:
            return False
        return True

    def estimate_quantity(self, market: Market, *, cash: float, price: float, side: SignalSide) -> int:
        if cash <= 0 or price <= 0:
            return 0
        raw_quantity = int(cash / price)
        lot_size = self.rules[market].lot_size
        return raw_quantity - (raw_quantity % lot_size)

    def transaction_cost(self, market: Market, *, notional: float, side: SignalSide) -> float:
        rule = self.rules[market]
        tax = rule.tax_rate_sell if side is SignalSide.SELL else 0.0
        return max(rule.min_fee, notional * (rule.commission_rate + rule.slippage_rate + tax))
```

- [ ] **Step 4: Run focused tests**

Run:

```bash
uv run --extra dev pytest tests/test_market_rules.py -q
```

Expected: passes.

- [ ] **Step 5: Commit**

```bash
git add src/evoquant/services/market_rules.py tests/test_market_rules.py
git commit -m "feat: add multi-market trading rules"
```

---

### Task 5: Strategy Interface, Momentum Signals, and Score-Weighted Portfolio

**Files:**
- Create: `src/evoquant/services/strategies.py`
- Create: `tests/test_strategies_signals.py`

- [ ] **Step 1: Write failing strategy tests**

Create `tests/test_strategies_signals.py`:

```python
from datetime import date, timedelta

import pytest

from evoquant.domain import Market, SignalSide
from evoquant.services.market_data import MarketBar
from evoquant.services.strategies import CrossSectionalMomentumStrategy, PortfolioConstructor


def _series(symbol: str, start_close: float, daily_step: float, days: int = 140) -> list[MarketBar]:
    start = date(2025, 1, 1)
    bars = []
    for index in range(days):
        close = start_close + daily_step * index
        bars.append(
            MarketBar(
                symbol=symbol,
                market=Market.US,
                session=start + timedelta(days=index),
                open=close - 0.5,
                high=close + 1,
                low=close - 1,
                close=close,
                volume=1_000_000,
                amount=close * 1_000_000,
                adjusted=True,
                suspended=False,
                limit_up=False,
                limit_down=False,
                source="fixture",
            )
        )
    return bars


def test_cross_sectional_momentum_buys_top_20_and_sells_outside_exit_rank():
    bars = _series("AAA", 10, 1.0) + _series("BBB", 10, 0.1) + _series("CCC", 30, -0.1)
    strategy = CrossSectionalMomentumStrategy(
        {
            "top_n": 1,
            "exit_rank": 2,
            "lookback_long": 120,
            "lookback_short": 20,
            "max_weight": 0.08,
            "min_amount": 1000,
            "max_volatility": 10,
            "max_drawdown": 1,
        }
    )

    signals = strategy.generate(Market.US, ["AAA", "BBB", "CCC"], bars, current_positions={"CCC": 100})
    by_symbol = {signal.symbol: signal for signal in signals}

    assert by_symbol["AAA"].signal is SignalSide.BUY
    assert by_symbol["CCC"].signal is SignalSide.SELL
    assert "120日动量" in by_symbol["AAA"].reason


def test_score_weighted_portfolio_caps_single_name_weight():
    constructor = PortfolioConstructor(max_weight=0.08)

    weighted = constructor.assign_weights(
        [
            ("AAA", Market.US, 10.0),
            ("BBB", Market.US, 5.0),
        ]
    )

    assert weighted[("AAA", Market.US)] == pytest.approx(0.08)
    assert weighted[("BBB", Market.US)] <= 0.08
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
uv run --extra dev pytest tests/test_strategies_signals.py -q
```

Expected: fails because `strategies.py` does not exist.

- [ ] **Step 3: Implement strategy dataclasses and momentum strategy**

Create `src/evoquant/services/strategies.py` with:

- `StrategySignal`
- `CrossSectionalMomentumStrategy`
- `PortfolioConstructor`

Implementation requirements:

- Group bars by `(symbol, market)` and sort by session.
- Use latest available bar as `as_of_date`.
- Compute:
  - 120-day return when enough bars exist.
  - 20-day return when enough bars exist.
  - realized volatility using daily returns.
  - max drawdown over available lookback.
- Rank scores within each market.
- Use the formula from the spec:
  - `0.50 * long_momentum_rank`
  - `0.25 * short_momentum_rank`
  - `-0.15 * volatility_penalty`
  - `-0.10 * drawdown_penalty`
- Hard filters:
  - insufficient bars -> risk flag `insufficient_data`
  - latest suspended -> risk flag `suspended`
  - amount below `min_amount` -> risk flag `low_liquidity`
  - volatility above `max_volatility` -> risk flag `high_volatility`
  - drawdown above `max_drawdown` -> risk flag `drawdown_limit`
  - CN limit_up blocks BUY
  - CN limit_down keeps SELL as blocked risk flag for draft/backtest later
- Buy if rank <= `top_n` and no blocking risk flag.
- Hold if existing position and rank <= `exit_rank` and no blocking risk flag.
- Sell if existing position and rank > `exit_rank` or blocking risk flag.
- Others are hold with target weight 0.

- [ ] **Step 4: Run focused tests**

Run:

```bash
uv run --extra dev pytest tests/test_strategies_signals.py -q
```

Expected: passes.

- [ ] **Step 5: Commit**

```bash
git add src/evoquant/services/strategies.py tests/test_strategies_signals.py
git commit -m "feat: add momentum signal strategy"
```

---

### Task 6: Signal Scanner, Scan Snapshots, and History API Service

**Files:**
- Create: `src/evoquant/services/signals.py`
- Modify: `tests/test_strategies_signals.py`

- [ ] **Step 1: Add failing scanner tests**

Append to `tests/test_strategies_signals.py`:

```python
from evoquant.services.signals import SignalScanner
from evoquant.storage import SQLiteStore


def test_signal_scanner_persists_scan_and_results(tmp_path):
    store = SQLiteStore(tmp_path / "state.db")
    bars = _series("AAA", 10, 1.0) + _series("BBB", 10, 0.1)
    scanner = SignalScanner(store)

    scan = scanner.run_scan(
        strategy_template="cross_sectional_momentum",
        parameters={
            "top_n": 1,
            "exit_rank": 2,
            "lookback_long": 120,
            "lookback_short": 20,
            "max_weight": 0.08,
            "min_amount": 1000,
            "max_volatility": 10,
            "max_drawdown": 1,
        },
        market_scope=[Market.US],
        universe={Market.US: ["AAA", "BBB"]},
        bars=bars,
        coverage={Market.US: 1.0},
        current_positions={},
    )
    results = scanner.list_results(scan.id)

    assert scan.status == "success"
    assert len(results) == 2
    assert results[0].rank == 1
    assert results[0].name_zh
```

- [ ] **Step 2: Run scanner test and verify it fails**

Run:

```bash
uv run --extra dev pytest tests/test_strategies_signals.py::test_signal_scanner_persists_scan_and_results -q
```

Expected: fails because `SignalScanner` does not exist.

- [ ] **Step 3: Implement SignalScanner**

Create `src/evoquant/services/signals.py` with:

- `SignalScan`
- `SignalResult`
- `SignalScanner.run_scan()`
- `SignalScanner.latest_scan()`
- `SignalScanner.list_scans()`
- `SignalScanner.list_results(scan_id)`

Implementation requirements:

- Reject market scope if any market coverage is below `0.70`, persist failed scan with error message.
- Use `CrossSectionalMomentumStrategy` for `cross_sectional_momentum`.
- Save scan parameters and coverage as JSON via `dumps`.
- Save results sorted by market then rank.
- For v2 first pass, if instrument master has no record, set `name` and `name_zh` to the symbol. Later API/frontend still works.
- Append audit event `signals.scan_completed` or `signals.scan_failed`.

- [ ] **Step 4: Run focused tests**

Run:

```bash
uv run --extra dev pytest tests/test_strategies_signals.py -q
```

Expected: passes.

- [ ] **Step 5: Commit**

```bash
git add src/evoquant/services/signals.py tests/test_strategies_signals.py
git commit -m "feat: persist signal scans"
```

---

### Task 7: Paper Order Draft Lifecycle

**Files:**
- Create: `src/evoquant/services/drafts.py`
- Create: `tests/test_order_drafts.py`

- [ ] **Step 1: Write failing draft tests**

Create `tests/test_order_drafts.py`:

```python
from datetime import date

from evoquant.domain import Market, OrderDraftStatus, SignalSide
from evoquant.services.drafts import PaperOrderDraftService
from evoquant.services.paper import PaperTradingService
from evoquant.storage import SQLiteStore


def test_draft_lifecycle_requires_approval_before_submit(tmp_path):
    store = SQLiteStore(tmp_path / "state.db")
    account = PaperTradingService(store).create_account("paper-us", 100_000)
    service = PaperOrderDraftService(store)

    draft = service.create_draft(
        scan_id="scan_1",
        account_id=account.id,
        strategy_id="strategy_1",
        symbol="AAPL",
        market=Market.US,
        side=SignalSide.BUY,
        target_weight=0.08,
        current_weight=0,
        reference_price=100,
        reason="score ranked top 20",
        risk_flags=[],
        trade_session=date(2026, 1, 5),
    )

    assert draft.status is OrderDraftStatus.DRAFT

    approved = service.approve(draft.id)
    submitted = service.submit(approved.id)

    assert approved.status is OrderDraftStatus.APPROVED
    assert submitted.status is OrderDraftStatus.SUBMITTED
    assert PaperTradingService(store).list_positions(account.id)[0].symbol == "AAPL"


def test_blocked_draft_cannot_be_approved(tmp_path):
    store = SQLiteStore(tmp_path / "state.db")
    account = PaperTradingService(store).create_account("paper-cn", 100_000)
    service = PaperOrderDraftService(store)

    draft = service.create_draft(
        scan_id="scan_1",
        account_id=account.id,
        strategy_id="strategy_1",
        symbol="600519",
        market=Market.CN,
        side=SignalSide.BUY,
        target_weight=0.08,
        current_weight=0,
        reference_price=1800,
        reason="limit up blocks buy",
        risk_flags=["limit_up"],
        trade_session=date(2026, 1, 5),
    )

    assert draft.status is OrderDraftStatus.BLOCKED
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
uv run --extra dev pytest tests/test_order_drafts.py -q
```

Expected: fails because `drafts.py` does not exist.

- [ ] **Step 3: Implement PaperOrderDraftService**

Create `src/evoquant/services/drafts.py` with:

- `PaperOrderDraft`
- `PaperOrderDraftService.create_draft()`
- `PaperOrderDraftService.list_drafts()`
- `PaperOrderDraftService.approve()`
- `PaperOrderDraftService.cancel()`
- `PaperOrderDraftService.submit()`

Implementation requirements:

- Draft quantity is based on account NAV * target weight / reference price, rounded by market lot size.
- If risk flags contain `limit_up`, `limit_down`, `suspended`, `stale_data`, or estimated quantity is 0, create status `BLOCKED`.
- `approve()` only works for `DRAFT`.
- `submit()` only works for `APPROVED`.
- `submit()` calls existing `PaperTradingService.submit_order()` and `fill_order()` through `/paper` service path, then marks draft `SUBMITTED`.
- Append audit events:
  - `draft.created`
  - `draft.approved`
  - `draft.cancelled`
  - `draft.submitted`

- [ ] **Step 4: Run focused tests**

Run:

```bash
uv run --extra dev pytest tests/test_order_drafts.py -q
```

Expected: passes.

- [ ] **Step 5: Commit**

```bash
git add src/evoquant/services/drafts.py tests/test_order_drafts.py
git commit -m "feat: add paper order draft lifecycle"
```

---

### Task 8: Real Signal Backtest Engine

**Files:**
- Modify: `src/evoquant/services/backtest.py`
- Create: `tests/test_real_backtest.py`

- [ ] **Step 1: Write failing real backtest tests**

Create `tests/test_real_backtest.py`:

```python
from evoquant.domain import Market
from evoquant.services.backtest import BacktestRunner
from tests.test_strategies_signals import _series


def test_real_backtest_runs_strategy_against_bars_and_returns_trades():
    bars = _series("AAA", 10, 1.0, days=160) + _series("BBB", 20, 0.2, days=160)

    result = BacktestRunner().run_signal_backtest(
        market=Market.US,
        universe=["AAA", "BBB"],
        bars=bars,
        parameters={
            "top_n": 1,
            "exit_rank": 2,
            "lookback_long": 120,
            "lookback_short": 20,
            "max_weight": 0.08,
            "min_amount": 1000,
            "max_volatility": 10,
            "max_drawdown": 1,
        },
        starting_cash=100_000,
    )

    assert result.metrics["total_return"] != 0
    assert result.trades
    assert result.equity_curve
    assert "avg_holding_days" in result.metrics
```

- [ ] **Step 2: Run test and verify it fails**

Run:

```bash
uv run --extra dev pytest tests/test_real_backtest.py -q
```

Expected: fails because `run_signal_backtest()` does not exist.

- [ ] **Step 3: Extend backtest runner without breaking current API**

Modify `src/evoquant/services/backtest.py`:

- Keep `BacktestRunner.run(equity, turnovers)` unchanged.
- Add `SignalBacktestTrade`.
- Add `SignalBacktestResult`.
- Add `BacktestRunner.run_signal_backtest()`.

Implementation requirements:

- Iterate sessions after the long lookback window.
- For each session, pass bars up to that session into `CrossSectionalMomentumStrategy`.
- Convert target weights into position changes.
- Apply transaction costs through `MarketRulesService`.
- Use close price as fill reference in v2.
- Track cash, positions, equity curve, trades, turnover, and average holding days.
- Respect CN lot size and T+1 through `MarketRulesService`.

- [ ] **Step 4: Run focused tests**

Run:

```bash
uv run --extra dev pytest tests/test_real_backtest.py tests/test_backtest_validation.py -q
```

Expected: passes.

- [ ] **Step 5: Commit**

```bash
git add src/evoquant/services/backtest.py tests/test_real_backtest.py
git commit -m "feat: add signal-driven backtests"
```

---

### Task 9: API Endpoints for Sync, Signals, Drafts, Real Backtests, and Schedule

**Files:**
- Modify: `src/evoquant/api.py`
- Create: `src/evoquant/services/scheduler.py`
- Modify: `tests/test_api.py`

- [ ] **Step 1: Add failing API tests**

Append to `tests/test_api.py`:

```python
def test_signal_scan_api_returns_snapshot(tmp_path):
    client = _client(tmp_path)

    response = client.post(
        "/api/signals/scans",
        json={
            "strategy_template": "cross_sectional_momentum",
            "markets": ["US"],
            "parameters": {
                "top_n": 1,
                "exit_rank": 2,
                "lookback_long": 120,
                "lookback_short": 20,
                "max_weight": 0.08,
                "min_amount": 1000,
                "max_volatility": 10,
                "max_drawdown": 1,
            },
        },
    )

    assert response.status_code in {201, 400}
    assert response.status_code != 500


def test_order_draft_api_lifecycle(tmp_path):
    client = _client(tmp_path)
    account = client.post(
        "/api/paper/accounts",
        json={"name": "paper-us", "starting_cash": 100000},
    ).json()

    draft = client.post(
        "/api/paper/drafts",
        json={
            "scan_id": "scan_1",
            "account_id": account["id"],
            "strategy_id": "strategy_1",
            "symbol": "AAPL",
            "market": "US",
            "side": "buy",
            "target_weight": 0.08,
            "current_weight": 0,
            "reference_price": 100,
            "reason": "api smoke",
            "risk_flags": [],
            "trade_session": "2026-01-05",
        },
    )
    assert draft.status_code == 201

    approved = client.patch(f"/api/paper/drafts/{draft.json()['id']}/approve")
    submitted = client.patch(f"/api/paper/drafts/{draft.json()['id']}/submit")

    assert approved.status_code == 200
    assert submitted.status_code == 200
    assert submitted.json()["status"] == "submitted"


def test_schedule_api_returns_default_market_schedules(tmp_path):
    client = _client(tmp_path)

    response = client.get("/api/schedules")

    assert response.status_code == 200
    markets = {row["market"] for row in response.json()}
    assert {"US", "CN"}.issubset(markets)
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
uv run --extra dev pytest tests/test_api.py -q
```

Expected: new API tests fail because endpoints do not exist.

- [ ] **Step 3: Implement scheduler service**

Create `src/evoquant/services/scheduler.py`:

- `ScheduleConfig`
- `SchedulerService.default_configs()`
- `SchedulerService.list_configs()`
- `SchedulerService.set_enabled(market, enabled)`

Defaults:

- CN: enabled true, timezone `Asia/Shanghai`, run_time `15:30`.
- US: enabled true, timezone `America/New_York`, run_time `16:30`.

- [ ] **Step 4: Add API models and routes**

Modify `src/evoquant/api.py`:

Add Pydantic models:

- `SignalScanCreate`
- `PaperDraftCreate`
- `RealBacktestCreate`
- `ScheduleUpdate`

Add routes:

- `POST /api/data-sync/{market}` — starts sync job using configured provider; in tests can return 400 if optional provider missing.
- `GET /api/data-sync/jobs`
- `GET /api/signals/scans`
- `POST /api/signals/scans`
- `GET /api/signals/scans/{scan_id}`
- `GET /api/signals/scans/{scan_id}/results`
- `POST /api/paper/drafts`
- `GET /api/paper/drafts`
- `PATCH /api/paper/drafts/{draft_id}/approve`
- `PATCH /api/paper/drafts/{draft_id}/cancel`
- `PATCH /api/paper/drafts/{draft_id}/submit`
- `POST /api/backtests/signal`
- `GET /api/schedules`
- `PATCH /api/schedules/{market}`

Error mapping:

- `KeyError` -> 404.
- invalid input or blocked action -> 400.
- optional provider package missing -> 400 with clear message.

- [ ] **Step 5: Run focused tests**

Run:

```bash
uv run --extra dev pytest tests/test_api.py -q
```

Expected: passes.

- [ ] **Step 6: Commit**

```bash
git add src/evoquant/api.py src/evoquant/services/scheduler.py tests/test_api.py
git commit -m "feat: expose v2 signal APIs"
```

---

### Task 10: Admin Console Signals and Workflow Pages

**Files:**
- Modify: `frontend/src/App.tsx`
- Create: `frontend/src/pages/Signals.tsx`
- Modify: `frontend/src/pages/DataHealth.tsx`
- Modify: `frontend/src/pages/Backtests.tsx`
- Modify: `frontend/src/pages/PaperTrading.tsx`
- Modify: `frontend/src/api.ts`
- Modify: `frontend/src/styles.css`

- [ ] **Step 1: Add API helpers**

Modify `frontend/src/api.ts`:

```ts
export async function apiDelete<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, { method: "DELETE" });
  if (!response.ok) throw await readError(response, `DELETE ${path}`);
  return response.json();
}
```

Keep existing `apiGet`, `apiPost`, and `apiPatch`.

- [ ] **Step 2: Add Signals navigation**

Modify `frontend/src/App.tsx`:

- Add `Signals` page import.
- Add nav item after Overview:
  - key `signals`
  - label `Signals`
  - icon `Radar` or `Activity`
- Add page title `Signals`.
- Render `<Signals />`.

- [ ] **Step 3: Create Signals page**

Create `frontend/src/pages/Signals.tsx` with:

- State:
  - `markets`: `US`, `CN`, `Both`
  - `viewMode`: `by-market`, `global`
  - `latestScan`
  - `results`
  - `state`
  - `message`
- Actions:
  - `Run Scan`
  - `Refresh Data`
  - `Generate Draft`
- Table columns:
  - Symbol
  - 中文名
  - Market
  - Close
  - Signal
  - Score
  - Weight
  - Reason
  - Risk
  - Date
  - Action

Empty states:

- No scan yet.
- Coverage insufficient.
- Provider unavailable.

The page must not submit paper orders directly; it only calls draft creation API.

- [ ] **Step 4: Enhance Data Health page**

Modify `frontend/src/pages/DataHealth.tsx`:

- Fetch `/api/data-sync/jobs`.
- Fetch `/api/schedules`.
- Show provider status, market coverage, failed symbols, latest sync time, and schedule status.
- Continue showing real empty state when no sync jobs exist.

- [ ] **Step 5: Enhance Backtests page**

Modify `frontend/src/pages/Backtests.tsx`:

- Add real backtest mode.
- Let user choose strategy template and market.
- Call `/api/backtests/signal`.
- Show metrics from signal backtest and keep existing sample backtest behavior as fallback mode.

- [ ] **Step 6: Enhance Paper Trading page**

Modify `frontend/src/pages/PaperTrading.tsx`:

- Fetch `/api/paper/drafts`.
- Add Draft Orders panel.
- Buttons:
  - Approve
  - Cancel
  - Submit
- Disabled and blocked states must be visible.
- Submitted draft should refresh orders/fills/positions.

- [ ] **Step 7: Add styling**

Modify `frontend/src/styles.css`:

- Add `.signal-grid`, `.signal-score`, `.risk-flags`, `.draft-list`, `.schedule-grid`.
- Keep dense operational UI.
- Avoid nested cards.
- Ensure tables scroll horizontally on mobile.

- [ ] **Step 8: Verify frontend**

Run:

```bash
cd frontend
npm run typecheck
npm run build
```

Expected: typecheck and build pass. Vite chunk-size warning is acceptable.

- [ ] **Step 9: Commit**

```bash
git add frontend/src
git commit -m "feat: add signals admin workflow"
```

---

### Task 11: Documentation and End-to-End Verification

**Files:**
- Modify: `README.md`
- Modify: `docs/evoquant_mvp_v1_operating_notes.md`
- Create: `docs/evoquant_mvp_v2_data_sources.md`

- [ ] **Step 1: Update README**

Modify `README.md`:

- Add `market-data` installation example:

```bash
uv sync --extra dev --extra market-data
```

- Add v2 workflow:

```text
sync market data -> run signals scan -> review buy/hold/sell -> create paper draft -> approve in Paper Trading
```

- Add non-investment-advice warning in Chinese.

- [ ] **Step 2: Create data source documentation**

Create `docs/evoquant_mvp_v2_data_sources.md`:

```markdown
# EvoQuant MVP v2 数据源说明

## 免费数据源

- 美股使用 yfinance。
- A 股使用 AKShare。
- 免费数据源可能延迟、缺失、限流或字段变化。
- 系统只用于研究和模拟盘，不构成投资建议。

## 本地缓存

- 外部数据先同步到 SQLite。
- Signals 扫描默认读取本地缓存。
- 每次同步记录覆盖率和失败 symbol。
- 覆盖率低于 70% 的市场不输出信号。

## 中文名称

- 美股和 A 股中文名通过 instrument master 维护。
- 美股中文名优先使用本地 CSV 覆盖。
- A 股中文名优先使用 provider 返回值，必要时由本地 CSV 覆盖。

## 默认扫描

- 数据窗口：5 年日线。
- 美股：S&P 500。
- A 股：沪深 300。
- 策略：cross_sectional_momentum。
- 输出：buy / hold / sell 策略信号。
```

- [ ] **Step 3: Run full verification**

Run:

```bash
uv run --extra dev pytest -q
cd frontend
npm run typecheck
npm run build
```

Expected:

- Python tests pass.
- TypeScript typecheck passes.
- Frontend build succeeds.

- [ ] **Step 4: Optional manual smoke test**

Start backend and frontend:

```bash
uv run evoquant --host 127.0.0.1 --port 8000
cd frontend
npm run dev -- --port 5173
```

Use browser or curl:

```bash
curl http://127.0.0.1:8000/healthz
curl http://127.0.0.1:8000/api/schedules
```

Expected:

- healthz returns `{"status":"ok"}`.
- schedules returns US and CN configs.
- Signals page renders without fallback fake rows.

- [ ] **Step 5: Commit docs**

```bash
git add README.md docs/evoquant_mvp_v1_operating_notes.md docs/evoquant_mvp_v2_data_sources.md
git commit -m "docs: add v2 real signals operating notes"
```

---

## Final Verification

After all tasks:

```bash
uv run --extra dev pytest -q
cd frontend
npm run typecheck
npm run build
```

Expected:

- All Python tests pass.
- TypeScript typecheck passes.
- Frontend build succeeds.
- No API route can place real live orders.
- Signals page can show scan history and signal results.
- Paper Trading page is the only place that can submit paper order drafts.

## Plan Self-Review

- Spec coverage: This plan covers provider sync, instrument master, local cache, data quality, market rules, cross-sectional momentum, scan snapshots, order drafts, real signal backtests, scheduling, API, frontend pages, docs, and safety boundaries.
- Scope control: The plan does not implement real broker APIs, minute-level strategy execution, LLM-generated arbitrary strategy code, production queues, RBAC, notifications, industry exposure, beta, or correlation constraints.
- Type consistency: The plan consistently uses `Market`, `SignalSide`, `OrderDraftStatus`, `MarketDataProvider`, `ProviderBar`, `MarketBar`, `StrategySignal`, `SignalScanner`, and `PaperOrderDraftService`.
- Testing: Network providers are tested through fake clients or CSV fixtures; unit tests do not depend on live yfinance or AKShare responses.
