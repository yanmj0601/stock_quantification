"""在不连接 PostgreSQL 或行情源的情况下导出 API 契约。"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def build_schema() -> dict:
    from evoquant.api import create_app
    app = create_app()
    return app.openapi()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    target = ROOT / "docs" / "openapi.json"
    content = json.dumps(build_schema(), ensure_ascii=False, indent=2) + "\n"
    if args.check:
        if not target.exists() or target.read_text() != content:
            raise SystemExit("docs/openapi.json is stale; run python tools/export_openapi.py")
        print("OpenAPI snapshot matches registered routes and request models")
    else:
        target.write_text(content)
        print(target)


if __name__ == "__main__":
    main()
