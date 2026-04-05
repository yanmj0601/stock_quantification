from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
import json

from stock_quantification.agents import Orchestrator, ResearchAgent, ReviewAgent, StrategyAgent
from stock_quantification.artifacts import write_json_artifact, write_text_artifact
from stock_quantification.cli import _instrument_name, _strategy_for_market
from stock_quantification.engine import (
    EqualWeightPortfolioConstructor,
    StandardExecutionPlanner,
    StandardRiskEngine,
    StandardStrategyRunner,
)
from stock_quantification.markets import ChinaMarketRules, USMarketRules
from stock_quantification.models import AccountConstraints, AccountState, BacktestContext, ExecutionMode, Market
from stock_quantification.real_data import build_market_snapshot
from stock_quantification.runtime import RuntimeEngine
from stock_quantification.state import InMemoryStateStore

START = date(2026, 3, 1)
END = date(2026, 3, 31)
INITIAL_CASH = Decimal("100000")
DETAIL_LIMIT = 20
HISTORY_LIMIT = 90
TOP_N = 10
ARTIFACT_DIR = "artifacts"


def weekdays(start: date, end: date):
    current = start
    while current <= end:
        if current.weekday() < 5:
            yield current
        current += timedelta(days=1)


def mark_nav(account_state, data_provider, as_of):
    nav = account_state.cash
    positions = []
    for instrument_id, position in sorted(account_state.positions.items()):
        if position.qty == 0:
            continue
        bar = data_provider.get_latest_bar(instrument_id, as_of)
        market_value = bar.close * Decimal(position.qty)
        nav += market_value
        positions.append(
            {
                "instrument_id": instrument_id,
                "qty": position.qty,
                "last_price": str(bar.close.quantize(Decimal("0.0001"))),
                "market_value": str(market_value.quantize(Decimal("0.0001"))),
            }
        )
    return nav, positions


def _actual_sessions(market: Market) -> list:
    sessions = []
    for day in weekdays(START, END):
        snapshot = build_market_snapshot(
            market,
            symbols=[],
            detail_limit=DETAIL_LIMIT,
            history_limit=HISTORY_LIMIT,
            as_of_date=day,
        )
        if snapshot.as_of.date() == day:
            sessions.append(snapshot)
    return sessions


def run_month(market: Market):
    snapshots = _actual_sessions(market)
    if not snapshots:
        raise RuntimeError(f"No sessions found for {market.value}")

    account_id = f"{market.value.lower()}-march-2026-backtest"
    state_store = InMemoryStateStore()
    state_store.save_account_state(
        AccountState(
            account_id=account_id,
            market=market,
            broker_id=f"paper-{market.value.lower()}",
            cash=INITIAL_CASH,
            buying_power=INITIAL_CASH,
            constraints=AccountConstraints(
                max_position_weight=Decimal("0.60"),
                max_single_order_value=INITIAL_CASH,
            ),
        )
    )

    fills_by_execution_date = defaultdict(list)
    approved_by_execution_date = defaultdict(list)
    daily = []

    for index, snapshot in enumerate(snapshots):
        account_state = state_store.get_account_state(account_id)
        nav, positions = mark_nav(account_state, snapshot.data_provider, snapshot.as_of)
        daily.append(
            {
                "trade_date": snapshot.as_of.date().isoformat(),
                "fills": fills_by_execution_date.get(snapshot.as_of.date().isoformat(), []),
                "approved_orders": approved_by_execution_date.get(snapshot.as_of.date().isoformat(), []),
                "end_of_day_nav": str(nav.quantize(Decimal("0.0001"))),
                "cash": str(account_state.cash.quantize(Decimal("0.0001"))),
                "positions": positions,
            }
        )
        if index == len(snapshots) - 1:
            continue

        strategy_runner = StandardStrategyRunner(
            snapshot.data_provider,
            snapshot.universe_provider,
            snapshot.calendar_provider,
        )
        execution_planner = StandardExecutionPlanner(snapshot.data_provider)
        orchestrator = Orchestrator(
            research_agent=ResearchAgent(strategy_runner),
            strategy_agent=StrategyAgent(
                strategy_runner,
                EqualWeightPortfolioConstructor(top_n=TOP_N),
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
        strategy = _strategy_for_market(
            market,
            snapshot.research_data_bundle,
            snapshot.as_of,
            snapshot.benchmark_instrument_id,
            TOP_N,
        )
        result = orchestrator.run(
            BacktestContext(as_of=snapshot.as_of),
            strategy,
            [account_id],
            ExecutionMode.AUTO,
        )
        next_execution_date = snapshots[index + 1].as_of.date().isoformat()
        instrument_lookup = {
            instrument.instrument_id: instrument
            for instrument in snapshot.data_provider.list_instruments(market)
        }
        for execution_result in result.execution_results:
            for fill in execution_result.fills:
                if fill.filled_qty <= 0:
                    continue
                instrument = instrument_lookup.get(fill.instrument_id)
                fills_by_execution_date[next_execution_date].append(
                    {
                        "instrument_id": fill.instrument_id,
                        "name": _instrument_name(instrument) if instrument is not None else fill.instrument_id,
                        "side": "BUY" if fill.cash_delta < 0 else "SELL",
                        "filled_qty": fill.filled_qty,
                        "price": str((fill.realized_price or fill.estimated_price).quantize(Decimal("0.0001"))),
                        "cash_delta": str(fill.cash_delta.quantize(Decimal("0.0001"))),
                        "fees": str(fill.total_fees.quantize(Decimal("0.0001"))),
                    }
                )
        approved_by_execution_date[next_execution_date].extend(
            {
                "instrument_id": intent.instrument_id,
                "side": intent.side.value,
                "qty": intent.qty,
            }
            for intent in result.order_intents
        )

    final_account = state_store.get_account_state(account_id)
    final_snapshot = snapshots[-1]
    final_nav, final_positions = mark_nav(final_account, final_snapshot.data_provider, final_snapshot.as_of)
    total_return = (final_nav / INITIAL_CASH) - Decimal("1")
    buy_count = sum(1 for day in daily for fill in day["fills"] if fill["side"] == "BUY")
    sell_count = sum(1 for day in daily for fill in day["fills"] if fill["side"] == "SELL")
    turnover_days = sum(1 for day in daily if day["fills"])
    summary = {
        "market": market.value,
        "start_date": snapshots[0].as_of.date().isoformat(),
        "end_date": snapshots[-1].as_of.date().isoformat(),
        "runtime_mode": "BACKTEST",
        "universe_scope": "FULL",
        "detail_limit": DETAIL_LIMIT,
        "history_limit": HISTORY_LIMIT,
        "top_n": TOP_N,
        "initial_cash": str(INITIAL_CASH),
        "final_nav": str(final_nav.quantize(Decimal("0.0001"))),
        "total_return": str(total_return.quantize(Decimal("0.0001"))),
        "trading_days": len(snapshots),
        "days_with_fills": turnover_days,
        "buy_fill_count": buy_count,
        "sell_fill_count": sell_count,
        "final_cash": str(final_account.cash.quantize(Decimal("0.0001"))),
        "final_positions": final_positions,
    }

    payload = {"summary": summary, "daily": daily}
    relative = f"2026-03/{market.value.lower()}_march_2026_backtest_rebalance.json"
    json_path = write_json_artifact(ARTIFACT_DIR, relative, payload)
    lines = [
        f"# {market.value} March 2026 Backtest Rebalance",
        "",
        f"- Start: {summary['start_date']}",
        f"- End: {summary['end_date']}",
        f"- Initial cash: {summary['initial_cash']}",
        f"- Final NAV: {summary['final_nav']}",
        f"- Total return: {summary['total_return']}",
        f"- Trading days: {summary['trading_days']}",
        f"- Days with fills: {summary['days_with_fills']}",
        "",
        "## Daily fills",
        "",
    ]
    for day in daily:
        if not day["fills"]:
            continue
        lines.append(f"### {day['trade_date']} NAV={day['end_of_day_nav']}")
        for fill in day["fills"]:
            lines.append(
                f"- {fill['side']} {fill['instrument_id']} {fill['name']} qty={fill['filled_qty']} "
                f"price={fill['price']} fees={fill['fees']}"
            )
        lines.append("")
    md_path = write_text_artifact(ARTIFACT_DIR, relative.replace(".json", ".md"), "\n".join(lines))
    return {"summary": summary, "artifacts": {"json": json_path, "markdown": md_path}, "daily": daily}


def main() -> None:
    output = [run_month(Market.CN), run_month(Market.US)]
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
