from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from evoquant.domain import Market, OrderDraftStatus, SignalSide, new_id, utc_now
from evoquant.services.market_rules import MarketRulesService
from evoquant.services.paper import PaperTradingService
from evoquant.storage import SQLiteStore, dumps, loads


@dataclass(frozen=True)
class PaperOrderDraft:
    id: str
    scan_id: str
    account_id: str
    strategy_id: str
    symbol: str
    market: Market
    side: SignalSide
    target_weight: float
    current_weight: float
    estimated_quantity: float
    reference_price: float
    reason: str
    risk_flags: tuple[str, ...]
    status: OrderDraftStatus


class PaperOrderDraftService:
    def __init__(self, store: SQLiteStore):
        self.store = store
        self.paper = PaperTradingService(store)
        self.rules = MarketRulesService.defaults()

    def create_draft(
        self,
        *,
        scan_id: str,
        account_id: str,
        strategy_id: str,
        symbol: str,
        market: Market,
        side: SignalSide,
        target_weight: float,
        current_weight: float,
        reference_price: float,
        reason: str,
        risk_flags: list[str],
        trade_session: date,
    ) -> PaperOrderDraft:
        account = self._account(account_id)
        quantity = self.rules.estimate_quantity(
            market,
            cash=account.nav * abs(target_weight - current_weight),
            price=reference_price,
            side=side,
        )
        blocking_flags = {"limit_up", "limit_down", "suspended", "stale_data"}
        status = (
            OrderDraftStatus.BLOCKED
            if quantity <= 0 or any(flag in blocking_flags for flag in risk_flags)
            else OrderDraftStatus.DRAFT
        )
        draft = PaperOrderDraft(
            id=new_id("draft"),
            scan_id=scan_id,
            account_id=account_id,
            strategy_id=strategy_id,
            symbol=symbol,
            market=market,
            side=side,
            target_weight=float(target_weight),
            current_weight=float(current_weight),
            estimated_quantity=float(quantity),
            reference_price=float(reference_price),
            reason=reason,
            risk_flags=tuple(risk_flags),
            status=status,
        )
        self._insert(draft)
        self._append_event(draft.id, "draft.created", {"status": draft.status.value})
        return draft

    def list_drafts(self) -> list[PaperOrderDraft]:
        with self.store.connection() as conn:
            rows = conn.execute(
                """
                SELECT id, scan_id, account_id, strategy_id, symbol, market, side,
                       target_weight, current_weight, estimated_quantity,
                       reference_price, reason, risk_flags, status
                FROM paper_order_drafts
                ORDER BY created_at DESC, rowid DESC
                """
            ).fetchall()
        return [self._from_row(row) for row in rows]

    def approve(self, draft_id: str) -> PaperOrderDraft:
        draft = self._get(draft_id)
        if draft.status is not OrderDraftStatus.DRAFT:
            raise RuntimeError("only draft orders can be approved")
        return self._set_status(draft, OrderDraftStatus.APPROVED, "draft.approved")

    def cancel(self, draft_id: str) -> PaperOrderDraft:
        draft = self._get(draft_id)
        if draft.status is OrderDraftStatus.SUBMITTED:
            raise RuntimeError("submitted drafts cannot be cancelled")
        return self._set_status(draft, OrderDraftStatus.CANCELLED, "draft.cancelled")

    def submit(self, draft_id: str) -> PaperOrderDraft:
        draft = self._get(draft_id)
        if draft.status is not OrderDraftStatus.APPROVED:
            raise RuntimeError("only approved drafts can be submitted")
        order = self.paper.submit_order(
            draft.account_id,
            draft.symbol,
            draft.market,
            draft.estimated_quantity if draft.side is SignalSide.BUY else -draft.estimated_quantity,
            draft.reference_price,
        )
        self.paper.fill_order(order.id, draft.reference_price, fee=0.0)
        return self._set_status(draft, OrderDraftStatus.SUBMITTED, "draft.submitted")

    def _account(self, account_id: str):
        with self.store.connection() as conn:
            row = conn.execute(
                "SELECT id, name, cash, nav FROM paper_accounts WHERE id = ?",
                (account_id,),
            ).fetchone()
        if row is None:
            raise KeyError(account_id)
        return self.paper._account_from_row(row)

    def _insert(self, draft: PaperOrderDraft) -> None:
        now = utc_now().isoformat()
        with self.store.connection() as conn:
            conn.execute(
                """
                INSERT INTO paper_order_drafts (
                    id, scan_id, account_id, strategy_id, symbol, market, side,
                    target_weight, current_weight, estimated_quantity,
                    reference_price, reason, risk_flags, status, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    draft.id,
                    draft.scan_id,
                    draft.account_id,
                    draft.strategy_id,
                    draft.symbol,
                    draft.market.value,
                    draft.side.value,
                    draft.target_weight,
                    draft.current_weight,
                    draft.estimated_quantity,
                    draft.reference_price,
                    draft.reason,
                    dumps(list(draft.risk_flags)),
                    draft.status.value,
                    now,
                    now,
                ),
            )

    def _get(self, draft_id: str) -> PaperOrderDraft:
        with self.store.connection() as conn:
            row = conn.execute(
                """
                SELECT id, scan_id, account_id, strategy_id, symbol, market, side,
                       target_weight, current_weight, estimated_quantity,
                       reference_price, reason, risk_flags, status
                FROM paper_order_drafts
                WHERE id = ?
                """,
                (draft_id,),
            ).fetchone()
        if row is None:
            raise KeyError(draft_id)
        return self._from_row(row)

    def _set_status(
        self, draft: PaperOrderDraft, status: OrderDraftStatus, event_type: str
    ) -> PaperOrderDraft:
        with self.store.connection() as conn:
            conn.execute(
                "UPDATE paper_order_drafts SET status = ?, updated_at = ? WHERE id = ?",
                (status.value, utc_now().isoformat(), draft.id),
            )
        self._append_event(draft.id, event_type, {"status": status.value})
        return PaperOrderDraft(
            id=draft.id,
            scan_id=draft.scan_id,
            account_id=draft.account_id,
            strategy_id=draft.strategy_id,
            symbol=draft.symbol,
            market=draft.market,
            side=draft.side,
            target_weight=draft.target_weight,
            current_weight=draft.current_weight,
            estimated_quantity=draft.estimated_quantity,
            reference_price=draft.reference_price,
            reason=draft.reason,
            risk_flags=draft.risk_flags,
            status=status,
        )

    def _from_row(self, row) -> PaperOrderDraft:
        return PaperOrderDraft(
            id=row["id"],
            scan_id=row["scan_id"],
            account_id=row["account_id"],
            strategy_id=row["strategy_id"],
            symbol=row["symbol"],
            market=Market(row["market"]),
            side=SignalSide(row["side"]),
            target_weight=float(row["target_weight"]),
            current_weight=float(row["current_weight"]),
            estimated_quantity=float(row["estimated_quantity"]),
            reference_price=float(row["reference_price"]),
            reason=row["reason"],
            risk_flags=tuple(loads(row["risk_flags"])),
            status=OrderDraftStatus(row["status"]),
        )

    def _append_event(self, entity_id: str, event_type: str, payload: dict) -> None:
        with self.store.connection() as conn:
            conn.execute(
                """
                INSERT INTO audit_events (id, entity_id, event_type, payload, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (new_id("evt"), entity_id, event_type, dumps(payload), utc_now().isoformat()),
            )
