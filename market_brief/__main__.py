"""CLI: ``python -m market_brief --once``."""

import argparse
import asyncio
import logging
import sys

from . import config, portfolio


def _configure_logging(verbose: bool):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    logging.basicConfig(
        level=logging.INFO if verbose else logging.WARNING,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        stream=sys.stderr,
    )


def _parse_args(argv=None):
    parser = argparse.ArgumentParser(
        prog="python -m market_brief",
        description="Daily pre-market portfolio monitor. Monitoring only — this tool never emits buy/sell calls or price targets.",
    )
    parser.add_argument("--once", action="store_true", help="Run the pipeline once and print the brief (default).")
    parser.add_argument("--no-compose", action="store_true", help="Skip the narrative composer and print the static digest.")
    parser.add_argument("--verbose", "-v", action="store_true", help="Log every feed, quote, and fallback to stderr.")
    return parser.parse_args(argv)


async def _run(args) -> int:
    runner = None
    if not args.no_compose:
        from . import claude
        runner = claude.get_runner()
    text = await portfolio.run_scan_and_notify(claude_runner=runner)
    if not text:
        print("Nothing to report today.")
    return 0


def main(argv=None) -> int:
    args = _parse_args(argv)
    _configure_logging(args.verbose)
    if not config.MARKET_BRIEF_WATCHLIST:
        print("Watchlist is empty — nothing to monitor.\nCopy config.example.yaml to config.yaml and add the instruments you want watched.", file=sys.stderr)
        return 2
    try:
        return asyncio.run(_run(args))
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
