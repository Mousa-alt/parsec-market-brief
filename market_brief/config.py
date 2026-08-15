"""Configuration — a single YAML file, read once at import.

Everything the pipeline needs is a module-level constant here, so the rest of
the package never touches the filesystem to answer "what is on the watchlist".
A malformed section degrades to a safe default and never raises at import time.
"""

import logging
import os
import re
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR: Path = Path(os.environ.get("MARKET_BRIEF_DATA_DIR") or (PROJECT_ROOT / "data")).resolve()


def _resolve_config_path() -> Path | None:
    env = os.environ.get("MARKET_BRIEF_CONFIG")
    if env:
        path = Path(env).expanduser()
        if not path.is_absolute():
            path = (PROJECT_ROOT / path).resolve()
        if path.exists():
            return path
        logger.warning("MARKET_BRIEF_CONFIG=%s does not exist", env)
    for name in ("config.yaml", "config.example.yaml"):
        candidate = PROJECT_ROOT / name
        if candidate.exists():
            if name.endswith(".example.yaml"):
                logger.warning("No config.yaml found — falling back to config.example.yaml. Copy it to config.yaml and edit before relying on the output.")
            return candidate
    return None


CONFIG_PATH: Path | None = _resolve_config_path()


def _load_yaml(path: Path | None) -> dict:
    if not path:
        logger.warning("No config file found; running on built-in defaults")
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        logger.exception("Could not read %s; running on built-in defaults", path)
        return {}
    if not isinstance(data, dict):
        logger.warning("%s does not contain a YAML mapping; ignoring it", path)
        return {}
    return data


_cfg = _load_yaml(CONFIG_PATH)


def _parse_hhmm(value, default: str = "08:00") -> str:
    s = str(value).strip()
    if ":" not in s:
        logger.warning("Invalid HH:MM config value %r; using %r", value, default)
        return default
    return s


def _trigger_list(raw, label: str) -> list[str]:
    if isinstance(raw, str):
        raw = [raw]
    out: list[str] = []
    if isinstance(raw, (list, tuple)):
        out = [t.strip().casefold() for t in raw if isinstance(t, str) and t.strip()]
    if raw and not out:
        logger.warning("%s ignored — expected a list of strings, got %r", label, raw)
    return out


def _optional_float(value, field: str, label: str):
    if value is None or value == "":
        return None
    try:
        number = float(value)
        if number < 0:
            raise ValueError
        return number
    except (TypeError, ValueError):
        logger.warning("%s: invalid %s %r; ignoring position field", label, field, value)
        return None


def _watchlist_entries(raw, label: str = "market_brief.watchlist") -> list[dict]:
    """Normalise watchlist rows while preserving optional P0.1 position data."""
    out: list[dict] = []
    if not isinstance(raw, (list, tuple)):
        if raw:
            logger.warning("%s ignored — expected a list of dicts, got %r", label, raw)
        return out
    for entry in raw:
        if not isinstance(entry, dict):
            logger.warning("%s: skipping non-dict entry %r", label, entry)
            continue
        symbol = str(entry.get("symbol", "")).strip()
        name = str(entry.get("name", "")).strip()
        if not symbol and not name:
            logger.warning("%s: skipping entry with no symbol and no name: %r", label, entry)
            continue
        aliases = entry.get("aliases", [])
        if isinstance(aliases, str):
            aliases = [aliases]
        news_only = bool(entry.get("news_only", False)) or not symbol
        row = {
            "symbol": symbol,
            "name": name or symbol,
            "aliases": [str(a).strip() for a in aliases if str(a).strip()],
            "market": str(entry.get("market", "")).strip(),
            "watch_only": bool(entry.get("watch_only", False)),
            "news_only": news_only,
            "quantity": _optional_float(entry.get("quantity"), "quantity", label),
            "cost_basis": _optional_float(entry.get("cost_basis"), "cost_basis", label),
            "currency": str(entry.get("currency", "")).strip().upper(),
            "account": str(entry.get("account", "")).strip(),
        }
        if news_only:
            row.update({"quantity": None, "cost_basis": None, "currency": "", "account": ""})
        out.append(row)
    return out


def _tracker_entries(raw, label: str = "market_brief.trackers") -> list[dict]:
    out: list[dict] = []
    if not isinstance(raw, (list, tuple)):
        if raw:
            logger.warning("%s ignored — expected a list of dicts, got %r", label, raw)
        return out
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        cik = re.sub(r"\D", "", str(entry.get("cik", "")))
        if not cik:
            logger.warning("%s: skipping tracker without a CIK: %r", label, entry)
            continue
        out.append({"name": str(entry.get("name", "")).strip() or f"CIK {cik}", "cik": cik.zfill(10)})
    return out


_DEFAULT_TIMEZONE = "Africa/Cairo"
TIMEZONE: str = str(_cfg.get("timezone", _DEFAULT_TIMEZONE)).strip() or _DEFAULT_TIMEZONE


def now():
    from datetime import datetime
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
    for name in (TIMEZONE, _DEFAULT_TIMEZONE):
        try:
            return datetime.now(ZoneInfo(name))
        except (ZoneInfoNotFoundError, KeyError, ValueError):
            logger.error("Timezone %r unavailable (is the `tzdata` package installed?)", name)
    return datetime.now().astimezone()


def today():
    return now().date()


_market_cfg = _cfg.get("market_brief", {})
if not isinstance(_market_cfg, dict):
    logger.warning("market_brief section is not a mapping; ignoring it")
    _market_cfg = {}

MARKET_BRIEF_ENABLED: bool = bool(_market_cfg.get("enabled", False))
MARKET_BRIEF_SCHEDULE_TIME: str = _parse_hhmm(_market_cfg.get("schedule_time", "08:00"), "08:00")
MARKET_BRIEF_WATCHLIST: list[dict] = _watchlist_entries(_market_cfg.get("watchlist", []))
MARKET_BRIEF_BASE_CURRENCY: str = str(_market_cfg.get("base_currency", "USD")).strip().upper() or "USD"
MARKET_BRIEF_MACRO_KEYWORDS: list[str] = _trigger_list(_market_cfg.get("macro_keywords", []), "market_brief.macro_keywords")
MARKET_BRIEF_MAX_ITEMS: int = int(_market_cfg.get("max_items", 25))
MARKET_BRIEF_TRACKERS: list[dict] = _tracker_entries(_market_cfg.get("trackers", []))
MARKET_BRIEF_SEC_CONTACT: str = str(_market_cfg.get("sec_contact", "market-brief@example.com")).strip() or "market-brief@example.com"
COMPOSE_MODEL: str = str(_market_cfg.get("compose_model", "claude-sonnet-4-6")).strip() or "claude-sonnet-4-6"

_delivery_cfg = _cfg.get("delivery", {})
if not isinstance(_delivery_cfg, dict):
    logger.warning("delivery section is not a mapping; ignoring it")
    _delivery_cfg = {}
DELIVERY_BACKEND: str = str(_delivery_cfg.get("backend", "console")).strip() or "console"
DELIVERY_OPTIONS: dict = {k: v for k, v in _delivery_cfg.items() if k != "backend"}
