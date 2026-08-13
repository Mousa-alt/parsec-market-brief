"""CLI: ``python -m market_brief --once``.

One run, one brief, printed to the console. That is the whole surface — there
is no daemon here on purpose: scheduling belongs to cron, systemd timers, or
whatever the deployment already uses, and a monitor that cannot be run by hand
cannot be trusted.
"""

import argparse
import asyncio
import logging
import sys

from . import brief, config


def _configure_logging(verbose: bool):
    # Log messages carry em-dashes and quoted feed titles, and a Windows
    # console defaults to cp1252 — without this, a log line about a failure
    # becomes its own UnicodeEncodeError. stdout is handled in ConsoleSender.
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass  # already wrapped or not reconfigurable (captured/piped stderr)

    logging.basicConfig(
        level=logging.INFO if verbose else logging.WARNING,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        stream=sys.stderr,
    )


def _parse_args(argv=None):
    parser = argparse.ArgumentParser(
        prog="python -m market_brief",
        description="Daily pre-market watchlist monitor. Monitoring only — "
                    "this tool never emits buy/sell calls or price targets.",
    )
    parser.add_argument(
        "--once", action="store_true",
        help="Run the pipeline once and print the brief (default).",
    )
    parser.add_argument(
        "--no-compose", action="store_true",
        help="Skip the narrative composer and print the static digest.",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Log every feed, quote, and fallback to stderr.",
    )
    return parser.parse_args(argv)


async def _run(args) -> int:
    runner = None
    if not args.no_compose:
        from . import claude
        runner = claude.get_runner()

    text = await brief.run_scan_and_notify(claude_runner=runner)
    if not text:
        print("Nothing to report today.")
    return 0


def main(argv=None) -> int:
    args = _parse_args(argv)
    _configure_logging(args.verbose)

    if not config.MARKET_BRIEF_WATCHLIST:
        print(
            "Watchlist is empty — nothing to monitor.\n"
            "Copy config.example.yaml to config.yaml and add the instruments "
            "you want watched.",
            file=sys.stderr,
        )
        return 2

    try:
        return asyncio.run(_run(args))
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
