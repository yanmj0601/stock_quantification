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
            write_json_artifact(
                tmpdir,
                "web/strategy_state.json",
                {
                    "markets": {
                        "US": {
                            "champion_preset_id": "us-champion",
                            "challenger_preset_id": "us-challenger",
                            "current_execution_preset_id": "us-current",
                        }
                    }
                },
            )
            write_json_artifact(
                tmpdir,
                "web/strategy_registry.json",
                {
                    "markets": {
                        "US": [
                            {
                                "preset_id": "us-current",
                                "market": "US",
                                "display_name": "US Current",
                                "family": "Momentum",
                                "description": "legacy registry",
                                "top_n": 8,
                                "alpha_weights": {"momentum": "0.5000"},
                                "policy_overrides": {"turnover_cap": "0.2000"},
                                "source_artifact_path": "results/us-current.json",
                                "source_subject_id": "suite:us-current",
                                "source_subject_name": "US Current",
                                "decision": "KEEP",
                                "created_at": "2026-05-05T10:02:00",
                            }
                        ]
                    }
                },
            )
            write_json_artifact(
                tmpdir,
                "web/result_index.json",
                {
                    "records": [
                        {
                            "result_id": "factor-backtest-us-current",
                            "artifact_kind": "factor_backtest",
                            "market": "US",
                            "sort_date": "2026-05-05",
                            "recorded_at": "2026-05-05T10:03:00",
                            "summary": {"subject_id": "us-current", "decision": "KEEP"},
                            "normalized_summary": {"subject_id": "us-current", "decision": "KEEP"},
                            "artifacts": {"json": "results/us-current.json"},
                        }
                    ]
                },
            )
            write_json_artifact(
                tmpdir,
                "web/paper_automation_state.json",
                {
                    "accounts": {
                        "web-paper-us": {
                            "last_trade_date": "2026-05-05",
                            "last_checked_at": "2026-05-05T15:30:00",
                            "last_status": "SUCCESS",
                        }
                    }
                },
            )
            write_json_artifact(
                tmpdir,
                "local_paper/web-paper-us/account.json",
                {
                    "account_id": "web-paper-us",
                    "market": "US",
                    "broker_id": "local-paper",
                    "cash": "100000.0000",
                    "buying_power": "98000.0000",
                    "last_sync_at": "2026-05-05T15:30:00",
                    "positions": [
                        {
                            "instrument_id": "US.AAPL",
                            "qty": 10,
                            "avg_cost": "200.0000",
                            "last_trade_date": "2026-05-05",
                        }
                    ],
                },
            )
            write_json_artifact(
                tmpdir,
                "local_paper/web-paper-us/ledger.json",
                {
                    "account_id": "web-paper-us",
                    "market": "US",
                    "starting_cash": "100000.0000",
                    "trades": [
                        {
                            "trade_date": "2026-05-05",
                            "created_at": "2026-05-05T15:30:00",
                            "instrument_id": "US.AAPL",
                            "side": "BUY",
                            "qty": 10,
                            "price": "200.0000",
                            "cash_delta": "-2000.0000",
                        }
                    ],
                    "nav_history": [
                        {
                            "as_of": "2026-05-05T15:30:00",
                            "trade_date": "2026-05-05",
                            "nav": "100100.0000",
                            "cash": "98000.0000",
                            "position_value": "2100.0000",
                            "cumulative_return": "0.0010",
                        }
                    ],
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
            self.assertEqual(
                store.load_strategy_state()["markets"]["US"]["current_execution_preset_id"],
                "us-current",
            )
            self.assertEqual(store.list_strategy_registry_records("US")[0]["preset_id"], "us-current")
            self.assertEqual(store.list_result_index_records(market="US")[0]["result_id"], "factor-backtest-us-current")
            self.assertEqual(
                store.load_paper_automation_state()["accounts"]["web-paper-us"]["last_status"],
                "SUCCESS",
            )
            self.assertEqual(store.load_local_paper_account("web-paper-us")["positions"][0]["instrument_id"], "US.AAPL")
            self.assertEqual(
                store.load_local_paper_ledger("web-paper-us")["trades"][0]["instrument_id"],
                "US.AAPL",
            )

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

    def test_strategy_state_round_trip_uses_sqlite_tables(self) -> None:
        with TemporaryDirectory() as tmpdir:
            store = SQLiteStateStore(tmpdir)

            store.save_market_strategy_state(
                "US",
                {
                    "champion_preset_id": "us-champion",
                    "challenger_preset_id": "us-challenger",
                    "current_execution_preset_id": "us-current",
                },
            )

            state = store.load_strategy_state()

            self.assertEqual(
                state["markets"]["US"],
                {
                    "champion_preset_id": "us-champion",
                    "challenger_preset_id": "us-challenger",
                    "current_execution_preset_id": "us-current",
                },
            )

    def test_strategy_registry_round_trip_uses_sqlite_tables(self) -> None:
        with TemporaryDirectory() as tmpdir:
            store = SQLiteStateStore(tmpdir)

            store.upsert_strategy_registry_record(
                {
                    "preset_id": "us-current",
                    "market": "US",
                    "display_name": "US Current",
                    "family": "Momentum",
                    "description": "registry round trip",
                    "top_n": 8,
                    "alpha_weights": {"momentum": "0.5000"},
                    "policy_overrides": {"turnover_cap": "0.2000"},
                    "source_artifact_path": "results/us-current.json",
                    "source_subject_id": "suite:us-current",
                    "source_subject_name": "US Current",
                    "decision": "KEEP",
                    "created_at": "2026-05-05T10:02:00",
                }
            )

            rows = store.list_strategy_registry_records("US")

            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["preset_id"], "us-current")
            self.assertEqual(rows[0]["alpha_weights"]["momentum"], "0.5000")
            self.assertEqual(rows[0]["policy_overrides"]["turnover_cap"], "0.2000")

    def test_result_index_round_trip_uses_sqlite_tables(self) -> None:
        with TemporaryDirectory() as tmpdir:
            store = SQLiteStateStore(tmpdir)

            store.upsert_result_index_record(
                {
                    "result_id": "factor-backtest-us-current",
                    "artifact_kind": "factor_backtest",
                    "market": "US",
                    "sort_date": "2026-05-05",
                    "recorded_at": "2026-05-05T10:03:00",
                    "summary": {"subject_id": "us-current", "decision": "KEEP"},
                    "normalized_summary": {"subject_id": "us-current", "decision": "KEEP"},
                    "artifacts": {"json": "results/us-current.json"},
                }
            )

            rows = store.list_result_index_records(market="US")

            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["result_id"], "factor-backtest-us-current")
            self.assertEqual(rows[0]["summary"]["subject_id"], "us-current")
            self.assertEqual(rows[0]["artifacts"]["json"], "results/us-current.json")

    def test_paper_automation_state_round_trip_uses_sqlite_tables(self) -> None:
        with TemporaryDirectory() as tmpdir:
            store = SQLiteStateStore(tmpdir)

            store.save_paper_automation_state(
                {
                    "accounts": {
                        "web-paper-us": {
                            "last_trade_date": "2026-05-05",
                            "last_checked_at": "2026-05-05T15:30:00",
                            "last_status": "SUCCESS",
                        }
                    }
                }
            )

            state = store.load_paper_automation_state()

            self.assertEqual(
                state,
                {
                    "accounts": {
                        "web-paper-us": {
                            "last_trade_date": "2026-05-05",
                            "last_checked_at": "2026-05-05T15:30:00",
                            "last_status": "SUCCESS",
                        }
                    }
                },
            )

    def test_local_paper_account_and_ledger_round_trip_uses_sqlite_tables(self) -> None:
        with TemporaryDirectory() as tmpdir:
            store = SQLiteStateStore(tmpdir)

            store.save_local_paper_account(
                {
                    "account_id": "web-paper-us",
                    "market": "US",
                    "broker_id": "local-paper",
                    "cash": "100000.0000",
                    "buying_power": "98000.0000",
                    "last_sync_at": "2026-05-05T15:30:00",
                    "positions": [
                        {
                            "instrument_id": "US.AAPL",
                            "qty": 10,
                            "avg_cost": "200.0000",
                            "last_trade_date": "2026-05-05",
                        }
                    ],
                }
            )
            store.append_local_paper_ledger_entries(
                "web-paper-us",
                [
                    {
                        "trade_date": "2026-05-05",
                        "created_at": "2026-05-05T15:30:00",
                        "instrument_id": "US.AAPL",
                        "side": "BUY",
                        "qty": 10,
                        "price": "200.0000",
                        "cash_delta": "-2000.0000",
                    }
                ],
            )
            store.save_local_paper_nav_history(
                "web-paper-us",
                [
                    {
                        "as_of": "2026-05-05T15:30:00",
                        "trade_date": "2026-05-05",
                        "nav": "100100.0000",
                        "cash": "98000.0000",
                        "position_value": "2100.0000",
                        "cumulative_return": "0.0010",
                    }
                ],
            )

            account = store.load_local_paper_account("web-paper-us")
            ledger = store.load_local_paper_ledger("web-paper-us")

            assert account is not None
            self.assertEqual(account["positions"][0]["instrument_id"], "US.AAPL")
            self.assertEqual(ledger["account_id"], "web-paper-us")
            self.assertEqual(ledger["starting_cash"], "100000.0000")
            self.assertEqual(ledger["trades"][0]["instrument_id"], "US.AAPL")
            self.assertEqual(ledger["nav_history"][0]["nav"], "100100.0000")

    def test_legacy_import_is_idempotent_and_backfills_missing_runtime_state(self) -> None:
        with TemporaryDirectory() as tmpdir:
            write_json_artifact(
                tmpdir,
                "web/strategy_state.json",
                {
                    "markets": {
                        "US": {
                            "champion_preset_id": "us-champion",
                            "challenger_preset_id": "us-challenger",
                            "current_execution_preset_id": "us-current",
                        },
                        "CN": {
                            "champion_preset_id": "cn-champion",
                            "challenger_preset_id": "cn-challenger",
                            "current_execution_preset_id": "cn-current",
                        },
                    }
                },
            )
            write_json_artifact(
                tmpdir,
                "web/strategy_registry.json",
                {
                    "markets": {
                        "US": [
                            {
                                "preset_id": "us-current",
                                "market": "US",
                                "display_name": "US Current",
                                "family": "Momentum",
                                "description": "legacy registry us",
                                "top_n": 8,
                                "alpha_weights": {"momentum": "0.5000"},
                                "policy_overrides": {"turnover_cap": "0.2000"},
                                "created_at": "2026-05-05T10:02:00",
                            }
                        ],
                        "CN": [
                            {
                                "preset_id": "cn-current",
                                "market": "CN",
                                "display_name": "CN Current",
                                "family": "Index",
                                "description": "legacy registry cn",
                                "top_n": 5,
                                "alpha_weights": {"quality": "0.3000"},
                                "policy_overrides": {"turnover_cap": "0.1000"},
                                "created_at": "2026-05-05T10:03:00",
                            }
                        ],
                    }
                },
            )
            write_json_artifact(
                tmpdir,
                "web/result_index.json",
                {
                    "records": [
                        {
                            "result_id": "us-result",
                            "artifact_kind": "factor_backtest",
                            "market": "US",
                            "sort_date": "2026-05-05",
                            "summary": {"subject_id": "us-current"},
                            "normalized_summary": {"subject_id": "us-current"},
                            "artifacts": {"json": "results/us.json"},
                        },
                        {
                            "result_id": "cn-result",
                            "artifact_kind": "factor_backtest",
                            "market": "CN",
                            "sort_date": "2026-05-04",
                            "summary": {"subject_id": "cn-current"},
                            "normalized_summary": {"subject_id": "cn-current"},
                            "artifacts": {"json": "results/cn.json"},
                        },
                    ]
                },
            )
            write_json_artifact(
                tmpdir,
                "web/paper_automation_state.json",
                {
                    "accounts": {
                        "web-paper-us": {
                            "last_trade_date": "2026-05-05",
                            "last_checked_at": "2026-05-05T15:30:00",
                            "last_status": "SUCCESS",
                        },
                        "web-paper-cn": {
                            "last_trade_date": "2026-05-05",
                            "last_checked_at": "2026-05-05T15:31:00",
                            "last_status": "FAILED",
                        },
                    }
                },
            )
            write_json_artifact(
                tmpdir,
                "local_paper/web-paper-us/account.json",
                {
                    "account_id": "web-paper-us",
                    "market": "US",
                    "broker_id": "local-paper",
                    "cash": "100000.0000",
                    "buying_power": "98000.0000",
                    "last_sync_at": "2026-05-05T15:30:00",
                    "positions": [],
                },
            )
            write_json_artifact(
                tmpdir,
                "local_paper/web-paper-us/ledger.json",
                {
                    "account_id": "web-paper-us",
                    "market": "US",
                    "starting_cash": "100000.0000",
                    "trades": [
                        {
                            "trade_date": "2026-05-05",
                            "created_at": "2026-05-05T15:30:00",
                            "instrument_id": "US.AAPL",
                            "side": "BUY",
                            "qty": 10,
                            "price": "200.0000",
                            "cash_delta": "-2000.0000",
                        }
                    ],
                    "nav_history": [
                        {
                            "as_of": "2026-05-05T15:30:00",
                            "trade_date": "2026-05-05",
                            "nav": "100100.0000",
                            "cash": "98000.0000",
                            "position_value": "2100.0000",
                            "cumulative_return": "0.0010",
                        }
                    ],
                },
            )

            store = SQLiteStateStore(tmpdir)
            store.save_market_strategy_state(
                "US",
                {
                    "champion_preset_id": "us-champion",
                    "challenger_preset_id": "us-challenger",
                    "current_execution_preset_id": "us-current",
                },
            )
            store.upsert_strategy_registry_record(
                {
                    "preset_id": "us-current",
                    "market": "US",
                    "display_name": "US Current",
                    "family": "Momentum",
                    "description": "existing sqlite us",
                    "top_n": 8,
                    "alpha_weights": {"momentum": "0.5000"},
                    "policy_overrides": {"turnover_cap": "0.2000"},
                    "created_at": "2026-05-05T10:02:00",
                }
            )
            store.upsert_result_index_record(
                {
                    "result_id": "us-result",
                    "artifact_kind": "factor_backtest",
                    "market": "US",
                    "sort_date": "2026-05-05",
                    "summary": {"subject_id": "us-current"},
                    "normalized_summary": {"subject_id": "us-current"},
                    "artifacts": {"json": "results/us.json"},
                }
            )
            store.save_paper_automation_state(
                {
                    "accounts": {
                        "web-paper-us": {
                            "last_trade_date": "2026-05-05",
                            "last_checked_at": "2026-05-05T15:30:00",
                            "last_status": "SUCCESS",
                        }
                    }
                }
            )
            store.save_local_paper_account(
                {
                    "account_id": "web-paper-us",
                    "market": "US",
                    "broker_id": "local-paper",
                    "cash": "100000.0000",
                    "buying_power": "98000.0000",
                    "last_sync_at": "2026-05-05T15:30:00",
                    "positions": [],
                }
            )

            store.import_legacy_strategy_state_json(Path(tmpdir))
            store.import_legacy_strategy_registry_json(Path(tmpdir))
            store.import_legacy_result_index_json(Path(tmpdir))
            store.import_legacy_paper_automation_json(Path(tmpdir))
            store.import_legacy_local_paper_account_json(Path(tmpdir) / "local_paper", "web-paper-us")
            store.import_legacy_local_paper_account_json(Path(tmpdir) / "local_paper", "web-paper-us")

            state = store.load_strategy_state()
            registry_rows = store.list_strategy_registry_records()
            result_rows = store.list_result_index_records()
            automation_state = store.load_paper_automation_state()
            ledger = store.load_local_paper_ledger("web-paper-us")

            self.assertEqual(state["markets"]["US"]["current_execution_preset_id"], "us-current")
            self.assertEqual(state["markets"]["CN"]["current_execution_preset_id"], "cn-current")
            self.assertEqual({row["preset_id"] for row in registry_rows}, {"us-current", "cn-current"})
            self.assertEqual({row["result_id"] for row in result_rows}, {"us-result", "cn-result"})
            self.assertEqual(
                set(automation_state["accounts"].keys()),
                {"web-paper-us", "web-paper-cn"},
            )
            self.assertEqual(ledger["starting_cash"], "100000.0000")
            self.assertEqual(len(ledger["trades"]), 1)
            self.assertEqual(len(ledger["nav_history"]), 1)

    def test_save_local_paper_account_preserves_existing_starting_cash_when_update_omits_it(self) -> None:
        with TemporaryDirectory() as tmpdir:
            store = SQLiteStateStore(tmpdir)

            store.save_local_paper_account(
                {
                    "account_id": "web-paper-us",
                    "market": "US",
                    "broker_id": "local-paper",
                    "cash": "100000.0000",
                    "buying_power": "98000.0000",
                    "starting_cash": "100000.0000",
                    "last_sync_at": "2026-05-05T15:30:00",
                    "positions": [],
                }
            )
            store.save_local_paper_account(
                {
                    "account_id": "web-paper-us",
                    "market": "US",
                    "broker_id": "local-paper",
                    "cash": "99000.0000",
                    "buying_power": "97000.0000",
                    "last_sync_at": "2026-05-05T15:35:00",
                    "positions": [],
                }
            )

            account = store.load_local_paper_account("web-paper-us")
            ledger = store.load_local_paper_ledger("web-paper-us")

            assert account is not None
            self.assertEqual(account["starting_cash"], "100000.0000")
            self.assertEqual(ledger["starting_cash"], "100000.0000")
