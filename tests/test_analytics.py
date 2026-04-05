from __future__ import annotations

from decimal import Decimal
from unittest import TestCase

from stock_quantification.analytics import (
    compute_return_beta,
    compute_factor_exposure,
    compute_information_coefficient,
    compute_performance_metrics,
    compute_sector_exposures,
)


class AnalyticsTests(TestCase):
    def test_compute_performance_metrics(self) -> None:
        metrics = compute_performance_metrics(
            [Decimal("0.01"), Decimal("-0.005"), Decimal("0.02")],
            turnovers=[Decimal("0.10"), Decimal("0.15"), Decimal("0.05")],
        )
        self.assertGreater(metrics.total_return, Decimal("0"))
        self.assertLess(metrics.max_drawdown, Decimal("0"))
        self.assertEqual(metrics.turnover_average, Decimal("0.10"))

    def test_compute_information_coefficient(self) -> None:
        metrics = compute_information_coefficient(
            {"A": Decimal("1"), "B": Decimal("2"), "C": Decimal("3")},
            {"A": Decimal("0.01"), "B": Decimal("0.02"), "C": Decimal("0.03")},
        )
        self.assertEqual(metrics.sample_size, 3)
        self.assertGreater(metrics.ic, Decimal("0"))
        self.assertGreater(metrics.rank_ic, Decimal("0"))

    def test_compute_sector_and_factor_exposure(self) -> None:
        weights = {"A": Decimal("0.4"), "B": Decimal("0.6")}
        sectors = {"A": "Tech", "B": "Health"}
        factor_values = {"A": Decimal("1.2"), "B": Decimal("-0.2")}
        exposures = compute_sector_exposures(weights, sectors)
        factor_exposure = compute_factor_exposure(weights, factor_values)
        self.assertEqual(exposures["Tech"], Decimal("0.4"))
        self.assertEqual(exposures["Health"], Decimal("0.6"))
        self.assertEqual(factor_exposure, Decimal("0.36"))

    def test_compute_return_beta(self) -> None:
        metrics = compute_return_beta(
            [Decimal("0.01"), Decimal("0.02"), Decimal("-0.01")],
            [Decimal("0.005"), Decimal("0.01"), Decimal("-0.005")],
        )
        self.assertEqual(metrics.sample_size, 3)
        self.assertGreater(metrics.beta, Decimal("0"))
        self.assertGreater(metrics.correlation, Decimal("0"))
