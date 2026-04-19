from __future__ import annotations

from decimal import Decimal
from unittest import TestCase

from stock_quantification import DatasetSnapshot, ExecutionAttempt as RootExecutionAttempt, FactorDefinition
from stock_quantification.execution_feedback import (
    ExecutionAttempt,
    aggregate_fill_rate,
    average_slippage_bps,
    reconcile_positions,
    summarize_execution_health,
)
from stock_quantification.models import Position


class ExecutionFeedbackTests(TestCase):
    def test_package_root_exports_new_foundation_types(self) -> None:
        self.assertIs(RootExecutionAttempt, ExecutionAttempt)
        snapshot = DatasetSnapshot("prices", 10)
        definition = FactorDefinition("momentum", "Momentum", "Price trend factor")

        self.assertEqual(snapshot.dataset_name, "prices")
        self.assertEqual(definition.factor_id, "momentum")

    def test_aggregate_fill_rate_and_slippage_from_attempts(self) -> None:
        attempts = [
            ExecutionAttempt(
                order_intent_id="acct:US.AAPL:1",
                account_id="acct",
                instrument_id="US.AAPL",
                requested_qty=100,
                filled_qty=100,
                slippage_bps=Decimal("3.0"),
            ),
            ExecutionAttempt(
                order_intent_id="acct:US.MSFT:1",
                account_id="acct",
                instrument_id="US.MSFT",
                requested_qty=50,
                filled_qty=25,
                slippage_bps=Decimal("6.0"),
            ),
            ExecutionAttempt(
                order_intent_id="acct:US.NVDA:1",
                account_id="acct",
                instrument_id="US.NVDA",
                requested_qty=50,
                filled_qty=0,
                slippage_bps=Decimal("0"),
            ),
        ]

        self.assertEqual(aggregate_fill_rate(attempts), Decimal("0.6250"))
        self.assertEqual(average_slippage_bps(attempts), Decimal("4.5000"))

    def test_summarize_execution_health_reports_no_activity(self) -> None:
        summary = summarize_execution_health([])

        self.assertEqual(summary.health_status, "NO_ACTIVITY")
        self.assertEqual(summary.total_attempts, 0)
        self.assertEqual(summary.fill_rate, Decimal("0.0000"))
        self.assertEqual(summary.average_slippage_bps, Decimal("0.0000"))
        self.assertEqual(summary.mismatch_count, 0)

    def test_summarize_execution_health_reports_degraded_and_critical(self) -> None:
        degraded = summarize_execution_health(
            [
                ExecutionAttempt(
                    order_intent_id="acct:US.AAPL:1",
                    account_id="acct",
                    instrument_id="US.AAPL",
                    requested_qty=100,
                    filled_qty=50,
                    slippage_bps=Decimal("5.0"),
                )
            ]
        )
        critical = summarize_execution_health(
            [
                ExecutionAttempt(
                    order_intent_id="acct:US.MSFT:1",
                    account_id="acct",
                    instrument_id="US.MSFT",
                    requested_qty=100,
                    filled_qty=40,
                    slippage_bps=Decimal("7.0"),
                )
            ]
        )

        self.assertEqual(degraded.health_status, "DEGRADED")
        self.assertEqual(degraded.fill_rate, Decimal("0.5000"))
        self.assertEqual(critical.health_status, "CRITICAL")
        self.assertEqual(critical.fill_rate, Decimal("0.4000"))

    def test_reconcile_positions_reports_mismatches(self) -> None:
        intended = {
            "US.AAPL": 100,
            "US.MSFT": Position("US.MSFT", 50, Decimal("410")),
        }
        observed = {
            "US.AAPL": 90,
            "US.MSFT": 50,
            "US.NVDA": 10,
        }

        differences = reconcile_positions(intended, observed)

        self.assertEqual(len(differences), 2)
        self.assertEqual(differences[0].instrument_id, "US.AAPL")
        self.assertEqual(differences[0].intended_qty, 100)
        self.assertEqual(differences[0].observed_qty, 90)
        self.assertEqual(differences[0].delta_qty, -10)
        self.assertEqual(differences[1].instrument_id, "US.NVDA")
        self.assertEqual(differences[1].intended_qty, 0)
        self.assertEqual(differences[1].observed_qty, 10)
        self.assertEqual(differences[1].delta_qty, 10)

    def test_reconcile_positions_rejects_ambiguous_quantity_values(self) -> None:
        with self.assertRaisesRegex(TypeError, "unsupported quantity value"):
            reconcile_positions({"US.AAPL": Decimal("10.9")}, {})

    def test_execution_attempt_rejects_non_int_quantities(self) -> None:
        with self.assertRaisesRegex(TypeError, "requested_qty must be an int"):
            ExecutionAttempt(
                order_intent_id="acct:US.AAPL:1",
                account_id="acct",
                instrument_id="US.AAPL",
                requested_qty=True,
                filled_qty=0,
                slippage_bps=Decimal("1.0"),
            )

    def test_execution_attempt_rejects_non_decimal_slippage(self) -> None:
        with self.assertRaisesRegex(TypeError, "slippage_bps must be a Decimal"):
            ExecutionAttempt(
                order_intent_id="acct:US.AAPL:1",
                account_id="acct",
                instrument_id="US.AAPL",
                requested_qty=10,
                filled_qty=10,
                slippage_bps=1.5,
            )

    def test_summarize_execution_health_flags_clean_and_mismatched_runs(self) -> None:
        clean_attempts = [
            ExecutionAttempt(
                order_intent_id="acct:US.AAPL:1",
                account_id="acct",
                instrument_id="US.AAPL",
                requested_qty=100,
                filled_qty=100,
                slippage_bps=Decimal("2.0"),
            )
        ]
        clean_summary = summarize_execution_health(
            clean_attempts,
            intended_positions={"US.AAPL": 100},
            observed_positions={"US.AAPL": 100},
        )

        self.assertEqual(clean_summary.health_status, "HEALTHY")
        self.assertEqual(clean_summary.fill_rate, Decimal("1.0000"))
        self.assertEqual(clean_summary.average_slippage_bps, Decimal("2.0000"))
        self.assertEqual(clean_summary.mismatch_count, 0)

        mismatch_summary = summarize_execution_health(
            clean_attempts,
            intended_positions={"US.AAPL": 100},
            observed_positions={"US.AAPL": 95},
        )

        self.assertEqual(mismatch_summary.health_status, "MISMATCH")
        self.assertEqual(mismatch_summary.mismatch_count, 1)
        self.assertEqual(mismatch_summary.reconciliation_differences[0].delta_qty, -5)
