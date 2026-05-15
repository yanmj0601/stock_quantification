from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Mapping, Sequence

from stock_quantification.sqlite_state import SQLiteStateStore


def _connect_runtime_sqlite(base_dir: str | Path) -> sqlite3.Connection:
    store = SQLiteStateStore(base_dir)
    conn = sqlite3.connect(store.db_path)
    conn.row_factory = sqlite3.Row
    return conn


def seed_strategy_state_sqlite(
    base_dir: str | Path,
    market: str,
    *,
    champion_preset_id: str | None,
    challenger_preset_id: str | None,
    current_execution_preset_id: str | None,
) -> None:
    payload = {
        "champion_preset_id": champion_preset_id,
        "challenger_preset_id": challenger_preset_id,
        "current_execution_preset_id": current_execution_preset_id,
    }
    with _connect_runtime_sqlite(base_dir) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS strategy_market_state (
                market TEXT PRIMARY KEY,
                champion_preset_id TEXT,
                challenger_preset_id TEXT,
                current_execution_preset_id TEXT,
                state_json TEXT
            )
            """
        )
        conn.execute(
            """
            INSERT OR REPLACE INTO strategy_market_state (
                market,
                champion_preset_id,
                challenger_preset_id,
                current_execution_preset_id,
                state_json
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                str(market),
                champion_preset_id,
                challenger_preset_id,
                current_execution_preset_id,
                json.dumps(payload, ensure_ascii=False, sort_keys=True),
            ),
        )


def seed_strategy_registry_sqlite(base_dir: str | Path, record: Mapping[str, Any]) -> None:
    with _connect_runtime_sqlite(base_dir) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS strategy_registry_records (
                preset_id TEXT PRIMARY KEY,
                market TEXT NOT NULL,
                display_name TEXT,
                family TEXT,
                description TEXT,
                top_n INTEGER,
                alpha_weights_json TEXT,
                policy_overrides_json TEXT,
                source_artifact_path TEXT,
                source_subject_id TEXT,
                source_subject_name TEXT,
                decision TEXT,
                created_at TEXT,
                record_json TEXT
            )
            """
        )
        conn.execute(
            """
            INSERT OR REPLACE INTO strategy_registry_records (
                preset_id,
                market,
                display_name,
                family,
                description,
                top_n,
                alpha_weights_json,
                policy_overrides_json,
                source_artifact_path,
                source_subject_id,
                source_subject_name,
                decision,
                created_at,
                record_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(record["preset_id"]),
                str(record["market"]),
                str(record.get("display_name") or ""),
                str(record.get("family") or ""),
                str(record.get("description") or ""),
                int(record.get("top_n") or 0),
                json.dumps(record.get("alpha_weights") or {}, ensure_ascii=False, sort_keys=True),
                json.dumps(record.get("policy_overrides") or {}, ensure_ascii=False, sort_keys=True),
                record.get("source_artifact_path"),
                record.get("source_subject_id"),
                record.get("source_subject_name"),
                record.get("decision"),
                record.get("created_at"),
                json.dumps(dict(record), ensure_ascii=False, sort_keys=True),
            ),
        )


def seed_result_index_sqlite(base_dir: str | Path, records: Sequence[Mapping[str, Any]]) -> None:
    with _connect_runtime_sqlite(base_dir) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS result_index_records (
                result_id TEXT PRIMARY KEY,
                artifact_kind TEXT NOT NULL,
                market TEXT,
                sort_date TEXT,
                summary_json TEXT,
                artifacts_json TEXT,
                normalized_summary_json TEXT,
                recorded_at TEXT,
                record_json TEXT
            )
            """
        )
        for record in records:
            conn.execute(
                """
                INSERT OR REPLACE INTO result_index_records (
                    result_id,
                    artifact_kind,
                    market,
                    sort_date,
                    summary_json,
                    artifacts_json,
                    normalized_summary_json,
                    recorded_at,
                    record_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(record["result_id"]),
                    str(record.get("artifact_kind") or ""),
                    str(record.get("market") or ""),
                    str(record.get("sort_date") or ""),
                    json.dumps(record.get("summary") or {}, ensure_ascii=False, sort_keys=True),
                    json.dumps(record.get("artifacts") or {}, ensure_ascii=False, sort_keys=True),
                    json.dumps(record.get("normalized_summary") or {}, ensure_ascii=False, sort_keys=True),
                    str(record.get("recorded_at") or record.get("sort_date") or ""),
                    json.dumps(dict(record), ensure_ascii=False, sort_keys=True),
                ),
            )


def seed_local_paper_sqlite_account(
    base_dir: str | Path,
    *,
    account_id: str,
    market: str,
    broker_id: str,
    cash: str,
    buying_power: str,
    positions: Sequence[Mapping[str, Any]],
    trades: Sequence[Mapping[str, Any]],
    nav_history: Sequence[Mapping[str, Any]],
) -> None:
    account_payload = {
        "account_id": account_id,
        "market": market,
        "broker_id": broker_id,
        "cash": cash,
        "buying_power": buying_power,
        "positions": list(positions),
    }
    with _connect_runtime_sqlite(base_dir) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS local_paper_accounts (
                account_id TEXT PRIMARY KEY,
                market TEXT NOT NULL,
                broker_id TEXT NOT NULL,
                cash TEXT NOT NULL,
                buying_power TEXT NOT NULL,
                last_sync_at TEXT,
                account_json TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS local_paper_positions (
                account_id TEXT NOT NULL,
                instrument_id TEXT NOT NULL,
                qty INTEGER NOT NULL,
                avg_cost TEXT NOT NULL,
                last_trade_date TEXT,
                position_json TEXT NOT NULL,
                PRIMARY KEY (account_id, instrument_id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS local_paper_ledger_entries (
                entry_id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id TEXT NOT NULL,
                trade_date TEXT,
                created_at TEXT,
                entry_json TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS local_paper_nav_history (
                account_id TEXT NOT NULL,
                as_of TEXT NOT NULL,
                trade_date TEXT,
                nav TEXT NOT NULL,
                cash TEXT NOT NULL,
                position_value TEXT NOT NULL,
                cumulative_return TEXT NOT NULL,
                nav_json TEXT NOT NULL,
                PRIMARY KEY (account_id, as_of)
            )
            """
        )
        conn.execute(
            """
            INSERT OR REPLACE INTO local_paper_accounts (
                account_id,
                market,
                broker_id,
                cash,
                buying_power,
                last_sync_at,
                account_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                account_id,
                market,
                broker_id,
                cash,
                buying_power,
                None,
                json.dumps(account_payload, ensure_ascii=False, sort_keys=True),
            ),
        )
        for position in positions:
            conn.execute(
                """
                INSERT OR REPLACE INTO local_paper_positions (
                    account_id,
                    instrument_id,
                    qty,
                    avg_cost,
                    last_trade_date,
                    position_json
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    account_id,
                    str(position["instrument_id"]),
                    int(position["qty"]),
                    str(position["avg_cost"]),
                    position.get("last_trade_date"),
                    json.dumps(dict(position), ensure_ascii=False, sort_keys=True),
                ),
            )
        for trade in trades:
            conn.execute(
                """
                INSERT INTO local_paper_ledger_entries (
                    account_id,
                    trade_date,
                    created_at,
                    entry_json
                ) VALUES (?, ?, ?, ?)
                """,
                (
                    account_id,
                    trade.get("trade_date"),
                    trade.get("created_at") or trade.get("trade_date"),
                    json.dumps(dict(trade), ensure_ascii=False, sort_keys=True),
                ),
            )
        for snapshot in nav_history:
            conn.execute(
                """
                INSERT OR REPLACE INTO local_paper_nav_history (
                    account_id,
                    as_of,
                    trade_date,
                    nav,
                    cash,
                    position_value,
                    cumulative_return,
                    nav_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    account_id,
                    str(snapshot["as_of"]),
                    snapshot.get("trade_date"),
                    str(snapshot["nav"]),
                    str(snapshot["cash"]),
                    str(snapshot["position_value"]),
                    str(snapshot["cumulative_return"]),
                    json.dumps(dict(snapshot), ensure_ascii=False, sort_keys=True),
                ),
            )
