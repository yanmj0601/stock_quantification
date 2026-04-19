# Paper-First Research Console Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild the current dashboard into a paper-first research console where A 股和美股两个模拟盘账户分别围绕各自当前最优策略持续运行、持续优化和持续复盘。

**Architecture:** Keep the existing filesystem-backed monolith and current `http.server` web entrypoint, but replace the current mixed dashboard information architecture with a paper-centered navigation tree. Add one small strategy-state store so “冠军 / 挑战者 / 当前执行策略” can flow from research outputs into the paper pages and the strategy-run forms without introducing a database.

**Tech Stack:** Python 3, `unittest`, existing `src/stock_quantification/web.py` app, filesystem-backed JSON artifacts under `artifacts/web/`, existing result index and local-paper ledger.

---

## Rollout Rules

- Do not reintroduce `Overview / Config / Logs / Ops` as first-class navigation items.
- Keep the existing dark console look, but prioritize readability over dense panel grids.
- Follow TDD for each behavior change.
- Prefer focused helpers/modules over adding more branching into existing monolith methods when possible.
- Every checkpoint must end with a green targeted `unittest` command.

## File Map

### Existing files to modify

- `src/stock_quantification/web.py`
  - Route table, navigation model, page-shell copy, page renderers, form handlers, and selected artifact rendering.
- `src/stock_quantification/cli.py`
  - Run path entrypoint; will need to accept an explicit preset or current-strategy selection instead of always using the hardcoded market default.
- `src/stock_quantification/engine.py`
  - Strategy resolution currently hardcodes `cn_index_enhancement` and `us_quality_momentum`; this needs an override path.
- `src/stock_quantification/strategy_catalog.py`
  - Add preset lookup helpers and keep preset identity stable for page display and run selection.
- `tests/test_web.py`
  - Main regression surface for routing, nav rendering, page composition, and form handling.

### New files to create

- `src/stock_quantification/strategy_state.py`
  - Filesystem-backed state for market-level `champion / challenger / current_execution_strategy`.
- `tests/test_strategy_state.py`
  - Unit coverage for state persistence and fallback behavior.

### Existing assets likely to modify

- `templates/dashboard.html`
  - If new secondary nav shell hooks are required.
- `static/styles.css`
  - Layout updates for paper-first navigation, timeline cards, and wider single-purpose pages.

---

## Checkpoints

1. **Checkpoint A: Information architecture** — new 一级/二级导航 and paper-first homepage shell exist.
2. **Checkpoint B: Strategy-state wiring** — market-level champion/challenger/current-strategy state exists and is readable from web pages.
3. **Checkpoint C: Split pages** — 模拟盘、策略优化、策略运行、结果中心 all follow single-responsibility subpages.
4. **Checkpoint D: Execution linkage** — run forms can execute against the currently selected market strategy.

### Task 1: Introduce a Dedicated Market Strategy State Store

**Files:**
- Create: `src/stock_quantification/strategy_state.py`
- Modify: `src/stock_quantification/__init__.py`
- Test: `tests/test_strategy_state.py`

- [ ] **Step 1: Write the failing tests for strategy-state persistence**

Add `tests/test_strategy_state.py` with coverage for:
- default empty state for CN and US
- saving champion/challenger/current execution strategy for one market without mutating the other
- reading persisted state back newest-first

```python
def test_strategy_state_round_trips_current_market_assignment():
    store = StrategyStateStore(tmpdir)
    store.set_market_state(
        Market.CN,
        champion_preset_id="cn_momentum_core",
        challenger_preset_id="cn_quality_momentum",
        current_execution_preset_id="cn_momentum_core",
    )
    state = store.load_market_state(Market.CN)
    assert state["champion_preset_id"] == "cn_momentum_core"
    assert state["challenger_preset_id"] == "cn_quality_momentum"
    assert state["current_execution_preset_id"] == "cn_momentum_core"
```

- [ ] **Step 2: Run the new test and verify it fails**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_strategy_state -v
```

Expected: `ModuleNotFoundError` or failing assertions because `StrategyStateStore` does not exist yet.

- [ ] **Step 3: Write the minimal strategy-state store**

Create `src/stock_quantification/strategy_state.py` with:

```python
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict

from .artifacts import read_json_artifact, write_json_artifact
from .models import Market

STATE_RELATIVE_PATH = "web/strategy_state.json"


class StrategyStateStore:
    def __init__(self, base_dir: str | Path, relative_path: str = STATE_RELATIVE_PATH) -> None:
        self._base_dir = Path(base_dir)
        self._relative_path = relative_path

    def load_state(self) -> Dict[str, Any]:
        payload = read_json_artifact(self._base_dir, self._relative_path)
        if not isinstance(payload, dict):
            return {"markets": {}}
        markets = payload.get("markets")
        return {"markets": markets if isinstance(markets, dict) else {}}

    def load_market_state(self, market: Market) -> Dict[str, Any]:
        state = self.load_state()
        return dict(state["markets"].get(market.value, {}))

    def set_market_state(
        self,
        market: Market,
        *,
        champion_preset_id: str = "",
        challenger_preset_id: str = "",
        current_execution_preset_id: str = "",
    ) -> Dict[str, Any]:
        state = self.load_state()
        state["markets"][market.value] = {
            "champion_preset_id": champion_preset_id,
            "challenger_preset_id": challenger_preset_id,
            "current_execution_preset_id": current_execution_preset_id,
        }
        write_json_artifact(self._base_dir, self._relative_path, state)
        return state
```

- [ ] **Step 4: Export the new store**

Update `src/stock_quantification/__init__.py` to export:

```python
from .strategy_state import StrategyStateStore
```

and add:

```python
"StrategyStateStore",
```

to `__all__`.

- [ ] **Step 5: Run the tests and commit**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_strategy_state -v
```

Expected: PASS.

Commit:

```bash
git add src/stock_quantification/strategy_state.py src/stock_quantification/__init__.py tests/test_strategy_state.py
git commit -m "feat: add market strategy state store"
```

### Task 2: Make Strategy Resolution Explicit in the Run Path

**Files:**
- Modify: `src/stock_quantification/strategy_catalog.py`
- Modify: `src/stock_quantification/engine.py`
- Modify: `src/stock_quantification/cli.py`
- Test: `tests/test_strategy_catalog.py`
- Test: `tests/test_web.py`

- [ ] **Step 1: Write the failing tests for preset lookup and explicit run selection**

Add or extend tests to assert:
- preset lookup by `preset_id` works for CN and US
- the run path can accept an explicit preset id instead of only the hardcoded market default

```python
def test_lookup_strategy_preset_returns_named_cn_preset(self):
    preset = lookup_strategy_preset(Market.CN, "cn_momentum_core")
    self.assertEqual(preset.preset_id, "cn_momentum_core")
```

```python
def test_handle_run_prefers_explicit_strategy_selection(self):
    body = {
        "market": ["CN"],
        "selected_strategy_cn": ["cn_momentum_core"],
    }
    # Expect the submitted job metadata to carry the selected preset id.
```

- [ ] **Step 2: Run the targeted tests to confirm failure**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_strategy_catalog tests.test_web -v
```

Expected: failures because preset lookup and explicit strategy selection are not wired yet.

- [ ] **Step 3: Add preset lookup helpers in the catalog**

Update `src/stock_quantification/strategy_catalog.py` with:

```python
def lookup_strategy_preset(market: Market, preset_id: str) -> StrategyPreset:
    for preset in strategy_presets_for_market(market):
        if preset.preset_id == preset_id:
            return preset
    raise ValueError(f"Unknown preset {preset_id} for market {market.value}")
```

- [ ] **Step 4: Thread an optional preset id through the run path**

Update `src/stock_quantification/cli.py` and `src/stock_quantification/engine.py` so the market run path can take:

```python
selected_preset_id: str | None = None
```

and resolve the strategy with:

```python
strategy = _strategy_for_market(
    market,
    snapshot.research_data_bundle,
    snapshot.as_of,
    snapshot.benchmark_instrument_id,
    top_n,
    selected_preset_id=selected_preset_id,
)
```

Implementation rule:
- if `selected_preset_id` is absent, preserve current default behavior
- if present, resolve the preset and build the strategy from that preset

- [ ] **Step 5: Re-run the tests and commit**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_strategy_catalog tests.test_web -v
```

Expected: PASS.

Commit:

```bash
git add src/stock_quantification/strategy_catalog.py src/stock_quantification/engine.py src/stock_quantification/cli.py tests/test_strategy_catalog.py tests/test_web.py
git commit -m "feat: support explicit preset selection in run path"
```

### Task 3: Replace the Old Primary Navigation with a Paper-First Shell

**Files:**
- Modify: `src/stock_quantification/web.py`
- Modify: `templates/dashboard.html`
- Modify: `static/styles.css`
- Test: `tests/test_web.py`

- [ ] **Step 1: Write the failing navigation tests**

Add assertions that the primary navigation now contains:
- `模拟盘`
- `策略优化`
- `策略运行`
- `结果中心`

and does not contain:
- `Overview / 总览`
- `Config / 项目配置`
- `Logs / 任务日志`

```python
self.assertIn("模拟盘", body)
self.assertIn("策略优化", body)
self.assertNotIn("Config / 项目配置", body)
```

- [ ] **Step 2: Run the targeted web tests and watch them fail**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_web.WebTests.test_home_page_renders_sidebar_navigation -v
```

Expected: FAIL because the old navigation labels are still rendered.

- [ ] **Step 3: Refactor the view model and sidebar renderer**

Update `src/stock_quantification/web.py`:
- replace the current four `overview/workbench/results/paper` primary views with:
  - `paper`
  - `optimize`
  - `run`
  - `results`
- introduce one helper that returns the active primary view and active secondary subview

Minimal shape:

```python
def _primary_view(self, query: Dict[str, List[str]]) -> str:
    raw = query.get("view", ["paper"])[0].strip().lower()
    return raw if raw in {"paper", "optimize", "run", "results"} else "paper"

def _subview(self, query: Dict[str, List[str]], allowed: set[str], default: str) -> str:
    raw = query.get("subview", [default])[0].strip().lower()
    return raw if raw in allowed else default
```

- [ ] **Step 4: Update the page shell and CSS hooks**

Modify `templates/dashboard.html` and `static/styles.css` so the shell supports:
- a stronger primary nav
- a secondary tab row per section
- wider single-column content areas for forms and timelines

Add CSS hooks such as:

```css
.secondary-nav { display: flex; gap: 12px; }
.page-shell--wide { max-width: 1480px; }
.timeline-list { display: grid; gap: 16px; }
```

- [ ] **Step 5: Run the focused web tests and commit**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_web -v
```

Expected: navigation and shell tests pass after the copy updates.

Commit:

```bash
git add src/stock_quantification/web.py templates/dashboard.html static/styles.css tests/test_web.py
git commit -m "feat: add paper-first primary navigation shell"
```

### Task 4: Rebuild the Paper Section into One Main Page Plus Holdings and Trades

**Files:**
- Modify: `src/stock_quantification/web.py`
- Modify: `static/styles.css`
- Test: `tests/test_web.py`

- [ ] **Step 1: Write the failing tests for the new paper subpages**

Add tests for:
- `view=paper&subview=main` rendering account summary + execution timeline + current strategy
- `view=paper&subview=holdings` rendering holdings only
- `view=paper&subview=trades` rendering trade history only

```python
response = self.app.render_home({"view": ["paper"], "subview": ["holdings"]})
self.assertIn("Current Holdings / 当前持仓", body)
self.assertNotIn("Execution Timeline / 执行时间流", body)
```

- [ ] **Step 2: Run the failing paper-page tests**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_web -v
```

Expected: FAIL because `paper` is still one monolithic page.

- [ ] **Step 3: Split the paper renderers by responsibility**

In `src/stock_quantification/web.py`, add:

```python
def _render_paper_main_page(self, query: Dict[str, List[str]]) -> WebResponse: ...
def _render_paper_holdings_page(self, query: Dict[str, List[str]]) -> WebResponse: ...
def _render_paper_trades_page(self, query: Dict[str, List[str]]) -> WebResponse: ...
```

Implementation rule:
- `main` keeps only account summary, execution timeline, and current strategy
- `holdings` keeps only holdings and exposure tables
- `trades` keeps only trade history and trade filters

- [ ] **Step 4: Add a current-strategy panel to the paper main page**

Read market strategy state and render:

```python
current_state = self._strategy_state_store().load_market_state(active_market)
champion = current_state.get("champion_preset_id", "")
challenger = current_state.get("challenger_preset_id", "")
current_execution = current_state.get("current_execution_preset_id", champion)
```

Display those values with:
- current execution strategy
- champion
- challenger
- switch suggestion CTA placeholder

- [ ] **Step 5: Re-run the tests and commit**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_web -v
```

Expected: paper subpage tests pass.

Commit:

```bash
git add src/stock_quantification/web.py static/styles.css tests/test_web.py
git commit -m "feat: split paper pages into main holdings and trades"
```

### Task 5: Split Strategy Optimization into Create, History, and Detail

**Files:**
- Modify: `src/stock_quantification/web.py`
- Modify: `static/styles.css`
- Test: `tests/test_web.py`

- [ ] **Step 1: Write the failing tests for optimize subpages**

Cover:
- `view=optimize&subview=create`
- `view=optimize&subview=history`
- `view=optimize&subview=detail`

and assert:
- create page shows the experiment forms only
- history page shows timeline cards only
- detail page shows a selected experiment result only

```python
self.assertIn("Create Experiment / 创建实验", body)
self.assertNotIn("Experiment Timeline / 实验时间流", body)
```

- [ ] **Step 2: Run the tests to confirm the current workbench shape fails**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_web -v
```

Expected: FAIL because `workbench` still mixes forms and history.

- [ ] **Step 3: Replace the old workbench route with optimize subviews**

Implement new renderers:

```python
def _render_optimize_create_page(self, query: Dict[str, List[str]]) -> WebResponse: ...
def _render_optimize_history_page(self, query: Dict[str, List[str]]) -> WebResponse: ...
def _render_optimize_detail_page(self, query: Dict[str, List[str]]) -> WebResponse: ...
```

Map old factor-backtest and strategy-suite outputs into:
- timeline rows for history
- champion/challenger/drop summary cards for detail

- [ ] **Step 4: Seed strategy-state suggestions from experiment detail**

In the detail page, derive a suggested state from the latest result:

```python
recommended = payload["summary"].get("recommended_presets", [])
watchlist = payload["summary"].get("watchlist_presets", [])
```

Display:
- champion candidate
- challenger candidate
- “send to current strategy” CTA placeholder

- [ ] **Step 5: Run the tests and commit**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_web -v
```

Expected: optimize subviews pass and old workbench references are gone.

Commit:

```bash
git add src/stock_quantification/web.py static/styles.css tests/test_web.py
git commit -m "feat: split strategy optimization into create history and detail"
```

### Task 6: Split Strategy Run into Create, History, and Detail

**Files:**
- Modify: `src/stock_quantification/web.py`
- Modify: `tests/test_web.py`

- [ ] **Step 1: Write the failing tests for run subpages**

Add tests for:
- `view=run&subview=create`
- `view=run&subview=history`
- `view=run&subview=detail`

and assert the create page renders the run form with explicit strategy selection, while history/detail pages render timeline/detail blocks separately.

- [ ] **Step 2: Run the targeted tests and confirm failure**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_web -v
```

Expected: FAIL because run UI is still embedded in the old workbench.

- [ ] **Step 3: Introduce explicit strategy selectors in the run form**

Add selectors such as:

```python
<select name="selected_strategy_cn">...</select>
<select name="selected_strategy_us">...</select>
```

Default behavior:
- if strategy state exists, default to `current_execution_preset_id`
- else fallback to the current market default preset

- [ ] **Step 4: Split the run pages**

Implement:

```python
def _render_run_create_page(self, query: Dict[str, List[str]]) -> WebResponse: ...
def _render_run_history_page(self, query: Dict[str, List[str]]) -> WebResponse: ...
def _render_run_detail_page(self, query: Dict[str, List[str]]) -> WebResponse: ...
```

History page should show a time-ordered list of prior runs; detail page should render a single run’s selected signals, trade suggestions, review, and simulated account effect.

- [ ] **Step 5: Run tests and commit**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_web -v
```

Expected: PASS.

Commit:

```bash
git add src/stock_quantification/web.py tests/test_web.py
git commit -m "feat: split strategy run into create history and detail"
```

### Task 7: Reframe the Results Center Around Champion, Challenger, Drop, and Archive

**Files:**
- Modify: `src/stock_quantification/web.py`
- Modify: `src/stock_quantification/result_index.py`
- Test: `tests/test_web.py`

- [ ] **Step 1: Write failing tests for results-center subpages**

Cover:
- `view=results&subview=champions`
- `view=results&subview=challengers`
- `view=results&subview=drops`
- `view=results&subview=archive`

Each should filter the same indexed data differently.

- [ ] **Step 2: Run the tests to confirm the old grouped results center fails**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_web -v
```

Expected: FAIL because results are currently grouped only by research/runtime.

- [ ] **Step 3: Add derived filters for champion/challenger/drop**

Update `src/stock_quantification/result_index.py` or `src/stock_quantification/web.py` helper logic so a record can be categorized by normalized summary fields such as:

```python
decision = normalized_summary.get("decision", "")
```

Rules:
- champion: current official market champion or latest KEEP result promoted to champion
- challenger: latest REVIEW candidate or explicit challenger assignment
- drop: DROP results
- archive: everything

- [ ] **Step 4: Render the new results subpages**

Implement dedicated renderers:

```python
def _render_results_champions_page(self, query: Dict[str, List[str]]) -> WebResponse: ...
def _render_results_challengers_page(self, query: Dict[str, List[str]]) -> WebResponse: ...
def _render_results_drops_page(self, query: Dict[str, List[str]]) -> WebResponse: ...
def _render_results_archive_page(self, query: Dict[str, List[str]]) -> WebResponse: ...
```

- [ ] **Step 5: Run tests and commit**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_web -v
```

Expected: PASS.

Commit:

```bash
git add src/stock_quantification/web.py src/stock_quantification/result_index.py tests/test_web.py
git commit -m "feat: refactor results center around champions and archive"
```

### Task 8: Wire the Half-Automatic Champion/Challenger Promotion Flow

**Files:**
- Modify: `src/stock_quantification/web.py`
- Modify: `src/stock_quantification/strategy_state.py`
- Test: `tests/test_strategy_state.py`
- Test: `tests/test_web.py`

- [ ] **Step 1: Write failing tests for promoting a challenger to current execution**

Cover a POST action such as:

```python
response = self.app.handle_set_current_strategy({
    "market": ["CN"],
    "preset_id": ["cn_momentum_core"],
})
```

Expected state:
- `current_execution_preset_id` becomes the selected preset
- the paper main page reflects the new current strategy

- [ ] **Step 2: Run the targeted tests and verify failure**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_strategy_state tests.test_web -v
```

Expected: FAIL because no promotion action exists yet.

- [ ] **Step 3: Add the strategy-promotion handler**

Implement in `src/stock_quantification/web.py`:

```python
def handle_set_current_strategy(self, body: Dict[str, List[str]]) -> WebResponse:
    market = Market(body["market"][0])
    preset_id = body["preset_id"][0].strip()
    state = self._strategy_state_store().load_market_state(market)
    self._strategy_state_store().set_market_state(
        market,
        champion_preset_id=state.get("champion_preset_id", preset_id),
        challenger_preset_id=state.get("challenger_preset_id", ""),
        current_execution_preset_id=preset_id,
    )
    return self._redirect(self._view_url("paper", query={"market_tab": market.value}))
```

- [ ] **Step 4: Surface the action in the paper current-strategy panel**

Render a button like:

```python
<form method="post" action="/strategy-state/current">
  <input type="hidden" name="market" value="CN" />
  <input type="hidden" name="preset_id" value="cn_momentum_core" />
  <button class="button button--primary" type="submit">设为当前执行策略</button>
</form>
```

- [ ] **Step 5: Run the tests, run a smoke suite, and commit**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_strategy_state tests.test_web tests.test_ops -v
```

Expected: PASS.

Commit:

```bash
git add src/stock_quantification/web.py src/stock_quantification/strategy_state.py tests/test_strategy_state.py tests/test_web.py
git commit -m "feat: add half-automatic current strategy promotion flow"
```

## Spec Coverage Review

- 信息架构收敛到 4 个一级页：Task 3
- 模拟盘主页面 + 持仓 + 成交历史：Task 4
- 策略优化创建/历史/详情：Task 5
- 策略运行创建/历史/详情：Task 6
- 结果中心冠军/挑战者/淘汰/归档：Task 7
- 双市场双账户标签与当前策略状态：Task 1 + Task 4 + Task 8
- 半自动冠军/挑战者切换：Task 8
- 显式用当前策略驱动运行页：Task 2 + Task 6

No spec gaps remain for the first rollout. Deferred items intentionally left out:
- automatic scheduling of repeated runs
- automatic promotion without user confirmation
- broker execution reconciliation beyond current local-paper semantics

## Placeholder Scan

- No `TODO` / `TBD` placeholders remain.
- Every code-changing task includes the exact file path and minimal code shape.
- Every task includes an explicit verification command.

## Type Consistency Review

- Strategy-state fields are consistently named:
  - `champion_preset_id`
  - `challenger_preset_id`
  - `current_execution_preset_id`
- Subview routing consistently uses:
  - `view`
  - `subview`
- Run-path override consistently uses:
  - `selected_preset_id`

