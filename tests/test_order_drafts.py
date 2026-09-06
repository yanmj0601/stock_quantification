from datetime import date

import pytest

from evoquant.domain import Market, OrderDraftStatus, RiskMode, SignalSide
from evoquant.services.drafts import PaperOrderDraftService
from evoquant.services.paper import PaperTradingService
from evoquant.services.risk import RiskService
from evoquant.storage import PostgreSQLStore


def test_draft_lifecycle_requires_approval_before_submit(tmp_path):
    store = PostgreSQLStore()
    account = PaperTradingService(store).create_account("paper-us", 100_000)
    service = PaperOrderDraftService(store)

    draft = service.create_draft(
        scan_id="scan_1",
        account_id=account.id,
        strategy_id="strategy_1",
        symbol="AAPL",
        market=Market.US,
        side=SignalSide.BUY,
        target_weight=0.08,
        current_weight=0,
        reference_price=100,
        reason="score ranked top 20",
        risk_flags=[],
        trade_session=date(2026, 1, 5),
    )

    assert draft.status is OrderDraftStatus.DRAFT

    approved = service.approve(draft.id)
    submitted = service.submit(approved.id)

    assert approved.status is OrderDraftStatus.APPROVED
    assert submitted.status is OrderDraftStatus.SUBMITTED
    assert PaperTradingService(store).list_positions(account.id)[0].symbol == "AAPL"


def test_blocked_draft_cannot_be_approved(tmp_path):
    store = PostgreSQLStore()
    account = PaperTradingService(store).create_account("paper-cn", 100_000)
    service = PaperOrderDraftService(store)

    draft = service.create_draft(
        scan_id="scan_1",
        account_id=account.id,
        strategy_id="strategy_1",
        symbol="600519",
        market=Market.CN,
        side=SignalSide.BUY,
        target_weight=0.08,
        current_weight=0,
        reference_price=1800,
        reason="limit up blocks buy",
        risk_flags=["limit_up"],
        trade_session=date(2026, 1, 5),
    )

    assert draft.status is OrderDraftStatus.BLOCKED

    with pytest.raises(RuntimeError, match="only draft orders can be approved"):
        service.approve(draft.id)


@pytest.mark.parametrize(
    ("side", "risk_flag"),
    [(SignalSide.BUY, "limit_down"), (SignalSide.SELL, "limit_up")],
)
def test_opposite_price_limit_does_not_block_draft(side, risk_flag):
    store = PostgreSQLStore()
    account = PaperTradingService(store).create_account("directional-limit", 100_000)
    draft = PaperOrderDraftService(store).create_draft(
        scan_id="scan_1",
        account_id=account.id,
        strategy_id="strategy_1",
        symbol="600000",
        market=Market.CN,
        side=side,
        target_weight=0.08 if side is SignalSide.BUY else 0,
        current_weight=0 if side is SignalSide.BUY else 0.08,
        reference_price=10,
        reason="directional price limit",
        risk_flags=[risk_flag],
        trade_session=date(2026, 1, 5),
    )
    assert draft.status is OrderDraftStatus.DRAFT


def test_approved_draft_cannot_submit_while_paper_trading_is_paused():
    store = PostgreSQLStore()
    account = PaperTradingService(store).create_account("paper-paused", 100_000)
    service = PaperOrderDraftService(store)
    draft = service.create_draft(
        scan_id="scan_1",
        account_id=account.id,
        strategy_id="strategy_1",
        symbol="AAPL",
        market=Market.US,
        side=SignalSide.BUY,
        target_weight=0.08,
        current_weight=0,
        reference_price=100,
        reason="score ranked top 20",
        risk_flags=[],
        trade_session=date(2026, 1, 5),
    )
    service.approve(draft.id)
    RiskService(store).set_mode(RiskMode.PAUSED, "maintenance")

    with pytest.raises(RuntimeError, match="paper trading is paused"):
        service.submit(draft.id)

    assert service._get(draft.id).status is OrderDraftStatus.APPROVED
