# Architecture Convergence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 收敛当前量化系统的回测、状态、执行与配置架构，解决重复壳层、全量重建快照的性能瓶颈，以及回测/模拟盘账本不一致的问题。

**Architecture:** 保留 `pipeline.py` 作为唯一策略计算内核，把 `agents.py`/`engine.py` 压缩成薄编排层；把回测从“逐日重建快照”改成“区间一次加载 + 时间滚动”；把账户状态转移统一收口到 broker/account state 层，并逐步把策略配置从硬编码 blueprint 抽离成声明式配置。

**Tech Stack:** Python 3.9, unittest, SQLite, existing `real_data.py`/`pipeline.py`/`backtest.py`/`local_paper.py`

---

### Task 1: Baseline Safety Net

**Files:**
- Modify: `tests/test_backtest.py`
- Modify: `tests/test_web.py`
- Modify: `tests/test_real_data.py`

- [ ] **Step 1: Write the failing regression tests**

```python
def test_actual_sessions_reuses_preloaded_market_dataset():
    ...

def test_backtest_and_local_paper_share_fill_cost_conventions():
    ...

def test_strategy_experiment_history_keeps_resume_entry():
    ...
```

- [ ] **Step 2: Run the targeted tests to verify failures**

Run: `PYTHONPATH=src python3 -m unittest tests.test_backtest tests.test_web tests.test_real_data -q`
Expected: FAIL with missing preloaded dataset path / mismatched state semantics / missing shared conventions

- [ ] **Step 3: Add only the minimal fixtures/helpers needed by the tests**

```python
class SnapshotBuilderSpy:
    ...
```

- [ ] **Step 4: Re-run the targeted tests**

Run: `PYTHONPATH=src python3 -m unittest tests.test_backtest tests.test_web tests.test_real_data -q`
Expected: still FAIL, but now failures should point at production behavior rather than missing test scaffolding

- [ ] **Step 5: Commit**

```bash
git add tests/test_backtest.py tests/test_web.py tests/test_real_data.py
git commit -m "test: lock architecture convergence regressions"
```

### Task 2: Introduce a Rolling Market Dataset for Backtests

**Files:**
- Create: `src/stock_quantification/backtest_dataset.py`
- Modify: `src/stock_quantification/backtest.py`
- Test: `tests/test_backtest.py`

- [ ] **Step 1: Write the failing dataset tests**

```python
def test_market_dataset_builds_sessions_once_for_requested_range():
    ...

def test_market_dataset_can_materialize_snapshot_for_each_session():
    ...
```

- [ ] **Step 2: Run only the new dataset tests**

Run: `PYTHONPATH=src python3 -m unittest tests.test_backtest.BacktestTests.test_market_dataset_builds_sessions_once_for_requested_range tests.test_backtest.BacktestTests.test_market_dataset_can_materialize_snapshot_for_each_session -v`
Expected: FAIL because `backtest_dataset.py` and the new dataset API do not exist yet

- [ ] **Step 3: Implement the dataset object**

```python
@dataclass(frozen=True)
class MarketDataset:
    market: Market
    sessions: List[date]
    instruments: List[Instrument]
    bars_by_instrument: Dict[str, List[Bar]]
    benchmark_instrument_id: Optional[str]
```

```python
def build_market_dataset(...):
    ...

def snapshot_for_session(...):
    ...
```

- [ ] **Step 4: Refactor `_actual_sessions()` to use the dataset instead of `build_market_snapshot()` per day**

```python
dataset = build_market_dataset(...)
snapshots = [snapshot_for_session(dataset, trade_date, ...) for trade_date in dataset.sessions]
```

- [ ] **Step 5: Run the backtest tests**

Run: `PYTHONPATH=src python3 -m unittest tests.test_backtest -q`
Expected: PASS for the new dataset tests and no regression in existing rolling backtest tests

- [ ] **Step 6: Commit**

```bash
git add src/stock_quantification/backtest_dataset.py src/stock_quantification/backtest.py tests/test_backtest.py
git commit -m "feat: preload rolling backtest market datasets"
```

### Task 3: Collapse Strategy Execution onto One Kernel

**Files:**
- Modify: `src/stock_quantification/agents.py`
- Modify: `src/stock_quantification/engine.py`
- Modify: `src/stock_quantification/backtest.py`
- Test: `tests/test_backtest.py`

- [ ] **Step 1: Write the failing orchestration tests**

```python
def test_orchestrator_reuses_pipeline_result_without_recomputing():
    ...

def test_research_agent_is_thin_wrapper_over_strategy_runner():
    ...
```

- [ ] **Step 2: Run the orchestration tests**

Run: `PYTHONPATH=src python3 -m unittest tests.test_backtest.BacktestTests.test_orchestrator_reuses_pipeline_result_without_recomputing tests.test_backtest.BacktestTests.test_research_agent_is_thin_wrapper_over_strategy_runner -v`
Expected: FAIL because the current path still rebuilds pipeline-derived structures through layered agent calls

- [ ] **Step 3: Make the agent layer explicitly thin**

```python
class ResearchAgent:
    def analyze(...):
        return StrategyAnalysis.from_runner_result(...)
```

```python
class StrategyAgent:
    def run(...):
        targets = analysis.targets
        ...
```

- [ ] **Step 4: Refactor `backtest.py` to construct the minimal execution stack**

```python
analysis = strategy_runner.run(...)
proposal = strategy_agent.run(..., analysis=analysis)
```

- [ ] **Step 5: Run the focused tests and then the broader module tests**

Run: `PYTHONPATH=src python3 -m unittest tests.test_backtest -q`
Expected: PASS with no duplicate pipeline execution inside the rolling loop

- [ ] **Step 6: Commit**

```bash
git add src/stock_quantification/agents.py src/stock_quantification/engine.py src/stock_quantification/backtest.py tests/test_backtest.py
git commit -m "refactor: thin strategy orchestration around pipeline kernel"
```

### Task 4: Unify Account State Transition Through a Broker Ledger Interface

**Files:**
- Create: `src/stock_quantification/broker_ledger.py`
- Modify: `src/stock_quantification/backtest.py`
- Modify: `src/stock_quantification/local_paper.py`
- Modify: `src/stock_quantification/runtime.py`
- Test: `tests/test_backtest.py`
- Test: `tests/test_local_paper.py`

- [ ] **Step 1: Write the failing shared-ledger tests**

```python
def test_backtest_ledger_and_local_paper_compute_nav_consistently():
    ...

def test_unknown_position_cleanup_uses_shared_ledger_events():
    ...
```

- [ ] **Step 2: Run the shared-ledger tests**

Run: `PYTHONPATH=src python3 -m unittest tests.test_backtest tests.test_local_paper -q`
Expected: FAIL because the backtest path still uses `_mark_nav()` and its own fill accounting

- [ ] **Step 3: Add a shared ledger abstraction**

```python
class BrokerLedger:
    def mark_nav(...)
    def apply_execution_result(...)
    def summarize_day(...)
```

- [ ] **Step 4: Switch backtest and local paper to the same ledger math**

```python
nav = ledger.mark_nav(account_state, data_provider, snapshot.as_of)
day_stats = ledger.apply_execution_result(...)
```

- [ ] **Step 5: Re-run shared-ledger tests**

Run: `PYTHONPATH=src python3 -m unittest tests.test_backtest tests.test_local_paper -q`
Expected: PASS with identical fee/notional/nav conventions in both paths

- [ ] **Step 6: Commit**

```bash
git add src/stock_quantification/broker_ledger.py src/stock_quantification/backtest.py src/stock_quantification/local_paper.py src/stock_quantification/runtime.py tests/test_backtest.py tests/test_local_paper.py
git commit -m "refactor: unify backtest and paper ledger accounting"
```

### Task 5: Move Strategy Configuration to a Declarative Catalog

**Files:**
- Create: `src/stock_quantification/strategy_blueprints.py`
- Modify: `src/stock_quantification/pipeline.py`
- Modify: `src/stock_quantification/engine.py`
- Modify: `src/stock_quantification/strategy_catalog.py`
- Test: `tests/test_pipeline.py`
- Test: `tests/test_strategy_catalog.py`

- [ ] **Step 1: Write the failing blueprint catalog tests**

```python
def test_cn_blueprint_can_be_loaded_from_declarative_spec():
    ...

def test_strategy_catalog_preserves_existing_preset_ids_after_blueprint_extraction():
    ...
```

- [ ] **Step 2: Run the blueprint tests**

Run: `PYTHONPATH=src python3 -m unittest tests.test_pipeline tests.test_strategy_catalog -q`
Expected: FAIL because blueprints still live inline in `pipeline.py`

- [ ] **Step 3: Extract blueprint specs into declarative structures**

```python
CN_INDEX_ENHANCEMENT_SPEC = {
    "feature_config": {...},
    "alpha_weights": {...},
    "portfolio_policy": {...},
}
```

- [ ] **Step 4: Replace hardcoded builder bodies with spec-driven assembly**

```python
def build_cn_index_enhancement_blueprint(...):
    return build_blueprint_from_spec(...)
```

- [ ] **Step 5: Re-run pipeline/catalog tests**

Run: `PYTHONPATH=src python3 -m unittest tests.test_pipeline tests.test_strategy_catalog -q`
Expected: PASS while preserving current preset ids and default behavior

- [ ] **Step 6: Commit**

```bash
git add src/stock_quantification/strategy_blueprints.py src/stock_quantification/pipeline.py src/stock_quantification/engine.py src/stock_quantification/strategy_catalog.py tests/test_pipeline.py tests/test_strategy_catalog.py
git commit -m "refactor: extract declarative strategy blueprint catalog"
```

### Task 6: Consolidate Serialization and Decimal Utilities

**Files:**
- Create: `src/stock_quantification/schema_utils.py`
- Modify: `src/stock_quantification/backtest.py`
- Modify: `src/stock_quantification/reporting.py`
- Modify: `src/stock_quantification/validation.py`
- Test: `tests/test_backtest.py`
- Test: `tests/test_validation.py`

- [ ] **Step 1: Write the failing utility tests**

```python
def test_decimal_serialization_is_shared_across_backtest_and_validation():
    ...
```

- [ ] **Step 2: Run the utility tests**

Run: `PYTHONPATH=src python3 -m unittest tests.test_backtest tests.test_validation -q`
Expected: FAIL because serialization and decimal conversion are duplicated across modules

- [ ] **Step 3: Introduce the shared utility layer**

```python
def to_decimal(value: object) -> Decimal:
    ...

def serialize_dataclass_payload(item) -> Dict[str, object]:
    ...
```

- [ ] **Step 4: Replace module-local duplicates**

```python
from .schema_utils import to_decimal, serialize_dataclass_payload
```

- [ ] **Step 5: Re-run the utility-facing tests**

Run: `PYTHONPATH=src python3 -m unittest tests.test_backtest tests.test_validation -q`
Expected: PASS with the old output shapes preserved

- [ ] **Step 6: Commit**

```bash
git add src/stock_quantification/schema_utils.py src/stock_quantification/backtest.py src/stock_quantification/reporting.py src/stock_quantification/validation.py tests/test_backtest.py tests/test_validation.py
git commit -m "refactor: share decimal and serialization utilities"
```

### Task 7: End-to-End Verification and Cleanup

**Files:**
- Modify: `README.md`
- Modify: `docs/superpowers/specs/2026-04-19-paper-first-research-console-design.md` (only if behavior docs now contradict implementation)
- Test: `tests/test_backtest.py`
- Test: `tests/test_local_paper.py`
- Test: `tests/test_pipeline.py`
- Test: `tests/test_strategy_catalog.py`
- Test: `tests/test_validation.py`
- Test: `tests/test_web.py`

- [ ] **Step 1: Run the full targeted regression suite**

Run: `PYTHONPATH=src python3 -m unittest tests.test_backtest tests.test_local_paper tests.test_pipeline tests.test_strategy_catalog tests.test_validation tests.test_web -q`
Expected: PASS

- [ ] **Step 2: Run a real CN strategy experiment and one rolling backtest smoke test**

Run: `PYTHONPATH=src python3 -m stock_quantification.cli --market CN --detail-limit 12 --history-limit 60 --top-n 5`
Expected: command completes without architecture-regression errors

Run: `PYTHONPATH=src python3 - <<'PY'\nfrom stock_quantification.backtest import ...\nPY`
Expected: rolling backtest completes using the new dataset/ledger path

- [ ] **Step 3: Update developer-facing docs**

```markdown
- backtest now uses preloaded market datasets
- strategy execution is pipeline-kernel-first
- local paper and backtest share broker ledger conventions
```

- [ ] **Step 4: Commit**

```bash
git add README.md docs/superpowers/specs/2026-04-19-paper-first-research-console-design.md
git commit -m "docs: document converged quant architecture"
```

---

**Spec coverage check**
- 回测加载瓶颈：Task 2
- 策略壳层收敛：Task 3
- 状态/账本统一：Task 4
- 配置声明式化：Task 5
- 序列化公共层：Task 6

**Placeholder scan**
- 已避免 TBD/TODO
- 所有任务都给了文件、命令和最小代码骨架

**Type consistency**
- 统一使用 `MarketDataset`, `BrokerLedger`, `build_blueprint_from_spec` 这些新增边界名
- 不在不同任务里复用冲突命名
