from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Dict, List, Mapping

from .engine import AStockSelectionStrategy, USStockSelectionStrategy
from .models import Market
from .pipeline import build_cn_index_enhancement_blueprint, build_us_quality_momentum_blueprint


@dataclass(frozen=True)
class StrategyPreset:
    preset_id: str
    market: Market
    display_name: str
    family: str
    description: str
    alpha_weights: Dict[str, Decimal]
    policy_overrides: Dict[str, Decimal]
    top_n: int = 4
    implemented: bool = True


def _base_alpha_weights(market: Market) -> Dict[str, Decimal]:
    if market == Market.CN:
        return dict(build_cn_index_enhancement_blueprint().alpha_weights)
    return dict(build_us_quality_momentum_blueprint().alpha_weights)


def _only_factors(market: Market, factors: List[str]) -> Dict[str, Decimal]:
    base = _base_alpha_weights(market)
    selected_total = sum(abs(base[name]) for name in factors)
    full_total = sum(abs(value) for value in base.values())
    scale = (full_total / selected_total) if selected_total else Decimal("1")
    weights = {name: Decimal("0") for name in base}
    for factor_name in factors:
        weights[factor_name] = (base[factor_name] * scale).quantize(Decimal("0.0001"))
    return weights


def _weights(market: Market, mapping: Mapping[str, Decimal]) -> Dict[str, Decimal]:
    base = {name: Decimal("0") for name in _base_alpha_weights(market)}
    for key, value in mapping.items():
        if key in base:
            base[key] = Decimal(value)
    return base


def strategy_presets_for_market(market: Market) -> List[StrategyPreset]:
    if market == Market.CN:
        return [
            StrategyPreset(
                preset_id="cn_baseline",
                market=market,
                display_name="A股基线增强",
                family="指数增强",
                description="当前默认的指数增强型多因子策略。",
                alpha_weights=_base_alpha_weights(market),
                policy_overrides={},
            ),
            StrategyPreset(
                preset_id="cn_momentum_core",
                market=market,
                display_name="A股动量核心",
                family="动量",
                description="以20/60日相对强弱和趋势为核心的中期动量策略。",
                alpha_weights=_only_factors(market, ["rel_ret_20", "rel_ret_60", "trend"]),
                policy_overrides={"turnover_cap": Decimal("0.20"), "rebalance_buffer": Decimal("0.04")},
            ),
            StrategyPreset(
                preset_id="cn_quality_momentum",
                market=market,
                display_name="A股质量动量",
                family="质量+动量",
                description="盈利能力叠加中期动量，兼顾趋势和回撤。",
                alpha_weights=_weights(
                    market,
                    {
                        "rel_ret_20": Decimal("0.16"),
                        "rel_ret_60": Decimal("0.24"),
                        "trend": Decimal("0.08"),
                        "profitability": Decimal("0.28"),
                        "volatility": Decimal("-0.08"),
                        "drawdown": Decimal("-0.16"),
                    },
                ),
                policy_overrides={"turnover_cap": Decimal("0.16"), "rebalance_buffer": Decimal("0.05")},
            ),
            StrategyPreset(
                preset_id="cn_low_vol_defensive",
                market=market,
                display_name="A股低波防御",
                family="低波动",
                description="降低波动和回撤暴露，保留少量中期趋势与盈利质量。",
                alpha_weights=_weights(
                    market,
                    {
                        "rel_ret_60": Decimal("0.16"),
                        "liquidity": Decimal("0.06"),
                        "profitability": Decimal("0.22"),
                        "volatility": Decimal("-0.26"),
                        "drawdown": Decimal("-0.24"),
                    },
                ),
                policy_overrides={"turnover_cap": Decimal("0.12"), "rebalance_buffer": Decimal("0.07")},
            ),
            StrategyPreset(
                preset_id="cn_liquidity_leaders",
                market=market,
                display_name="A股流动性龙头",
                family="流动性",
                description="优先流动性和中期强势，偏向高成交活跃标的。",
                alpha_weights=_weights(
                    market,
                    {
                        "rel_ret_20": Decimal("0.18"),
                        "rel_ret_60": Decimal("0.18"),
                        "trend": Decimal("0.08"),
                        "liquidity": Decimal("0.32"),
                        "drawdown": Decimal("-0.12"),
                    },
                ),
                policy_overrides={"turnover_cap": Decimal("0.18"), "rebalance_buffer": Decimal("0.05")},
            ),
        ]

    return [
        StrategyPreset(
            preset_id="us_baseline",
            market=market,
            display_name="美股基线质量动量",
            family="质量+动量",
            description="当前默认的大市值质量动量多因子策略。",
            alpha_weights=_base_alpha_weights(market),
            policy_overrides={},
        ),
        StrategyPreset(
            preset_id="us_momentum_core",
            market=market,
            display_name="美股动量核心",
            family="动量",
            description="以相对强弱和趋势为核心的中期动量策略。",
            alpha_weights=_only_factors(market, ["rel_ret_20", "rel_ret_60", "trend", "liquidity"]),
            policy_overrides={"turnover_cap": Decimal("0.14"), "rebalance_buffer": Decimal("0.05")},
        ),
        StrategyPreset(
            preset_id="us_quality_focus",
            market=market,
            display_name="美股质量精选",
            family="质量",
            description="以盈利能力和经营质量为核心，辅以回撤控制。",
            alpha_weights=_weights(
                market,
                {
                    "rel_ret_60": Decimal("0.12"),
                    "profitability": Decimal("0.32"),
                    "quality": Decimal("0.24"),
                    "volatility": Decimal("-0.10"),
                    "drawdown": Decimal("-0.18"),
                },
            ),
            policy_overrides={"turnover_cap": Decimal("0.10"), "rebalance_buffer": Decimal("0.08")},
        ),
        StrategyPreset(
            preset_id="us_low_vol_defensive",
            market=market,
            display_name="美股低波防御",
            family="低波动",
            description="质量和盈利能力叠加低波动约束，强调防守。",
            alpha_weights=_weights(
                market,
                {
                    "rel_ret_60": Decimal("0.10"),
                    "profitability": Decimal("0.20"),
                    "quality": Decimal("0.20"),
                    "volatility": Decimal("-0.28"),
                    "drawdown": Decimal("-0.22"),
                },
            ),
            policy_overrides={"turnover_cap": Decimal("0.10"), "rebalance_buffer": Decimal("0.08")},
        ),
        StrategyPreset(
            preset_id="us_liquidity_leaders",
            market=market,
            display_name="美股流动性龙头",
            family="流动性",
            description="优先高流动性大市值股票，保留一定中期动量。",
            alpha_weights=_weights(
                market,
                {
                    "rel_ret_20": Decimal("0.16"),
                    "rel_ret_60": Decimal("0.18"),
                    "liquidity": Decimal("0.34"),
                    "trend": Decimal("0.08"),
                    "drawdown": Decimal("-0.14"),
                },
            ),
            policy_overrides={"turnover_cap": Decimal("0.12"), "rebalance_buffer": Decimal("0.06")},
        ),
    ]


def build_strategy_from_preset(
    preset: StrategyPreset,
    benchmark_instrument_id: str | None,
    benchmark_weights: Mapping[str, Decimal],
):
    common_kwargs = {
        "top_n": preset.top_n,
        "benchmark_instrument_id": benchmark_instrument_id,
        "benchmark_weights": dict(benchmark_weights),
        "alpha_weights_override": dict(preset.alpha_weights),
        "portfolio_policy_override": dict(preset.policy_overrides),
    }
    if preset.market == Market.CN:
        return AStockSelectionStrategy(**common_kwargs)
    return USStockSelectionStrategy(**common_kwargs)
