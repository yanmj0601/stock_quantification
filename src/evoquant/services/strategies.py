from __future__ import annotations

from dataclasses import dataclass
from math import sqrt
from statistics import pstdev
from typing import Mapping

from evoquant.domain import Market, SignalSide
from evoquant.services.market_data import MarketBar


@dataclass(frozen=True)
class StrategySignal:
    symbol: str
    market: Market
    signal: SignalSide
    score: float
    target_weight: float
    reason: str
    risk_flags: tuple[str, ...]
    as_of_date: str


@dataclass(frozen=True)
class _ScoredSymbol:
    symbol: str
    market: Market
    latest: MarketBar
    long_return: float
    short_return: float
    volatility: float
    max_drawdown: float
    risk_flags: tuple[str, ...]
    score: float = 0.0
    rank: int = 0


class PortfolioConstructor:
    def __init__(self, max_weight: float):
        self.max_weight = float(max_weight)

    def assign_weights(
        self, scores: list[tuple[str, Market, float]]
    ) -> dict[tuple[str, Market], float]:
        positive_scores = [(symbol, market, score) for symbol, market, score in scores if score > 0]
        total_score = sum(score for _, _, score in positive_scores)
        if total_score <= 0:
            return {(symbol, market): 0.0 for symbol, market, _ in scores}
        return {
            (symbol, market): min(self.max_weight, score / total_score)
            for symbol, market, score in positive_scores
        }


class CrossSectionalMomentumStrategy:
    def __init__(self, parameters: Mapping[str, object]):
        self.top_n = int(parameters.get("top_n", 20))
        self.exit_rank = int(parameters.get("exit_rank", 50))
        self.lookback_long = int(parameters.get("lookback_long", 120))
        self.lookback_short = int(parameters.get("lookback_short", 20))
        self.max_weight = float(parameters.get("max_weight", 0.08))
        self.min_amount = float(parameters.get("min_amount", 0))
        self.max_volatility = float(parameters.get("max_volatility", 1))
        self.max_drawdown = float(parameters.get("max_drawdown", 1))

    def generate(
        self,
        market: Market,
        universe: list[str],
        bars: list[MarketBar] | dict[str, list[MarketBar]],
        current_positions: Mapping[str, float],
    ) -> list[StrategySignal]:
        if isinstance(bars, dict):
            by_symbol = bars
        else:
            by_symbol = _bars_by_symbol(market, universe, bars)
        scored = [self._score_symbol(symbol, by_symbol.get(symbol, [])) for symbol in universe]
        eligible = [item for item in scored if item is not None]
        ranked = self._rank(eligible)
        weight_map = PortfolioConstructor(self.max_weight).assign_weights(
            [
                (item.symbol, item.market, item.score)
                for item in ranked
                if item.rank <= self.top_n and not _has_blocking_risk(item.risk_flags)
            ]
        )

        signals: list[StrategySignal] = []
        for item in ranked:
            has_position = current_positions.get(item.symbol, 0) > 0
            target_weight = weight_map.get((item.symbol, item.market), 0.0)
            if item.rank <= self.top_n and target_weight > 0:
                side = SignalSide.BUY
            elif has_position and item.rank <= self.exit_rank and not _has_blocking_risk(item.risk_flags):
                side = SignalSide.HOLD
            elif has_position:
                side = SignalSide.SELL
            else:
                side = SignalSide.HOLD

            signals.append(
                StrategySignal(
                    symbol=item.symbol,
                    market=item.market,
                    signal=side,
                    score=round(item.score, 6),
                    target_weight=round(target_weight, 6),
                    reason=(
                        f"120日动量 {item.long_return:.2%}; "
                        f"20日动量 {item.short_return:.2%}; "
                        f"rank {item.rank}"
                    ),
                    risk_flags=item.risk_flags,
                    as_of_date=item.latest.session.isoformat(),
                )
            )
        return signals

    def _score_symbol(self, symbol: str, bars: list[MarketBar]) -> _ScoredSymbol | None:
        if not bars:
            return None
        ordered = sorted(bars, key=lambda bar: bar.session)
        latest = ordered[-1]
        risk_flags: list[str] = []
        if len(ordered) <= self.lookback_long:
            risk_flags.append("insufficient_data")
        if latest.suspended:
            risk_flags.append("suspended")
        if latest.amount < self.min_amount:
            risk_flags.append("low_liquidity")

        long_return = _period_return(ordered, self.lookback_long)
        short_return = _period_return(ordered, self.lookback_short)
        returns = _daily_returns(ordered[-self.lookback_long :])
        volatility = pstdev(returns) * sqrt(252) if len(returns) > 1 else 0.0
        drawdown = abs(_max_drawdown([bar.close for bar in ordered[-self.lookback_long :]]))

        if volatility > self.max_volatility:
            risk_flags.append("high_volatility")
        if drawdown > self.max_drawdown:
            risk_flags.append("drawdown_limit")
        if latest.limit_up and latest.market is Market.CN:
            risk_flags.append("limit_up")
        if latest.limit_down and latest.market is Market.CN:
            risk_flags.append("limit_down")

        return _ScoredSymbol(
            symbol=symbol,
            market=latest.market,
            latest=latest,
            long_return=long_return,
            short_return=short_return,
            volatility=volatility,
            max_drawdown=drawdown,
            risk_flags=tuple(dict.fromkeys(risk_flags)),
        )

    def _rank(self, scored: list[_ScoredSymbol]) -> list[_ScoredSymbol]:
        long_rank = _rank_percentiles({item.symbol: item.long_return for item in scored})
        short_rank = _rank_percentiles({item.symbol: item.short_return for item in scored})
        volatility_rank = _rank_percentiles(
            {item.symbol: item.volatility for item in scored}, reverse=False
        )
        drawdown_rank = _rank_percentiles(
            {item.symbol: item.max_drawdown for item in scored}, reverse=False
        )
        with_scores = [
            _ScoredSymbol(
                symbol=item.symbol,
                market=item.market,
                latest=item.latest,
                long_return=item.long_return,
                short_return=item.short_return,
                volatility=item.volatility,
                max_drawdown=item.max_drawdown,
                risk_flags=item.risk_flags,
                score=(
                    0.50 * long_rank[item.symbol]
                    + 0.25 * short_rank[item.symbol]
                    - 0.15 * volatility_rank[item.symbol]
                    - 0.10 * drawdown_rank[item.symbol]
                ),
            )
            for item in scored
        ]
        ordered = sorted(with_scores, key=lambda item: item.score, reverse=True)
        return [
            _ScoredSymbol(
                symbol=item.symbol,
                market=item.market,
                latest=item.latest,
                long_return=item.long_return,
                short_return=item.short_return,
                volatility=item.volatility,
                max_drawdown=item.max_drawdown,
                risk_flags=item.risk_flags,
                score=item.score,
                rank=index + 1,
            )
            for index, item in enumerate(ordered)
        ]


def _bars_by_symbol(
    market: Market, universe: list[str], bars: list[MarketBar]
) -> dict[str, list[MarketBar]]:
    universe_set = set(universe)
    grouped: dict[str, list[MarketBar]] = {symbol: [] for symbol in universe}
    for bar in bars:
        if bar.market is market and bar.symbol in universe_set:
            grouped.setdefault(bar.symbol, []).append(bar)
    return grouped


def _period_return(bars: list[MarketBar], lookback: int) -> float:
    if len(bars) <= lookback:
        return 0.0
    start = bars[-lookback - 1].close
    end = bars[-1].close
    return 0.0 if start == 0 else (end / start) - 1


def _daily_returns(bars: list[MarketBar]) -> list[float]:
    values: list[float] = []
    for previous, current in zip(bars, bars[1:]):
        if previous.close != 0:
            values.append((current.close / previous.close) - 1)
    return values


def _max_drawdown(values: list[float]) -> float:
    peak = values[0] if values else 0
    max_drawdown = 0.0
    for value in values:
        peak = max(peak, value)
        drawdown = 0.0 if peak == 0 else (value - peak) / peak
        max_drawdown = min(max_drawdown, drawdown)
    return max_drawdown


def _rank_percentiles(values: dict[str, float], reverse: bool = True) -> dict[str, float]:
    if not values:
        return {}
    ordered = sorted(values.items(), key=lambda item: item[1], reverse=reverse)
    if len(ordered) == 1:
        return {ordered[0][0]: 1.0}
    denominator = len(ordered) - 1
    return {symbol: 1.0 - (index / denominator) for index, (symbol, _) in enumerate(ordered)}


def _has_blocking_risk(risk_flags: tuple[str, ...]) -> bool:
    return any(
        flag
        in {
            "insufficient_data",
            "suspended",
            "low_liquidity",
            "high_volatility",
            "drawdown_limit",
            "limit_up",
        }
        for flag in risk_flags
    )
