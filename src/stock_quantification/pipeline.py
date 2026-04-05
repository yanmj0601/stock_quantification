from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from math import sqrt
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from .interfaces import MarketDataProvider
from .models import AssetType, Bar, Instrument, InstrumentStatus, Market, Position, TargetPosition


def _to_decimal(value: object) -> Decimal:
    if isinstance(value, Decimal):
        return value
    if value is None:
        return Decimal("0")
    return Decimal(str(value))


def _mean(values: Sequence[Decimal]) -> Decimal:
    if not values:
        return Decimal("0")
    return sum(values, Decimal("0")) / Decimal(len(values))


def _std(values: Sequence[Decimal]) -> Decimal:
    if len(values) < 2:
        return Decimal("0")
    avg = _mean(values)
    variance = sum((value - avg) ** 2 for value in values) / Decimal(len(values) - 1)
    return Decimal(str(sqrt(float(variance))))


def _zscore(value: Decimal, mean: Decimal, std: Decimal) -> Decimal:
    if std == 0:
        return Decimal("0")
    return (value - mean) / std


def _clamp(value: Decimal, lower: Decimal, upper: Decimal) -> Decimal:
    return max(lower, min(value, upper))


def _max_drawdown(closes: Sequence[Decimal]) -> Decimal:
    if len(closes) < 2:
        return Decimal("0")
    peak = closes[0]
    worst = Decimal("0")
    for close in closes:
        if close > peak:
            peak = close
        if peak != 0:
            drawdown = (close / peak) - Decimal("1")
            if drawdown < worst:
                worst = drawdown
    return worst


def _simple_return(closes: Sequence[Decimal]) -> Decimal:
    if len(closes) < 2 or closes[0] == 0:
        return Decimal("0")
    return (closes[-1] / closes[0]) - Decimal("1")


def _moving_average(values: Sequence[Decimal]) -> Decimal:
    return _mean(values)


def _sector_for(instrument: Instrument) -> str:
    return str(
        instrument.attributes.get("sector")
        or instrument.attributes.get("industry")
        or instrument.attributes.get("sector_name")
        or "UNKNOWN"
    )


@dataclass(frozen=True)
class UniverseFilter:
    min_listed_days: int = 120
    min_history_bars: int = 2
    lookback_bars: int = 60
    min_average_turnover: Decimal = Decimal("50000000")
    min_latest_price: Decimal = Decimal("3")
    max_latest_price: Optional[Decimal] = None
    allowed_asset_types: Tuple[AssetType, ...] = (AssetType.COMMON_STOCK,)
    excluded_statuses: Tuple[InstrumentStatus, ...] = (InstrumentStatus.HALTED,)
    require_not_st: bool = True
    allowed_instrument_ids: Optional[Tuple[str, ...]] = None


@dataclass(frozen=True)
class FeatureConfig:
    return_windows: Tuple[int, ...] = (5, 20, 60)
    volatility_window: int = 20
    trend_window: int = 20
    liquidity_window: int = 20
    benchmark_window: int = 20

    @property
    def max_lookback(self) -> int:
        return max(
            max(self.return_windows, default=1),
            self.volatility_window,
            self.trend_window,
            self.liquidity_window,
            self.benchmark_window,
        )


@dataclass(frozen=True)
class PortfolioPolicy:
    top_n: int = 10
    max_position_weight: Decimal = Decimal("0.15")
    max_sector_weight: Decimal = Decimal("0.35")
    cash_buffer: Decimal = Decimal("0.05")
    benchmark_blend: Decimal = Decimal("0.0")
    turnover_cap: Decimal = Decimal("0.25")
    rebalance_buffer: Decimal = Decimal("0.00")
    min_alpha: Decimal = Decimal("0")


@dataclass(frozen=True)
class StrategyBlueprint:
    strategy_id: str
    market: Market
    universe_filter: UniverseFilter
    feature_config: FeatureConfig
    alpha_weights: Mapping[str, Decimal]
    portfolio_policy: PortfolioPolicy
    benchmark_instrument_id: Optional[str] = None
    benchmark_weights: Mapping[str, Decimal] = field(default_factory=dict)


@dataclass(frozen=True)
class UniverseMember:
    instrument: Instrument
    latest_bar: Bar
    average_turnover: Decimal
    latest_price: Decimal
    listed_days: int
    sector: str


@dataclass(frozen=True)
class UniverseSelection:
    market: Market
    as_of: datetime
    selected: List[UniverseMember]
    rejected: Dict[str, List[str]]


@dataclass(frozen=True)
class FeatureRow:
    instrument_id: str
    market: Market
    sector: str
    raw: Dict[str, Decimal]
    standardized: Dict[str, Decimal]


@dataclass(frozen=True)
class AlphaScore:
    instrument_id: str
    score: Decimal
    contributions: Dict[str, Decimal]


@dataclass(frozen=True)
class PortfolioDiagnostics:
    gross_exposure: Decimal
    cash_buffer: Decimal
    turnover: Decimal
    sector_exposure: Dict[str, Decimal]
    selected_count: int


@dataclass(frozen=True)
class PortfolioPlan:
    targets: List[TargetPosition]
    weights: Dict[str, Decimal]
    diagnostics: PortfolioDiagnostics


@dataclass(frozen=True)
class ResearchPipelineResult:
    blueprint: StrategyBlueprint
    universe: UniverseSelection
    features: List[FeatureRow]
    alpha_scores: List[AlphaScore]
    portfolio: PortfolioPlan


class UniverseBuilder:
    def __init__(self, data_provider: MarketDataProvider) -> None:
        self._data_provider = data_provider

    def build(self, blueprint: StrategyBlueprint, as_of: datetime) -> UniverseSelection:
        selected: List[UniverseMember] = []
        rejected: Dict[str, List[str]] = {}
        for instrument in self._data_provider.list_instruments(blueprint.market):
            reasons = self._screen_instrument(instrument, blueprint, as_of)
            if reasons:
                rejected[instrument.instrument_id] = reasons
                continue
            latest_bar = self._data_provider.get_latest_bar(instrument.instrument_id, as_of)
            history = self._data_provider.get_price_history(
                instrument.instrument_id,
                as_of,
                blueprint.universe_filter.lookback_bars,
            )
            average_turnover = _mean([bar.turnover for bar in history])
            selected.append(
                UniverseMember(
                    instrument=instrument,
                    latest_bar=latest_bar,
                    average_turnover=average_turnover,
                    latest_price=latest_bar.close,
                    listed_days=int(instrument.attributes.get("listed_days", 3650)),
                    sector=_sector_for(instrument),
                )
            )
        selected.sort(key=lambda item: (item.average_turnover, item.latest_price), reverse=True)
        return UniverseSelection(market=blueprint.market, as_of=as_of, selected=selected, rejected=rejected)

    def _screen_instrument(self, instrument: Instrument, blueprint: StrategyBlueprint, as_of: datetime) -> List[str]:
        reasons: List[str] = []
        universe_filter = blueprint.universe_filter
        if instrument.status in universe_filter.excluded_statuses:
            reasons.append("status_excluded")
        if instrument.asset_type not in universe_filter.allowed_asset_types:
            reasons.append("asset_type_excluded")
        if universe_filter.require_not_st and bool(instrument.attributes.get("is_st")):
            reasons.append("st_excluded")
        if universe_filter.allowed_instrument_ids and instrument.instrument_id not in universe_filter.allowed_instrument_ids:
            reasons.append("not_in_allowed_set")
        listed_days_value = instrument.attributes.get("listed_days")
        if listed_days_value is not None and int(listed_days_value) < universe_filter.min_listed_days:
            reasons.append("listed_days_too_short")

        try:
            latest_bar = self._data_provider.get_latest_bar(instrument.instrument_id, as_of)
            history = self._data_provider.get_price_history(
                instrument.instrument_id,
                as_of,
                universe_filter.lookback_bars,
            )
            if len(history) < universe_filter.min_history_bars:
                reasons.append("insufficient_history")
                return reasons
            latest_price = latest_bar.close
            if latest_price < universe_filter.min_latest_price:
                reasons.append("price_too_low")
            if universe_filter.max_latest_price is not None and latest_price > universe_filter.max_latest_price:
                reasons.append("price_too_high")
            average_turnover = _mean([bar.turnover for bar in history])
            if average_turnover < universe_filter.min_average_turnover:
                reasons.append("illiquid")
        except Exception:
            reasons.append("history_unavailable")
        return reasons


class FeaturePipeline:
    def __init__(self, data_provider: MarketDataProvider) -> None:
        self._data_provider = data_provider

    def build(self, blueprint: StrategyBlueprint, universe: UniverseSelection, as_of: datetime) -> List[FeatureRow]:
        benchmark_returns = self._benchmark_returns(blueprint, as_of)
        rows: List[FeatureRow] = []
        for member in universe.selected:
            history = self._data_provider.get_price_history(
                member.instrument.instrument_id,
                as_of,
                blueprint.feature_config.max_lookback + 1,
            )
            closes = [bar.close for bar in history]
            turnovers = [bar.turnover for bar in history]
            raw: Dict[str, Decimal] = {
                "profitability": _to_decimal(member.instrument.attributes.get("profitability", 0)),
                "quality": _to_decimal(member.instrument.attributes.get("quality", 0)),
                "leverage": _to_decimal(member.instrument.attributes.get("leverage", 0)),
                "liquidity": _mean(turnovers[-blueprint.feature_config.liquidity_window :]),
                "trend": _closes_ratio(closes, blueprint.feature_config.trend_window),
                "volatility": _volatility(closes, blueprint.feature_config.volatility_window),
                "drawdown": _max_drawdown(closes[-blueprint.feature_config.volatility_window :]),
                "sector_momentum": _to_decimal(member.instrument.attributes.get("sector_momentum", 0)),
            }
            for window in blueprint.feature_config.return_windows:
                raw[f"ret_{window}"] = _simple_return(closes[-(window + 1) :])
                if benchmark_returns:
                    raw[f"rel_ret_{window}"] = raw[f"ret_{window}"] - benchmark_returns.get(window, Decimal("0"))
            rows.append(
                FeatureRow(
                    instrument_id=member.instrument.instrument_id,
                    market=member.instrument.market,
                    sector=member.sector,
                    raw=raw,
                    standardized={},
                )
            )
        return self._standardize(rows)

    def _benchmark_returns(self, blueprint: StrategyBlueprint, as_of: datetime) -> Dict[int, Decimal]:
        if not blueprint.benchmark_instrument_id:
            return {}
        history = self._data_provider.get_price_history(
            blueprint.benchmark_instrument_id,
            as_of,
            blueprint.feature_config.max_lookback + 1,
        )
        closes = [bar.close for bar in history]
        return {
            window: _simple_return(closes[-(window + 1) :])
            for window in blueprint.feature_config.return_windows
            if len(closes) > window
        }

    def _standardize(self, rows: List[FeatureRow]) -> List[FeatureRow]:
        if not rows:
            return rows
        feature_names = sorted({feature for row in rows for feature in row.raw})
        stats = {
            feature: (
                _mean([row.raw.get(feature, Decimal("0")) for row in rows]),
                _std([row.raw.get(feature, Decimal("0")) for row in rows]),
            )
            for feature in feature_names
        }
        standardized_rows: List[FeatureRow] = []
        for row in rows:
            standardized = {
                feature: _zscore(row.raw.get(feature, Decimal("0")), stats[feature][0], stats[feature][1])
                for feature in feature_names
            }
            standardized_rows.append(
                FeatureRow(
                    instrument_id=row.instrument_id,
                    market=row.market,
                    sector=row.sector,
                    raw=row.raw,
                    standardized=standardized,
                )
            )
        return standardized_rows


class AlphaModel:
    def score(self, features: List[FeatureRow], weights: Mapping[str, Decimal]) -> List[AlphaScore]:
        scores: List[AlphaScore] = []
        for row in features:
            contributions: Dict[str, Decimal] = {}
            total = Decimal("0")
            for feature_name, weight in weights.items():
                feature_value = row.standardized.get(feature_name, Decimal("0"))
                contribution = _to_decimal(weight) * feature_value
                contributions[feature_name] = contribution
                total += contribution
            scores.append(
                AlphaScore(
                    instrument_id=row.instrument_id,
                    score=total.quantize(Decimal("0.0001")),
                    contributions=contributions,
                )
            )
        scores.sort(key=lambda item: item.score, reverse=True)
        return scores


class PortfolioBuilder:
    def build(
        self,
        blueprint: StrategyBlueprint,
        universe: UniverseSelection,
        features: List[FeatureRow],
        alpha_scores: List[AlphaScore],
        current_weights: Optional[Mapping[str, Decimal]] = None,
    ) -> PortfolioPlan:
        feature_map = {row.instrument_id: row for row in features}
        candidate_scores = alpha_scores[: blueprint.portfolio_policy.top_n]
        if not candidate_scores:
            return PortfolioPlan(targets=[], weights={}, diagnostics=PortfolioDiagnostics(Decimal("0"), blueprint.portfolio_policy.cash_buffer, Decimal("0"), {}, 0))

        active_weights = self._build_active_weights(candidate_scores, blueprint.portfolio_policy)
        benchmark_weights = self._normalise_weights(
            blueprint.benchmark_weights,
            Decimal("1") - blueprint.portfolio_policy.cash_buffer,
        )
        blended = self._blend_with_benchmark(active_weights, benchmark_weights, blueprint.portfolio_policy)
        target_capped = self._apply_position_caps(
            self._apply_sector_caps(blended, feature_map, blueprint.portfolio_policy),
            blueprint.portfolio_policy,
        )
        current_capped: Optional[Mapping[str, Decimal]] = None
        if current_weights:
            normalized_current = self._normalise_weights(current_weights, Decimal("1") - blueprint.portfolio_policy.cash_buffer)
            current_capped = self._apply_position_caps(
                self._apply_sector_caps(normalized_current, feature_map, blueprint.portfolio_policy),
                blueprint.portfolio_policy,
            )
        buffered_target = self._apply_rebalance_buffer(target_capped, current_capped, blueprint.portfolio_policy)
        final_weights = self._apply_turnover_cap(buffered_target, current_capped, blueprint.portfolio_policy)
        final_weights = self._normalize_to_investable(final_weights, blueprint.portfolio_policy)

        diagnostics = PortfolioDiagnostics(
            gross_exposure=sum(final_weights.values(), Decimal("0")),
            cash_buffer=Decimal("1") - sum(final_weights.values(), Decimal("0")),
            turnover=self._turnover(final_weights, current_capped),
            sector_exposure=self._sector_exposure(final_weights, feature_map),
            selected_count=len(candidate_scores),
        )
        targets = [
            TargetPosition(
                as_of=universe.as_of,
                strategy_id=blueprint.strategy_id,
                account_scope=blueprint.market.value,
                instrument_id=instrument_id,
                target_weight=weight.quantize(Decimal("0.0001")),
            )
            for instrument_id, weight in final_weights.items()
            if weight > 0
        ]
        targets.sort(key=lambda item: item.target_weight, reverse=True)
        return PortfolioPlan(targets=targets, weights=final_weights, diagnostics=diagnostics)

    def _build_active_weights(self, alpha_scores: List[AlphaScore], policy: PortfolioPolicy) -> Dict[str, Decimal]:
        investable = Decimal("1") - policy.cash_buffer
        positive_scores = [max(score.score, Decimal("0")) for score in alpha_scores]
        if sum(positive_scores, Decimal("0")) == 0:
            equal_weight = investable / Decimal(len(alpha_scores))
            return {score.instrument_id: equal_weight for score in alpha_scores}
        total = sum(positive_scores, Decimal("0"))
        return {
            score.instrument_id: (score.score if score.score > 0 else Decimal("0")) / total * investable
            for score in alpha_scores
        }

    def _blend_with_benchmark(
        self,
        active_weights: Mapping[str, Decimal],
        benchmark_weights: Mapping[str, Decimal],
        policy: PortfolioPolicy,
    ) -> Dict[str, Decimal]:
        if not benchmark_weights or policy.benchmark_blend <= 0:
            return dict(active_weights)
        investable = Decimal("1") - policy.cash_buffer
        securities = set(active_weights) | set(benchmark_weights)
        blended = {
            instrument_id: (Decimal("1") - policy.benchmark_blend) * active_weights.get(instrument_id, Decimal("0"))
            + policy.benchmark_blend * benchmark_weights.get(instrument_id, Decimal("0"))
            for instrument_id in securities
        }
        return self._normalize_to_investable(blended, policy)

    def _apply_sector_caps(
        self,
        weights: Mapping[str, Decimal],
        feature_map: Mapping[str, FeatureRow],
        policy: PortfolioPolicy,
    ) -> Dict[str, Decimal]:
        adjusted = dict(weights)
        for sector, exposure in self._sector_exposure(adjusted, feature_map).items():
            if exposure <= policy.max_sector_weight or exposure == 0:
                continue
            factor = policy.max_sector_weight / exposure
            for instrument_id, weight in list(adjusted.items()):
                if feature_map.get(instrument_id) and feature_map[instrument_id].sector == sector:
                    adjusted[instrument_id] = weight * factor
        return adjusted

    def _apply_position_caps(self, weights: Mapping[str, Decimal], policy: PortfolioPolicy) -> Dict[str, Decimal]:
        adjusted = dict(weights)
        for instrument_id, weight in list(adjusted.items()):
            if weight > policy.max_position_weight:
                adjusted[instrument_id] = policy.max_position_weight
        return adjusted

    def _apply_turnover_cap(
        self,
        target_weights: Mapping[str, Decimal],
        current_weights: Optional[Mapping[str, Decimal]],
        policy: PortfolioPolicy,
    ) -> Dict[str, Decimal]:
        if not current_weights or policy.turnover_cap <= 0:
            return dict(target_weights)
        current = dict(current_weights)
        target = dict(target_weights)
        turnover = self._turnover(target, current)
        if turnover <= policy.turnover_cap:
            return target
        scale = policy.turnover_cap / turnover if turnover > 0 else Decimal("0")
        securities = set(current) | set(target)
        adjusted = {
            instrument_id: current.get(instrument_id, Decimal("0"))
            + (target.get(instrument_id, Decimal("0")) - current.get(instrument_id, Decimal("0"))) * scale
            for instrument_id in securities
        }
        return adjusted

    def _apply_rebalance_buffer(
        self,
        target_weights: Mapping[str, Decimal],
        current_weights: Optional[Mapping[str, Decimal]],
        policy: PortfolioPolicy,
    ) -> Dict[str, Decimal]:
        if not current_weights or policy.rebalance_buffer <= 0:
            return dict(target_weights)
        adjusted: Dict[str, Decimal] = {}
        securities = set(target_weights) | set(current_weights)
        for instrument_id in securities:
            current_weight = current_weights.get(instrument_id, Decimal("0"))
            target_weight = target_weights.get(instrument_id, Decimal("0"))
            drift = target_weight - current_weight
            if target_weight == 0 and current_weight <= policy.rebalance_buffer:
                continue
            if abs(drift) <= policy.rebalance_buffer:
                if current_weight > 0:
                    adjusted[instrument_id] = current_weight
                continue
            if target_weight > 0:
                adjusted[instrument_id] = target_weight
        return adjusted

    def _normalize_to_investable(self, weights: Mapping[str, Decimal], policy: PortfolioPolicy) -> Dict[str, Decimal]:
        investable = Decimal("1") - policy.cash_buffer
        total = sum(weights.values(), Decimal("0"))
        if total <= 0:
            return {}
        if total <= investable:
            return {instrument_id: Decimal(weight) for instrument_id, weight in weights.items() if Decimal(weight) > 0}
        return {instrument_id: (weight / total) * investable for instrument_id, weight in weights.items() if weight > 0}

    def _normalise_weights(self, weights: Mapping[str, Decimal], investable: Decimal) -> Dict[str, Decimal]:
        total = sum(weights.values(), Decimal("0"))
        if total <= 0:
            return {}
        return {
            instrument_id: (Decimal(weight) / total) * investable
            for instrument_id, weight in weights.items()
            if Decimal(weight) > 0
        }

    def _turnover(self, target: Mapping[str, Decimal], current: Optional[Mapping[str, Decimal]]) -> Decimal:
        if not current:
            return Decimal("0")
        securities = set(target) | set(current)
        return sum(abs(target.get(s, Decimal("0")) - current.get(s, Decimal("0"))) for s in securities) / Decimal("2")

    def _sector_exposure(self, weights: Mapping[str, Decimal], feature_map: Mapping[str, FeatureRow]) -> Dict[str, Decimal]:
        exposure: Dict[str, Decimal] = {}
        for instrument_id, weight in weights.items():
            sector = feature_map.get(instrument_id).sector if feature_map.get(instrument_id) else "UNKNOWN"
            exposure[sector] = exposure.get(sector, Decimal("0")) + weight
        return exposure


class ResearchPipeline:
    def __init__(self, data_provider: MarketDataProvider) -> None:
        self._universe_builder = UniverseBuilder(data_provider)
        self._feature_pipeline = FeaturePipeline(data_provider)
        self._alpha_model = AlphaModel()
        self._portfolio_builder = PortfolioBuilder()

    def run(
        self,
        blueprint: StrategyBlueprint,
        as_of: datetime,
        current_weights: Optional[Mapping[str, Decimal]] = None,
    ) -> ResearchPipelineResult:
        universe = self._universe_builder.build(blueprint, as_of)
        features = self._feature_pipeline.build(blueprint, universe, as_of)
        alpha_scores = self._alpha_model.score(features, blueprint.alpha_weights)
        portfolio = self._portfolio_builder.build(blueprint, universe, features, alpha_scores, current_weights=current_weights)
        return ResearchPipelineResult(
            blueprint=blueprint,
            universe=universe,
            features=features,
            alpha_scores=alpha_scores,
            portfolio=portfolio,
        )


def _closes_ratio(closes: Sequence[Decimal], window: int) -> Decimal:
    if len(closes) < window + 1:
        return Decimal("0")
    subset = closes[-(window + 1) :]
    if subset[0] == 0:
        return Decimal("0")
    return (subset[-1] / subset[0]) - Decimal("1")


def _volatility(closes: Sequence[Decimal], window: int) -> Decimal:
    subset = closes[-window:]
    if len(subset) < 2:
        return Decimal("0")
    returns = []
    for idx in range(1, len(subset)):
        prev = subset[idx - 1]
        current = subset[idx]
        if prev != 0:
            returns.append((current / prev) - Decimal("1"))
    return _std(returns)


def build_cn_index_enhancement_blueprint(
    benchmark_instrument_id: Optional[str] = None,
    allowed_instrument_ids: Optional[Tuple[str, ...]] = None,
    benchmark_weights: Optional[Mapping[str, Decimal]] = None,
) -> StrategyBlueprint:
    return StrategyBlueprint(
        strategy_id="cn_index_enhancement",
        market=Market.CN,
        universe_filter=UniverseFilter(
            min_listed_days=252,
            lookback_bars=60,
            min_average_turnover=Decimal("50000000"),
            min_latest_price=Decimal("3"),
            allowed_instrument_ids=allowed_instrument_ids,
        ),
        feature_config=FeatureConfig(return_windows=(5, 20, 60), volatility_window=20, trend_window=20, liquidity_window=20, benchmark_window=20),
        alpha_weights={
            "rel_ret_20": Decimal("0.18"),
            "rel_ret_60": Decimal("0.24"),
            "trend": Decimal("0.08"),
            "liquidity": Decimal("0.05"),
            "profitability": Decimal("0.25"),
            "volatility": Decimal("-0.10"),
            "drawdown": Decimal("-0.15"),
        },
        portfolio_policy=PortfolioPolicy(
            top_n=4,
            max_position_weight=Decimal("0.30"),
            max_sector_weight=Decimal("0.55"),
            cash_buffer=Decimal("0.05"),
            benchmark_blend=Decimal("0.15"),
            turnover_cap=Decimal("0.18"),
            rebalance_buffer=Decimal("0.05"),
            min_alpha=Decimal("0"),
        ),
        benchmark_instrument_id=benchmark_instrument_id,
        benchmark_weights=benchmark_weights or {},
    )


def build_us_quality_momentum_blueprint(
    benchmark_instrument_id: Optional[str] = None,
    allowed_instrument_ids: Optional[Tuple[str, ...]] = None,
    benchmark_weights: Optional[Mapping[str, Decimal]] = None,
) -> StrategyBlueprint:
    return StrategyBlueprint(
        strategy_id="us_quality_momentum",
        market=Market.US,
        universe_filter=UniverseFilter(
            min_listed_days=252,
            lookback_bars=60,
            min_average_turnover=Decimal("100000000"),
            min_latest_price=Decimal("5"),
            allowed_instrument_ids=allowed_instrument_ids,
        ),
        feature_config=FeatureConfig(return_windows=(5, 20, 60), volatility_window=20, trend_window=20, liquidity_window=20, benchmark_window=20),
        alpha_weights={
            "rel_ret_20": Decimal("0.15"),
            "rel_ret_60": Decimal("0.20"),
            "liquidity": Decimal("0.05"),
            "profitability": Decimal("0.25"),
            "quality": Decimal("0.15"),
            "trend": Decimal("0.10"),
            "volatility": Decimal("-0.10"),
            "drawdown": Decimal("-0.15"),
        },
        portfolio_policy=PortfolioPolicy(
            top_n=4,
            max_position_weight=Decimal("0.28"),
            max_sector_weight=Decimal("0.45"),
            cash_buffer=Decimal("0.05"),
            benchmark_blend=Decimal("0.10"),
            turnover_cap=Decimal("0.14"),
            rebalance_buffer=Decimal("0.06"),
            min_alpha=Decimal("0"),
        ),
        benchmark_instrument_id=benchmark_instrument_id,
        benchmark_weights=benchmark_weights or {},
    )
