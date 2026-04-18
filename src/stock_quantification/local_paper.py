from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from pathlib import Path
import shutil
from typing import Any, Dict, Iterable, List, Mapping, Optional

from .artifacts import read_json_artifact, write_json_artifact, write_text_artifact
from .models import AccountConstraints, AccountState, Market, OrderIntent, Position
from .runtime import ExecutionResult

ROOT_DIR = Path(__file__).resolve().parents[2]
DEFAULT_LOCAL_PAPER_ROOT = ROOT_DIR / "artifacts" / "local_paper"


def _to_decimal(value: object) -> Decimal:
    return Decimal(str(value or "0"))


def _serialize_position(position: Position) -> Dict[str, Any]:
    return {
        "instrument_id": position.instrument_id,
        "qty": position.qty,
        "avg_cost": str(position.avg_cost),
        "last_trade_date": position.last_trade_date.isoformat() if position.last_trade_date is not None else None,
    }


def _serialize_account_state(account_state: AccountState) -> Dict[str, Any]:
    return {
        "account_id": account_state.account_id,
        "market": account_state.market.value,
        "broker_id": account_state.broker_id,
        "cash": str(account_state.cash),
        "buying_power": str(account_state.buying_power),
        "last_sync_at": account_state.last_sync_at.isoformat() if account_state.last_sync_at is not None else None,
        "positions": [_serialize_position(position) for position in sorted(account_state.positions.values(), key=lambda item: item.instrument_id)],
    }


def _deserialize_account_state(payload: Mapping[str, Any]) -> AccountState:
    positions = {
        str(item["instrument_id"]): Position(
            instrument_id=str(item["instrument_id"]),
            qty=int(item["qty"]),
            avg_cost=_to_decimal(item.get("avg_cost")),
            last_trade_date=(
                datetime.fromisoformat(str(item["last_trade_date"])).date()
                if item.get("last_trade_date")
                else None
            ),
        )
        for item in payload.get("positions", [])
    }
    last_sync_at_raw = payload.get("last_sync_at")
    return AccountState(
        account_id=str(payload["account_id"]),
        market=Market(str(payload["market"])),
        broker_id=str(payload.get("broker_id", "local-paper")),
        cash=_to_decimal(payload.get("cash")),
        buying_power=_to_decimal(payload.get("buying_power")),
        positions=positions,
        last_sync_at=datetime.fromisoformat(str(last_sync_at_raw)) if last_sync_at_raw else None,
        constraints=AccountConstraints(
            max_position_weight=Decimal("0.60"),
            max_single_order_value=_to_decimal(payload.get("buying_power")),
        ),
    )


class LocalPaperLedger:
    def __init__(self, base_dir: str | Path = DEFAULT_LOCAL_PAPER_ROOT) -> None:
        self._base_dir = Path(base_dir)

    def sync_account_state(
        self,
        account_id: str,
        market: Market,
        initial_cash: Decimal,
    ) -> AccountState:
        existing = read_json_artifact(self._base_dir, self._account_relative_path(account_id))
        if existing is not None:
            account_state = _deserialize_account_state(existing)
            if account_state.market != market:
                raise ValueError(
                    f"Local paper account {account_id} belongs to {account_state.market.value}; "
                    f"use a different account id for {market.value}"
                )
            return account_state
        account_state = AccountState(
            account_id=account_id,
            market=market,
            broker_id="local-paper",
            cash=initial_cash,
            buying_power=initial_cash,
            last_sync_at=datetime.utcnow(),
            constraints=AccountConstraints(max_position_weight=Decimal("0.60"), max_single_order_value=initial_cash),
        )
        self._write_account(account_state)
        self._write_ledger(
            account_id,
            {
                "account_id": account_id,
                "market": market.value,
                "starting_cash": str(initial_cash),
                "trades": [],
                "nav_history": [
                    {
                        "as_of": datetime.utcnow().isoformat(),
                        "trade_date": datetime.utcnow().date().isoformat(),
                        "nav": str(initial_cash),
                        "cash": str(initial_cash),
                        "position_value": "0",
                        "cumulative_return": "0.0000",
                    }
                ],
            },
        )
        return account_state

    def record_execution(
        self,
        account_id: str,
        strategy_id: str,
        market: Market,
        order_intents: Iterable[OrderIntent],
        execution_results: Iterable[ExecutionResult],
        instrument_names: Optional[Mapping[str, str]] = None,
        price_map: Optional[Mapping[str, Decimal]] = None,
    ) -> Dict[str, Any]:
        instrument_names = instrument_names or {}
        price_map = price_map or {}
        order_lookup = {intent.order_intent_id: intent for intent in order_intents if intent.account_id == account_id}
        relevant_results = [result for result in execution_results if result.output_account_state.account_id == account_id]
        if not relevant_results:
            return {"account": None, "trade_records": [], "paths": {}}

        latest_result = relevant_results[-1]
        account_state = latest_result.output_account_state
        result_as_of = latest_result.context.as_of
        self._write_account(account_state)

        ledger = read_json_artifact(self._base_dir, self._ledger_relative_path(account_id)) or {
            "account_id": account_id,
            "market": market.value,
            "starting_cash": None,
            "trades": [],
            "nav_history": [],
        }
        trade_records: List[Dict[str, Any]] = []
        for result in relevant_results:
            for fill in result.fills:
                if fill.filled_qty <= 0:
                    continue
                order_intent = order_lookup.get(fill.order_intent_id)
                trade_records.append(
                    {
                        "executed_at": result.context.as_of.isoformat(),
                        "trade_date": result.context.as_of.date().isoformat(),
                        "account_id": account_id,
                        "market": market.value,
                        "strategy_id": strategy_id,
                        "instrument_id": fill.instrument_id,
                        "name": instrument_names.get(fill.instrument_id, fill.instrument_id),
                        "side": order_intent.side.value if order_intent is not None else "UNKNOWN",
                        "requested_qty": fill.requested_qty,
                        "filled_qty": fill.filled_qty,
                        "estimated_price": str(fill.estimated_price),
                        "realized_price": str(fill.realized_price) if fill.realized_price is not None else None,
                        "cash_delta": str(fill.cash_delta),
                        "status": fill.status.value,
                    }
                )
        ledger["trades"] = list(ledger.get("trades", [])) + trade_records
        trades_all = list(ledger.get("trades", []))
        starting_cash = self._resolve_starting_cash(account_state, ledger, trades_all)
        ledger["starting_cash"] = str(starting_cash)
        nav_history = list(ledger.get("nav_history", []))
        if not nav_history:
            baseline_trade_date = trade_records[0]["trade_date"] if trade_records else latest_result.context.as_of.date().isoformat()
            nav_history.append(
                {
                    "as_of": result_as_of.isoformat(),
                    "trade_date": baseline_trade_date,
                    "nav": str(starting_cash.quantize(Decimal("0.0001"))),
                    "cash": str(starting_cash.quantize(Decimal("0.0001"))),
                    "position_value": "0.0000",
                    "cumulative_return": "0.0000",
                }
            )
        nav_snapshot = self._nav_snapshot(
            account_state=account_state,
            as_of=result_as_of,
            trade_date=latest_result.context.as_of.date().isoformat(),
            starting_cash=starting_cash,
            price_map=price_map,
        )
        if not nav_history or nav_history[-1].get("as_of") != nav_snapshot["as_of"]:
            nav_history.append(nav_snapshot)
        ledger["nav_history"] = nav_history
        ledger_path = self._write_ledger(account_id, ledger)

        run_stamp = latest_result.context.as_of.strftime("%Y%m%dT%H%M%S")
        run_relative = f"{account_id}/runs/{run_stamp}_{strategy_id}.json"
        run_payload = {
            "summary": {
                "artifact_type": "local_paper_run",
                "account_id": account_id,
                "market": market.value,
                "strategy_id": strategy_id,
                "trade_count": len(trade_records),
                "cash": str(account_state.cash),
                "buying_power": str(account_state.buying_power),
                "position_count": len(account_state.positions),
                "runtime_mode": "LOCAL_PAPER",
                "as_of": latest_result.context.as_of.isoformat(),
            },
            "account": _serialize_account_state(account_state),
            "trades": trade_records,
        }
        run_json_path = write_json_artifact(self._base_dir, run_relative, run_payload)
        md_lines = [
            f"# Local Paper Run {account_id}",
            "",
            f"- as_of: {latest_result.context.as_of.isoformat()}",
            f"- strategy_id: {strategy_id}",
            f"- trade_count: {len(trade_records)}",
            f"- cash: {account_state.cash}",
            f"- buying_power: {account_state.buying_power}",
        ]
        run_md_path = write_text_artifact(
            self._base_dir,
            run_relative.replace(".json", ".md"),
            "\n".join(md_lines) + "\n",
        )
        overview = self.account_overview(account_id)
        return {
            "account": overview,
            "summary": run_payload["summary"],
            "trade_records": trade_records,
            "paths": {
                "account": str(self._base_dir / self._account_relative_path(account_id)),
                "ledger": ledger_path,
                "run_json": run_json_path,
                "run_markdown": run_md_path,
            },
        }

    def account_overview(
        self,
        account_id: str,
        recent_trade_limit: int = 12,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        payload = read_json_artifact(self._base_dir, self._account_relative_path(account_id))
        if payload is None:
            return None
        account_state = _deserialize_account_state(payload)
        ledger = read_json_artifact(self._base_dir, self._ledger_relative_path(account_id)) or {"trades": [], "nav_history": []}
        trades = self._filter_by_date(list(ledger.get("trades", [])), start_date, end_date)
        recent_trades = list(reversed(trades[-recent_trade_limit:]))
        nav_history = self._filter_by_date(list(ledger.get("nav_history", [])), start_date, end_date)
        latest_nav = _to_decimal(nav_history[-1]["nav"]) if nav_history else account_state.cash
        starting_cash = self._resolve_starting_cash(account_state, ledger, list(ledger.get("trades", [])))
        cumulative_return = Decimal("0")
        if starting_cash != 0:
            cumulative_return = ((latest_nav / starting_cash) - Decimal("1")).quantize(Decimal("0.0001"))
        return {
            "account_id": account_state.account_id,
            "market": account_state.market.value,
            "broker_id": account_state.broker_id,
            "cash": str(account_state.cash),
            "buying_power": str(account_state.buying_power),
            "position_count": len(account_state.positions),
            "trade_count": len(list(ledger.get("trades", []))),
            "filtered_trade_count": len(trades),
            "positions": [_serialize_position(position) for position in sorted(account_state.positions.values(), key=lambda item: item.instrument_id)],
            "filtered_trades": trades,
            "recent_trades": recent_trades,
            "nav_history": nav_history,
            "latest_nav": str(latest_nav),
            "cumulative_return": str(cumulative_return),
            "filter_start_date": start_date,
            "filter_end_date": end_date,
        }

    def latest_account_overview(
        self,
        recent_trade_limit: int = 12,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        account_paths = sorted(self._base_dir.glob("*/account.json"), key=lambda item: item.stat().st_mtime, reverse=True)
        if not account_paths:
            return None
        account_id = account_paths[0].parent.name
        return self.account_overview(account_id, recent_trade_limit=recent_trade_limit, start_date=start_date, end_date=end_date)

    def reset_account(self, account_id: str) -> bool:
        account_dir = self._base_dir / account_id
        if not account_dir.exists():
            return False
        shutil.rmtree(account_dir)
        return True

    def list_accounts(self) -> List[str]:
        return sorted(path.parent.name for path in self._base_dir.glob("*/account.json"))

    def _account_relative_path(self, account_id: str) -> str:
        return f"{account_id}/account.json"

    def _ledger_relative_path(self, account_id: str) -> str:
        return f"{account_id}/ledger.json"

    def _write_account(self, account_state: AccountState) -> str:
        return write_json_artifact(self._base_dir, self._account_relative_path(account_state.account_id), _serialize_account_state(account_state))

    def _write_ledger(self, account_id: str, payload: Dict[str, Any]) -> str:
        return write_json_artifact(self._base_dir, self._ledger_relative_path(account_id), payload)

    def _filter_by_date(
        self,
        rows: List[Dict[str, Any]],
        start_date: Optional[str],
        end_date: Optional[str],
    ) -> List[Dict[str, Any]]:
        filtered = rows
        if start_date:
            filtered = [row for row in filtered if str(row.get("trade_date", "")) >= start_date]
        if end_date:
            filtered = [row for row in filtered if str(row.get("trade_date", "")) <= end_date]
        return filtered

    def _nav_snapshot(
        self,
        account_state: AccountState,
        as_of: datetime,
        trade_date: str,
        starting_cash: Decimal,
        price_map: Mapping[str, Decimal],
    ) -> Dict[str, str]:
        position_value = Decimal("0")
        for position in account_state.positions.values():
            mark_price = price_map.get(position.instrument_id, position.avg_cost)
            position_value += Decimal(position.qty) * mark_price
        nav = (account_state.cash + position_value).quantize(Decimal("0.0001"))
        cumulative_return = Decimal("0")
        if starting_cash != 0:
            cumulative_return = ((nav / starting_cash) - Decimal("1")).quantize(Decimal("0.0001"))
        return {
            "as_of": as_of.isoformat(),
            "trade_date": trade_date,
            "nav": str(nav),
            "cash": str(account_state.cash.quantize(Decimal("0.0001"))),
            "position_value": str(position_value.quantize(Decimal("0.0001"))),
            "cumulative_return": str(cumulative_return),
        }

    def _resolve_starting_cash(
        self,
        account_state: AccountState,
        ledger: Mapping[str, Any],
        trades: List[Dict[str, Any]],
    ) -> Decimal:
        trade_cash_delta = sum((_to_decimal(item.get("cash_delta")) for item in trades), Decimal("0"))
        inferred = (account_state.cash - trade_cash_delta).quantize(Decimal("0.0001"))
        explicit = ledger.get("starting_cash")
        if explicit not in (None, "", "None"):
            explicit_value = _to_decimal(explicit).quantize(Decimal("0.0001"))
            if trades and inferred > 0 and abs(explicit_value - inferred) > Decimal("0.01"):
                return inferred
            return explicit_value
        return inferred
