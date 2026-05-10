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
                """
            )
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
