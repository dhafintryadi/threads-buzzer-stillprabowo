"""CLI scraper: python main.py {auth,status,discovery,filter,engagement,accounts,profiles,feeds,build,all}."""

from __future__ import annotations

import argparse
import asyncio
import sys

from pipeline import run_stage, run_all, STAGES
from modules.auth import interactive_login
from modules import status as status_module


def main() -> None:
    parser = argparse.ArgumentParser(description="Threads #StillPrabowo scraper")
    parser.add_argument(
        "command",
        choices=["auth", "status", *STAGES, "all"],
        help="Tahap yang ingin dijalankan",
    )
    args = parser.parse_args()

    if args.command == "auth":
        asyncio.run(interactive_login())
    elif args.command == "status":
        status_module.run()
    elif args.command == "all":
        asyncio.run(run_all())
    else:
        asyncio.run(run_stage(args.command))


if __name__ == "__main__":
    sys.exit(main())
