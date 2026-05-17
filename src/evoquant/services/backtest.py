from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from types import MappingProxyType
from typing import Mapping, Sequence

from evoquant.domain import Market, SignalSide
from evoquant.metrics import calculate_performance
from evoquant.services.market_data import MarketBar
from evoquant.services.market_rules import MarketRulesService
from evoquant.services.strategies import CrossSectionalMomentumStrategy


@dataclass(frozen=True)
class BacktestResult:
    metrics: Mapping[str, float]

    def __post_init__(self) -> None:
        object.__setattr__(self, "metrics", MappingProxyType(dict(self.metrics)))


@dataclass(frozen=True)
class SignalBacktestTrade:
    session: date
    symbol: str
    market: Market
    side: SignalSide
    quantity: int
    price: float
    notional: float
    cost: float


@dataclass(frozen=True)
class SignalBacktestResult:
    metrics: Mapping[str, float]
    equity_curve: tuple[float, ...]
    trades: tuple[SignalBacktestTrade, ...]
    positions: Mapping[str, int]

    def __post_init__(self) -> None:
        object.__setattr__(self, "metrics", MappingProxyType(dict(self.metrics)))
        object.__setattr__(self, "positions", MappingProxyType(dict(self.positions)))


class BacktestRunner:
    def run(self, equity: list[float], turnovers: list[float]) -> BacktestResult:
        metrics = calculate_performance(equity, turnovers)
        result_metrics = {
            "total_return": metrics.total_return,
            "cagr": metrics.cagr,
            "volatility": metrics.volatility,
            "sharpe": metrics.sharpe,
            "sortino": metrics.sortino,
            "max_drawdown": metrics.max_drawdown,
            "calmar": metrics.calmar,
            "turnover": metrics.turnover,
        }
        return BacktestResult(MappingProxyType(result_metrics.copy()))

    def run_signal_backtest(
        self,
        *,
        market: Market,
        universe: list[str],
        bars: list[MarketBar],
        parameters: Mapping[str, object],
        starting_cash: float,
    ) -> SignalBacktestResult:
        strategy = CrossSectionalMomentumStrategy(parameters)
        rules = MarketRulesService.defaults()
        sessions = sorted({bar.session for bar in bars if bar.market is market})
        lookback_long = int(parameters.get("lookback_long", 120))
        cash = float(starting_cash)
        positions: dict[str, int] = {}
        acquired_sessions: dict[str, date] = {}
        trades: list[SignalBacktestTrade] = []
        equity_curve: list[float] = []
        turnover_notional = 0.0

        for session in sessions[lookback_long:]:
            bars_to_date = [bar for bar in bars if bar.market is market and bar.session <= session]
            latest_by_symbol = _latest_bars_for_session(bars_to_date, session)
            if not latest_by_symbol:
                continue

            signals = strategy.generate(market, universe, bars_to_date, positions)
            for signal in signals:
                latest = latest_by_symbol.get(signal.symbol)
                if latest is None or latest.close <= 0:
                    continue
                current_quantity = positions.get(signal.symbol, 0)
                equity = cash + _positions_value(positions, latest_by_symbol)
                target_value = equity * signal.target_weight
                target_quantity = rules.estimate_quantity(
                    market,
                    cash=target_value,
                    price=latest.close,
                    side=SignalSide.BUY,
                )

                if signal.signal is SignalSide.BUY and target_quantity > current_quantity:
                    quantity = target_quantity - current_quantity
                    notional = quantity * latest.close
                    cost = rules.transaction_cost(market, notional=notional, side=SignalSide.BUY)
                    if notional + cost <= cash:
                        cash -= notional + cost
                        positions[signal.symbol] = current_quantity + quantity
                        acquired_sessions.setdefault(signal.symbol, session)
                        turnover_notional += notional
                        trades.append(
                            SignalBacktestTrade(
                                session,
                                signal.symbol,
                                market,
                                SignalSide.BUY,
                                quantity,
                                latest.close,
                                notional,
                                cost,
                            )
                        )
                elif signal.signal is SignalSide.SELL and current_quantity > 0:
                    if not rules.can_sell(
                        market,
                        quantity=current_quantity,
                        acquired_session=acquired_sessions.get(signal.symbol, session),
                        trade_session=session,
                        limit_down=latest.limit_down,
                        suspended=latest.suspended,
                    ):
                        continue
                    notional = current_quantity * latest.close
                    cost = rules.transaction_cost(market, notional=notional, side=SignalSide.SELL)
                    cash += notional - cost
                    turnover_notional += notional
                    trades.append(
                        SignalBacktestTrade(
                            session,
                            signal.symbol,
                            market,
                            SignalSide.SELL,
                            current_quantity,
                            latest.close,
                            notional,
                            cost,
                        )
                    )
                    positions.pop(signal.symbol, None)
                    acquired_sessions.pop(signal.symbol, None)

            equity_curve.append(cash + _positions_value(positions, latest_by_symbol))

        if len(equity_curve) < 2:
            equity_curve = [starting_cash, cash]
        performance = calculate_performance(equity_curve, [])
        metrics = {
            "total_return": performance.total_return,
            "cagr": performance.cagr,
            "volatility": performance.volatility,
            "sharpe": performance.sharpe,
            "sortino": performance.sortino,
            "max_drawdown": performance.max_drawdown,
            "calmar": performance.calmar,
            "turnover": performance.turnover,
        }
        metrics["turnover"] = (
            round(turnover_notional / max(sum(equity_curve) / len(equity_curve), 1), 6)
            if equity_curve
            else 0.0
        )
        metrics["win_rate"] = _win_rate(trades)
        metrics["avg_holding_days"] = _avg_holding_days(trades)
        return SignalBacktestResult(
            metrics=metrics,
            equity_curve=tuple(equity_curve),
            trades=tuple(trades),
            positions=positions,
        )


def _latest_bars_for_session(bars: Sequence[MarketBar], session: date) -> dict[str, MarketBar]:
    by_symbol = {}
    for bar in bars:
        if bar.session <= session:
            existing = by_symbol.get(bar.symbol)
            if existing is None or bar.session > existing.session:
                by_symbol[bar.symbol] = bar
    return by_symbol


def _positions_value(positions: Mapping[str, int], latest_by_symbol: Mapping[str, MarketBar]) -> float:
    return sum(
        quantity * latest_by_symbol[symbol].close
        for symbol, quantity in positions.items()
        if symbol in latest_by_symbol
    )


def _win_rate(trades: Sequence[SignalBacktestTrade]) -> float:
    sells = [trade for trade in trades if trade.side is SignalSide.SELL]
    if not sells:
        return 0.0
    return 0.0


def _avg_holding_days(trades: Sequence[SignalBacktestTrade]) -> float:
    buys: dict[str, date] = {}
    holding_days: list[int] = []
    for trade in trades:
        if trade.side is SignalSide.BUY:
            buys[trade.symbol] = trade.session
        elif trade.side is SignalSide.SELL and trade.symbol in buys:
            holding_days.append((trade.session - buys.pop(trade.symbol)).days)
    return round(sum(holding_days) / len(holding_days), 2) if holding_days else 0.0
