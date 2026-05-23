from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import Any


class SQLiteStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        conn = self._connect()
        try:
            yield conn
        except Exception:
            conn.rollback()
            raise
        else:
            conn.commit()
        finally:
            conn.close()

    def initialize(self) -> None:
        with self.connection() as conn:
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
                CREATE TABLE IF NOT EXISTS bar_sync_jobs (
                    id TEXT PRIMARY KEY,
                    market TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    status TEXT NOT NULL,
                    batch_size INTEGER NOT NULL,
                    total_symbols INTEGER NOT NULL,
                    completed_symbols INTEGER NOT NULL,
                    success_symbols INTEGER NOT NULL,
                    failed_symbols INTEGER NOT NULL,
                    progress REAL NOT NULL,
                    failures TEXT NOT NULL,
                    scheduled_for TEXT NOT NULL DEFAULT '',
                    started_at TEXT,
                    finished_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
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
                """
            )


def dumps(value: Any) -> str:
    return json.dumps(_thaw(value), ensure_ascii=False, sort_keys=True)


def loads(value: str) -> Any:
    return json.loads(value)


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw(nested) for key, nested in value.items()}
    if isinstance(value, tuple):
        return [_thaw(nested) for nested in value]
    if isinstance(value, list):
        return [_thaw(nested) for nested in value]
    return value
