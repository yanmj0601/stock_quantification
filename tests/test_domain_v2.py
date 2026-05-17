from evoquant.domain import Market, OrderDraftStatus, SignalSide, TimeFrame


def test_v2_signal_and_draft_enums_are_stable():
    assert SignalSide.BUY.value == "buy"
    assert SignalSide.HOLD.value == "hold"
    assert SignalSide.SELL.value == "sell"
    assert OrderDraftStatus.DRAFT.value == "draft"
    assert OrderDraftStatus.BLOCKED.value == "blocked"
    assert TimeFrame.DAILY.value == "1d"


def test_existing_markets_remain_supported():
    assert {market.value for market in Market} == {"US", "CN", "CRYPTO"}
