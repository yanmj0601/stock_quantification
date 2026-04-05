from __future__ import annotations

import argparse
import json
from datetime import date, timedelta
from decimal import Decimal
from typing import Dict, Iterable, List

from stock_quantification.agents import Orchestrator, ResearchAgent, ReviewAgent, StrategyAgent
from stock_quantification.artifacts import write_json_artifact, write_text_artifact
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
from stock_quantification.strategy_catalog import build_strategy_from_preset, strategy_presets_for_market

ARTIFACT_DIR = "artifacts"
INITIAL_CASH = Decimal("100000")


def _weekdays(start: date, end: date):
    current = start
    while current <= end:
        if current.weekday() < 5:
            yield current
        current += timedelta(days=1)


def _mark_nav(account_state, data_provider, as_of):
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


def _actual_sessions(
    market: Market,
    start_date: date,
    end_date: date,
    detail_limit: int,
    history_limit: int,
) -> list:
    sessions = []
    for day in _weekdays(start_date, end_date):
        snapshot_history_limit = max(
            history_limit,
            min(1000, max(120, (date.today() - day).days + 40)),
        )
        snapshot = build_market_snapshot(
            market,
            symbols=[],
            detail_limit=detail_limit,
            history_limit=snapshot_history_limit,
            as_of_date=day,
        )
        if snapshot.as_of.date() == day:
            sessions.append(snapshot)
    return sessions


def _benchmark_weights(snapshot, market: Market) -> Dict[str, Decimal]:
    available_ids = {
        instrument.instrument_id
        for instrument in snapshot.research_data_bundle.market_data_provider.list_instruments(market)
    }
    return {
        instrument_id: weight
        for instrument_id, weight in snapshot.research_data_bundle.benchmark_weights(market, snapshot.as_of.date()).items()
        if instrument_id in available_ids
    }


def run_strategy_suite(
    market: Market,
    start_date: date,
    end_date: date,
    detail_limit: int,
    history_limit: int,
) -> Dict[str, object]:
    snapshots = _actual_sessions(market, start_date, end_date, detail_limit, history_limit)
    if len(snapshots) < 2:
        raise RuntimeError(f"Not enough sessions found for {market.value}")

    summaries: List[Dict[str, object]] = []
    strategy_presets = strategy_presets_for_market(market)

    for preset in strategy_presets:
        account_id = f"{market.value.lower()}-{preset.preset_id}"
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

        daily = []
        for index, snapshot in enumerate(snapshots):
            account_state = state_store.get_account_state(account_id)
            nav = _mark_nav(account_state, snapshot.data_provider, snapshot.as_of)
            daily.append(
                {
                    "trade_date": snapshot.as_of.date().isoformat(),
                    "end_of_day_nav": str(nav.quantize(Decimal("0.0001"))),
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
                    EqualWeightPortfolioConstructor(top_n=preset.top_n),
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
            strategy = build_strategy_from_preset(
                preset,
                snapshot.benchmark_instrument_id,
                _benchmark_weights(snapshot, market),
            )
            orchestrator.run(
                BacktestContext(as_of=snapshot.as_of),
                strategy,
                [account_id],
                ExecutionMode.AUTO,
            )

        final_nav = Decimal(daily[-1]["end_of_day_nav"])
        total_return = (final_nav / INITIAL_CASH) - Decimal("1")
        max_drawdown = _compute_max_drawdown(Decimal(day["end_of_day_nav"]) for day in daily)
        summaries.append(
            {
                "preset_id": preset.preset_id,
                "display_name": preset.display_name,
                "family": preset.family,
                "description": preset.description,
                "total_return": str(total_return.quantize(Decimal("0.0001"))),
                "max_drawdown": str(max_drawdown.quantize(Decimal("0.0001"))),
                "final_nav": str(final_nav.quantize(Decimal("0.0001"))),
                "trading_days": len(daily),
            }
        )

    summaries.sort(key=lambda item: Decimal(item["total_return"]), reverse=True)
    payload = {
        "market": market.value,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "initial_cash": str(INITIAL_CASH),
        "detail_limit": detail_limit,
        "history_limit": history_limit,
        "strategies": summaries,
    }
    relative = f"{end_date.isoformat()}/{market.value.lower()}_strategy_suite.json"
    json_path = write_json_artifact(ARTIFACT_DIR, relative, payload)
    lines = [
        f"# {market.value} Strategy Suite",
        "",
        f"- period: {start_date.isoformat()} to {end_date.isoformat()}",
        f"- initial_cash: {INITIAL_CASH}",
        "",
        "| 策略 | 家族 | 总收益 | 最大回撤 |",
        "| --- | --- | --- | --- |",
    ]
    for row in summaries:
        lines.append(
            f"| {row['display_name']} | {row['family']} | {row['total_return']} | {row['max_drawdown']} |"
        )
    md_path = write_text_artifact(ARTIFACT_DIR, relative.replace(".json", ".md"), "\n".join(lines) + "\n")
    return {"summary": payload, "artifacts": {"json": json_path, "markdown": md_path}}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a suite of mainstream long-only strategy presets.")
    parser.add_argument("--market", choices=["CN", "US", "ALL"], default="ALL")
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--end-date", required=True)
    parser.add_argument("--detail-limit-cn", type=int, default=8)
    parser.add_argument("--detail-limit-us", type=int, default=6)
    parser.add_argument("--history-limit", type=int, default=60)
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    start_date = date.fromisoformat(args.start_date)
    end_date = date.fromisoformat(args.end_date)
    markets = [Market.CN, Market.US] if args.market == "ALL" else [Market(args.market)]
    outputs = []
    for market in markets:
        detail_limit = args.detail_limit_cn if market == Market.CN else args.detail_limit_us
        outputs.append(
            run_strategy_suite(
                market,
                start_date=start_date,
                end_date=end_date,
                detail_limit=detail_limit,
                history_limit=args.history_limit,
            )
        )
    print(json.dumps(outputs, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
