from __future__ import annotations

import json
import sqlite3
import tempfile
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from unittest import TestCase

from stock_quantification.artifacts import read_json_artifact
from stock_quantification.broker_ledger import BrokerLedger
from stock_quantification.local_paper import LocalPaperLedger
from stock_quantification.models import (
    AccountState,
    Market,
    OrderIntent,
    OrderSide,
    OrderType,
    PaperContext,
    Position,
)
from stock_quantification.runtime import ExecutionFill, ExecutionResult, ExecutionStatus


def _seed_local_paper_sqlite_account(
    base_dir: str | Path,
    *,
    account_id: str,
    market: str,
    broker_id: str,
    cash: str,
    buying_power: str,
    positions: list[dict],
    trades: list[dict],
    nav_history: list[dict],
) -> None:
    db_path = Path(base_dir) / "web" / "app_state.sqlite3"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
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
        account_payload = {
            "account_id": account_id,
            "market": market,
            "broker_id": broker_id,
            "cash": cash,
            "buying_power": buying_power,
            "positions": positions,
        }
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
                    json.dumps(position, ensure_ascii=False, sort_keys=True),
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
                    json.dumps(trade, ensure_ascii=False, sort_keys=True),
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
                    json.dumps(snapshot, ensure_ascii=False, sort_keys=True),
                ),
            )


class LocalPaperLedgerTests(TestCase):
    def test_sync_account_state_bootstraps_and_persists(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            ledger = LocalPaperLedger(tmpdir)
            account = ledger.sync_account_state("paper-us", Market.US, Decimal("100000"))
            self.assertEqual(account.cash, Decimal("100000"))
            overview = ledger.account_overview("paper-us")
            self.assertEqual(overview["trade_count"], 0)
            self.assertEqual(overview["position_count"], 0)

    def test_record_execution_appends_trade_records_and_updates_account(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            ledger = LocalPaperLedger(tmpdir)
            ledger.sync_account_state("paper-us", Market.US, Decimal("100000"))
            as_of = datetime(2026, 4, 6, 16, 0, 0)
            result = ExecutionResult(
                context=PaperContext(as_of=as_of),
                input_account_state=AccountState(
                    account_id="paper-us",
                    market=Market.US,
                    broker_id="local-paper",
                    cash=Decimal("100000"),
                    buying_power=Decimal("100000"),
                ),
                output_account_state=AccountState(
                    account_id="paper-us",
                    market=Market.US,
                    broker_id="local-paper",
                    cash=Decimal("72000"),
                    buying_power=Decimal("72000"),
                    positions={"US.AAPL": Position("US.AAPL", 100, Decimal("280"))},
                ),
                fills=[
                    ExecutionFill(
                        order_intent_id="paper-us:US.AAPL:2026-04-06",
                        account_id="paper-us",
                        instrument_id="US.AAPL",
                        mode=Market.US,  # type: ignore[arg-type]
                        status=ExecutionStatus.FILLED,
                        requested_qty=100,
                        filled_qty=100,
                        remaining_qty=0,
                        reference_price=Decimal("279.5"),
                        estimated_price=Decimal("280"),
                        realized_price=Decimal("280"),
                        slippage_bps=Decimal("2"),
                        commission=Decimal("1"),
                        taxes=Decimal("0"),
                        total_fees=Decimal("1"),
                        cash_delta=Decimal("-28001"),
                        estimated_cash_delta=Decimal("-28001"),
                        notes=[],
                    )
                ],
                applied_corporate_actions=[],
            )
            orders = [
                OrderIntent(
                    order_intent_id="paper-us:US.AAPL:2026-04-06",
                    account_id="paper-us",
                    instrument_id="US.AAPL",
                    side=OrderSide.BUY,
                    qty=100,
                    order_type=OrderType.MARKET,
                    limit_price=None,
                    time_in_force="DAY",
                    source_strategy_id="us_quality_momentum",
                    requires_manual_approval=False,
                )
            ]
            record = ledger.record_execution(
                account_id="paper-us",
                strategy_id="us_quality_momentum",
                market=Market.US,
                order_intents=orders,
                execution_results=[result],
                instrument_names={"US.AAPL": "Apple"},
                price_map={"US.AAPL": Decimal("282")},
            )
            self.assertEqual(len(record["trade_records"]), 1)
            self.assertEqual(record["summary"]["trade_count"], 1)
            self.assertEqual(record["summary"]["strategy_id"], "us_quality_momentum")
            self.assertEqual(record["trade_records"][0]["side"], "BUY")
            overview = ledger.account_overview("paper-us")
            self.assertEqual(overview["position_count"], 1)
            self.assertEqual(overview["trade_count"], 1)
            self.assertEqual(len(overview["nav_history"]), 2)
            self.assertEqual(overview["latest_nav"], "100200.0000")
            self.assertEqual(overview["nav_history"][-1]["as_of"], as_of.isoformat())
            run_payload = read_json_artifact(tmpdir, "paper-us/runs/20260406T160000_us_quality_momentum.json")
            self.assertEqual(run_payload["normalized_summary"]["decision"], "RECORDED")
            self.assertEqual(run_payload["normalized_summary"]["subject_name"], "paper-us / us_quality_momentum")

    def test_record_execution_skips_zero_fill_trade_noise_and_keeps_nav_consistent(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            ledger = LocalPaperLedger(tmpdir)
            ledger.sync_account_state("paper-us", Market.US, Decimal("100000"))
            as_of = datetime(2026, 4, 7, 16, 0, 0)
            result = ExecutionResult(
                context=PaperContext(as_of=as_of),
                input_account_state=AccountState(
                    account_id="paper-us",
                    market=Market.US,
                    broker_id="local-paper",
                    cash=Decimal("100000"),
                    buying_power=Decimal("100000"),
                ),
                output_account_state=AccountState(
                    account_id="paper-us",
                    market=Market.US,
                    broker_id="local-paper",
                    cash=Decimal("100000"),
                    buying_power=Decimal("100000"),
                    positions={},
                ),
                fills=[
                    ExecutionFill(
                        order_intent_id="paper-us:US.AAPL:2026-04-07",
                        account_id="paper-us",
                        instrument_id="US.AAPL",
                        mode=Market.US,  # type: ignore[arg-type]
                        status=ExecutionStatus.SKIPPED,
                        requested_qty=100,
                        filled_qty=0,
                        remaining_qty=100,
                        reference_price=Decimal("280"),
                        estimated_price=Decimal("280"),
                        realized_price=None,
                        slippage_bps=Decimal("0"),
                        commission=Decimal("0"),
                        taxes=Decimal("0"),
                        total_fees=Decimal("0"),
                        cash_delta=Decimal("0"),
                        estimated_cash_delta=Decimal("0"),
                        notes=["no_fill"],
                    )
                ],
                applied_corporate_actions=[],
            )
            orders = [
                OrderIntent(
                    order_intent_id="paper-us:US.AAPL:2026-04-07",
                    account_id="paper-us",
                    instrument_id="US.AAPL",
                    side=OrderSide.BUY,
                    qty=100,
                    order_type=OrderType.MARKET,
                    limit_price=None,
                    time_in_force="DAY",
                    source_strategy_id="us_quality_momentum",
                    requires_manual_approval=False,
                )
            ]

            record = ledger.record_execution(
                account_id="paper-us",
                strategy_id="us_quality_momentum",
                market=Market.US,
                order_intents=orders,
                execution_results=[result],
                instrument_names={"US.AAPL": "Apple"},
                price_map={},
            )

            self.assertEqual(record["trade_records"], [])
            self.assertEqual(record["summary"]["trade_count"], 0)
            overview = ledger.account_overview("paper-us")
            self.assertEqual(overview["trade_count"], 0)
            self.assertEqual(len(overview["nav_history"]), 2)
            self.assertEqual(overview["latest_nav"], "100000.0000")
            self.assertEqual(overview["nav_history"][-1]["as_of"], as_of.isoformat())

    def test_reset_account_removes_local_paper_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            ledger = LocalPaperLedger(tmpdir)
            ledger.sync_account_state("paper-us", Market.US, Decimal("100000"))
            self.assertTrue(ledger.reset_account("paper-us"))
            self.assertIsNone(ledger.account_overview("paper-us"))

    def test_liquidate_unknown_positions_clears_stale_holdings_and_records_sell_trades(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            ledger = LocalPaperLedger(tmpdir)
            account = ledger.sync_account_state("paper-us", Market.US, Decimal("100000"))
            account.cash = Decimal("70000")
            account.buying_power = Decimal("70000")
            account.positions = {
                "US.KEEP": Position("US.KEEP", 10, Decimal("100")),
                "US.STALE": Position("US.STALE", 5, Decimal("200")),
            }
            ledger._write_account(account)

            result = ledger.liquidate_unknown_positions(
                account_id="paper-us",
                valid_instrument_ids={"US.KEEP"},
                as_of=datetime(2026, 5, 6, 16, 0, 0),
            )

            self.assertEqual(result["liquidated_count"], 1)
            self.assertEqual(len(result["trade_records"]), 1)
            self.assertEqual(result["trade_records"][0]["instrument_id"], "US.STALE")
            self.assertEqual(result["trade_records"][0]["side"], "SELL")
            overview = ledger.account_overview("paper-us")
            self.assertEqual(overview["position_count"], 1)
            self.assertEqual(overview["trade_count"], 1)
            self.assertNotIn("US.STALE", {row["instrument_id"] for row in overview["positions"]})
            self.assertEqual(overview["cash"], "71000.0000")

    def test_unknown_position_cleanup_uses_shared_ledger_events(self) -> None:
        account_state = AccountState(
            account_id="paper-us",
            market=Market.US,
            broker_id="local-paper",
            cash=Decimal("70000"),
            buying_power=Decimal("70000"),
            positions={
                "US.KEEP": Position("US.KEEP", 10, Decimal("100")),
                "US.STALE": Position("US.STALE", 5, Decimal("200")),
            },
        )

        cleaned_state, trade_records = BrokerLedger().liquidate_unknown_positions(
            account_state=account_state,
            valid_instrument_ids={"US.KEEP"},
            as_of=datetime(2026, 5, 6, 16, 0, 0),
        )

        self.assertEqual(cleaned_state.cash, Decimal("71000.0000"))
        self.assertEqual(len(trade_records), 1)
        self.assertEqual(trade_records[0]["instrument_id"], "US.STALE")
        self.assertEqual(trade_records[0]["note"], "unknown_position_auto_liquidation")

    def test_sync_account_state_rejects_cross_market_reuse(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            ledger = LocalPaperLedger(tmpdir)
            ledger.sync_account_state("paper-shared", Market.US, Decimal("100000"))
            with self.assertRaisesRegex(ValueError, "belongs to US"):
                ledger.sync_account_state("paper-shared", Market.CN, Decimal("100000"))

    def test_local_paper_account_overview_works_without_account_json_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            _seed_local_paper_sqlite_account(
                tmpdir,
                account_id="paper-us",
                market="US",
                broker_id="local-paper",
                cash="95500.0000",
                buying_power="95500.0000",
                positions=[
                    {
                        "instrument_id": "US.AAPL",
                        "qty": 10,
                        "avg_cost": "280.0000",
                        "last_trade_date": "2026-04-18",
                    }
                ],
                trades=[
                    {
                        "trade_date": "2026-04-18",
                        "side": "BUY",
                        "instrument_id": "US.AAPL",
                        "filled_qty": 10,
                        "realized_price": "280.0000",
                        "cash_delta": "-2800.0000",
                    }
                ],
                nav_history=[
                    {
                        "as_of": "2026-04-18T16:00:00",
                        "trade_date": "2026-04-18",
                        "nav": "100100.0000",
                        "cash": "95500.0000",
                        "position_value": "4600.0000",
                        "cumulative_return": "0.0010",
                    }
                ],
            )

            overview = LocalPaperLedger(tmpdir).account_overview("paper-us")

            self.assertIsNotNone(overview)
            assert overview is not None
            self.assertEqual(overview["account_id"], "paper-us")
            self.assertEqual(overview["position_count"], 1)
            self.assertEqual(overview["trade_count"], 1)
            self.assertEqual(overview["latest_nav"], "100100.0000")
