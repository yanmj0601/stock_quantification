from datetime import date

from evoquant.domain import Market, SignalSide
from evoquant.services.market_rules import MarketRulesService


def test_cn_rounds_buy_quantity_to_lot_size():
    rules = MarketRulesService.defaults()

    quantity = rules.estimate_quantity(
        Market.CN, cash=123456, price=25.3, side=SignalSide.BUY
    )

    assert quantity % 100 == 0
    assert quantity == 4800


def test_cn_t_plus_one_blocks_same_day_sell():
    rules = MarketRulesService.defaults()

    allowed = rules.can_sell(
        Market.CN,
        quantity=100,
        acquired_session=date(2026, 1, 2),
        trade_session=date(2026, 1, 2),
        limit_down=False,
        suspended=False,
    )

    assert allowed is False


def test_us_allows_same_day_sell_when_not_suspended():
    rules = MarketRulesService.defaults()

    allowed = rules.can_sell(
        Market.US,
        quantity=1,
        acquired_session=date(2026, 1, 2),
        trade_session=date(2026, 1, 2),
        limit_down=False,
        suspended=False,
    )

    assert allowed is True


def test_limit_up_blocks_new_cn_buy():
    rules = MarketRulesService.defaults()

    assert rules.can_buy(Market.CN, limit_up=True, suspended=False) is False
    assert rules.can_buy(Market.CN, limit_up=False, suspended=False) is True
