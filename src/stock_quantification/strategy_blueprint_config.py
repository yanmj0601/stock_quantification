from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Mapping


CONFIG_PATH = Path(__file__).with_name("strategy_blueprints.json")


@lru_cache(maxsize=1)
def load_strategy_blueprint_specs() -> Dict[str, Dict[str, Any]]:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def load_strategy_blueprint_spec(strategy_id: str) -> Mapping[str, Any]:
    specs = load_strategy_blueprint_specs()
    try:
        return specs[strategy_id]
    except KeyError as exc:
        raise KeyError(f"Unknown strategy blueprint spec: {strategy_id}") from exc
