from __future__ import annotations

import json
import sys

from stock_quantification.broker import BrokerError, build_broker_adapter


def main() -> int:
    try:
        adapter = build_broker_adapter("ALPACA_PAPER")
        account_state = adapter.sync_account_state()
    except BrokerError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    output = {
        "broker": "ALPACA_PAPER",
        "account_id": account_state.account_id,
        "market": account_state.market.value,
        "cash": str(account_state.cash),
        "buying_power": str(account_state.buying_power),
        "position_count": len(account_state.positions),
        "positions": [
            {
                "instrument_id": position.instrument_id,
                "qty": position.qty,
                "avg_cost": str(position.avg_cost),
            }
            for position in sorted(account_state.positions.values(), key=lambda item: item.instrument_id)
        ],
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
