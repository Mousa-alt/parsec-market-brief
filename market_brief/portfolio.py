"""P0.1 portfolio model: optional positions, sourced FX, and daily P&L.

Position metadata remains local to config/runtime. The persisted brief archive
receives the position-free narrative; the delivered brief may include P&L.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

import httpx

from . import config

logger = logging.getLogger(__name__)
SUPPORTED_CURRENCIES = {"SAR", "EGP", "USD", "GBP"}
FX_SOURCE = "Yahoo Finance"
FX_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range=5d&interval=1d"
HTTP_TIMEOUT = 15


def parse_position(entry: dict) -> dict:
    out = dict(entry)
    for key in ("quantity", "cost_basis"):
        value = entry.get(key)
        try:
            out[key] = float(value) if value is not None else None
        except (TypeError, ValueError):
            logger.warning("Invalid %s for %s; ignoring", key, entry.get("symbol") or entry.get("name"))
            out[key] = None
    out["currency"] = str(entry.get("currency", "")).strip().upper()
    out["account"] = str(entry.get("account", "")).strip()
    return out


def has_position(entry: dict) -> bool:
    return not entry.get("news_only") and isinstance(entry.get("quantity"), (int, float)) and entry["quantity"] > 0


def fetch_fx_rate(source: str, target: str) -> dict:
    """Fetch an explicit FX close. Failure never falls back to an assumed rate."""
    source, target = source.upper(), target.upper()
    as_of = datetime.now(timezone.utc).date().isoformat()
    if source == target:
        return {"ok": True, "rate": 1.0, "source": "identity", "as_of": as_of, "pair": f"{source}/{target}"}
    if source not in SUPPORTED_CURRENCIES or target not in SUPPORTED_CURRENCIES:
        return {"ok": False, "rate": None, "source": FX_SOURCE, "as_of": as_of, "pair": f"{source}/{target}"}
    symbol = f"{source}{target}=X"
    try:
        response = httpx.get(FX_URL.format(symbol=symbol), timeout=HTTP_TIMEOUT, follow_redirects=True)
        response.raise_for_status()
        result = (((response.json().get("chart") or {}).get("result") or [None])[0])
        if not result:
            raise ValueError("no FX chart result")
        closes = ((((result.get("indicators") or {}).get("quote") or [{}])[0]).get("close") or [])
        closes = [x for x in closes if isinstance(x, (int, float))]
        if not closes:
            raise ValueError("no FX close")
        timestamps = result.get("timestamp") or []
        if timestamps:
            as_of = datetime.fromtimestamp(timestamps[-1], timezone.utc).date().isoformat()
        return {"ok": True, "rate": float(closes[-1]), "source": FX_SOURCE, "as_of": as_of, "pair": f"{source}/{target}"}
    except Exception as exc:
        logger.warning("FX %s/%s unavailable: %s", source, target, exc)
        return {"ok": False, "rate": None, "source": FX_SOURCE, "as_of": as_of, "pair": f"{source}/{target}"}


def enrich_position(quote: dict, entry: dict, base_currency: str, fx_fetcher=fetch_fx_rate) -> dict:
    out = dict(quote)
    position = parse_position(entry)
    if not has_position(position) or not quote.get("ok"):
        return out
    local_currency = position.get("currency") or str(quote.get("currency", "")).upper()
    daily_local = (quote["last"] - quote["prev"]) * position["quantity"]
    out.update({
        "quantity": position["quantity"], "cost_basis": position.get("cost_basis"),
        "position_currency": local_currency, "account": position.get("account", ""),
        "daily_pnl_local": round(daily_local, 2), "daily_pnl_base": None,
        "base_currency": base_currency, "fx": None,
        "price_source": "Yahoo Finance closes", "price_as_of": config.today().isoformat(),
    })
    fx = fx_fetcher(local_currency, base_currency)
    out["fx"] = fx
    if fx.get("ok"):
        out["daily_pnl_base"] = round(daily_local * fx["rate"], 2)
    return out


def format_position_pnl(position: dict) -> str:
    if position.get("daily_pnl_local") is None:
        return ""
    local, base = position.get("position_currency", ""), position.get("base_currency", "")
    source = f"{position.get('price_source', 'Yahoo Finance closes')}, as of {position.get('price_as_of', 'unknown')}"
    text = f"daily P&L {position['daily_pnl_local']:+.2f} {local} [{source}]"
    if local == base:
        return text
    fx = position.get("fx") or {}
    if position.get("daily_pnl_base") is None:
        return text + f"; {base} conversion unavailable [{fx.get('source', FX_SOURCE)}, as of {fx.get('as_of', 'unknown')}]"
    return text + (f"; {position['daily_pnl_base']:+.2f} {base} [FX {fx.get('pair')} "
                   f"{fx.get('rate'):.6g}, {fx.get('source')}, as of {fx.get('as_of')}]" )


def enrich_prices(prices: list[dict], watchlist: list[dict], base_currency: str) -> list[dict]:
    by_symbol = {str(e.get("symbol", "")): e for e in watchlist}
    return [enrich_position(p, by_symbol.get(str(p.get("symbol", "")), {}), base_currency) for p in prices]


def portfolio_lines(prices: list[dict]) -> list[str]:
    lines = []
    for p in prices:
        rendered = format_position_pnl(p)
        if rendered:
            lines.append(f"- {p.get('name') or p.get('symbol')}: {rendered}")
    return lines


async def run_scan_and_notify(sender=None, claude_runner=None) -> str:
    """Run the existing monitor, adding P0.1 P&L only to the delivered output.

    The archived copy intentionally excludes position-derived values. A dead FX
    source removes only base-currency conversion; the local-currency P&L stays.
    """
    from . import brief, senders
    if sender is None:
        sender = senders.get_sender(config.DELIVERY_BACKEND, **config.DELIVERY_OPTIONS)
    data = await asyncio.to_thread(brief.scan)
    prices = enrich_prices(data["prices"], config.MARKET_BRIEF_WATCHLIST, config.MARKET_BRIEF_BASE_CURRENCY)
    items, smart = data["items"], data.get("smart_money") or []
    if not prices and not items and not smart:
        return ""
    # Compose from market facts only: quantity/cost basis never enter the model prompt.
    clean_prices = [{k: v for k, v in p.items() if k not in {
        "quantity", "cost_basis", "position_currency", "account", "daily_pnl_local",
        "daily_pnl_base", "base_currency", "fx", "price_source", "price_as_of"
    }} for p in prices]
    narrative, _ = await brief.compose_brief(clean_prices, items, claude_runner, smart_money=smart)
    lines = portfolio_lines(prices)
    delivered = narrative
    if lines:
        delivered = narrative + "\n\n*Portfolio P&L*\n" + "\n".join(lines)
    try:
        await sender.send(delivered, "market brief")
    except Exception as exc:
        logger.warning("Market brief: delivery failed: %s", exc)
    # Local archive remains useful for novelty while carrying no position data.
    brief.archive_brief(narrative)
    return delivered
