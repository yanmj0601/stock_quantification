from __future__ import annotations

import json
import os
from datetime import datetime
from decimal import Decimal
from typing import Dict, List, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .interfaces import BrokerAdapter
from .models import (
    AccountConstraints,
    AccountState,
    BrokerOrder,
    Market,
    OrderIntent,
    OrderType,
    Position,
)


class BrokerError(RuntimeError):
    pass


class UnsupportedBrokerMarketError(BrokerError):
    pass


def _to_decimal(value: object) -> Decimal:
    return Decimal(str(value or "0"))


def _parse_datetime(value: object) -> datetime:
    raw = str(value or "")
    if not raw:
        return datetime.utcnow()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    return datetime.fromisoformat(raw)


class AlpacaPaperBrokerAdapter(BrokerAdapter):
    def __init__(
        self,
        key_id: str,
        secret_key: str,
        base_url: str = "https://paper-api.alpaca.markets",
        timeout_seconds: float = 15.0,
    ) -> None:
        self._key_id = key_id
        self._secret_key = secret_key
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds

    @classmethod
    def from_env(cls) -> "AlpacaPaperBrokerAdapter":
        key_id = os.getenv("ALPACA_PAPER_KEY_ID") or os.getenv("APCA_API_KEY_ID")
        secret_key = os.getenv("ALPACA_PAPER_SECRET_KEY") or os.getenv("APCA_API_SECRET_KEY")
        if not key_id or not secret_key:
            raise BrokerError("Missing Alpaca paper credentials in environment")
        return cls(key_id=key_id, secret_key=secret_key)

    def sync_account_state(self, account_id: str = "alpaca-paper-us") -> AccountState:
        account = self._request_json("GET", "/v2/account")
        positions_payload = self._request_json("GET", "/v2/positions")
        positions = {
            f"US.{item['symbol'].upper()}": Position(
                instrument_id=f"US.{item['symbol'].upper()}",
                qty=int(Decimal(str(item.get("qty", "0")))),
                avg_cost=_to_decimal(item.get("avg_entry_price")),
            )
            for item in positions_payload
        }
        cash = _to_decimal(account.get("cash"))
        buying_power = _to_decimal(account.get("buying_power") or account.get("cash"))
        return AccountState(
            account_id=account_id,
            market=Market.US,
            broker_id="alpaca-paper",
            cash=cash,
            buying_power=buying_power,
            positions=positions,
            last_sync_at=datetime.utcnow(),
            constraints=AccountConstraints(
                max_position_weight=Decimal("0.60"),
                max_single_order_value=buying_power if buying_power > 0 else Decimal("0"),
            ),
        )

    def submit_orders(self, order_intents: List[OrderIntent]) -> List[BrokerOrder]:
        broker_orders: List[BrokerOrder] = []
        for order_intent in order_intents:
            instrument_id = order_intent.instrument_id.upper()
            if not instrument_id.startswith("US."):
                raise UnsupportedBrokerMarketError("Alpaca paper only supports US instruments")
            payload = {
                "symbol": instrument_id.split(".", 1)[1],
                "qty": str(order_intent.qty),
                "side": order_intent.side.value.lower(),
                "type": "market" if order_intent.order_type == OrderType.MARKET else "limit",
                "time_in_force": order_intent.time_in_force.lower(),
                "client_order_id": self._client_order_id(order_intent.order_intent_id),
            }
            if order_intent.order_type == OrderType.LIMIT and order_intent.limit_price is not None:
                payload["limit_price"] = str(order_intent.limit_price)
            response = self._request_json("POST", "/v2/orders", payload)
            broker_orders.append(
                BrokerOrder(
                    broker_order_id=str(response["id"]),
                    account_id=order_intent.account_id,
                    order_intent_id=order_intent.order_intent_id,
                    instrument_id=order_intent.instrument_id,
                    side=order_intent.side.value,
                    requested_qty=order_intent.qty,
                    status=str(response.get("status", "accepted")),
                    submitted_at=_parse_datetime(response.get("submitted_at")),
                    filled_qty=int(Decimal(str(response.get("filled_qty", "0")))),
                    avg_fill_price=(
                        _to_decimal(response.get("filled_avg_price"))
                        if response.get("filled_avg_price") not in (None, "")
                        else None
                    ),
                )
            )
        return broker_orders

    def _client_order_id(self, order_intent_id: str) -> str:
        sanitized = "".join(ch if ch.isalnum() or ch in ("-", "_") else "-" for ch in order_intent_id)
        return sanitized[:48]

    def _request_json(
        self,
        method: str,
        path: str,
        payload: Optional[Dict[str, object]] = None,
    ) -> object:
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        request = Request(
            url=f"{self._base_url}{path}",
            data=body,
            method=method,
            headers={
                "accept": "application/json",
                "content-type": "application/json",
                "APCA-API-KEY-ID": self._key_id,
                "APCA-API-SECRET-KEY": self._secret_key,
            },
        )
        try:
            with urlopen(request, timeout=self._timeout_seconds) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise BrokerError(f"Alpaca request failed: {exc.code} {detail}") from exc
        except URLError as exc:
            raise BrokerError(f"Alpaca request failed: {exc.reason}") from exc


def build_broker_adapter(name: str) -> BrokerAdapter:
    normalized = name.strip().upper()
    if normalized == "ALPACA_PAPER":
        return AlpacaPaperBrokerAdapter.from_env()
    raise BrokerError(f"Unsupported broker adapter: {name}")
