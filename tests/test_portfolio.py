"""P0.1 tests. All I/O is mocked; no live network."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from market_brief import config, portfolio


def test_watchlist_position_fields_are_optional():
    rows = config._watchlist_entries([
        {"symbol": "1180.SR", "name": "SNB", "market": "tadawul"},
        {"symbol": "TSM", "name": "TSMC", "quantity": 2, "cost_basis": 180,
         "currency": "usd", "account": "broker-a"},
    ])
    assert rows[0]["quantity"] is None
    assert rows[0]["cost_basis"] is None
    assert rows[1]["quantity"] == 2.0
    assert rows[1]["currency"] == "USD"
    assert rows[1]["account"] == "broker-a"


def test_news_only_discards_position_fields():
    row = config._watchlist_entries([{"name": "CIB", "news_only": True,
        "quantity": 100, "cost_basis": 50, "currency": "EGP"}])[0]
    assert row["news_only"] is True
    assert row["quantity"] is None
    assert row["cost_basis"] is None


def test_position_daily_pnl_local_and_base(monkeypatch):
    monkeypatch.setattr(config, "today", lambda: __import__("datetime").date(2026, 8, 15))
    quote = {"symbol": "1180.SR", "name": "SNB", "ok": True,
             "last": 40.0, "prev": 39.0, "currency": "SAR"}
    entry = {"symbol": "1180.SR", "quantity": 10, "cost_basis": 35,
             "currency": "SAR", "account": "local"}
    fx = lambda source, target: {"ok": True, "rate": 0.2666,
        "source": "Yahoo Finance", "as_of": "2026-08-14", "pair": "SAR/USD"}
    p = portfolio.enrich_position(quote, entry, "USD", fx_fetcher=fx)
    assert p["daily_pnl_local"] == 10.0
    assert p["daily_pnl_base"] == 2.67
    text = portfolio.format_position_pnl(p)
    assert "10.00 SAR" in text and "2.67 USD" in text
    assert "Yahoo Finance" in text and "2026-08-14" in text


def test_fx_failure_keeps_local_pnl():
    quote = {"symbol": "X", "ok": True, "last": 11.0, "prev": 10.0, "currency": "GBP"}
    entry = {"symbol": "X", "quantity": 3, "currency": "GBP"}
    fx = lambda *_: {"ok": False, "rate": None, "source": "Yahoo Finance",
                     "as_of": "2026-08-15", "pair": "GBP/USD"}
    p = portfolio.enrich_position(quote, entry, "USD", fx_fetcher=fx)
    assert p["daily_pnl_local"] == 3.0
    assert p["daily_pnl_base"] is None
    assert "conversion unavailable" in portfolio.format_position_pnl(p)


def test_fx_fetch_is_mocked_and_sourced():
    response = MagicMock()
    response.raise_for_status = MagicMock()
    response.json.return_value = {"chart": {"result": [{
        "timestamp": [1786665600],
        "indicators": {"quote": [{"close": [0.2665]}]},
    }]}}
    with patch("market_brief.portfolio.httpx.get", return_value=response) as get:
        fx = portfolio.fetch_fx_rate("SAR", "USD")
    assert fx["ok"] is True
    assert fx["rate"] == 0.2665
    assert fx["source"] == "Yahoo Finance"
    assert get.call_count == 1


@pytest.mark.asyncio
async def test_pipeline_archives_position_free_narrative(monkeypatch):
    from market_brief import brief
    position = {"symbol": "TSM", "name": "TSMC", "quantity": 2.0,
                "cost_basis": 180.0, "currency": "USD", "news_only": False}
    monkeypatch.setattr(config, "MARKET_BRIEF_WATCHLIST", [position])
    monkeypatch.setattr(config, "MARKET_BRIEF_BASE_CURRENCY", "USD")
    monkeypatch.setattr(brief, "scan", lambda: {"prices": [{"symbol": "TSM", "name": "TSMC",
        "ok": True, "last": 201.0, "prev": 200.0, "currency": "USD", "flagged": False}],
        "items": [], "smart_money": []})
    monkeypatch.setattr(portfolio, "fetch_fx_rate", lambda *_: {"ok": True, "rate": 1.0,
        "source": "identity", "as_of": "2026-08-15", "pair": "USD/USD"})
    monkeypatch.setattr(brief, "compose_brief", AsyncMock(return_value=("*📊 Market brief*\nquiet", False)))
    archived = []
    monkeypatch.setattr(brief, "archive_brief", lambda text: archived.append(text))
    sender = MagicMock()
    sender.send = AsyncMock()
    delivered = await portfolio.run_scan_and_notify(sender=sender, claude_runner=None)
    assert "Portfolio P&L" in delivered
    assert "2.00 USD" in delivered
    assert archived == ["*📊 Market brief*\nquiet"]
    assert "2.0" not in archived[0] and "180" not in archived[0]
