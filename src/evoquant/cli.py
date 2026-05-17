from __future__ import annotations

import argparse

from evoquant import __version__


def main() -> None:
    import uvicorn

    parser = argparse.ArgumentParser(description="EvoQuant local command line entry point.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--version", action="store_true", help="Print the EvoQuant package version.")
    args = parser.parse_args()

    if args.version:
        print(__version__)
        return

    uvicorn.run("evoquant.api:app", host=args.host, port=args.port, reload=False)
