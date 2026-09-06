import pytest

from evoquant.domain import Market
from evoquant.services.paper import PaperTradingService
from evoquant.storage import PostgreSQLStore, loads


def test_paper_trading_records_order_fill_position_and_nav(tmp_path):
    service = PaperTradingService(PostgreSQLStore())
    account = service.create_account("default", starting_cash=100_000)

    order = service.submit_order(account.id, "AAPL", Market.US, quantity=10, limit_price=100)
    fill = service.fill_order(order.id, fill_price=99.5, fee=1.0)
    account_after = service.mark_to_market(account.id, {"AAPL": 101.0})

    assert fill.quantity == 10
    assert service.list_positions(account.id)[0].quantity == 10
    assert account_after.cash == 99_004.0
    assert account_after.nav == 100_014.0


def test_paper_trading_raises_for_unknown_account_and_order(tmp_path):
    service = PaperTradingService(PostgreSQLStore())

    with pytest.raises(KeyError) as account_error:
        service.submit_order("acct_missing", "AAPL", Market.US, quantity=10, limit_price=100)
    with pytest.raises(KeyError) as order_error:
        service.fill_order("ord_missing", fill_price=100, fee=1)

    assert account_error.value.args == ("acct_missing",)
    assert order_error.value.args == ("ord_missing",)


def test_order_and_fill_write_audit_events(tmp_path):
    store = PostgreSQLStore()
    service = PaperTradingService(store)
    account = service.create_account("default", starting_cash=100_000)

    order = service.submit_order(account.id, "AAPL", Market.US, quantity=10, limit_price=100)
    fill = service.fill_order(order.id, fill_price=99.5, fee=1.0)

    with store.connection() as conn:
        rows = conn.execute(
            """
            SELECT event_type, payload
            FROM audit_events
            WHERE entity_id IN (?, ?)
            ORDER BY created_at ASC, rowid ASC
            """,
            (order.id, fill.id),
        ).fetchall()

    assert [row["event_type"] for row in rows] == ["paper.order_submitted", "paper.order_filled"]
    assert loads(rows[0]["payload"])["account_id"] == account.id
    assert loads(rows[1]["payload"])["order_id"] == order.id


def test_multiple_fills_update_weighted_average_cost(tmp_path):
    service = PaperTradingService(PostgreSQLStore())
    account = service.create_account("default", starting_cash=100_000)

    first = service.submit_order(account.id, "AAPL", Market.US, quantity=10, limit_price=100)
    second = service.submit_order(account.id, "AAPL", Market.US, quantity=20, limit_price=110)
    service.fill_order(first.id, fill_price=100, fee=0)
    service.fill_order(second.id, fill_price=110, fee=0)

    position = service.list_positions(account.id)[0]

    assert position.quantity == 30
    assert position.average_cost == pytest.approx(106.6666666667)


def test_sell_reduces_quantity_without_changing_remaining_cost():
    service = PaperTradingService(PostgreSQLStore())
    account = service.create_account("sell", 100_000)
    buy = service.submit_order(account.id, "AAPL", Market.US, 10, 100)
    service.fill_order(buy.id, 100, 0)
    sell = service.submit_order(account.id, "AAPL", Market.US, -4, 120)
    service.fill_order(sell.id, 120, 0)
    position = service.list_positions(account.id)[0]
    assert position.quantity == 6
    assert position.average_cost == 100


def test_full_close_removes_position_and_realizes_cash():
    service = PaperTradingService(PostgreSQLStore())
    account = service.create_account("close", 100_000)
    buy = service.submit_order(account.id, "AAPL", Market.US, 10, 100)
    service.fill_order(buy.id, 100, 0)
    sell = service.submit_order(account.id, "AAPL", Market.US, -10, 120)
    service.fill_order(sell.id, 120, 0)
    assert service.list_positions(account.id) == []
    assert service.mark_to_market(account.id, {}).cash == 100_200


def test_order_cannot_fill_twice():
    store = PostgreSQLStore()
    service = PaperTradingService(store)
    account = service.create_account("duplicate", 100_000)
    order = service.submit_order(account.id, "AAPL", Market.US, 10, 100)
    service.fill_order(order.id, 100, 0)
    with pytest.raises(RuntimeError, match="already filled"):
        service.fill_order(order.id, 100, 0)
    assert service.list_positions(account.id)[0].quantity == 10
    with store.connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM paper_fills").fetchone()[0] == 1


def test_submit_order_rejects_insufficient_cash_and_oversell():
    store = PostgreSQLStore()
    service = PaperTradingService(store)
    account = service.create_account("limits", 1_000)

    with pytest.raises(RuntimeError, match="insufficient cash"):
        service.submit_order(account.id, "AAPL", Market.US, 11, 100)
    with pytest.raises(RuntimeError, match="cannot sell more than the current position"):
        service.submit_order(account.id, "AAPL", Market.US, -1, 100)

    with store.connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM paper_orders").fetchone()[0] == 0
