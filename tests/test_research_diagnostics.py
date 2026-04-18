from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest import TestCase

from stock_quantification.backtest import RollingBacktestDay, RollingBacktestReport, RollingBacktestSummary
from stock_quantification.models import Market
from stock_quantification.research_diagnostics import (
    build_strategy_scorecard,
    summarize_alpha_mix,
    summarize_regimes,
)
from stock_quantification.strategy_catalog import strategy_presets_for_market


class ResearchDiagnosticsTests(TestCase):
    def test_summarize_alpha_mix_groups_known_factors(self) -> None:
        preset = next(item for item in strategy_presets_for_market(Market.US) if item.preset_id == "us_quality_focus")
        mix = summarize_alpha_mix(preset)
        self.assertEqual(mix[0].family, "quality")
        self.assertGreater(mix[0].gross_weight, Decimal("0"))

    def test_regime_and_scorecard_capture_keep_candidate(self) -> None:
        preset = next(item for item in strategy_presets_for_market(Market.US) if item.preset_id == "us_baseline")
        report = RollingBacktestReport(
            summary=RollingBacktestSummary(
                market="US",
                preset_id=preset.preset_id,
                display_name=preset.display_name,
                start_date=date(2026, 1, 1).isoformat(),
                end_date=date(2026, 1, 3).isoformat(),
                trading_days=3,
                initial_cash=Decimal("100000"),
                final_nav=Decimal("106000"),
                total_return=Decimal("0.0600"),
                max_drawdown=Decimal("-0.0400"),
                best_nav=Decimal("106000"),
                worst_nav=Decimal("100000"),
                days_with_fills=2,
                buy_fill_count=2,
                sell_fill_count=1,
                benchmark_available=True,
                benchmark_final_nav=Decimal("103000"),
                benchmark_total_return=Decimal("0.0300"),
                benchmark_max_drawdown=Decimal("-0.0200"),
                excess_return=Decimal("0.0300"),
                annualized_return=Decimal("0.8000"),
                annualized_volatility=Decimal("0.1500"),
                sharpe_ratio=Decimal("1.2000"),
                average_turnover=Decimal("0.0800"),
                total_traded_notional=Decimal("30000"),
                total_fees=Decimal("120"),
                fee_drag=Decimal("0.0012"),
                pre_fee_return=Decimal("0.0612"),
            ),
            daily=[
                RollingBacktestDay(
                    trade_date="2026-01-01",
                    end_of_day_nav=Decimal("100000"),
                    cash=Decimal("50000"),
                    benchmark_nav=Decimal("100000"),
                    period_return=Decimal("0"),
                    benchmark_period_return=Decimal("0"),
                    excess_period_return=Decimal("0"),
                    portfolio_return=Decimal("0"),
                    benchmark_return=Decimal("0"),
                    excess_return=Decimal("0"),
                    cumulative_portfolio_return=Decimal("0"),
                    cumulative_benchmark_return=Decimal("0"),
                    cumulative_excess_return=Decimal("0"),
                    buy_fill_count=0,
                    sell_fill_count=0,
                    gross_traded_notional=Decimal("0"),
                    total_fees=Decimal("0"),
                    turnover=Decimal("0"),
                ),
                RollingBacktestDay(
                    trade_date="2026-01-02",
                    end_of_day_nav=Decimal("103000"),
                    cash=Decimal("48000"),
                    benchmark_nav=Decimal("101000"),
                    period_return=Decimal("0.0300"),
                    benchmark_period_return=Decimal("0.0100"),
                    excess_period_return=Decimal("0.0200"),
                    portfolio_return=Decimal("0.0300"),
                    benchmark_return=Decimal("0.0100"),
                    excess_return=Decimal("0.0200"),
                    cumulative_portfolio_return=Decimal("0.0300"),
                    cumulative_benchmark_return=Decimal("0.0100"),
                    cumulative_excess_return=Decimal("0.0200"),
                    buy_fill_count=1,
                    sell_fill_count=0,
                    gross_traded_notional=Decimal("15000"),
                    total_fees=Decimal("50"),
                    turnover=Decimal("0.1456"),
                ),
                RollingBacktestDay(
                    trade_date="2026-01-03",
                    end_of_day_nav=Decimal("106000"),
                    cash=Decimal("47000"),
                    benchmark_nav=Decimal("103000"),
                    period_return=Decimal("0.0291"),
                    benchmark_period_return=Decimal("0.0198"),
                    excess_period_return=Decimal("0.0093"),
                    portfolio_return=Decimal("0.0600"),
                    benchmark_return=Decimal("0.0300"),
                    excess_return=Decimal("0.0300"),
                    cumulative_portfolio_return=Decimal("0.0600"),
                    cumulative_benchmark_return=Decimal("0.0300"),
                    cumulative_excess_return=Decimal("0.0300"),
                    buy_fill_count=1,
                    sell_fill_count=1,
                    gross_traded_notional=Decimal("15000"),
                    total_fees=Decimal("70"),
                    turnover=Decimal("0.1415"),
                ),
            ],
        )
        regimes = summarize_regimes(report)
        scorecard = build_strategy_scorecard(preset, report, regimes)
        self.assertEqual(len(regimes), 2)
        self.assertEqual(scorecard.decision, "KEEP")
        self.assertGreater(scorecard.score, Decimal("0"))
