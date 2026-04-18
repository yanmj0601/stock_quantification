from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, timedelta
from decimal import Decimal
from statistics import median
from typing import Dict, Iterable, List, Mapping, Optional, Sequence

from .agents import Orchestrator, ResearchAgent, ReviewAgent, StrategyAgent
from .engine import (
    EqualWeightPortfolioConstructor,
    StandardExecutionPlanner,
    StandardRiskEngine,
    StandardStrategyRunner,
)
from .markets import ChinaMarketRules, USMarketRules
from .models import AccountConstraints, AccountState, BacktestContext, ExecutionMode, Market
from .real_data import (
    MarketSnapshot,
    build_market_snapshot,
    fetch_cn_benchmark_history,
    fetch_cn_detailed_history,
    fetch_us_benchmark_history,
    fetch_us_daily_history,
)
from .runtime import RuntimeEngine
from .state import InMemoryStateStore
from .strategy_catalog import StrategyPreset, build_strategy_from_preset
from .analytics import InformationCoefficientMetrics, compute_information_coefficient, compute_performance_metrics


@dataclass(frozen=True)
class ForwardReturnRow:
    instrument_id: str
    name: str
    sector: str
    entry_date: str
    exit_date: str
    entry_price: Decimal
    exit_price: Decimal
    holding_sessions: int
    forward_return: Decimal
    benchmark_return: Decimal
    excess_return: Decimal
    target_weight: Decimal
    qty: int
    buy_price: Decimal | None
    score: Decimal
    reason: str


@dataclass(frozen=True)
class BacktestSummary:
    selection_date: str
    exit_date: str
    holding_sessions: int
    selected_count: int
    positive_count: int
    negative_count: int
    win_rate: Decimal
    equal_weight_return: Decimal
    benchmark_return: Decimal
    excess_return: Decimal
    average_return: Decimal
    median_return: Decimal
    average_excess_return: Decimal
    best_instrument_id: str
    best_name: str
    best_return: Decimal
    worst_instrument_id: str
    worst_name: str
    worst_return: Decimal
    ic: Decimal
    rank_ic: Decimal
    ic_sample_size: int


@dataclass(frozen=True)
class BacktestReport:
    summary: BacktestSummary
    rows: List[ForwardReturnRow]


@dataclass(frozen=True)
class RollingBacktestDay:
    trade_date: str
    end_of_day_nav: Decimal
    cash: Decimal
    benchmark_nav: Optional[Decimal]
    period_return: Decimal
    benchmark_period_return: Optional[Decimal]
    excess_period_return: Optional[Decimal]
    portfolio_return: Decimal
    benchmark_return: Optional[Decimal]
    excess_return: Optional[Decimal]
    cumulative_portfolio_return: Decimal
    cumulative_benchmark_return: Optional[Decimal]
    cumulative_excess_return: Optional[Decimal]
    buy_fill_count: int
    sell_fill_count: int
    gross_traded_notional: Decimal
    total_fees: Decimal
    turnover: Decimal


@dataclass(frozen=True)
class RollingBacktestSummary:
    market: str
    preset_id: str
    display_name: str
    start_date: str
    end_date: str
    trading_days: int
    initial_cash: Decimal
    final_nav: Decimal
    total_return: Decimal
    max_drawdown: Decimal
    best_nav: Decimal
    worst_nav: Decimal
    days_with_fills: int
    buy_fill_count: int
    sell_fill_count: int
    benchmark_available: bool
    benchmark_final_nav: Optional[Decimal]
    benchmark_total_return: Optional[Decimal]
    benchmark_max_drawdown: Optional[Decimal]
    excess_return: Optional[Decimal]
    annualized_return: Decimal
    annualized_volatility: Decimal
    sharpe_ratio: Decimal
    average_turnover: Decimal
    total_traded_notional: Decimal
    total_fees: Decimal
    fee_drag: Decimal
    pre_fee_return: Decimal


@dataclass(frozen=True)
class RollingBacktestReport:
    summary: RollingBacktestSummary
    daily: List[RollingBacktestDay]


def _to_decimal(value: object) -> Decimal:
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _serialize_row(row: ForwardReturnRow) -> Dict[str, object]:
    payload = asdict(row)
    for key, value in payload.items():
        if isinstance(value, Decimal):
            payload[key] = str(value.quantize(Decimal("0.0001")))
    if row.buy_price is None:
        payload["buy_price"] = None
    return payload


def _serialize_summary(summary: BacktestSummary) -> Dict[str, object]:
    payload = asdict(summary)
    for key, value in payload.items():
        if isinstance(value, Decimal):
            payload[key] = str(value.quantize(Decimal("0.0001")))
    return payload


def serialize_backtest_report(report: BacktestReport) -> Dict[str, object]:
    return {
        "summary": _serialize_summary(report.summary),
        "rows": [_serialize_row(row) for row in report.rows],
    }


def serialize_rolling_backtest_report(report: RollingBacktestReport) -> Dict[str, object]:
    summary = _serialize_summary(report.summary)
    daily: List[Dict[str, object]] = []
    for item in report.daily:
        payload = asdict(item)
        for key, value in payload.items():
            if isinstance(value, Decimal):
                payload[key] = str(value.quantize(Decimal("0.0001")))
        daily.append(payload)
    return {"summary": summary, "daily": daily}


def build_forward_return_report(
    market: Market,
    trade_date: date,
    recommended_stocks: Sequence[Mapping[str, object]],
    ranked_candidates: Sequence[Mapping[str, object]],
    holding_sessions: int = 5,
) -> BacktestReport:
    if holding_sessions <= 0:
        raise ValueError("holding_sessions must be positive")

    benchmark_entry_price, benchmark_exit_price, exit_date = _benchmark_window(market, trade_date, holding_sessions)
    benchmark_return = _simple_return(benchmark_entry_price, benchmark_exit_price)

    rows: List[ForwardReturnRow] = []
    for stock in recommended_stocks:
        entry_date, resolved_exit_date, entry_price, exit_price = _instrument_window(
            market,
            str(stock["instrument_id"]),
            trade_date,
            holding_sessions,
        )
        buy_price = _optional_decimal(stock.get("buy_price"))
        effective_entry = buy_price or entry_price
        forward_return = _simple_return(effective_entry, exit_price)
        rows.append(
            ForwardReturnRow(
                instrument_id=str(stock["instrument_id"]),
                name=str(stock.get("name", stock["instrument_id"])),
                sector=str(stock.get("sector", "UNKNOWN")),
                entry_date=entry_date.isoformat(),
                exit_date=resolved_exit_date.isoformat(),
                entry_price=entry_price,
                exit_price=exit_price,
                holding_sessions=holding_sessions,
                forward_return=forward_return,
                benchmark_return=benchmark_return,
                excess_return=forward_return - benchmark_return,
                target_weight=_to_decimal(stock.get("target_weight", "0")),
                qty=int(stock.get("qty", 0)),
                buy_price=buy_price,
                score=_to_decimal(stock.get("score", "0")),
                reason=str(stock.get("reason", "")),
            )
        )

    rows.sort(key=lambda item: item.forward_return, reverse=True)

    factor_values = {
        str(row["instrument_id"]): _to_decimal(row.get("score", "0"))
        for row in ranked_candidates
    }
    future_returns = {
        row.instrument_id: row.forward_return
        for row in rows
    }
    ic_metrics: InformationCoefficientMetrics = compute_information_coefficient(factor_values, future_returns)
    summary = _build_summary(trade_date, exit_date, holding_sessions, rows, benchmark_return, ic_metrics)
    return BacktestReport(summary=summary, rows=rows)


def build_rolling_strategy_backtest_report(
    market: Market,
    preset: StrategyPreset,
    start_date: date,
    end_date: date,
    detail_limit: int,
    history_limit: int,
    initial_cash: Decimal = Decimal("100000"),
    build_snapshot_fn=build_market_snapshot,
) -> RollingBacktestReport:
    snapshots = _actual_sessions(
        market=market,
        start_date=start_date,
        end_date=end_date,
        detail_limit=detail_limit,
        history_limit=history_limit,
        build_snapshot_fn=build_snapshot_fn,
    )
    if len(snapshots) < 2:
        raise RuntimeError(f"Not enough sessions found for {market.value}")

    account_id = f"{market.value.lower()}-{preset.preset_id}-rolling"
    state_store = InMemoryStateStore()
    state_store.save_account_state(
        AccountState(
            account_id=account_id,
            market=market,
            broker_id=f"paper-{market.value.lower()}",
            cash=initial_cash,
            buying_power=initial_cash,
            constraints=AccountConstraints(
                max_position_weight=Decimal("0.60"),
                max_single_order_value=initial_cash,
            ),
        )
    )

    fills_by_execution_date: Dict[str, Dict[str, Decimal | int]] = {}
    benchmark_base_price: Optional[Decimal] = None
    daily: List[RollingBacktestDay] = []
    buy_fill_count = 0
    sell_fill_count = 0
    benchmark_nav_values: List[Decimal] = []
    benchmark_available = True
    previous_nav = initial_cash
    previous_benchmark_nav: Optional[Decimal] = None
    total_traded_notional = Decimal("0")
    total_fees = Decimal("0")
    period_returns: List[Decimal] = []
    turnovers: List[Decimal] = []

    for index, snapshot in enumerate(snapshots):
        account_state = state_store.get_account_state(account_id)
        nav = _mark_nav(account_state, snapshot.data_provider, snapshot.as_of)
        benchmark_nav: Optional[Decimal] = None
        benchmark_return: Optional[Decimal] = None
        excess_return: Optional[Decimal] = None
        if snapshot.benchmark_instrument_id:
            try:
                benchmark_bar = snapshot.data_provider.get_latest_bar(snapshot.benchmark_instrument_id, snapshot.as_of)
                if benchmark_base_price is None:
                    benchmark_base_price = benchmark_bar.close
                if benchmark_base_price and benchmark_base_price > 0:
                    benchmark_nav = (initial_cash * benchmark_bar.close / benchmark_base_price).quantize(Decimal("0.0001"))
                    benchmark_return = (benchmark_nav / initial_cash) - Decimal("1")
                    excess_return = ((nav / initial_cash) - Decimal("1")) - benchmark_return
                    benchmark_nav_values.append(benchmark_nav)
            except Exception:
                benchmark_available = False
        else:
            benchmark_available = False

        fill_stats = fills_by_execution_date.get(
            snapshot.as_of.date().isoformat(),
            {
                "buy_fill_count": 0,
                "sell_fill_count": 0,
                "gross_traded_notional": Decimal("0"),
                "total_fees": Decimal("0"),
            },
        )
        day_buy_fill_count = int(fill_stats["buy_fill_count"])
        day_sell_fill_count = int(fill_stats["sell_fill_count"])
        day_gross_traded_notional = _to_decimal(fill_stats["gross_traded_notional"])
        day_total_fees = _to_decimal(fill_stats["total_fees"])
        buy_fill_count += day_buy_fill_count
        sell_fill_count += day_sell_fill_count
        total_traded_notional += day_gross_traded_notional
        total_fees += day_total_fees
        period_return = Decimal("0") if previous_nav == 0 else (nav / previous_nav) - Decimal("1")
        benchmark_period_return: Optional[Decimal] = None
        if benchmark_nav is not None and previous_benchmark_nav not in (None, Decimal("0")):
            benchmark_period_return = (benchmark_nav / previous_benchmark_nav) - Decimal("1")
        excess_period_return = (
            period_return - benchmark_period_return
            if benchmark_period_return is not None
            else None
        )
        turnover = Decimal("0") if nav == 0 else (day_gross_traded_notional / nav)
        period_returns.append(period_return)
        turnovers.append(turnover)
        daily.append(
            RollingBacktestDay(
                trade_date=snapshot.as_of.date().isoformat(),
                end_of_day_nav=nav,
                cash=account_state.cash,
                benchmark_nav=benchmark_nav,
                period_return=period_return,
                benchmark_period_return=benchmark_period_return,
                excess_period_return=excess_period_return,
                portfolio_return=(nav / initial_cash) - Decimal("1"),
                benchmark_return=benchmark_return,
                excess_return=excess_return,
                cumulative_portfolio_return=(nav / initial_cash) - Decimal("1"),
                cumulative_benchmark_return=benchmark_return,
                cumulative_excess_return=excess_return,
                buy_fill_count=day_buy_fill_count,
                sell_fill_count=day_sell_fill_count,
                gross_traded_notional=day_gross_traded_notional,
                total_fees=day_total_fees,
                turnover=turnover,
            )
        )
        previous_nav = nav
        previous_benchmark_nav = benchmark_nav if benchmark_nav is not None else previous_benchmark_nav
        if index == len(snapshots) - 1:
            continue

        orchestrator = _build_orchestrator(snapshot, state_store, preset.top_n)
        strategy = build_strategy_from_preset(
            preset,
            snapshot.benchmark_instrument_id,
            _benchmark_weights(snapshot, market),
        )
        result = orchestrator.run(
            BacktestContext(as_of=snapshot.as_of),
            strategy,
            [account_id],
            ExecutionMode.AUTO,
        )
        next_execution_date = snapshots[index + 1].as_of.date().isoformat()
        next_day_stats = {
            "buy_fill_count": 0,
            "sell_fill_count": 0,
            "gross_traded_notional": Decimal("0"),
            "total_fees": Decimal("0"),
        }
        for execution_result in result.execution_results:
            for fill in execution_result.fills:
                if fill.filled_qty <= 0:
                    continue
                if fill.cash_delta < 0:
                    next_day_stats["buy_fill_count"] = int(next_day_stats["buy_fill_count"]) + 1
                else:
                    next_day_stats["sell_fill_count"] = int(next_day_stats["sell_fill_count"]) + 1
                reference_price = fill.realized_price or fill.estimated_price
                next_day_stats["gross_traded_notional"] = _to_decimal(next_day_stats["gross_traded_notional"]) + (
                    reference_price * Decimal(fill.filled_qty)
                )
                next_day_stats["total_fees"] = _to_decimal(next_day_stats["total_fees"]) + fill.total_fees
        fills_by_execution_date[next_execution_date] = next_day_stats

    nav_values = [day.end_of_day_nav for day in daily]
    final_nav = daily[-1].end_of_day_nav
    benchmark_final_nav = benchmark_nav_values[-1] if benchmark_available and benchmark_nav_values else None
    benchmark_total_return = (
        ((benchmark_final_nav / initial_cash) - Decimal("1"))
        if benchmark_final_nav is not None
        else None
    )
    performance = compute_performance_metrics(period_returns, turnovers)
    summary = RollingBacktestSummary(
        market=market.value,
        preset_id=preset.preset_id,
        display_name=preset.display_name,
        start_date=daily[0].trade_date,
        end_date=daily[-1].trade_date,
        trading_days=len(daily),
        initial_cash=initial_cash,
        final_nav=final_nav,
        total_return=(final_nav / initial_cash) - Decimal("1"),
        max_drawdown=_compute_max_drawdown(nav_values),
        best_nav=max(nav_values),
        worst_nav=min(nav_values),
        days_with_fills=sum(1 for day in daily if day.buy_fill_count or day.sell_fill_count),
        buy_fill_count=buy_fill_count,
        sell_fill_count=sell_fill_count,
        benchmark_available=benchmark_available and benchmark_final_nav is not None,
        benchmark_final_nav=benchmark_final_nav,
        benchmark_total_return=benchmark_total_return,
        benchmark_max_drawdown=(
            _compute_max_drawdown(benchmark_nav_values)
            if benchmark_available and benchmark_nav_values
            else None
        ),
        excess_return=(
            ((final_nav / initial_cash) - Decimal("1")) - benchmark_total_return
            if benchmark_total_return is not None
            else None
        ),
        annualized_return=performance.annualized_return,
        annualized_volatility=performance.annualized_volatility,
        sharpe_ratio=performance.sharpe_ratio,
        average_turnover=performance.turnover_average,
        total_traded_notional=total_traded_notional,
        total_fees=total_fees,
        fee_drag=(total_fees / initial_cash) if initial_cash != 0 else Decimal("0"),
        pre_fee_return=((final_nav + total_fees) / initial_cash) - Decimal("1"),
    )
    return RollingBacktestReport(summary=summary, daily=daily)


def _build_summary(
    trade_date: date,
    exit_date: date,
    holding_sessions: int,
    rows: Sequence[ForwardReturnRow],
    benchmark_return: Decimal,
    ic_metrics: InformationCoefficientMetrics,
) -> BacktestSummary:
    if not rows:
        return BacktestSummary(
            selection_date=trade_date.isoformat(),
            exit_date=exit_date.isoformat(),
            holding_sessions=holding_sessions,
            selected_count=0,
            positive_count=0,
            negative_count=0,
            win_rate=Decimal("0"),
            equal_weight_return=Decimal("0"),
            benchmark_return=benchmark_return,
            excess_return=Decimal("0") - benchmark_return,
            average_return=Decimal("0"),
            median_return=Decimal("0"),
            average_excess_return=Decimal("0"),
            best_instrument_id="",
            best_name="",
            best_return=Decimal("0"),
            worst_instrument_id="",
            worst_name="",
            worst_return=Decimal("0"),
            ic=ic_metrics.ic,
            rank_ic=ic_metrics.rank_ic,
            ic_sample_size=ic_metrics.sample_size,
        )

    returns = [row.forward_return for row in rows]
    excess_returns = [row.excess_return for row in rows]
    equal_weight_return = sum(returns, Decimal("0")) / Decimal(len(returns))
    best = max(rows, key=lambda item: item.forward_return)
    worst = min(rows, key=lambda item: item.forward_return)
    positive_count = sum(1 for row in rows if row.forward_return > 0)
    negative_count = sum(1 for row in rows if row.forward_return < 0)
    return BacktestSummary(
        selection_date=trade_date.isoformat(),
        exit_date=exit_date.isoformat(),
        holding_sessions=holding_sessions,
        selected_count=len(rows),
        positive_count=positive_count,
        negative_count=negative_count,
        win_rate=Decimal(positive_count) / Decimal(len(rows)),
        equal_weight_return=equal_weight_return,
        benchmark_return=benchmark_return,
        excess_return=equal_weight_return - benchmark_return,
        average_return=equal_weight_return,
        median_return=Decimal(str(median([float(item) for item in returns]))),
        average_excess_return=sum(excess_returns, Decimal("0")) / Decimal(len(excess_returns)),
        best_instrument_id=best.instrument_id,
        best_name=best.name,
        best_return=best.forward_return,
        worst_instrument_id=worst.instrument_id,
        worst_name=worst.name,
        worst_return=worst.forward_return,
        ic=ic_metrics.ic,
        rank_ic=ic_metrics.rank_ic,
        ic_sample_size=ic_metrics.sample_size,
    )


def _weekdays(start: date, end: date):
    current = start
    while current <= end:
        if current.weekday() < 5:
            yield current
        current += timedelta(days=1)


def _actual_sessions(
    market: Market,
    start_date: date,
    end_date: date,
    detail_limit: int,
    history_limit: int,
    build_snapshot_fn=build_market_snapshot,
) -> List[MarketSnapshot]:
    sessions: List[MarketSnapshot] = []
    for day in _weekdays(start_date, end_date):
        snapshot_history_limit = max(
            history_limit,
            min(1000, max(120, (date.today() - day).days + 40)),
        )
        snapshot = build_snapshot_fn(
            market,
            symbols=[],
            detail_limit=detail_limit,
            history_limit=snapshot_history_limit,
            as_of_date=day,
        )
        if snapshot.as_of.date() == day:
            sessions.append(snapshot)
    return sessions


def _benchmark_weights(snapshot: MarketSnapshot, market: Market) -> Dict[str, Decimal]:
    available_ids = {
        instrument.instrument_id
        for instrument in snapshot.research_data_bundle.market_data_provider.list_instruments(market)
    }
    return {
        instrument_id: weight
        for instrument_id, weight in snapshot.research_data_bundle.benchmark_weights(market, snapshot.as_of.date()).items()
        if instrument_id in available_ids
    }


def _build_orchestrator(snapshot: MarketSnapshot, state_store: InMemoryStateStore, top_n: int) -> Orchestrator:
    strategy_runner = StandardStrategyRunner(
        snapshot.data_provider,
        snapshot.universe_provider,
        snapshot.calendar_provider,
    )
    execution_planner = StandardExecutionPlanner(snapshot.data_provider)
    return Orchestrator(
        research_agent=ResearchAgent(strategy_runner),
        strategy_agent=StrategyAgent(
            strategy_runner,
            EqualWeightPortfolioConstructor(top_n=top_n),
            execution_planner,
            state_store,
        ),
        review_agent=ReviewAgent(),
        execution_planner=execution_planner,
        risk_engine=StandardRiskEngine(
            snapshot.data_provider,
            {Market.CN: ChinaMarketRules(), Market.US: USMarketRules()},
        ),
        state_store=state_store,
        runtime_engine=RuntimeEngine(snapshot.data_provider, snapshot.calendar_provider),
    )


def _mark_nav(account_state: AccountState, data_provider, as_of) -> Decimal:
    nav = account_state.cash
    for instrument_id, position in account_state.positions.items():
        if position.qty == 0:
            continue
        bar = data_provider.get_latest_bar(instrument_id, as_of)
        nav += bar.close * Decimal(position.qty)
    return nav


def _compute_max_drawdown(nav_values: Iterable[Decimal]) -> Decimal:
    peak = Decimal("0")
    max_drawdown = Decimal("0")
    for nav in nav_values:
        if nav > peak:
            peak = nav
        if peak > 0:
            drawdown = (nav / peak) - Decimal("1")
            if drawdown < max_drawdown:
                max_drawdown = drawdown
    return max_drawdown


def _benchmark_window(market: Market, trade_date: date, holding_sessions: int) -> tuple[Decimal, Decimal, date]:
    if market == Market.CN:
        _, bars = fetch_cn_benchmark_history(limit=180)
    else:
        _, bars = fetch_us_benchmark_history(limit=180)
    entry_date, exit_date, entry_price, exit_price = _price_window(bars, trade_date, holding_sessions)
    del entry_date
    return entry_price, exit_price, exit_date


def _instrument_window(
    market: Market,
    instrument_id: str,
    trade_date: date,
    holding_sessions: int,
) -> tuple[date, date, Decimal, Decimal]:
    symbol = instrument_id.split(".", 1)[1]
    if market == Market.CN:
        _, bars = fetch_cn_detailed_history(symbol, limit=180)
    else:
        _, bars = fetch_us_daily_history(symbol, lookback_days=365, limit=180)
    return _price_window(bars, trade_date, holding_sessions)


def _price_window(bars: Sequence[object], trade_date: date, holding_sessions: int) -> tuple[date, date, Decimal, Decimal]:
    eligible = [bar for bar in bars if bar.timestamp.date() <= trade_date]
    if not eligible:
        raise ValueError("No eligible bars on or before %s" % trade_date.isoformat())
    entry_bar = eligible[-1]
    full = list(bars)
    try:
        entry_index = full.index(entry_bar)
    except ValueError as exc:  # pragma: no cover - defensive
        raise ValueError("Unable to locate entry bar") from exc
    exit_index = min(entry_index + holding_sessions, len(full) - 1)
    exit_bar = full[exit_index]
    return entry_bar.timestamp.date(), exit_bar.timestamp.date(), entry_bar.close, exit_bar.close


def _simple_return(entry_price: Decimal, exit_price: Decimal) -> Decimal:
    if entry_price == 0:
        return Decimal("0")
    return (exit_price / entry_price) - Decimal("1")


def _optional_decimal(value: object) -> Decimal | None:
    if value in (None, "", "n/a"):
        return None
    return _to_decimal(value)
