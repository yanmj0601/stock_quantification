from __future__ import annotations

import tempfile
from datetime import datetime
from decimal import Decimal
from unittest import TestCase

from stock_quantification.artifacts import read_json_artifact
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

    def test_sync_account_state_rejects_cross_market_reuse(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            ledger = LocalPaperLedger(tmpdir)
            ledger.sync_account_state("paper-shared", Market.US, Decimal("100000"))
            with self.assertRaisesRegex(ValueError, "belongs to US"):
                ledger.sync_account_state("paper-shared", Market.CN, Decimal("100000"))
