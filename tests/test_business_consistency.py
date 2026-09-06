"""无需数据库即可运行的业务规则回归测试。"""
from dataclasses import replace
from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from evoquant.domain import Market, OrderDraftStatus
from evoquant.services.auto_sync import AutoBarSyncService
from evoquant.services.market_data import MarketBar
from evoquant.services.strategies import CrossSectionalMomentumStrategy, _ScoredSymbol


def test_higher_risk_reduces_score():
    bar = MarketBar('AAA', Market.US, date(2026, 1, 1), 10, 10, 10, 10, 100, 1000, True, False, False, False, 'test')
    base = _ScoredSymbol('AAA', Market.US, bar, .2, .1, .1, -.1, ())
    other = replace(base, symbol='BBB', volatility=.2, max_drawdown=-.2)
    strategy = CrossSectionalMomentumStrategy({})
    low_risk = {x.symbol: x.score for x in strategy._rank([base, other])}['AAA']
    high_risk = {x.symbol: x.score for x in strategy._rank([replace(base, volatility=.3, max_drawdown=-.3), other])}['AAA']
    assert low_risk > high_risk


def test_signal_reason_uses_actual_lookbacks():
    bars = [MarketBar('AAA', Market.US, date(2026, 1, day), 10, 10, 10, 10 + day, 100, 1000, True, False, False, False, 'test') for day in range(1, 6)]
    signal = CrossSectionalMomentumStrategy({'lookback_long': 3, 'lookback_short': 1}).generate(Market.US, ['AAA'], bars, {})[0]
    assert '3日动量' in signal.reason
    assert '1日动量' in signal.reason


def test_scheduled_signals_leave_drafts_for_human_approval():
    store = MagicMock()
    conn = store.connection.return_value.__enter__.return_value
    conn.execute.return_value.fetchall.side_effect = [
        [{'id': 'account', 'nav': 100000}],
        [{'session': '2026-01-01'}],
        [],
    ]
    result = SimpleNamespace(symbol='AAA', signal='buy', close=100, target_weight=.08, reason='test', risk_flags=())
    with patch('evoquant.services.auto_sync.InstrumentMaster') as master, patch('evoquant.services.auto_sync.MarketDataService') as data, patch('evoquant.services.signals.SignalScanner') as scanner, patch('evoquant.services.drafts.PaperOrderDraftService') as drafts, patch('evoquant.api._latest_sync_coverage', return_value=1):
        master.return_value.list_by_market.return_value = [SimpleNamespace(symbol='AAA', tradable=True)]
        data.return_value.list_bars.return_value = [object()]
        scanner.return_value.run_scan.return_value = SimpleNamespace(id='scan', status='success')
        scanner.return_value.list_results.return_value = [result]
        drafts.return_value.create_draft.return_value = SimpleNamespace(id='draft', status=OrderDraftStatus.DRAFT)
        AutoBarSyncService(store, lambda market: None).run_auto_trading(Market.US, date(2026, 1, 2))
        drafts.return_value.create_draft.assert_called_once()
        drafts.return_value.approve.assert_not_called()
        drafts.return_value.submit.assert_not_called()


def test_cn_universe_excludes_foreign_currency_b_shares():
    from evoquant.providers.baostock import _is_cn_stock
    assert _is_cn_stock('SH', '600000')
    assert _is_cn_stock('SZ', '301001')
    assert not _is_cn_stock('SH', '900901')
    assert not _is_cn_stock('SZ', '200002')
