from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from decimal import Decimal, ROUND_DOWN
from typing import Dict, Iterable, List, Optional, Sequence

from .interfaces import (
    CalendarProvider,
    ExecutionPlanner,
    MarketDataProvider,
    MarketRules,
    PortfolioConstructor,
    RiskEngine,
    StrategyDefinition,
    StrategyRunner,
    UniverseProvider,
)
from .models import (
    AccountState,
    AssetType,
    FactorSnapshot,
    Instrument,
    Market,
    OrderIntent,
    OrderSide,
    OrderType,
    Position,
    RiskCheckResult,
    RuntimeContext,
    SignalSnapshot,
    TargetPosition,
    TradeSuggestion,
)
from .pipeline import (
    PortfolioPolicy,
    ResearchPipeline,
    ResearchPipelineResult,
    StrategyBlueprint,
    build_cn_index_enhancement_blueprint,
    build_us_quality_momentum_blueprint,
)


def _decimal(value: str) -> Decimal:
    return Decimal(value)


def _safe_ratio(current: Decimal, previous: Decimal) -> Decimal:
    if previous == 0:
        return Decimal("0")
    return (current / previous) - Decimal("1")


class InMemoryMarketDataProvider(MarketDataProvider):
    def __init__(self, instruments: Iterable[Instrument], bars_by_instrument: Dict[str, List]) -> None:
        self._instruments = {instrument.instrument_id: instrument for instrument in instruments}
        self._bars_by_instrument = {
            instrument_id: sorted(bars, key=lambda bar: bar.timestamp)
            for instrument_id, bars in bars_by_instrument.items()
        }

    def get_instrument(self, instrument_id: str) -> Instrument:
        return self._instruments[instrument_id]

    def list_instruments(self, market: Market) -> List[Instrument]:
        return [instrument for instrument in self._instruments.values() if instrument.market == market]

    def get_latest_bar(self, instrument_id: str, as_of: datetime):
        eligible = [bar for bar in self._bars_by_instrument[instrument_id] if bar.timestamp <= as_of]
        if not eligible:
            raise KeyError("No bar found for instrument_id=%s as_of=%s" % (instrument_id, as_of.isoformat()))
        return eligible[-1]

    def get_price_history(self, instrument_id: str, as_of: datetime, limit: int) -> List:
        eligible = [bar for bar in self._bars_by_instrument[instrument_id] if bar.timestamp <= as_of]
        if len(eligible) < limit:
            return eligible
        return eligible[-limit:]

    def get_next_bar(self, instrument_id: str, after: datetime):
        eligible = [bar for bar in self._bars_by_instrument[instrument_id] if bar.timestamp > after]
        if not eligible:
            return None
        return eligible[0]


class InMemoryCalendarProvider(CalendarProvider):
    def __init__(self, sessions_by_market: Dict[Market, List[datetime]]) -> None:
        self._sessions_by_market = {market: sorted(sessions) for market, sessions in sessions_by_market.items()}

    def is_session(self, market: Market, as_of: datetime) -> bool:
        return as_of in self._sessions_by_market.get(market, [])

    def next_session(self, market: Market, as_of: datetime) -> datetime:
        for session in self._sessions_by_market.get(market, []):
            if session > as_of:
                return session
        raise KeyError("No future session found for %s" % market.value)


class InMemoryUniverseProvider(UniverseProvider):
    def __init__(self, data_provider: MarketDataProvider) -> None:
        self._data_provider = data_provider

    def get_universe(self, market: Market, as_of: datetime) -> List[str]:
        del as_of
        return [instrument.instrument_id for instrument in self._data_provider.list_instruments(market)]


class BaseSelectionStrategy(StrategyDefinition):
    strategy_id = ""
    market = Market.CN

    def __init__(
        self,
        top_n: int = 2,
        benchmark_instrument_id: Optional[str] = None,
        benchmark_weights: Optional[Dict[str, Decimal]] = None,
        alpha_weights_override: Optional[Dict[str, Decimal]] = None,
        portfolio_policy_override: Optional[Dict[str, Decimal]] = None,
    ) -> None:
        self.top_n = top_n
        self.benchmark_instrument_id = benchmark_instrument_id
        self.benchmark_weights = benchmark_weights or {}
        self.alpha_weights_override = alpha_weights_override or {}
        self.portfolio_policy_override = portfolio_policy_override or {}

    def _build_signal(
        self,
        as_of: datetime,
        instrument_id: str,
        score: Decimal,
        reason: str,
    ) -> SignalSnapshot:
        return SignalSnapshot(
            as_of=as_of,
            strategy_id=self.strategy_id,
            instrument_id=instrument_id,
            score=score.quantize(Decimal("0.0001")),
            direction="LONG",
            reason=reason,
        )

    def _pipeline_blueprint(self, allowed_instrument_ids: Sequence[str]) -> StrategyBlueprint:
        raise NotImplementedError

    def _apply_blueprint_overrides(self, blueprint: StrategyBlueprint) -> StrategyBlueprint:
        updated_blueprint = blueprint
        if self.alpha_weights_override:
            updated_blueprint = replace(
                updated_blueprint,
                alpha_weights={
                    **updated_blueprint.alpha_weights,
                    **self.alpha_weights_override,
                },
            )
        if self.portfolio_policy_override:
            updated_blueprint = replace(
                updated_blueprint,
                portfolio_policy=replace(
                    updated_blueprint.portfolio_policy,
                    **self.portfolio_policy_override,
                ),
            )
        return updated_blueprint

    def _run_pipeline(
        self,
        data_provider: MarketDataProvider,
        universe: Sequence[str],
        as_of: datetime,
        current_weights: Optional[Dict[str, Decimal]] = None,
    ) -> Dict[str, List]:
        blueprint = self._pipeline_blueprint(universe)
        pipeline_result = ResearchPipeline(data_provider).run(blueprint, as_of, current_weights=current_weights)
        alpha_by_instrument = {alpha.instrument_id: alpha for alpha in pipeline_result.alpha_scores}
        selected_targets = [
            target
            for target in pipeline_result.portfolio.targets
            if data_provider.get_instrument(target.instrument_id).asset_type == AssetType.COMMON_STOCK
        ]
        signal_target_ids = [target.instrument_id for target in selected_targets[: self.top_n]]
        selected_ids = {target.instrument_id for target in selected_targets}
        signals = [
            self._build_signal(
                as_of,
                instrument_id,
                alpha_by_instrument[instrument_id].score,
                self._build_reason(alpha_by_instrument[instrument_id].contributions),
            )
            for instrument_id in signal_target_ids
            if instrument_id in alpha_by_instrument
        ]
        factors = self._build_factor_snapshots(as_of, pipeline_result, selected_ids)
        diagnostics = {
            "gross_exposure": str(pipeline_result.portfolio.diagnostics.gross_exposure),
            "cash_buffer": str(pipeline_result.portfolio.diagnostics.cash_buffer),
            "turnover": str(pipeline_result.portfolio.diagnostics.turnover),
            "selected_count": pipeline_result.portfolio.diagnostics.selected_count,
            "sector_exposure": {sector: str(weight) for sector, weight in pipeline_result.portfolio.diagnostics.sector_exposure.items()},
        }
        return {
            "signals": signals,
            "factors": factors,
            "targets": selected_targets,
            "portfolio_diagnostics": diagnostics,
            "rankings": self._build_rankings(pipeline_result),
        }

    def _build_factor_snapshots(
        self,
        as_of: datetime,
        pipeline_result: ResearchPipelineResult,
        selected_ids: Sequence[str],
    ) -> List[FactorSnapshot]:
        factors: List[FactorSnapshot] = []
        selected_lookup = set(selected_ids)
        for row in pipeline_result.features:
            if row.instrument_id not in selected_lookup:
                continue
            for factor_name, factor_value in row.raw.items():
                factors.append(
                    FactorSnapshot(
                        as_of=as_of,
                        instrument_id=row.instrument_id,
                        factor_name=factor_name,
                        factor_value=factor_value.quantize(Decimal("0.0001")),
                    )
                )
        return factors

    def _build_reason(self, contributions: Dict[str, Decimal]) -> str:
        ranked = sorted(contributions.items(), key=lambda item: abs(item[1]), reverse=True)
        top_terms = [f"{name}:{value.quantize(Decimal('0.0001'))}" for name, value in ranked[:3]]
        return "alpha(" + ", ".join(top_terms) + ")"

    def _build_rankings(self, pipeline_result: ResearchPipelineResult) -> List[Dict[str, object]]:
        feature_map = {row.instrument_id: row for row in pipeline_result.features}
        weights = pipeline_result.portfolio.weights
        rankings: List[Dict[str, object]] = []
        for alpha_score in pipeline_result.alpha_scores:
            row = feature_map.get(alpha_score.instrument_id)
            rankings.append(
                {
                    "instrument_id": alpha_score.instrument_id,
                    "score": alpha_score.score,
                    "sector": row.sector if row else "UNKNOWN",
                    "selected": alpha_score.instrument_id in weights,
                    "target_weight": weights.get(alpha_score.instrument_id, Decimal("0")),
                    "contributions": alpha_score.contributions,
                    "raw_features": row.raw if row else {},
                }
            )
        return rankings


class AStockSelectionStrategy(BaseSelectionStrategy):
    strategy_id = "cn_index_enhancement"
    market = Market.CN

    def generate(
        self,
        data_provider: MarketDataProvider,
        universe: Sequence[str],
        as_of: datetime,
        current_weights: Optional[Dict[str, Decimal]] = None,
    ) -> Dict[str, List]:
        return self._run_pipeline(data_provider, universe, as_of, current_weights=current_weights)

    def _pipeline_blueprint(self, allowed_instrument_ids: Sequence[str]) -> StrategyBlueprint:
        allowed_ids = tuple(allowed_instrument_ids)
        benchmark_weights = self.benchmark_weights
        blueprint = build_cn_index_enhancement_blueprint(
            benchmark_instrument_id=self.benchmark_instrument_id,
            allowed_instrument_ids=allowed_ids,
            benchmark_weights=benchmark_weights,
        )
        adjusted = replace(
            blueprint,
            portfolio_policy=replace(
                blueprint.portfolio_policy,
                top_n=self.top_n,
                benchmark_blend=blueprint.portfolio_policy.benchmark_blend if benchmark_weights else Decimal("0"),
            ),
        )
        return self._apply_blueprint_overrides(adjusted)


class USStockSelectionStrategy(BaseSelectionStrategy):
    strategy_id = "us_quality_momentum"
    market = Market.US

    def generate(
        self,
        data_provider: MarketDataProvider,
        universe: Sequence[str],
        as_of: datetime,
        current_weights: Optional[Dict[str, Decimal]] = None,
    ) -> Dict[str, List]:
        return self._run_pipeline(data_provider, universe, as_of, current_weights=current_weights)

    def _pipeline_blueprint(self, allowed_instrument_ids: Sequence[str]) -> StrategyBlueprint:
        allowed_ids = tuple(allowed_instrument_ids)
        benchmark_weights = self.benchmark_weights
        blueprint = build_us_quality_momentum_blueprint(
            benchmark_instrument_id=self.benchmark_instrument_id,
            allowed_instrument_ids=allowed_ids,
            benchmark_weights=benchmark_weights,
        )
        adjusted = replace(
            blueprint,
            portfolio_policy=replace(
                blueprint.portfolio_policy,
                top_n=self.top_n,
                benchmark_blend=blueprint.portfolio_policy.benchmark_blend if benchmark_weights else Decimal("0"),
            ),
        )
        return self._apply_blueprint_overrides(adjusted)


class StandardStrategyRunner(StrategyRunner):
    def __init__(
        self,
        data_provider: MarketDataProvider,
        universe_provider: UniverseProvider,
        calendar_provider: CalendarProvider,
    ) -> None:
        self._data_provider = data_provider
        self._universe_provider = universe_provider
        self._calendar_provider = calendar_provider

    def run(
        self,
        strategy: StrategyDefinition,
        as_of: datetime,
        account_states: Optional[Iterable[AccountState]] = None,
    ) -> Dict[str, List]:
        if not self._calendar_provider.is_session(strategy.market, as_of):
            raise ValueError("as_of must be a valid trading session")
        universe = self._universe_provider.get_universe(strategy.market, as_of)
        current_weights = self._current_weights(account_states or [], strategy.market, as_of)
        return strategy.generate(self._data_provider, universe, as_of, current_weights=current_weights or None)

    def _current_weights(
        self,
        account_states: Iterable[AccountState],
        market: Market,
        as_of: datetime,
    ) -> Dict[str, Decimal]:
        account_list = [account_state for account_state in account_states if account_state.market == market]
        if not account_list:
            return {}
        values: Dict[str, Decimal] = {}
        nav = Decimal("0")
        for account_state in account_list:
            nav += account_state.cash
            for position in account_state.positions.values():
                instrument = self._data_provider.get_instrument(position.instrument_id)
                if instrument.market != market or position.qty == 0:
                    continue
                market_value = self._position_market_value(position.instrument_id, position.qty, as_of)
                values[position.instrument_id] = values.get(position.instrument_id, Decimal("0")) + market_value
                nav += market_value
        if nav <= 0:
            return {}
        return {
            instrument_id: market_value / nav
            for instrument_id, market_value in values.items()
            if market_value > 0
        }

    def _position_market_value(self, instrument_id: str, qty: int, as_of: datetime) -> Decimal:
        latest_price = self._data_provider.get_latest_bar(instrument_id, as_of).close
        return latest_price * Decimal(qty)


class EqualWeightPortfolioConstructor(PortfolioConstructor):
    def __init__(self, top_n: int = 2) -> None:
        self._top_n = top_n

    def build_targets(self, strategy_id: str, market: Market, as_of: datetime, signals: List[SignalSnapshot]) -> List[TargetPosition]:
        selected = [signal for signal in signals if signal.score > 0][: self._top_n]
        if not selected:
            return []
        weight = Decimal("1") / Decimal(str(len(selected)))
        return [
            TargetPosition(
                as_of=as_of,
                strategy_id=strategy_id,
                account_scope=market.value,
                instrument_id=signal.instrument_id,
                target_weight=weight.quantize(Decimal("0.0001")),
            )
            for signal in selected
        ]


class StandardExecutionPlanner(ExecutionPlanner):
    def __init__(
        self,
        data_provider: MarketDataProvider,
        min_trade_value_by_market: Optional[Dict[Market, Decimal]] = None,
    ) -> None:
        self._data_provider = data_provider
        self._min_trade_value_by_market = min_trade_value_by_market or {
            Market.CN: Decimal("2500"),
            Market.US: Decimal("250"),
        }

    def build_trade_suggestions(
        self,
        account_states: Iterable[AccountState],
        targets: List[TargetPosition],
        as_of: datetime,
        source_strategy_id: str,
    ) -> List[TradeSuggestion]:
        targets_by_instrument = {target.instrument_id: target for target in targets}
        suggestions: List[TradeSuggestion] = []
        for account_state in account_states:
            nav = account_state.cash + sum(
                self._position_market_value(position.instrument_id, position.qty, as_of)
                for position in account_state.positions.values()
            )
            rebalance_instruments = set(targets_by_instrument) | {
                instrument_id
                for instrument_id, position in account_state.positions.items()
                if position.qty != 0
            }
            for instrument_id in sorted(rebalance_instruments):
                target = targets_by_instrument.get(
                    instrument_id,
                    TargetPosition(
                        as_of=as_of,
                        strategy_id=source_strategy_id,
                        account_scope=account_state.market.value,
                        instrument_id=instrument_id,
                        target_weight=Decimal("0"),
                    ),
                )
                instrument = self._data_provider.get_instrument(target.instrument_id)
                if instrument.market != account_state.market:
                    continue
                latest_price = self._data_provider.get_latest_bar(target.instrument_id, as_of).close
                raw_target_qty = (nav * target.target_weight / latest_price).to_integral_value(rounding=ROUND_DOWN)
                target_qty = int(raw_target_qty)
                if account_state.market == Market.CN:
                    target_qty -= target_qty % 100
                current_qty = account_state.positions.get(target.instrument_id).qty if target.instrument_id in account_state.positions else 0
                delta_qty = target_qty - current_qty
                if delta_qty == 0:
                    continue
                side = OrderSide.BUY if delta_qty > 0 else OrderSide.SELL
                qty = abs(delta_qty)
                trade_value = latest_price * Decimal(qty)
                if trade_value < self._min_trade_value_by_market.get(account_state.market, Decimal("0")):
                    continue
                suggestions.append(
                    TradeSuggestion(
                        suggestion_id=f"{account_state.account_id}:{source_strategy_id}:{target.instrument_id}:{as_of.isoformat()}",
                        as_of=as_of,
                        account_id=account_state.account_id,
                        instrument_id=target.instrument_id,
                        side=side,
                        suggested_qty=qty,
                        rationale=f"rebalance_to_{target.target_weight}",
                        source_strategy_id=source_strategy_id,
                        target_qty=target_qty,
                    )
                )
        return suggestions

    def build_order_intents(
        self,
        trade_suggestions: List[TradeSuggestion],
        requires_manual_approval: bool,
    ) -> List[OrderIntent]:
        return [
            OrderIntent(
                order_intent_id=f"{suggestion.account_id}:{suggestion.instrument_id}:{suggestion.as_of.isoformat()}",
                account_id=suggestion.account_id,
                instrument_id=suggestion.instrument_id,
                side=suggestion.side,
                qty=suggestion.suggested_qty,
                order_type=OrderType.MARKET,
                limit_price=None,
                time_in_force="DAY",
                source_strategy_id=suggestion.source_strategy_id,
                requires_manual_approval=requires_manual_approval,
            )
            for suggestion in trade_suggestions
        ]

    def _position_market_value(self, instrument_id: str, qty: int, as_of: datetime) -> Decimal:
        latest_price = self._data_provider.get_latest_bar(instrument_id, as_of).close
        return latest_price * Decimal(qty)


class StandardRiskEngine(RiskEngine):
    def __init__(self, data_provider: MarketDataProvider, market_rules_by_market: Dict[Market, MarketRules]) -> None:
        self._data_provider = data_provider
        self._market_rules_by_market = market_rules_by_market

    def validate(
        self,
        account_states: Dict[str, AccountState],
        order_intents: List[OrderIntent],
        context: RuntimeContext,
    ) -> Dict[str, List]:
        risk_results: List[RiskCheckResult] = []
        approved: List[OrderIntent] = []
        projected_states = {
            account_id: self._clone_account_state(account_state)
            for account_id, account_state in account_states.items()
        }
        order_groups: Dict[str, List[OrderIntent]] = {}
        for order_intent in order_intents:
            order_groups.setdefault(order_intent.account_id, []).append(order_intent)
        ordered_intents: List[OrderIntent] = []
        for account_id, account_order_intents in order_groups.items():
            del account_id
            ordered_intents.extend(
                sorted(
                    account_order_intents,
                    key=lambda item: (0 if item.side == OrderSide.SELL else 1, item.instrument_id),
                )
            )
        for order_intent in ordered_intents:
            account_state = projected_states[order_intent.account_id]
            instrument = self._data_provider.get_instrument(order_intent.instrument_id)
            violations = self._market_rules_by_market[instrument.market].validate_order_intent(
                account_state,
                order_intent,
                self._data_provider,
                context.as_of,
            )
            violations.extend(self._apply_account_constraints(account_state, order_intent, context.as_of))
            passed = not violations
            if passed:
                approved.append(order_intent)
                self._apply_approved_order(account_state, order_intent, context.as_of)
            risk_results.append(
                RiskCheckResult(
                    account_id=order_intent.account_id,
                    order_intent_id=order_intent.order_intent_id,
                    passed=passed,
                    violations=violations,
                )
            )
        return {"order_intents": approved, "risk_results": risk_results}

    def _apply_account_constraints(self, account_state: AccountState, order_intent: OrderIntent, as_of: datetime) -> List[str]:
        violations: List[str] = []
        constraints = account_state.constraints
        if order_intent.instrument_id in constraints.banned_instruments:
            violations.append("instrument_banned")
        if order_intent.side == OrderSide.SELL and not constraints.allow_short:
            current_qty = account_state.positions.get(order_intent.instrument_id).qty if order_intent.instrument_id in account_state.positions else 0
            if order_intent.qty > current_qty:
                violations.append("short_selling_not_allowed")
        latest_price = self._data_provider.get_latest_bar(order_intent.instrument_id, as_of).close
        order_value = latest_price * Decimal(order_intent.qty)
        if order_value > constraints.max_single_order_value:
            violations.append("single_order_value_exceeded")
        projected_state = self._project_account_state(account_state, order_intent, latest_price, as_of)
        nav = projected_state.cash + sum(
            self._data_provider.get_latest_bar(position.instrument_id, as_of).close * Decimal(position.qty)
            for position in projected_state.positions.values()
        )
        if order_intent.side == OrderSide.BUY and order_value > account_state.buying_power:
            violations.append("insufficient_buying_power")
        if nav > 0:
            projected_qty = projected_state.positions.get(order_intent.instrument_id).qty if order_intent.instrument_id in projected_state.positions else 0
            projected_weight = (latest_price * Decimal(projected_qty)) / nav if projected_qty > 0 else Decimal("0")
            if projected_weight > constraints.max_position_weight:
                violations.append("max_position_weight_exceeded")
        return violations

    def _project_account_state(
        self,
        account_state: AccountState,
        order_intent: OrderIntent,
        latest_price: Decimal,
        as_of: datetime,
    ) -> AccountState:
        projected = self._clone_account_state(account_state)
        qty_delta = order_intent.qty if order_intent.side == OrderSide.BUY else -order_intent.qty
        cash_delta = latest_price * Decimal(order_intent.qty)
        if order_intent.side == OrderSide.BUY:
            projected.cash -= cash_delta
            projected.buying_power -= cash_delta
        else:
            projected.cash += cash_delta
            projected.buying_power += cash_delta
        current_qty = projected.positions.get(order_intent.instrument_id).qty if order_intent.instrument_id in projected.positions else 0
        next_qty = current_qty + qty_delta
        if next_qty > 0:
            avg_cost = projected.positions.get(order_intent.instrument_id).avg_cost if order_intent.instrument_id in projected.positions else latest_price
            projected.positions[order_intent.instrument_id] = Position(
                instrument_id=order_intent.instrument_id,
                qty=next_qty,
                avg_cost=avg_cost,
                last_trade_date=as_of.date(),
            )
        else:
            projected.positions.pop(order_intent.instrument_id, None)
        return projected

    def _apply_approved_order(self, account_state: AccountState, order_intent: OrderIntent, as_of: datetime) -> None:
        latest_price = self._data_provider.get_latest_bar(order_intent.instrument_id, as_of).close
        projected = self._project_account_state(account_state, order_intent, latest_price, as_of)
        account_state.cash = projected.cash
        account_state.buying_power = projected.buying_power
        account_state.positions = projected.positions

    def _clone_account_state(self, account_state: AccountState) -> AccountState:
        return AccountState(
            account_id=account_state.account_id,
            market=account_state.market,
            broker_id=account_state.broker_id,
            cash=account_state.cash,
            buying_power=account_state.buying_power,
            positions={
                instrument_id: position
                for instrument_id, position in account_state.positions.items()
            },
            open_orders=list(account_state.open_orders),
            last_sync_at=account_state.last_sync_at,
            constraints=account_state.constraints,
        )
