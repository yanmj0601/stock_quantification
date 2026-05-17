from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from evoquant.domain import Market, SignalSide


@dataclass(frozen=True)
class MarketRule:
    commission_rate: float
    tax_rate_sell: float
    slippage_rate: float
    min_fee: float
    lot_size: int
    t_plus_one: bool


class MarketRulesService:
    def __init__(self, rules: dict[Market, MarketRule]):
        self.rules = rules

    @classmethod
    def defaults(cls) -> MarketRulesService:
        return cls(
            {
                Market.US: MarketRule(0.0005, 0.0, 0.0005, 0.0, 1, False),
                Market.CN: MarketRule(0.0003, 0.0005, 0.0005, 5.0, 100, True),
                Market.CRYPTO: MarketRule(0.001, 0.0, 0.001, 0.0, 1, False),
            }
        )

    def can_buy(self, market: Market, *, limit_up: bool, suspended: bool) -> bool:
        if suspended:
            return False
        if market is Market.CN and limit_up:
            return False
        return True

    def can_sell(
        self,
        market: Market,
        *,
        quantity: float,
        acquired_session: date,
        trade_session: date,
        limit_down: bool,
        suspended: bool,
    ) -> bool:
        if quantity <= 0 or suspended:
            return False
        rule = self.rules[market]
        if market is Market.CN and limit_down:
            return False
        if rule.t_plus_one and acquired_session >= trade_session:
            return False
        return True

    def estimate_quantity(
        self, market: Market, *, cash: float, price: float, side: SignalSide
    ) -> int:
        if cash <= 0 or price <= 0:
            return 0
        raw_quantity = int(cash / price)
        lot_size = self.rules[market].lot_size
        return raw_quantity - (raw_quantity % lot_size)

    def transaction_cost(
        self, market: Market, *, notional: float, side: SignalSide
    ) -> float:
        rule = self.rules[market]
        tax = rule.tax_rate_sell if side is SignalSide.SELL else 0.0
        return max(rule.min_fee, notional * (rule.commission_rate + rule.slippage_rate + tax))
