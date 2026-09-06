from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from evoquant.domain import Market, new_id, utc_now
from evoquant.storage import PostgreSQLStore, dumps


@dataclass(frozen=True)
class PaperAccount:
    id: str
    name: str
    cash: float
    nav: float


@dataclass(frozen=True)
class PaperOrder:
    id: str
    account_id: str
    symbol: str
    market: Market
    quantity: float
    limit_price: float
    status: str
    created_at: datetime


@dataclass(frozen=True)
class PaperFill:
    id: str
    order_id: str
    account_id: str
    symbol: str
    market: Market
    quantity: float
    fill_price: float
    fee: float
    created_at: datetime


@dataclass(frozen=True)
class PaperPosition:
    account_id: str
    symbol: str
    market: Market
    quantity: float
    average_cost: float


class PaperTradingService:
    def __init__(self, store: PostgreSQLStore):
        self.store = store
        self._initialize_schema()

    def create_account(self, name: str, starting_cash: float) -> PaperAccount:
        account = PaperAccount(
            id=new_id("acct"),
            name=name,
            cash=float(starting_cash),
            nav=float(starting_cash),
        )
        now = utc_now().isoformat()
        with self.store.connection() as conn:
            conn.execute(
                """
                INSERT INTO paper_accounts (id, name, cash, nav, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (account.id, account.name, account.cash, account.nav, now, now),
            )
        return account

    def delete_account(self, account_id: str) -> None:
        with self.store.connection() as conn:
            if self._account_row(conn, account_id) is None:
                raise KeyError(account_id)
            conn.execute("DELETE FROM paper_accounts WHERE id = ?", (account_id,))
            conn.execute("DELETE FROM paper_positions WHERE account_id = ?", (account_id,))
            conn.execute("DELETE FROM paper_orders WHERE account_id = ?", (account_id,))
            conn.execute("DELETE FROM paper_fills WHERE account_id = ?", (account_id,))
            conn.execute("DELETE FROM paper_order_drafts WHERE account_id = ?", (account_id,))
            self._append_event(
                conn,
                account_id,
                "paper.account_deleted",
                {"account_id": account_id},
            )

    def submit_order(
        self,
        account_id: str,
        symbol: str,
        market: Market,
        quantity: float,
        limit_price: float,
    ) -> PaperOrder:
        if quantity == 0:
            raise ValueError("quantity must be non-zero")
        if limit_price <= 0:
            raise ValueError("limit_price must be positive")
        created_at = utc_now()
        order = PaperOrder(
            id=new_id("ord"),
            account_id=account_id,
            symbol=symbol,
            market=market,
            quantity=float(quantity),
            limit_price=float(limit_price),
            status="submitted",
            created_at=created_at,
        )
        with self.store.connection() as conn:
            account_row = self._account_row(conn, account_id)
            if account_row is None:
                raise KeyError(account_id)
            if order.quantity > 0 and order.quantity * order.limit_price > float(account_row["cash"]):
                raise RuntimeError("insufficient cash for paper order")
            if order.quantity < 0:
                position_row = conn.execute(
                    """
                    SELECT quantity
                    FROM paper_positions
                    WHERE account_id = ? AND symbol = ? AND market = ?
                    """,
                    (account_id, symbol, market.value),
                ).fetchone()
                available = float(position_row["quantity"]) if position_row else 0.0
                if abs(order.quantity) > available:
                    raise RuntimeError("cannot sell more than the current position")
            conn.execute(
                """
                INSERT INTO paper_orders (
                    id, account_id, symbol, market, quantity, limit_price, status, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    order.id,
                    order.account_id,
                    order.symbol,
                    order.market.value,
                    order.quantity,
                    order.limit_price,
                    order.status,
                    order.created_at.isoformat(),
                ),
            )
            self._append_event(
                conn,
                order.id,
                "paper.order_submitted",
                {
                    "account_id": order.account_id,
                    "symbol": order.symbol,
                    "market": order.market.value,
                    "quantity": order.quantity,
                    "limit_price": order.limit_price,
                },
            )
        return order

    def fill_order(self, order_id: str, fill_price: float, fee: float) -> PaperFill:
        created_at = utc_now()
        with self.store.connection() as conn:
            order_row = conn.execute(
                """
                SELECT id, account_id, symbol, market, quantity, status
                FROM paper_orders
                WHERE id = ?
                """,
                (order_id,),
            ).fetchone()
            if order_row is None:
                raise KeyError(order_id)
            if order_row["status"] == "filled":
                raise RuntimeError("order is already filled")
            if fill_price <= 0:
                raise ValueError("fill_price must be positive")
            if fee < 0:
                raise ValueError("fee must be non-negative")

            fill = PaperFill(
                id=new_id("fill"),
                order_id=order_row["id"],
                account_id=order_row["account_id"],
                symbol=order_row["symbol"],
                market=Market(order_row["market"]),
                quantity=float(order_row["quantity"]),
                fill_price=float(fill_price),
                fee=float(fee),
                created_at=created_at,
            )
            account_row = self._account_row(conn, fill.account_id)
            if account_row is None:
                raise KeyError(fill.account_id)

            conn.execute(
                """
                INSERT INTO paper_fills (
                    id, order_id, account_id, symbol, market, quantity,
                    fill_price, fee, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    fill.id,
                    fill.order_id,
                    fill.account_id,
                    fill.symbol,
                    fill.market.value,
                    fill.quantity,
                    fill.fill_price,
                    fill.fee,
                    fill.created_at.isoformat(),
                ),
            )
            conn.execute(
                "UPDATE paper_orders SET status = ? WHERE id = ?",
                ("filled", fill.order_id),
            )

            cash = float(account_row["cash"]) - (fill.quantity * fill.fill_price + fill.fee)
            conn.execute(
                "UPDATE paper_accounts SET cash = ?, updated_at = ? WHERE id = ?",
                (cash, utc_now().isoformat(), fill.account_id),
            )
            self._upsert_position(conn, fill)
            self._append_event(
                conn,
                fill.id,
                "paper.order_filled",
                {
                    "order_id": fill.order_id,
                    "account_id": fill.account_id,
                    "symbol": fill.symbol,
                    "market": fill.market.value,
                    "quantity": fill.quantity,
                    "fill_price": fill.fill_price,
                    "fee": fill.fee,
                },
            )
        return fill

    def list_positions(self, account_id: str) -> list[PaperPosition]:
        with self.store.connection() as conn:
            if self._account_row(conn, account_id) is None:
                raise KeyError(account_id)
            rows = conn.execute(
                """
                SELECT account_id, symbol, market, quantity, average_cost
                FROM paper_positions
                WHERE account_id = ?
                ORDER BY symbol ASC, market ASC
                """,
                (account_id,),
            ).fetchall()
        return [self._position_from_row(row) for row in rows]

    def mark_to_market(self, account_id: str, prices: dict[str, float]) -> PaperAccount:
        with self.store.connection() as conn:
            account_row = self._account_row(conn, account_id)
            if account_row is None:
                raise KeyError(account_id)
            position_rows = conn.execute(
                """
                SELECT account_id, symbol, market, quantity, average_cost
                FROM paper_positions
                WHERE account_id = ?
                """,
                (account_id,),
            ).fetchall()
            market_value = sum(
                float(row["quantity"]) * float(prices.get(row["symbol"], row["average_cost"]))
                for row in position_rows
            )
            nav = float(account_row["cash"]) + market_value
            updated_at = utc_now().isoformat()
            conn.execute(
                "UPDATE paper_accounts SET nav = ?, updated_at = ? WHERE id = ?",
                (nav, updated_at, account_id),
            )
            updated_row = self._account_row(conn, account_id)
        return self._account_from_row(updated_row)

    def _initialize_schema(self) -> None:
        with self.store.connection() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS paper_accounts (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    cash REAL NOT NULL,
                    nav REAL NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS paper_orders (
                    id TEXT PRIMARY KEY,
                    account_id TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    market TEXT NOT NULL,
                    quantity REAL NOT NULL,
                    limit_price REAL NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS paper_fills (
                    id TEXT PRIMARY KEY,
                    order_id TEXT NOT NULL,
                    account_id TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    market TEXT NOT NULL,
                    quantity REAL NOT NULL,
                    fill_price REAL NOT NULL,
                    fee REAL NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS paper_positions (
                    account_id TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    market TEXT NOT NULL,
                    quantity REAL NOT NULL,
                    average_cost REAL NOT NULL,
                    PRIMARY KEY (account_id, symbol, market)
                );
                """
            )

    def _upsert_position(self, conn, fill: PaperFill) -> None:
        row = conn.execute(
            """
            SELECT quantity, average_cost
            FROM paper_positions
            WHERE account_id = ? AND symbol = ? AND market = ?
            """,
            (fill.account_id, fill.symbol, fill.market.value),
        ).fetchone()
        if row is None:
            if fill.quantity < 0:
                raise RuntimeError("paper trading cannot create a short position")
            conn.execute(
                """
                INSERT INTO paper_positions (
                    account_id, symbol, market, quantity, average_cost
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    fill.account_id,
                    fill.symbol,
                    fill.market.value,
                    fill.quantity,
                    fill.fill_price,
                ),
            )
            return

        existing_quantity = float(row["quantity"])
        existing_cost = float(row["average_cost"])
        new_quantity = existing_quantity + fill.quantity
        if new_quantity < 0:
            raise RuntimeError("paper trading cannot create a short position")
        if new_quantity == 0:
            conn.execute(
                """
                DELETE FROM paper_positions
                WHERE account_id = ? AND symbol = ? AND market = ?
                """,
                (fill.account_id, fill.symbol, fill.market.value),
            )
            return
        if fill.quantity < 0:
            new_cost = existing_cost
        else:
            new_cost = (
                (existing_quantity * existing_cost) + (fill.quantity * fill.fill_price)
            ) / new_quantity
        conn.execute(
            """
            UPDATE paper_positions
            SET quantity = ?, average_cost = ?
            WHERE account_id = ? AND symbol = ? AND market = ?
            """,
            (new_quantity, new_cost, fill.account_id, fill.symbol, fill.market.value),
        )

    def _append_event(self, conn, entity_id: str, event_type: str, payload: dict) -> None:
        conn.execute(
            """
            INSERT INTO audit_events (id, entity_id, event_type, payload, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (new_id("evt"), entity_id, event_type, dumps(payload), utc_now().isoformat()),
        )

    def _account_row(self, conn, account_id: str):
        return conn.execute(
            "SELECT id, name, cash, nav FROM paper_accounts WHERE id = ?",
            (account_id,),
        ).fetchone()

    def _account_from_row(self, row) -> PaperAccount:
        return PaperAccount(
            id=row["id"],
            name=row["name"],
            cash=float(row["cash"]),
            nav=float(row["nav"]),
        )

    def _position_from_row(self, row) -> PaperPosition:
        return PaperPosition(
            account_id=row["account_id"],
            symbol=row["symbol"],
            market=Market(row["market"]),
            quantity=float(row["quantity"]),
            average_cost=float(row["average_cost"]),
        )
