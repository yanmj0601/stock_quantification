from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal
from unittest import TestCase

from stock_quantification.engine import InMemoryMarketDataProvider
from stock_quantification.models import AssetType, Bar, Instrument, Market
from stock_quantification.pipeline import (
    PortfolioPolicy,
    ResearchPipeline,
    UniverseBuilder,
    build_cn_index_enhancement_blueprint,
    build_us_quality_momentum_blueprint,
)


def _build_bars(instrument_id: str, start_price: Decimal, start_dt: datetime, days: int, step: Decimal, turnover: Decimal):
    bars = []
    price = start_price
    for index in range(days):
        current_dt = start_dt + timedelta(days=index)
        open_price = price
        close_price = price + step
        high_price = close_price + Decimal("0.2")
        low_price = open_price - Decimal("0.2")
        bars.append(
            Bar(
                instrument_id=instrument_id,
                timestamp=current_dt,
                open=open_price,
                high=high_price,
                low=low_price,
                close=close_price,
                volume=1000000 + index * 1000,
                turnover=turnover + Decimal(index * 10000),
            )
        )
        price = close_price
    return bars


class PipelineTests(TestCase):
    def setUp(self) -> None:
        self.as_of = datetime(2026, 4, 3, 15, 0, 0)
        start_dt = self.as_of - timedelta(days=69)
        instruments = [
            Instrument(
                "CN.600036",
                Market.CN,
                "600036",
                AssetType.COMMON_STOCK,
                "CNY",
                "SSE",
                attributes={"listed_days": 900, "sector": "Financials", "profitability": "0.4"},
            ),
            Instrument(
                "CN.600519",
                Market.CN,
                "600519",
                AssetType.COMMON_STOCK,
                "CNY",
                "SSE",
                attributes={"listed_days": 1600, "sector": "Consumer", "profitability": "0.8"},
            ),
            Instrument(
                "CN.000333",
                Market.CN,
                "000333",
                AssetType.COMMON_STOCK,
                "CNY",
                "SZSE",
                attributes={"listed_days": 1200, "sector": "Industrials", "profitability": "0.5"},
            ),
            Instrument(
                "CN.600666",
                Market.CN,
                "600666",
                AssetType.COMMON_STOCK,
                "CNY",
                "SSE",
                attributes={"listed_days": 1000, "sector": "Industrials", "profitability": "0.2", "is_st": True},
            ),
            Instrument(
                "US.AAPL",
                Market.US,
                "AAPL",
                AssetType.COMMON_STOCK,
                "USD",
                "NASDAQ",
                attributes={"listed_days": 2000, "sector": "Technology", "profitability": "0.7", "quality": "0.6"},
            ),
            Instrument(
                "US.MSFT",
                Market.US,
                "MSFT",
                AssetType.COMMON_STOCK,
                "USD",
                "NASDAQ",
                attributes={"listed_days": 2200, "sector": "Technology", "profitability": "0.9", "quality": "0.8"},
            ),
            Instrument(
                "US.JNJ",
                Market.US,
                "JNJ",
                AssetType.COMMON_STOCK,
                "USD",
                "NYSE",
                attributes={"listed_days": 2200, "sector": "HealthCare", "profitability": "0.5", "quality": "0.7"},
            ),
            Instrument(
                "US.BABA",
                Market.US,
                "BABA",
                AssetType.ADR,
                "USD",
                "NYSE",
                attributes={"listed_days": 1200, "sector": "Technology", "profitability": "0.3"},
            ),
        ]
        bars = {
            "CN.600036": _build_bars("CN.600036", Decimal("36"), start_dt, 70, Decimal("0.15"), Decimal("600000000")),
            "CN.600519": _build_bars("CN.600519", Decimal("1500"), start_dt, 70, Decimal("1.2"), Decimal("800000000")),
            "CN.000333": _build_bars("CN.000333", Decimal("45"), start_dt, 70, Decimal("0.25"), Decimal("700000000")),
            "CN.600666": _build_bars("CN.600666", Decimal("8"), start_dt, 70, Decimal("0.05"), Decimal("100000000")),
            "US.AAPL": _build_bars("US.AAPL", Decimal("180"), start_dt, 70, Decimal("0.6"), Decimal("1500000000")),
            "US.MSFT": _build_bars("US.MSFT", Decimal("300"), start_dt, 70, Decimal("0.8"), Decimal("1800000000")),
            "US.JNJ": _build_bars("US.JNJ", Decimal("150"), start_dt, 70, Decimal("0.3"), Decimal("1200000000")),
            "US.BABA": _build_bars("US.BABA", Decimal("90"), start_dt, 70, Decimal("0.4"), Decimal("900000000")),
        }
        self.data_provider = InMemoryMarketDataProvider(instruments, bars)

    def test_universe_builder_filters_st_and_adr(self) -> None:
        cn_blueprint = build_cn_index_enhancement_blueprint(allowed_instrument_ids=("CN.600036", "CN.600519", "CN.000333", "CN.600666"))
        us_blueprint = build_us_quality_momentum_blueprint(allowed_instrument_ids=("US.AAPL", "US.MSFT", "US.JNJ", "US.BABA"))

        cn_universe = UniverseBuilder(self.data_provider).build(cn_blueprint, self.as_of)
        us_universe = UniverseBuilder(self.data_provider).build(us_blueprint, self.as_of)

        self.assertNotIn("CN.600666", [member.instrument.instrument_id for member in cn_universe.selected])
        self.assertNotIn("US.BABA", [member.instrument.instrument_id for member in us_universe.selected])

    def test_research_pipeline_generates_multi_factor_alpha(self) -> None:
        blueprint = build_us_quality_momentum_blueprint(
            allowed_instrument_ids=("US.AAPL", "US.MSFT", "US.JNJ"),
        )
        result = ResearchPipeline(self.data_provider).run(blueprint, self.as_of)

        self.assertTrue(result.features)
        self.assertIn("ret_20", result.features[0].raw)
        self.assertIn("volatility", result.features[0].raw)
        self.assertIn("profitability", result.features[0].raw)
        self.assertTrue(result.alpha_scores)
        self.assertTrue(result.portfolio.targets)

    def test_portfolio_builder_applies_sector_and_turnover_controls(self) -> None:
        blueprint = build_us_quality_momentum_blueprint(
            allowed_instrument_ids=("US.AAPL", "US.MSFT", "US.JNJ"),
        )
        blueprint = replace(
            blueprint,
            benchmark_weights={"US.AAPL": Decimal("0.40"), "US.MSFT": Decimal("0.40"), "US.JNJ": Decimal("0.20")},
            portfolio_policy=PortfolioPolicy(
                top_n=3,
                max_position_weight=Decimal("0.50"),
                max_sector_weight=Decimal("0.45"),
                cash_buffer=Decimal("0.05"),
                benchmark_blend=Decimal("0.20"),
                turnover_cap=Decimal("0.10"),
                min_alpha=Decimal("0"),
            ),
        )
        current_weights = {
            "US.AAPL": Decimal("0.60"),
            "US.MSFT": Decimal("0.20"),
            "US.JNJ": Decimal("0.15"),
        }

        result = ResearchPipeline(self.data_provider).run(blueprint, self.as_of, current_weights=current_weights)
        tech_weight = result.portfolio.diagnostics.sector_exposure.get("Technology", Decimal("0"))

        self.assertLessEqual(result.portfolio.diagnostics.turnover, Decimal("0.10"))
        self.assertLessEqual(tech_weight, Decimal("0.45"))
        self.assertEqual(result.portfolio.diagnostics.selected_count, 3)

    def test_portfolio_builder_uses_rebalance_buffer_to_hold_near_target_weights(self) -> None:
        blueprint = build_us_quality_momentum_blueprint(
            allowed_instrument_ids=("US.AAPL", "US.MSFT", "US.JNJ"),
        )
        blueprint = replace(
            blueprint,
            alpha_weights={},
            portfolio_policy=PortfolioPolicy(
                top_n=3,
                max_position_weight=Decimal("0.60"),
                max_sector_weight=Decimal("0.80"),
                cash_buffer=Decimal("0.05"),
                benchmark_blend=Decimal("0.00"),
                turnover_cap=Decimal("1.00"),
                rebalance_buffer=Decimal("0.10"),
                min_alpha=Decimal("0"),
            ),
        )
        current_weights = {
            "US.AAPL": Decimal("0.34"),
            "US.MSFT": Decimal("0.31"),
            "US.JNJ": Decimal("0.30"),
        }

        result = ResearchPipeline(self.data_provider).run(blueprint, self.as_of, current_weights=current_weights)
        target_weights = result.portfolio.weights

        self.assertEqual(target_weights["US.AAPL"].quantize(Decimal("0.0001")), Decimal("0.3400"))
        self.assertEqual(target_weights["US.MSFT"].quantize(Decimal("0.0001")), Decimal("0.3100"))
        self.assertEqual(target_weights["US.JNJ"].quantize(Decimal("0.0001")), Decimal("0.3000"))
        self.assertEqual(result.portfolio.diagnostics.turnover.quantize(Decimal("0.0001")), Decimal("0.0000"))
