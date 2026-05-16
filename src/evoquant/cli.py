from __future__ import annotations

import argparse

from evoquant import __version__


def main() -> None:
    parser = argparse.ArgumentParser(description="EvoQuant local command line entry point.")
    parser.add_argument("--version", action="store_true", help="Print the EvoQuant package version.")
    args = parser.parse_args()

    if args.version:
        print(__version__)
        return

    print(
        "EvoQuant skeleton is installed. The API server will be enabled in a later implementation task."
    )
