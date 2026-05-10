from __future__ import annotations

from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from stock_quantification.artifacts import write_json_artifact
from stock_quantification.sqlite_state import SQLiteStateStore


class SQLiteStateStoreTests(TestCase):
    def test_enqueue_claim_and_finish_job(self) -> None:
        with TemporaryDirectory() as tmpdir:
            store = SQLiteStateStore(tmpdir)
            job = store.enqueue_job("strategy_run", metadata={"market": "US"}, payload={"market": "US"})
            self.assertEqual(job["status"], "QUEUED")

            claimed = store.claim_next_job(owner_pid=101, owner_started_at="2026-05-05T10:00:00")
            self.assertIsNotNone(claimed)
            self.assertEqual(claimed["job_id"], job["job_id"])
            self.assertEqual(claimed["status"], "RUNNING")

            store.finish_job(job["job_id"], status="SUCCESS", detail="done", metadata={"count": 1})
            finished = store.get_job(job["job_id"])
            assert finished is not None
            self.assertEqual(finished["status"], "SUCCESS")
            self.assertEqual(finished["metadata"]["result_metadata"]["count"], 1)

    def test_claim_next_job_uses_fifo_for_queued_jobs(self) -> None:
        with TemporaryDirectory() as tmpdir:
            store = SQLiteStateStore(tmpdir)
            first = store.enqueue_job("strategy_run", payload={"index": 1})
            second = store.enqueue_job("factor_backtest", payload={"index": 2})

            claimed = store.claim_next_job(owner_pid=101, owner_started_at="2026-05-05T10:00:00")
            self.assertIsNotNone(claimed)
            assert claimed is not None
            self.assertEqual(claimed["job_id"], first["job_id"])
            self.assertIsNone(store.claim_next_job(owner_pid=101, owner_started_at="2026-05-05T10:00:00"))

            store.finish_job(first["job_id"], status="SUCCESS", detail="done")
            claimed_second = store.claim_next_job(owner_pid=101, owner_started_at="2026-05-05T10:00:00")
            self.assertIsNotNone(claimed_second)
            assert claimed_second is not None
            self.assertEqual(claimed_second["job_id"], second["job_id"])

    def test_imports_legacy_json_state(self) -> None:
        with TemporaryDirectory() as tmpdir:
            write_json_artifact(
                tmpdir,
                "web/ops_state.json",
                {
                    "heartbeats": {"web": "2026-05-05T10:00:00"},
                    "active_job": {
                        "job_id": "legacy-running",
                        "kind": "strategy_run",
                        "status": "RUNNING",
                        "started_at": "2026-05-05T09:59:00",
                        "detail": "running",
                    },
                    "job_history": [
                        {
                            "job_id": "legacy-finished",
                            "kind": "factor_backtest",
                            "status": "SUCCESS",
                            "started_at": "2026-05-05T09:00:00",
                            "finished_at": "2026-05-05T09:05:00",
                            "detail": "ok",
                        }
                    ],
                    "audit_events": [
                        {
                            "category": "runtime",
                            "action": "strategy_run",
                            "status": "FAILED",
                            "detail": "legacy event",
                            "metadata": {"market": "US"},
                        }
                    ],
                },
            )
            write_json_artifact(
                tmpdir,
                "web/task_logs.json",
                {
                    "entries": [
                        {
                            "created_at": "2026-05-05T10:01:00",
                            "category": "research",
                            "action": "factor_backtest",
                            "status": "BLOCKED",
                            "detail": "legacy blocked",
                            "metadata": {"active_job": "strategy_run"},
                        }
                    ]
                },
            )
            write_json_artifact(
                tmpdir,
                "web/run_history.json",
                {
                    "records": [
                        {"run_instance_id": "legacy-run", "market": "US", "trade_date": "2026-05-05"}
                    ]
                },
            )

            store = SQLiteStateStore(tmpdir)

            self.assertEqual(store.load_heartbeats()["web"], "2026-05-05T10:00:00")
            jobs = store.list_recent_jobs(limit=10)
            job_ids = {row["job_id"] for row in jobs}
            self.assertIn("legacy-running", job_ids)
            self.assertIn("legacy-finished", job_ids)
            legacy_running = next(row for row in jobs if row["job_id"] == "legacy-running")
            self.assertEqual(legacy_running["status"], "STALE")
            events = store.list_events(limit=10)
            self.assertEqual(len(events), 2)
            history = store.list_run_history(limit=10)
            self.assertEqual(history[0]["run_instance_id"], "legacy-run")

    def test_appends_and_reads_run_history(self) -> None:
        with TemporaryDirectory() as tmpdir:
            store = SQLiteStateStore(tmpdir)
            store.append_run_history(
                [
                    {"run_instance_id": "one", "market": "US"},
                    {"run_instance_id": "two", "market": "CN"},
                ]
            )
            history = store.list_run_history(limit=10)
            self.assertEqual([row["run_instance_id"] for row in history], ["one", "two"])

    def test_list_events_returns_latest_subset_in_chronological_order(self) -> None:
        with TemporaryDirectory() as tmpdir:
            store = SQLiteStateStore(tmpdir)
            store.append_event(category="research", action="factor_backtest", status="QUEUED", detail="oldest")
            store.append_event(category="research", action="factor_backtest", status="RUNNING", detail="middle")
            store.append_event(category="research", action="factor_backtest", status="FAILED", detail="latest")

            events = store.list_events(limit=2)

            self.assertEqual([row["detail"] for row in events], ["middle", "latest"])

    def test_list_run_history_returns_latest_subset_in_chronological_order(self) -> None:
        with TemporaryDirectory() as tmpdir:
            store = SQLiteStateStore(tmpdir)
            store.append_run_history(
                [
                    {"run_instance_id": "one", "market": "US"},
                    {"run_instance_id": "two", "market": "CN"},
                    {"run_instance_id": "three", "market": "US"},
                ]
            )

            history = store.list_run_history(limit=2)

            self.assertEqual([row["run_instance_id"] for row in history], ["two", "three"])

    def test_cache_market_bars_round_trip(self) -> None:
        with TemporaryDirectory() as tmpdir:
            store = SQLiteStateStore(tmpdir)
            store.cache_market_bars(
                market="US",
                symbol="AAPL",
                assetclass="stocks",
                instrument_id="US.AAPL",
                asset_type="COMMON_STOCK",
                currency="USD",
                exchange="NASDAQ",
                display_name="Apple Inc.",
                source="nasdaq",
                bars=[
                    {
                        "trade_date": "2026-05-08",
                        "open_price": "200",
                        "close_price": "201",
                        "high_price": "202",
                        "low_price": "199",
                        "volume": 100,
                        "turnover": "20100",
                        "adjustment_flag": "RAW",
                    },
                    {
                        "trade_date": "2026-05-09",
                        "open_price": "201",
                        "close_price": "203",
                        "high_price": "204",
                        "low_price": "200",
                        "volume": 150,
                        "turnover": "30450",
                        "adjustment_flag": "RAW",
                    },
                ],
            )

            rows = store.load_market_bars(
                market="US",
                symbol="AAPL",
                assetclass="stocks",
                start_date=date(2026, 5, 8),
                end_date=date(2026, 5, 9),
            )

            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0]["trade_date"], "2026-05-08")
            self.assertEqual(rows[1]["close_price"], "203")
