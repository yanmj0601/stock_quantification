# Runtime State SQLite Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把当前仍由 JSON 承担的运行时状态迁入 SQLite，包括 `strategy_state`、`strategy_registry`、`result_index`、`paper_automation_state` 以及 `local_paper` 的账户与账本层，同时保留源码配置和 dated artifact 结果文件为文件制品。

**Architecture:** 以 `SQLiteStateStore` 为底层统一运行时状态仓，新增面向策略状态、结果索引和本地模拟盘账本的 SQLite repository/API；各上层 store 保持现有 public interface，先实现“SQLite 为主、legacy JSON 只做一次导入”的双读迁移，再移除 JSON 写路径。实验/回测结果工件继续保留为 JSON/Markdown 文件，只把索引和运行时状态搬进库里。

**Tech Stack:** Python 3.9, unittest, sqlite3, existing `sqlite_state.py`, `strategy_state.py`, `strategy_registry.py`, `result_index.py`, `local_paper.py`

---

### Task 1: Lock the Migration Boundaries with Regression Tests

**Files:**
- Modify: `tests/test_strategy_state.py`
- Modify: `tests/test_strategy_registry.py`
- Modify: `tests/test_web.py`
- Modify: `tests/test_local_paper.py`

- [ ] **Step 1: Write failing migration-boundary tests**

```python
def test_strategy_state_prefers_sqlite_over_legacy_json():
    ...

def test_strategy_registry_reads_sqlite_records_without_json_file():
    ...

def test_result_center_works_when_result_index_is_backed_by_sqlite():
    ...

def test_local_paper_account_overview_works_without_account_json_files():
    ...
```

- [ ] **Step 2: Run the targeted tests to verify the current gaps**

Run: `PYTHONPATH=src python3 -m unittest tests.test_strategy_state tests.test_strategy_registry tests.test_web tests.test_local_paper -q`
Expected: FAIL because the current stores still depend on JSON-backed runtime files

- [ ] **Step 3: Add minimal test helpers/fixtures only**

```python
def _seed_sqlite_state(store, ...):
    ...
```

```python
def _seed_local_paper_sqlite(store, ...):
    ...
```

- [ ] **Step 4: Re-run the same targeted tests**

Run: `PYTHONPATH=src python3 -m unittest tests.test_strategy_state tests.test_strategy_registry tests.test_web tests.test_local_paper -q`
Expected: still FAIL, but now failures should point at production persistence behavior instead of missing test scaffolding

- [ ] **Step 5: Commit**

```bash
git add tests/test_strategy_state.py tests/test_strategy_registry.py tests/test_web.py tests/test_local_paper.py
git commit -m "test: lock sqlite runtime migration boundaries"
```

### Task 2: Extend SQLiteStateStore with Strategy/Index/Paper Tables

**Files:**
- Modify: `src/stock_quantification/sqlite_state.py`
- Test: `tests/test_sqlite_state.py`

- [ ] **Step 1: Write the failing repository-level tests**

```python
def test_strategy_state_round_trip_uses_sqlite_tables():
    ...

def test_strategy_registry_round_trip_uses_sqlite_tables():
    ...

def test_result_index_round_trip_uses_sqlite_tables():
    ...

def test_paper_automation_state_round_trip_uses_sqlite_tables():
    ...

def test_local_paper_account_and_ledger_round_trip_uses_sqlite_tables():
    ...
```

- [ ] **Step 2: Run the new SQLite tests**

Run: `PYTHONPATH=src python3 -m unittest tests.test_sqlite_state -q`
Expected: FAIL because the schema/repository methods do not exist yet

- [ ] **Step 3: Add the new tables to `_initialize()`**

```python
CREATE TABLE IF NOT EXISTS strategy_market_state (...);
CREATE TABLE IF NOT EXISTS strategy_registry_records (...);
CREATE TABLE IF NOT EXISTS result_index_records (...);
CREATE TABLE IF NOT EXISTS paper_automation_state (...);
CREATE TABLE IF NOT EXISTS local_paper_accounts (...);
CREATE TABLE IF NOT EXISTS local_paper_positions (...);
CREATE TABLE IF NOT EXISTS local_paper_ledger_entries (...);
CREATE TABLE IF NOT EXISTS local_paper_nav_history (...);
```

- [ ] **Step 4: Add typed CRUD helpers on `SQLiteStateStore`**

```python
def load_strategy_state(self) -> Dict[str, Any]: ...
def save_market_strategy_state(self, market: str, payload: Dict[str, Any]) -> None: ...
def list_strategy_registry_records(self, market: Optional[str] = None) -> List[Dict[str, Any]]: ...
def upsert_strategy_registry_record(self, record: Dict[str, Any]) -> None: ...
def list_result_index_records(self, ...) -> List[Dict[str, Any]]: ...
def upsert_result_index_record(self, record: Dict[str, Any]) -> None: ...
def load_paper_automation_state(self) -> Dict[str, Any]: ...
def save_paper_automation_state(self, payload: Dict[str, Any]) -> None: ...
def load_local_paper_account(self, account_id: str) -> Optional[Dict[str, Any]]: ...
def save_local_paper_account(self, payload: Dict[str, Any]) -> None: ...
def append_local_paper_ledger_entries(self, account_id: str, entries: Iterable[Dict[str, Any]]) -> None: ...
def load_local_paper_ledger(self, account_id: str) -> Dict[str, Any]: ...
```

- [ ] **Step 5: Add one-time legacy import helpers**

```python
def import_legacy_strategy_state_json(self, base_dir: Path) -> None: ...
def import_legacy_strategy_registry_json(self, base_dir: Path) -> None: ...
def import_legacy_result_index_json(self, base_dir: Path) -> None: ...
def import_legacy_paper_automation_json(self, base_dir: Path) -> None: ...
def import_legacy_local_paper_account_json(self, base_dir: Path, account_id: str) -> None: ...
```

- [ ] **Step 6: Re-run the SQLite tests**

Run: `PYTHONPATH=src python3 -m unittest tests.test_sqlite_state -q`
Expected: PASS for the new table/repository tests and no regression in existing queue/cache tests

- [ ] **Step 7: Commit**

```bash
git add src/stock_quantification/sqlite_state.py tests/test_sqlite_state.py
git commit -m "feat: add sqlite repositories for runtime state"
```

### Task 3: Migrate StrategyStateStore to SQLite-First Persistence

**Files:**
- Modify: `src/stock_quantification/strategy_state.py`
- Test: `tests/test_strategy_state.py`

- [ ] **Step 1: Write the failing store tests**

```python
def test_load_state_imports_legacy_json_once_then_uses_sqlite():
    ...

def test_set_current_execution_preset_writes_sqlite_without_strategy_state_json():
    ...
```

- [ ] **Step 2: Run the focused strategy-state tests**

Run: `PYTHONPATH=src python3 -m unittest tests.test_strategy_state -q`
Expected: FAIL because `StrategyStateStore` still reads/writes `web/strategy_state.json`

- [ ] **Step 3: Replace JSON persistence with `SQLiteStateStore`**

```python
class StrategyStateStore:
    def __init__(...):
        self._sqlite = SQLiteStateStore(self._base_dir)
```

```python
def load_state(self) -> Dict[str, Any]:
    state = self._sqlite.load_strategy_state()
    if state_is_empty(...):
        self._sqlite.import_legacy_strategy_state_json(self._base_dir)
        state = self._sqlite.load_strategy_state()
    return _normalize_state(state)
```

- [ ] **Step 4: Update mutation methods to write through SQLite only**

```python
self._sqlite.save_market_strategy_state(market_enum.value, payload)
```

- [ ] **Step 5: Re-run the strategy-state tests**

Run: `PYTHONPATH=src python3 -m unittest tests.test_strategy_state -q`
Expected: PASS with no new `strategy_state.json` writes required

- [ ] **Step 6: Commit**

```bash
git add src/stock_quantification/strategy_state.py tests/test_strategy_state.py
git commit -m "refactor: back strategy state with sqlite"
```

### Task 4: Migrate StrategyRegistryStore to SQLite-First Persistence

**Files:**
- Modify: `src/stock_quantification/strategy_registry.py`
- Modify: `src/stock_quantification/strategy_catalog.py`
- Test: `tests/test_strategy_registry.py`

- [ ] **Step 1: Write the failing registry tests**

```python
def test_promote_factor_backtest_candidate_persists_to_sqlite():
    ...

def test_list_market_presets_reads_registered_candidates_from_sqlite():
    ...
```

- [ ] **Step 2: Run the focused registry tests**

Run: `PYTHONPATH=src python3 -m unittest tests.test_strategy_registry -q`
Expected: FAIL because `StrategyRegistryStore` still writes `web/strategy_registry.json`

- [ ] **Step 3: Back `StrategyRegistryStore` with SQLite**

```python
class StrategyRegistryStore:
    def __init__(...):
        self._sqlite = SQLiteStateStore(self._base_dir)
```

```python
def load_state(self) -> Dict[str, Any]:
    rows = self._sqlite.list_strategy_registry_records()
    if not rows:
        self._sqlite.import_legacy_strategy_registry_json(self._base_dir)
        rows = self._sqlite.list_strategy_registry_records()
    return _rows_to_market_state(rows)
```

- [ ] **Step 4: Update promotion/upsert to use SQLite records**

```python
self._sqlite.upsert_strategy_registry_record(candidate)
```

- [ ] **Step 5: Re-run the registry tests**

Run: `PYTHONPATH=src python3 -m unittest tests.test_strategy_registry -q`
Expected: PASS and existing market preset behavior remains unchanged

- [ ] **Step 6: Commit**

```bash
git add src/stock_quantification/strategy_registry.py src/stock_quantification/strategy_catalog.py tests/test_strategy_registry.py
git commit -m "refactor: back strategy registry with sqlite"
```

### Task 5: Migrate Result Index Metadata to SQLite While Keeping Artifact Files

**Files:**
- Modify: `src/stock_quantification/result_index.py`
- Modify: `src/stock_quantification/web.py`
- Test: `tests/test_web.py`
- Test: `tests/test_artifacts.py`

- [ ] **Step 1: Write the failing index/history tests**

```python
def test_record_result_writes_index_metadata_to_sqlite():
    ...

def test_results_views_render_when_result_index_json_is_absent():
    ...
```

- [ ] **Step 2: Run the focused result-index tests**

Run: `PYTHONPATH=src python3 -m unittest tests.test_web tests.test_artifacts -q`
Expected: FAIL because `result_index.py` still depends on `web/result_index.json`

- [ ] **Step 3: Move `record_result()` / `list_results()` onto SQLite metadata**

```python
sqlite = SQLiteStateStore(base_dir)
sqlite.upsert_result_index_record(normalized)
```

```python
rows = sqlite.list_result_index_records(...)
```

- [ ] **Step 4: Keep artifact lookup file-based**

```python
artifact_path = row["artifacts"]["json"]
payload = read_json_artifact(base_dir, artifact_path)
```

- [ ] **Step 5: Re-run the result-index tests**

Run: `PYTHONPATH=src python3 -m unittest tests.test_web tests.test_artifacts -q`
Expected: PASS with history/detail pages still opening artifact files correctly

- [ ] **Step 6: Commit**

```bash
git add src/stock_quantification/result_index.py src/stock_quantification/web.py tests/test_web.py tests/test_artifacts.py
git commit -m "refactor: store result index metadata in sqlite"
```

### Task 6: Migrate Paper Automation State to SQLite

**Files:**
- Modify: `src/stock_quantification/web.py`
- Test: `tests/test_web.py`

- [ ] **Step 1: Write the failing automation-state tests**

```python
def test_paper_automation_state_reads_from_sqlite_without_json_file():
    ...

def test_auto_run_updates_sqlite_automation_state_after_success():
    ...
```

- [ ] **Step 2: Run the focused web tests**

Run: `PYTHONPATH=src python3 -m unittest tests.test_web -q`
Expected: FAIL because automation status still uses `paper_automation_state.json`

- [ ] **Step 3: Replace JSON automation state reads/writes with `SQLiteStateStore`**

```python
automation_state = sqlite.load_paper_automation_state()
sqlite.save_paper_automation_state(updated_state)
```

- [ ] **Step 4: Re-run the web tests**

Run: `PYTHONPATH=src python3 -m unittest tests.test_web -q`
Expected: PASS with the paper page and automation loop behavior unchanged

- [ ] **Step 5: Commit**

```bash
git add src/stock_quantification/web.py tests/test_web.py
git commit -m "refactor: store paper automation state in sqlite"
```

### Task 7: Migrate Local Paper Account Snapshots to SQLite

**Files:**
- Modify: `src/stock_quantification/local_paper.py`
- Test: `tests/test_local_paper.py`

- [ ] **Step 1: Write the failing local-paper account tests**

```python
def test_sync_account_state_creates_sqlite_account_without_account_json():
    ...

def test_account_overview_reconstructs_positions_from_sqlite_snapshot():
    ...
```

- [ ] **Step 2: Run the focused local-paper tests**

Run: `PYTHONPATH=src python3 -m unittest tests.test_local_paper -q`
Expected: FAIL because account sync/overview still depend on per-account `account.json`

- [ ] **Step 3: Back account snapshot reads/writes with SQLite**

```python
def sync_account_state(...):
    existing = self._sqlite.load_local_paper_account(account_id)
```

```python
def _write_account(self, account_state: AccountState) -> None:
    self._sqlite.save_local_paper_account(_serialize_account_state(account_state))
```

- [ ] **Step 4: Keep public API unchanged while removing JSON dependency**

```python
def list_accounts(self) -> List[str]:
    return self._sqlite.list_local_paper_accounts()
```

- [ ] **Step 5: Re-run the local-paper tests**

Run: `PYTHONPATH=src python3 -m unittest tests.test_local_paper -q`
Expected: PASS with account sync/reset/overview semantics preserved

- [ ] **Step 6: Commit**

```bash
git add src/stock_quantification/local_paper.py tests/test_local_paper.py
git commit -m "refactor: store local paper accounts in sqlite"
```

### Task 8: Migrate Local Paper Ledger and NAV History to SQLite

**Files:**
- Modify: `src/stock_quantification/local_paper.py`
- Modify: `src/stock_quantification/broker_ledger.py`
- Test: `tests/test_local_paper.py`
- Test: `tests/test_integration_flow.py`

- [ ] **Step 1: Write the failing ledger tests**

```python
def test_record_execution_appends_sqlite_ledger_entries_and_nav_history():
    ...

def test_liquidate_unknown_positions_persists_cleanup_to_sqlite_ledger():
    ...

def test_recent_trades_and_nav_history_render_from_sqlite_ledger():
    ...
```

- [ ] **Step 2: Run the ledger-focused tests**

Run: `PYTHONPATH=src python3 -m unittest tests.test_local_paper tests.test_integration_flow -q`
Expected: FAIL because trade/nav history still depend on `ledger.json`

- [ ] **Step 3: Replace ledger JSON mutation with append-only SQLite writes**

```python
self._sqlite.append_local_paper_ledger_entries(account_id, trade_records)
self._sqlite.append_local_paper_nav_history(account_id, [nav_snapshot])
```

- [ ] **Step 4: Rebuild overview/trade history from SQLite**

```python
ledger = self._sqlite.load_local_paper_ledger(account_id)
trades = ledger["trades"]
nav_history = ledger["nav_history"]
```

- [ ] **Step 5: Keep run artifact output file-based**

```python
run_json_path = write_json_artifact(...)
run_md_path = write_text_artifact(...)
```

- [ ] **Step 6: Re-run the local-paper/integration tests**

Run: `PYTHONPATH=src python3 -m unittest tests.test_local_paper tests.test_integration_flow -q`
Expected: PASS with fills, NAV, cleanup events, and run artifacts unchanged from a user perspective

- [ ] **Step 7: Commit**

```bash
git add src/stock_quantification/local_paper.py src/stock_quantification/broker_ledger.py tests/test_local_paper.py tests/test_integration_flow.py
git commit -m "refactor: store local paper ledger in sqlite"
```

### Task 9: Remove Legacy JSON Runtime Writes and Update Documentation

**Files:**
- Modify: `src/stock_quantification/strategy_state.py`
- Modify: `src/stock_quantification/strategy_registry.py`
- Modify: `src/stock_quantification/result_index.py`
- Modify: `src/stock_quantification/local_paper.py`
- Modify: `README.md`
- Modify: `.gitignore`
- Test: `tests/test_web.py`
- Test: `tests/test_local_paper.py`

- [ ] **Step 1: Write the failing cleanup/documentation tests**

```python
def test_runtime_state_operations_do_not_create_legacy_json_files():
    ...
```

- [ ] **Step 2: Run the cleanup tests**

Run: `PYTHONPATH=src python3 -m unittest tests.test_web tests.test_local_paper -q`
Expected: FAIL because legacy JSON writes are still present in some code paths

- [ ] **Step 3: Remove runtime JSON write paths**

```python
# delete calls to write_json_artifact(..., "web/strategy_state.json", ...)
# delete calls to write_json_artifact(..., "web/strategy_registry.json", ...)
# delete calls to write_json_artifact(..., "web/result_index.json", ...)
# delete calls to write_json_artifact(..., "local_paper/.../account.json", ...)
# delete calls to write_json_artifact(..., "local_paper/.../ledger.json", ...)
```

- [ ] **Step 4: Update docs and ignore rules**

```text
README: runtime state lives in SQLite; artifacts remain file-based
.gitignore: drop legacy runtime JSON assumptions if no longer needed
```

- [ ] **Step 5: Run the full regression suite**

Run: `PYTHONPATH=src python3 -m unittest discover -s tests -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/stock_quantification/strategy_state.py src/stock_quantification/strategy_registry.py src/stock_quantification/result_index.py src/stock_quantification/local_paper.py README.md .gitignore tests/test_web.py tests/test_local_paper.py
git commit -m "refactor: finalize sqlite runtime state migration"
```

### Task 10: End-to-End Verification and Manual Smoke Test

**Files:**
- Modify: `docs/superpowers/specs/2026-05-15-runtime-state-sqlite-migration-design.md`
- Modify: `README.md`

- [ ] **Step 1: Run the focused runtime-state suite**

Run: `PYTHONPATH=src python3 -m unittest tests.test_sqlite_state tests.test_strategy_state tests.test_strategy_registry tests.test_local_paper tests.test_web tests.test_integration_flow -q`
Expected: PASS

- [ ] **Step 2: Run the full suite**

Run: `PYTHONPATH=src python3 -m unittest discover -s tests -q`
Expected: PASS

- [ ] **Step 3: Start the local web app and smoke test the key flows**

Run: `env PYTHONPATH=src python3 -m stock_quantification.web`
Expected: service starts successfully

- [ ] **Step 4: Verify the key UI/runtime flows manually**

Check:
- `策略实验 / 历史` still loads
- `策略任务 / 历史` still loads
- `结果中心` still resolves detail pages
- `模拟盘` still shows holdings/trades/NAV
- no new runtime JSON state files are required for these flows

- [ ] **Step 5: Commit final doc sync if needed**

```bash
git add docs/superpowers/specs/2026-05-15-runtime-state-sqlite-migration-design.md README.md
git commit -m "docs: finalize sqlite runtime migration rollout notes"
```
