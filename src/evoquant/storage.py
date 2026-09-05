from __future__ import annotations

import json
import os
import re
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from typing import Any


class PostgresCursorWrapper:
    def __init__(self, raw_cursor):
        self.raw_cursor = raw_cursor

    def execute(self, sql: str, params: Any = None):
        # 1. 智能拦截并转换 PRAGMA table_info 检查为 PostgreSQL 的 information_schema 系统查询
        m = re.match(r"PRAGMA\s+table_info\((\w+)\)", sql.strip(), re.IGNORECASE)
        if m:
            table_name = m.group(1).lower()
            sql = f"""
            SELECT column_name AS name
            FROM information_schema.columns
            WHERE table_name = '{table_name}'
            """
            self.raw_cursor.execute(sql)
            return self

        # 2. 智能转译 sqlite_master 为 PostgreSQL 的 information_schema.tables
        if "sqlite_master" in sql:
            sql = sql.replace("sqlite_master", "information_schema.tables")
            sql = sql.replace("type = 'table'", "table_schema = 'public'")
            sql = sql.replace("ORDER BY name", "ORDER BY table_name")
            sql = sql.replace("SELECT name", "SELECT table_name AS name")

        # 3. 清理不可用的 SQLite 方言 rowid
        sql = sql.replace(", rowid ASC", "").replace(", rowid DESC", "").replace("rowid ASC", "created_at ASC").replace("rowid DESC", "created_at DESC")

        # 4. 将问号占位符 ? 动态转换为 PostgreSQL 格式 %s
        sql = sql.replace("?", "%s")
        self.raw_cursor.execute(sql, params)
        return self

    def executemany(self, sql: str, seq_of_parameters: Any):
        sql = sql.replace("?", "%s")
        self.raw_cursor.executemany(sql, seq_of_parameters)
        return self

    def fetchone(self):
        return self.raw_cursor.fetchone()

    def fetchall(self):
        return self.raw_cursor.fetchall()

    @property
    def rowcount(self):
        return self.raw_cursor.rowcount


class PostgresConnectionWrapper:
    def __init__(self, raw_conn):
        self.raw_conn = raw_conn

    def cursor(self):
        import psycopg2.extras
        raw_cur = self.raw_conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        return PostgresCursorWrapper(raw_cur)

    def execute(self, sql: str, params: Any = None):
        cur = self.cursor()
        cur.execute(sql, params)
        return cur

    def executescript(self, script: str):
        script = script.replace("REAL", "DOUBLE PRECISION")
        script = script.replace("INTEGER", "BIGINT")
        cur = self.cursor()
        cur.raw_cursor.execute(script)
        return cur

    def executemany(self, sql: str, seq_of_parameters: Any):
        cur = self.cursor()
        cur.executemany(sql, seq_of_parameters)
        return cur

    def commit(self):
        self.raw_conn.commit()

    def rollback(self):
        self.raw_conn.rollback()

    def close(self):
        self.raw_conn.close()


class PostgreSQLStore:
    def __init__(self, dsn: str | None = None):
        self.dsn = dsn or os.environ.get(
            "EVOQUANT_DB_URL",
            "postgresql://postgres:password@192.168.124.18:45869/evoquant"
        )
        self.initialize()

    def _connect(self):
        import psycopg2
        return psycopg2.connect(self.dsn)

    @contextmanager
    def connection(self) -> Iterator[PostgresConnectionWrapper]:
        conn = self._connect()
        wrapped = PostgresConnectionWrapper(conn)
        try:
            yield wrapped
        except Exception:
            wrapped.rollback()
            raise
        else:
            wrapped.commit()
        finally:
            wrapped.close()

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
                    version BIGINT NOT NULL,
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
                    tradable BIGINT NOT NULL,
                    lot_size BIGINT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (symbol, market)
                );
                CREATE TABLE IF NOT EXISTS market_bars (
                    symbol TEXT NOT NULL,
                    market TEXT NOT NULL,
                    session TEXT NOT NULL,
                    open DOUBLE PRECISION NOT NULL,
                    high DOUBLE PRECISION NOT NULL,
                    low DOUBLE PRECISION NOT NULL,
                    close DOUBLE PRECISION NOT NULL,
                    volume DOUBLE PRECISION NOT NULL,
                    amount DOUBLE PRECISION NOT NULL,
                    adjusted BIGINT NOT NULL,
                    suspended BIGINT NOT NULL,
                    limit_up BIGINT NOT NULL,
                    limit_down BIGINT NOT NULL,
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
                    total_symbols BIGINT NOT NULL,
                    success_symbols BIGINT NOT NULL,
                    failed_symbols BIGINT NOT NULL,
                    coverage DOUBLE PRECISION NOT NULL,
                    failures TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS market_quality_reports (
                    id TEXT PRIMARY KEY,
                    sync_job_id TEXT NOT NULL,
                    market TEXT NOT NULL,
                    missing_bars BIGINT NOT NULL,
                    duplicate_bars BIGINT NOT NULL,
                    price_anomalies BIGINT NOT NULL,
                    suspended_count BIGINT NOT NULL,
                    limit_up_count BIGINT NOT NULL,
                    limit_down_count BIGINT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS bar_sync_jobs (
                    id TEXT PRIMARY KEY,
                    market TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    status TEXT NOT NULL,
                    batch_size BIGINT NOT NULL,
                    total_symbols BIGINT NOT NULL,
                    completed_symbols BIGINT NOT NULL,
                    success_symbols BIGINT NOT NULL,
                    failed_symbols BIGINT NOT NULL,
                    progress DOUBLE PRECISION NOT NULL,
                    failures TEXT NOT NULL,
                    target_symbols TEXT NOT NULL DEFAULT '[]',
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
                    close DOUBLE PRECISION NOT NULL,
                    signal TEXT NOT NULL,
                    score DOUBLE PRECISION NOT NULL,
                    target_weight DOUBLE PRECISION NOT NULL,
                    reason TEXT NOT NULL,
                    risk_flags TEXT NOT NULL,
                    as_of_date TEXT NOT NULL,
                    rank BIGINT NOT NULL,
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
                    target_weight DOUBLE PRECISION NOT NULL,
                    current_weight DOUBLE PRECISION NOT NULL,
                    estimated_quantity DOUBLE PRECISION NOT NULL,
                    reference_price DOUBLE PRECISION NOT NULL,
                    reason TEXT NOT NULL,
                    risk_flags TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS schedule_configs (
                    id TEXT PRIMARY KEY,
                    market TEXT NOT NULL,
                    enabled BIGINT NOT NULL,
                    timezone TEXT NOT NULL,
                    run_time TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                """
            )
            _ensure_column(
                conn,
                "bar_sync_jobs",
                "scheduled_for",
                "VARCHAR NOT NULL DEFAULT ''",
            )
            _ensure_column(
                conn,
                "bar_sync_jobs",
                "target_symbols",
                "VARCHAR NOT NULL DEFAULT '[]'",
            )


Store = PostgreSQLStore


def dumps(value: Any) -> str:
    return json.dumps(_thaw(value), ensure_ascii=False, sort_keys=True)


def loads(value: str) -> Any:
    return json.loads(value)


def _ensure_column(
    conn: Any,
    table_name: str,
    column_name: str,
    column_definition: str,
) -> None:
    columns = {
        row["name"] for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    }
    if column_name not in columns:
        conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_definition}")


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw(nested) for key, nested in value.items()}
    if isinstance(value, tuple):
        return [_thaw(nested) for nested in value]
    if isinstance(value, list):
        return [_thaw(nested) for nested in value]
    return value
