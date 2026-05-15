from __future__ import annotations

from datetime import date, datetime
import json
import os
from pathlib import Path
import sqlite3
from typing import Any, Dict, Iterable, List, Optional
import uuid

from .artifacts import ensure_directory, read_json_artifact


SQLITE_STATE_RELATIVE_PATH = "web/app_state.sqlite3"
LEGACY_OPS_STATE_RELATIVE_PATH = "web/ops_state.json"
LEGACY_TASK_LOG_RELATIVE_PATH = "web/task_logs.json"
LEGACY_RUN_HISTORY_RELATIVE_PATH = "web/run_history.json"
LEGACY_STRATEGY_STATE_RELATIVE_PATH = "web/strategy_state.json"
LEGACY_STRATEGY_REGISTRY_RELATIVE_PATH = "web/strategy_registry.json"
LEGACY_RESULT_INDEX_RELATIVE_PATH = "web/result_index.json"
LEGACY_PAPER_AUTOMATION_RELATIVE_PATH = "web/paper_automation_state.json"
LEGACY_LOCAL_PAPER_ROOT_RELATIVE_PATH = "local_paper"


def _utc_now() -> str:
    return datetime.utcnow().isoformat(timespec="seconds")


def _json_dumps(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def _json_loads(raw_value: Any, fallback: Any) -> Any:
    if not raw_value:
        return fallback
    try:
        return json.loads(str(raw_value))
    except (TypeError, ValueError, json.JSONDecodeError):
        return fallback


class SQLiteStateStore:
    def __init__(self, base_dir: str | Path, relative_path: str = SQLITE_STATE_RELATIVE_PATH) -> None:
        self._base_dir = Path(base_dir)
        self._relative_path = relative_path
        self._db_path = ensure_directory(self._base_dir) / relative_path
        ensure_directory(self._db_path.parent)
        self._initialize()

    @property
    def db_path(self) -> Path:
        return self._db_path

    def enqueue_job(
        self,
        kind: str,
        *,
        metadata: Optional[Dict[str, Any]] = None,
        payload: Optional[Dict[str, Any]] = None,
        status: str = "QUEUED",
        stage: str = "QUEUED",
        detail: str = "Task accepted and waiting in queue.",
    ) -> Dict[str, Any]:
        created_at = _utc_now()
        job_id = self._job_id(kind, created_at, metadata or {}, payload or {})
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO jobs (
                    job_id, kind, status, stage, detail, progress_pct,
                    metadata_json, payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job_id,
                    kind,
                    status,
                    stage,
                    detail,
                    0,
                    _json_dumps(metadata or {}),
                    _json_dumps(payload or {}),
                    created_at,
                ),
            )
        return self.get_job(job_id) or {}

    def claim_next_job(self, *, owner_pid: int, owner_started_at: str) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            running_row = conn.execute(
                "SELECT job_id FROM jobs WHERE status = 'RUNNING' ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
            if running_row is not None:
                conn.commit()
                return None
            row = conn.execute(
                "SELECT job_id FROM jobs WHERE status = 'QUEUED' ORDER BY created_at ASC, rowid ASC LIMIT 1"
            ).fetchone()
            if row is None:
                conn.commit()
                return None
            started_at = _utc_now()
            conn.execute(
                """
                UPDATE jobs
                SET status = 'RUNNING',
                    stage = CASE WHEN stage = 'QUEUED' THEN 'STARTING' ELSE stage END,
                    detail = CASE WHEN detail = 'Task accepted and waiting in queue.' THEN 'Task claimed by background worker.' ELSE detail END,
                    started_at = ?,
                    owner_pid = ?,
                    owner_started_at = ?
                WHERE job_id = ?
                """,
                (started_at, owner_pid, owner_started_at, row["job_id"]),
            )
            claimed = conn.execute("SELECT * FROM jobs WHERE job_id = ?", (row["job_id"],)).fetchone()
            conn.commit()
        return self._row_to_job(claimed) if claimed is not None else None

    def update_job(
        self,
        job_id: str,
        *,
        progress_pct: Optional[int] = None,
        stage: Optional[str] = None,
        detail: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        job = self.get_job(job_id)
        if not job:
            return {}
        merged_metadata = dict(job.get("metadata", {}))
        if metadata:
            merged_metadata.update(metadata)
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE jobs
                SET progress_pct = ?,
                    stage = ?,
                    detail = ?,
                    metadata_json = ?
                WHERE job_id = ?
                """,
                (
                    max(0, min(100, int(progress_pct if progress_pct is not None else job.get("progress_pct", 0)))),
                    stage if stage is not None else job.get("stage", ""),
                    detail if detail is not None else job.get("detail", ""),
                    _json_dumps(merged_metadata),
                    job_id,
                ),
            )
        return self.get_job(job_id) or {}

    def finish_job(
        self,
        job_id: str,
        *,
        status: str,
        detail: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        job = self.get_job(job_id)
        if not job:
            return {}
        merged_metadata = dict(job.get("metadata", {}))
        if metadata:
            merged_metadata["result_metadata"] = metadata
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE jobs
                SET status = ?,
                    detail = ?,
                    progress_pct = 100,
                    finished_at = ?,
                    metadata_json = ?
                WHERE job_id = ?
                """,
                (
                    status,
                    detail or job.get("detail", ""),
                    _utc_now(),
                    _json_dumps(merged_metadata),
                    job_id,
                ),
            )
        return self.get_job(job_id) or {}

    def append_event(
        self,
        *,
        category: str,
        action: str,
        status: str,
        detail: str,
        metadata: Optional[Dict[str, Any]] = None,
        job_id: Optional[str] = None,
        created_at: Optional[str] = None,
    ) -> Dict[str, Any]:
        created_at = str(created_at or _utc_now())
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO job_events (
                    job_id, category, action, status, detail, metadata_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (job_id, category, action, status, detail, _json_dumps(metadata or {}), created_at),
            )
            event_id = int(cursor.lastrowid)
        return {
            "event_id": event_id,
            "job_id": job_id,
            "category": category,
            "action": action,
            "status": status,
            "detail": detail,
            "metadata": metadata or {},
            "created_at": created_at,
        }

    def list_events(self, limit: int = 400) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM job_events ORDER BY event_id DESC LIMIT ?",
                (max(1, int(limit)),),
            ).fetchall()
        return [self._row_to_event(row) for row in reversed(rows)]

    def append_run_history(self, records: Iterable[Dict[str, Any]]) -> None:
        rows = [dict(record) for record in records if isinstance(record, dict)]
        if not rows:
            return
        with self._connect() as conn:
            for record in rows:
                run_instance_id = str(record.get("run_instance_id") or self._job_id("run-history", _utc_now(), record, {}))
                conn.execute(
                    """
                    INSERT OR REPLACE INTO run_history (
                        run_instance_id, recorded_at, record_json
                    ) VALUES (?, ?, ?)
                    """,
                    (run_instance_id, _utc_now(), _json_dumps(record)),
                )

    def list_run_history(self, limit: int = 200) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT history_id, recorded_at, record_json FROM run_history ORDER BY history_id DESC LIMIT ?",
                (max(1, int(limit)),),
            ).fetchall()
        results: List[Dict[str, Any]] = []
        for row in reversed(rows):
            payload = _json_loads(row["record_json"], {})
            if isinstance(payload, dict):
                payload["history_id"] = int(row["history_id"])
                if not payload.get("created_at"):
                    payload["created_at"] = str(row["recorded_at"])
                if not payload.get("recorded_at"):
                    payload["recorded_at"] = str(row["recorded_at"])
                results.append(payload)
        return results

    def load_heartbeats(self) -> Dict[str, str]:
        payload = self.get_kv("heartbeats", {})
        return payload if isinstance(payload, dict) else {}

    def save_heartbeat(self, component: str, value: str) -> Dict[str, str]:
        heartbeats = self.load_heartbeats()
        heartbeats[str(component)] = str(value)
        self.set_kv("heartbeats", heartbeats)
        return heartbeats

    def get_kv(self, key: str, fallback: Any = None) -> Any:
        with self._connect() as conn:
            row = conn.execute("SELECT value_json FROM kv_state WHERE key = ?", (key,)).fetchone()
        if row is None:
            return fallback
        return _json_loads(row["value_json"], fallback)

    def set_kv(self, key: str, value: Any) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO kv_state (key, value_json, updated_at) VALUES (?, ?, ?)",
                (key, _json_dumps(value), _utc_now()),
            )

    def delete_kv(self, key: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM kv_state WHERE key = ?", (key,))

    def cache_market_bars(
        self,
        *,
        market: str,
        symbol: str,
        assetclass: str,
        instrument_id: str,
        asset_type: str,
        currency: str,
        exchange: str,
        display_name: str,
        bars: Iterable[Dict[str, Any]],
        source: str,
        fetched_at: Optional[str] = None,
    ) -> None:
        rows = [dict(row) for row in bars if isinstance(row, dict)]
        if not rows:
            return
        resolved_fetched_at = str(fetched_at or _utc_now())
        with self._connect() as conn:
            for row in rows:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO market_bars (
                        market, symbol, assetclass, trade_date, instrument_id, asset_type,
                        currency, exchange, display_name, open_price, close_price,
                        high_price, low_price, volume, turnover, adjustment_flag,
                        fetched_at, source
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(market),
                        str(symbol),
                        str(assetclass),
                        str(row["trade_date"]),
                        str(instrument_id),
                        str(asset_type),
                        str(currency),
                        str(exchange),
                        str(display_name),
                        str(row["open_price"]),
                        str(row["close_price"]),
                        str(row["high_price"]),
                        str(row["low_price"]),
                        int(row["volume"]),
                        str(row["turnover"]),
                        str(row.get("adjustment_flag") or ""),
                        resolved_fetched_at,
                        str(source),
                    ),
                )

    def load_market_bars(
        self,
        *,
        market: str,
        symbol: str,
        assetclass: str,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> List[Dict[str, Any]]:
        clauses = ["market = ?", "symbol = ?", "assetclass = ?"]
        params: List[Any] = [str(market), str(symbol), str(assetclass)]
        if start_date is not None:
            clauses.append("trade_date >= ?")
            params.append(start_date.isoformat())
        if end_date is not None:
            clauses.append("trade_date <= ?")
            params.append(end_date.isoformat())
        query = (
            "SELECT * FROM market_bars WHERE "
            + " AND ".join(clauses)
            + " ORDER BY trade_date ASC"
        )
        with self._connect() as conn:
            rows = conn.execute(query, tuple(params)).fetchall()
        return [
            {
                "market": row["market"],
                "symbol": row["symbol"],
                "assetclass": row["assetclass"],
                "trade_date": row["trade_date"],
                "instrument_id": row["instrument_id"],
                "asset_type": row["asset_type"],
                "currency": row["currency"],
                "exchange": row["exchange"],
                "display_name": row["display_name"],
                "open_price": row["open_price"],
                "close_price": row["close_price"],
                "high_price": row["high_price"],
                "low_price": row["low_price"],
                "volume": int(row["volume"] or 0),
                "turnover": row["turnover"],
                "adjustment_flag": row["adjustment_flag"] or None,
                "fetched_at": row["fetched_at"],
                "source": row["source"],
            }
            for row in rows
        ]

    def load_strategy_state(self) -> Dict[str, Any]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT market, state_json FROM strategy_market_state ORDER BY market ASC"
            ).fetchall()
        markets: Dict[str, Any] = {}
        for row in rows:
            state = _json_loads(row["state_json"], {})
            markets[str(row["market"])] = state if isinstance(state, dict) else {}
        return {"markets": markets}

    def save_market_strategy_state(self, market: str, payload: Dict[str, Any]) -> None:
        normalized = payload if isinstance(payload, dict) else {}
        with self._connect() as conn:
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
                    normalized.get("champion_preset_id"),
                    normalized.get("challenger_preset_id"),
                    normalized.get("current_execution_preset_id"),
                    _json_dumps(normalized),
                ),
            )

    def list_strategy_registry_records(self, market: Optional[str] = None) -> List[Dict[str, Any]]:
        query = "SELECT * FROM strategy_registry_records"
        params: List[Any] = []
        if market is not None:
            query += " WHERE market = ?"
            params.append(str(market))
        query += " ORDER BY COALESCE(created_at, ''), preset_id"
        with self._connect() as conn:
            rows = conn.execute(query, tuple(params)).fetchall()
        return [self._row_to_strategy_registry_record(row) for row in reversed(rows)]

    def upsert_strategy_registry_record(self, record: Dict[str, Any]) -> None:
        normalized = dict(record) if isinstance(record, dict) else {}
        if not normalized.get("preset_id"):
            raise ValueError("record.preset_id is required")
        with self._connect() as conn:
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
                    str(normalized["preset_id"]),
                    str(normalized.get("market") or ""),
                    str(normalized.get("display_name") or ""),
                    str(normalized.get("family") or ""),
                    str(normalized.get("description") or ""),
                    int(normalized.get("top_n") or 0),
                    _json_dumps(normalized.get("alpha_weights") or {}),
                    _json_dumps(normalized.get("policy_overrides") or {}),
                    normalized.get("source_artifact_path"),
                    normalized.get("source_subject_id"),
                    normalized.get("source_subject_name"),
                    normalized.get("decision"),
                    normalized.get("created_at"),
                    _json_dumps(normalized),
                ),
            )

    def list_result_index_records(
        self,
        *,
        artifact_kind: Optional[str] = None,
        market: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        clauses: List[str] = []
        params: List[Any] = []
        if artifact_kind is not None:
            clauses.append("artifact_kind = ?")
            params.append(str(artifact_kind))
        if market is not None:
            clauses.append("market = ?")
            params.append(str(market))
        query = "SELECT * FROM result_index_records"
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY COALESCE(sort_date, recorded_at, '') DESC, result_id DESC"
        if limit is not None:
            query += " LIMIT ?"
            params.append(max(0, int(limit)))
        with self._connect() as conn:
            rows = conn.execute(query, tuple(params)).fetchall()
        return [self._row_to_result_index_record(row) for row in rows]

    def upsert_result_index_record(self, record: Dict[str, Any]) -> None:
        normalized = dict(record) if isinstance(record, dict) else {}
        if not normalized.get("result_id"):
            raise ValueError("record.result_id is required")
        with self._connect() as conn:
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
                    str(normalized["result_id"]),
                    str(normalized.get("artifact_kind") or ""),
                    str(normalized.get("market") or ""),
                    str(normalized.get("sort_date") or ""),
                    _json_dumps(normalized.get("summary") or {}),
                    _json_dumps(normalized.get("artifacts") or {}),
                    _json_dumps(normalized.get("normalized_summary") or {}),
                    str(normalized.get("recorded_at") or normalized.get("sort_date") or ""),
                    _json_dumps(normalized),
                ),
            )

    def load_paper_automation_state(self) -> Dict[str, Any]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT account_id, state_json FROM paper_automation_state ORDER BY account_id ASC"
            ).fetchall()
        accounts: Dict[str, Any] = {}
        for row in rows:
            state = _json_loads(row["state_json"], {})
            accounts[str(row["account_id"])] = state if isinstance(state, dict) else {}
        return {"accounts": accounts}

    def save_paper_automation_state(self, payload: Dict[str, Any]) -> None:
        accounts = payload.get("accounts") if isinstance(payload, dict) else {}
        normalized_accounts = accounts if isinstance(accounts, dict) else {}
        with self._connect() as conn:
            conn.execute("DELETE FROM paper_automation_state")
            for account_id, state in normalized_accounts.items():
                state_payload = state if isinstance(state, dict) else {}
                conn.execute(
                    """
                    INSERT INTO paper_automation_state (
                        account_id,
                        last_trade_date,
                        last_checked_at,
                        last_status,
                        last_error,
                        state_json
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(account_id),
                        state_payload.get("last_trade_date"),
                        state_payload.get("last_checked_at"),
                        state_payload.get("last_status"),
                        state_payload.get("last_error"),
                        _json_dumps(state_payload),
                    ),
                )

    def load_local_paper_account(self, account_id: str) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            account_row = conn.execute(
                "SELECT * FROM local_paper_accounts WHERE account_id = ?",
                (str(account_id),),
            ).fetchone()
            if account_row is None:
                return None
            position_rows = conn.execute(
                """
                SELECT position_json
                FROM local_paper_positions
                WHERE account_id = ?
                ORDER BY instrument_id ASC
                """,
                (str(account_id),),
            ).fetchall()
        payload = _json_loads(account_row["account_json"], {})
        if not isinstance(payload, dict):
            payload = {}
        payload["account_id"] = str(account_row["account_id"])
        payload["market"] = str(account_row["market"])
        payload["broker_id"] = str(account_row["broker_id"])
        payload["cash"] = str(account_row["cash"])
        payload["buying_power"] = str(account_row["buying_power"])
        payload["starting_cash"] = account_row["starting_cash"]
        payload["last_sync_at"] = account_row["last_sync_at"]
        payload["positions"] = [
            self._row_to_local_paper_position(row["position_json"])
            for row in position_rows
        ]
        return payload

    def save_local_paper_account(self, payload: Dict[str, Any]) -> None:
        normalized = dict(payload) if isinstance(payload, dict) else {}
        account_id = str(normalized.get("account_id") or "").strip()
        if not account_id:
            raise ValueError("payload.account_id is required")
        positions = normalized.get("positions")
        normalized_positions = list(positions) if isinstance(positions, list) else []
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO local_paper_accounts (
                    account_id,
                    market,
                    broker_id,
                    cash,
                    buying_power,
                    starting_cash,
                    last_sync_at,
                    account_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    account_id,
                    str(normalized.get("market") or ""),
                    str(normalized.get("broker_id") or ""),
                    str(normalized.get("cash") or "0"),
                    str(normalized.get("buying_power") or "0"),
                    self._resolve_starting_cash_value(account_id, normalized),
                    normalized.get("last_sync_at"),
                    _json_dumps(normalized),
                ),
            )
            conn.execute("DELETE FROM local_paper_positions WHERE account_id = ?", (account_id,))
            for position in normalized_positions:
                if not isinstance(position, dict) or not position.get("instrument_id"):
                    continue
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
                        int(position.get("qty") or 0),
                        str(position.get("avg_cost") or "0"),
                        position.get("last_trade_date"),
                        _json_dumps(dict(position)),
                    ),
                )

    def append_local_paper_ledger_entries(self, account_id: str, entries: Iterable[Dict[str, Any]]) -> None:
        rows = [dict(entry) for entry in entries if isinstance(entry, dict)]
        if not rows:
            return
        with self._connect() as conn:
            for entry in rows:
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
                        str(account_id),
                        entry.get("trade_date"),
                        entry.get("created_at") or entry.get("trade_date") or _utc_now(),
                        _json_dumps(entry),
                    ),
                )

    def save_local_paper_nav_history(self, account_id: str, snapshots: Iterable[Dict[str, Any]]) -> None:
        rows = [dict(snapshot) for snapshot in snapshots if isinstance(snapshot, dict)]
        if not rows:
            return
        with self._connect() as conn:
            for snapshot in rows:
                if not snapshot.get("as_of"):
                    continue
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
                        str(account_id),
                        str(snapshot["as_of"]),
                        snapshot.get("trade_date"),
                        str(snapshot.get("nav") or "0"),
                        str(snapshot.get("cash") or "0"),
                        str(snapshot.get("position_value") or "0"),
                        str(snapshot.get("cumulative_return") or "0"),
                        _json_dumps(snapshot),
                    ),
                )

    def load_local_paper_ledger(self, account_id: str) -> Dict[str, Any]:
        account = self.load_local_paper_account(account_id)
        with self._connect() as conn:
            trade_rows = conn.execute(
                """
                SELECT entry_json
                FROM local_paper_ledger_entries
                WHERE account_id = ?
                ORDER BY COALESCE(created_at, trade_date, '') ASC, entry_id ASC
                """,
                (str(account_id),),
            ).fetchall()
            nav_rows = conn.execute(
                """
                SELECT nav_json
                FROM local_paper_nav_history
                WHERE account_id = ?
                ORDER BY as_of ASC
                """,
                (str(account_id),),
            ).fetchall()
        return {
            "account_id": str(account_id),
            "market": account.get("market") if isinstance(account, dict) else None,
            "starting_cash": account.get("starting_cash") if isinstance(account, dict) else None,
            "trades": [self._json_row_payload(row["entry_json"]) for row in trade_rows],
            "nav_history": [self._json_row_payload(row["nav_json"]) for row in nav_rows],
        }

    def get_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
        return self._row_to_job(row) if row is not None else None

    def get_active_job(self) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM jobs WHERE status = 'RUNNING' ORDER BY started_at DESC, created_at DESC LIMIT 1"
            ).fetchone()
        return self._row_to_job(row) if row is not None else None

    def list_recent_jobs(self, limit: int = 200) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM jobs
                WHERE status != 'QUEUED'
                ORDER BY COALESCE(finished_at, started_at, created_at) DESC, rowid DESC
                LIMIT ?
                """,
                (max(1, int(limit)),),
            ).fetchall()
        return [self._row_to_job(row) for row in rows]

    def list_queued_jobs(self, limit: int = 200) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM jobs WHERE status = 'QUEUED' ORDER BY created_at ASC, rowid ASC LIMIT ?",
                (max(1, int(limit)),),
            ).fetchall()
        return [self._row_to_job(row) for row in rows]

    def mark_previous_running_jobs_stale(self, *, owner_pid: int, owner_started_at: str) -> None:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT job_id, detail FROM jobs
                WHERE status = 'RUNNING'
                  AND NOT (owner_pid = ? AND owner_started_at = ?)
                """,
                (owner_pid, owner_started_at),
            ).fetchall()
            now = _utc_now()
            for row in rows:
                conn.execute(
                    """
                    UPDATE jobs
                    SET status = 'STALE',
                        detail = ?,
                        progress_pct = 100,
                        finished_at = ?
                    WHERE job_id = ?
                    """,
                    ("Recovered orphaned running job from previous process.", now, row["job_id"]),
                )

    def _initialize(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    job_id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL,
                    status TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    detail TEXT NOT NULL,
                    progress_pct INTEGER NOT NULL DEFAULT 0,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    started_at TEXT,
                    finished_at TEXT,
                    owner_pid INTEGER,
                    owner_started_at TEXT
                );
                CREATE TABLE IF NOT EXISTS job_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT,
                    category TEXT NOT NULL,
                    action TEXT NOT NULL,
                    status TEXT NOT NULL,
                    detail TEXT NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS run_history (
                    history_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_instance_id TEXT NOT NULL UNIQUE,
                    recorded_at TEXT NOT NULL,
                    record_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS kv_state (
                    key TEXT PRIMARY KEY,
                    value_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS market_bars (
                    market TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    assetclass TEXT NOT NULL,
                    trade_date TEXT NOT NULL,
                    instrument_id TEXT NOT NULL,
                    asset_type TEXT NOT NULL,
                    currency TEXT NOT NULL,
                    exchange TEXT NOT NULL,
                    display_name TEXT NOT NULL,
                    open_price TEXT NOT NULL,
                    close_price TEXT NOT NULL,
                    high_price TEXT NOT NULL,
                    low_price TEXT NOT NULL,
                    volume INTEGER NOT NULL,
                    turnover TEXT NOT NULL,
                    adjustment_flag TEXT,
                    fetched_at TEXT NOT NULL,
                    source TEXT NOT NULL,
                    PRIMARY KEY (market, symbol, assetclass, trade_date)
                );
                CREATE INDEX IF NOT EXISTS idx_market_bars_lookup
                ON market_bars (market, symbol, assetclass, trade_date);
                CREATE TABLE IF NOT EXISTS strategy_market_state (
                    market TEXT PRIMARY KEY,
                    champion_preset_id TEXT,
                    challenger_preset_id TEXT,
                    current_execution_preset_id TEXT,
                    state_json TEXT NOT NULL
                );
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
                    record_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_strategy_registry_market_created
                ON strategy_registry_records (market, created_at);
                CREATE TABLE IF NOT EXISTS result_index_records (
                    result_id TEXT PRIMARY KEY,
                    artifact_kind TEXT NOT NULL,
                    market TEXT,
                    sort_date TEXT,
                    summary_json TEXT,
                    artifacts_json TEXT,
                    normalized_summary_json TEXT,
                    recorded_at TEXT,
                    record_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_result_index_lookup
                ON result_index_records (market, artifact_kind, sort_date, recorded_at);
                CREATE TABLE IF NOT EXISTS paper_automation_state (
                    account_id TEXT PRIMARY KEY,
                    last_trade_date TEXT,
                    last_checked_at TEXT,
                    last_status TEXT,
                    last_error TEXT,
                    state_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS local_paper_accounts (
                    account_id TEXT PRIMARY KEY,
                    market TEXT NOT NULL,
                    broker_id TEXT NOT NULL,
                    cash TEXT NOT NULL,
                    buying_power TEXT NOT NULL,
                    starting_cash TEXT,
                    last_sync_at TEXT,
                    account_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS local_paper_positions (
                    account_id TEXT NOT NULL,
                    instrument_id TEXT NOT NULL,
                    qty INTEGER NOT NULL,
                    avg_cost TEXT NOT NULL,
                    last_trade_date TEXT,
                    position_json TEXT NOT NULL,
                    PRIMARY KEY (account_id, instrument_id)
                );
                CREATE TABLE IF NOT EXISTS local_paper_ledger_entries (
                    entry_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    account_id TEXT NOT NULL,
                    trade_date TEXT,
                    created_at TEXT,
                    entry_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_local_paper_ledger_account_created
                ON local_paper_ledger_entries (account_id, created_at, trade_date, entry_id);
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
                );
                CREATE INDEX IF NOT EXISTS idx_local_paper_nav_account_asof
                ON local_paper_nav_history (account_id, as_of);
                """
            )
            self._ensure_column(conn, "local_paper_accounts", "starting_cash", "TEXT")
        if self.get_kv("legacy_import_complete", False):
            return
        self._import_legacy_json_state()
        self.set_kv("legacy_import_complete", True)

    def _import_legacy_json_state(self) -> None:
        ops_payload = read_json_artifact(self._base_dir, LEGACY_OPS_STATE_RELATIVE_PATH)
        if isinstance(ops_payload, dict):
            heartbeats = ops_payload.get("heartbeats")
            if isinstance(heartbeats, dict):
                self.set_kv("heartbeats", heartbeats)
            active_job = ops_payload.get("active_job")
            if isinstance(active_job, dict):
                imported = self._normalize_legacy_job(active_job, default_status="STALE")
                self._import_job(imported)
            for row in ops_payload.get("job_history", []):
                if isinstance(row, dict):
                    self._import_job(self._normalize_legacy_job(row))
            for row in ops_payload.get("audit_events", []):
                if isinstance(row, dict):
                    self.append_event(
                        category=str(row.get("category", "runtime")),
                        action=str(row.get("action", "legacy")),
                        status=str(row.get("status", "INFO")),
                        detail=str(row.get("detail", "")),
                        metadata=row.get("metadata") if isinstance(row.get("metadata"), dict) else {},
                        created_at=str(row.get("created_at") or ""),
                    )
        task_payload = read_json_artifact(self._base_dir, LEGACY_TASK_LOG_RELATIVE_PATH)
        if isinstance(task_payload, dict):
            for row in task_payload.get("entries", []):
                if isinstance(row, dict):
                    self.append_event(
                        category=str(row.get("category", "runtime")),
                        action=str(row.get("action", "legacy")),
                        status=str(row.get("status", "INFO")),
                        detail=str(row.get("detail", "")),
                        metadata=row.get("metadata") if isinstance(row.get("metadata"), dict) else {},
                        created_at=str(row.get("created_at") or ""),
                    )
        run_payload = read_json_artifact(self._base_dir, LEGACY_RUN_HISTORY_RELATIVE_PATH)
        if isinstance(run_payload, dict):
            self.append_run_history(row for row in run_payload.get("records", []) if isinstance(row, dict))
        self.import_legacy_strategy_state_json(self._base_dir)
        self.import_legacy_strategy_registry_json(self._base_dir)
        self.import_legacy_result_index_json(self._base_dir)
        self.import_legacy_paper_automation_json(self._base_dir)
        local_paper_root = self._base_dir / LEGACY_LOCAL_PAPER_ROOT_RELATIVE_PATH
        if local_paper_root.exists():
            for account_path in sorted(local_paper_root.glob("*/account.json")):
                self.import_legacy_local_paper_account_json(local_paper_root, account_path.parent.name)

    def import_legacy_strategy_state_json(self, base_dir: Path) -> None:
        payload = self._read_legacy_json(base_dir, LEGACY_STRATEGY_STATE_RELATIVE_PATH)
        markets = payload.get("markets") if isinstance(payload, dict) else None
        if not isinstance(markets, dict):
            return
        for market, state in markets.items():
            if isinstance(state, dict):
                self.save_market_strategy_state(str(market), state)

    def import_legacy_strategy_registry_json(self, base_dir: Path) -> None:
        payload = self._read_legacy_json(base_dir, LEGACY_STRATEGY_REGISTRY_RELATIVE_PATH)
        markets = payload.get("markets") if isinstance(payload, dict) else None
        if not isinstance(markets, dict):
            return
        for rows in markets.values():
            if not isinstance(rows, list):
                continue
            for row in rows:
                if isinstance(row, dict) and row.get("preset_id"):
                    self.upsert_strategy_registry_record(dict(row))

    def import_legacy_result_index_json(self, base_dir: Path) -> None:
        payload = self._read_legacy_json(base_dir, LEGACY_RESULT_INDEX_RELATIVE_PATH)
        records = payload.get("records") if isinstance(payload, dict) else None
        if not isinstance(records, list):
            return
        for row in records:
            if isinstance(row, dict) and row.get("result_id"):
                self.upsert_result_index_record(dict(row))

    def import_legacy_paper_automation_json(self, base_dir: Path) -> None:
        payload = self._read_legacy_json(base_dir, LEGACY_PAPER_AUTOMATION_RELATIVE_PATH)
        accounts = payload.get("accounts") if isinstance(payload, dict) else None
        if not isinstance(accounts, dict):
            return
        with self._connect() as conn:
            for account_id, state in accounts.items():
                state_payload = state if isinstance(state, dict) else {}
                conn.execute(
                    """
                    INSERT OR REPLACE INTO paper_automation_state (
                        account_id,
                        last_trade_date,
                        last_checked_at,
                        last_status,
                        last_error,
                        state_json
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(account_id),
                        state_payload.get("last_trade_date"),
                        state_payload.get("last_checked_at"),
                        state_payload.get("last_status"),
                        state_payload.get("last_error"),
                        _json_dumps(state_payload),
                    ),
                )

    def import_legacy_local_paper_account_json(self, base_dir: Path, account_id: str) -> None:
        account_payload = self._read_legacy_json(base_dir, f"{account_id}/account.json")
        if not isinstance(account_payload, dict):
            return
        ledger_payload = self._read_legacy_json(base_dir, f"{account_id}/ledger.json")
        if isinstance(ledger_payload, dict) and ledger_payload.get("starting_cash") not in (None, ""):
            account_payload = dict(account_payload)
            account_payload["starting_cash"] = str(ledger_payload.get("starting_cash"))
        self.save_local_paper_account(account_payload)
        if not isinstance(ledger_payload, dict):
            return
        with self._connect() as conn:
            conn.execute("DELETE FROM local_paper_ledger_entries WHERE account_id = ?", (str(account_id),))
            conn.execute("DELETE FROM local_paper_nav_history WHERE account_id = ?", (str(account_id),))
        trades = ledger_payload.get("trades")
        if isinstance(trades, list):
            self.append_local_paper_ledger_entries(account_id, trades)
        nav_history = ledger_payload.get("nav_history")
        if isinstance(nav_history, list):
            self.save_local_paper_nav_history(account_id, nav_history)

    def _import_job(self, payload: Dict[str, Any]) -> None:
        if not payload.get("job_id"):
            return
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO jobs (
                    job_id, kind, status, stage, detail, progress_pct,
                    metadata_json, payload_json, created_at, started_at,
                    finished_at, owner_pid, owner_started_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    payload["job_id"],
                    payload.get("kind", "legacy_job"),
                    payload.get("status", "SUCCESS"),
                    payload.get("stage", payload.get("status", "DONE")),
                    payload.get("detail", ""),
                    int(payload.get("progress_pct", 100)),
                    _json_dumps(payload.get("metadata", {})),
                    _json_dumps(payload.get("payload", {})),
                    payload.get("created_at") or payload.get("started_at") or _utc_now(),
                    payload.get("started_at"),
                    payload.get("finished_at") or _utc_now(),
                    payload.get("owner_pid"),
                    payload.get("owner_started_at"),
                ),
            )

    def _normalize_legacy_job(self, payload: Dict[str, Any], default_status: Optional[str] = None) -> Dict[str, Any]:
        metadata = payload.get("metadata", {})
        if not isinstance(metadata, dict):
            metadata = {}
        result_metadata = payload.get("result_metadata")
        if isinstance(result_metadata, dict):
            metadata = dict(metadata)
            metadata["result_metadata"] = result_metadata
        status = str(default_status or payload.get("status") or "SUCCESS")
        return {
            "job_id": str(payload.get("job_id") or self._job_id(str(payload.get("kind", "legacy")), _utc_now(), metadata, {})),
            "kind": str(payload.get("kind", "legacy_job")),
            "status": status,
            "stage": str(payload.get("stage") or status),
            "detail": str(payload.get("detail", "")),
            "progress_pct": int(payload.get("progress_pct", 100 if status != "QUEUED" else 0)),
            "metadata": metadata,
            "payload": {},
            "created_at": str(payload.get("created_at") or payload.get("started_at") or _utc_now()),
            "started_at": payload.get("started_at"),
            "finished_at": payload.get("finished_at") or (_utc_now() if status != "QUEUED" else None),
            "owner_pid": payload.get("owner_pid"),
            "owner_started_at": payload.get("owner_started_at"),
        }

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def _row_to_job(self, row: sqlite3.Row) -> Dict[str, Any]:
        return {
            "job_id": row["job_id"],
            "kind": row["kind"],
            "status": row["status"],
            "stage": row["stage"],
            "detail": row["detail"],
            "progress_pct": int(row["progress_pct"] or 0),
            "metadata": _json_loads(row["metadata_json"], {}),
            "payload": _json_loads(row["payload_json"], {}),
            "created_at": row["created_at"],
            "started_at": row["started_at"],
            "finished_at": row["finished_at"],
            "owner_pid": row["owner_pid"],
            "owner_started_at": row["owner_started_at"],
        }

    def _row_to_event(self, row: sqlite3.Row) -> Dict[str, Any]:
        return {
            "event_id": int(row["event_id"]),
            "job_id": row["job_id"],
            "category": row["category"],
            "action": row["action"],
            "status": row["status"],
            "detail": row["detail"],
            "metadata": _json_loads(row["metadata_json"], {}),
            "created_at": row["created_at"],
        }

    def _row_to_strategy_registry_record(self, row: sqlite3.Row) -> Dict[str, Any]:
        payload = _json_loads(row["record_json"], {})
        if isinstance(payload, dict) and payload.get("preset_id"):
            return payload
        return {
            "preset_id": row["preset_id"],
            "market": row["market"],
            "display_name": row["display_name"],
            "family": row["family"],
            "description": row["description"],
            "top_n": int(row["top_n"] or 0),
            "alpha_weights": _json_loads(row["alpha_weights_json"], {}),
            "policy_overrides": _json_loads(row["policy_overrides_json"], {}),
            "source_artifact_path": row["source_artifact_path"],
            "source_subject_id": row["source_subject_id"],
            "source_subject_name": row["source_subject_name"],
            "decision": row["decision"],
            "created_at": row["created_at"],
        }

    def _row_to_result_index_record(self, row: sqlite3.Row) -> Dict[str, Any]:
        payload = _json_loads(row["record_json"], {})
        if isinstance(payload, dict) and payload.get("result_id"):
            return payload
        return {
            "result_id": row["result_id"],
            "artifact_kind": row["artifact_kind"],
            "market": row["market"],
            "sort_date": row["sort_date"],
            "summary": _json_loads(row["summary_json"], {}),
            "artifacts": _json_loads(row["artifacts_json"], {}),
            "normalized_summary": _json_loads(row["normalized_summary_json"], {}),
            "recorded_at": row["recorded_at"],
        }

    def _row_to_local_paper_position(self, raw_value: Any) -> Dict[str, Any]:
        payload = _json_loads(raw_value, {})
        return payload if isinstance(payload, dict) else {}

    def _json_row_payload(self, raw_value: Any) -> Dict[str, Any]:
        payload = _json_loads(raw_value, {})
        return payload if isinstance(payload, dict) else {}

    def _read_legacy_json(self, base_dir: Path, relative_path: str) -> Any:
        try:
            return read_json_artifact(base_dir, relative_path)
        except json.JSONDecodeError:
            return None

    def _resolve_starting_cash_value(self, account_id: str, payload: Dict[str, Any]) -> str:
        explicit = payload.get("starting_cash")
        if explicit not in (None, ""):
            return str(explicit)
        existing = self.load_local_paper_account(account_id)
        if isinstance(existing, dict) and existing.get("starting_cash") not in (None, ""):
            return str(existing["starting_cash"])
        return str(payload.get("cash") or "0")

    def _ensure_column(self, conn: sqlite3.Connection, table_name: str, column_name: str, column_sql: str) -> None:
        columns = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
        if any(str(row["name"]) == column_name for row in columns):
            return
        conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_sql}")

    def _job_id(
        self,
        kind: str,
        created_at: str,
        metadata: Dict[str, Any],
        payload: Dict[str, Any],
    ) -> str:
        base = f"{kind}|{created_at}|{_json_dumps(metadata)}|{_json_dumps(payload)}|{os.getpid()}"
        import hashlib

        digest = hashlib.sha1(base.encode("utf-8")).hexdigest()[:8]
        return f"{digest}{uuid.uuid4().hex[:4]}"
