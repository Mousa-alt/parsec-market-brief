# Source evaluation — what we tested, what survived

> Hand-tested August 2026 by automated research agents with live fetches (not doc-reading).
> Verdict scale: **USE** (in product) · viable-backup · dead/blocked/paid.

## Saudi market (Tadawul) — ~21 candidates tested

| Source | Result | Verdict |
|---|---|---|
| Argaam EN main-news RSS | Valid feed, live items same-day | **USE** |
| Argaam EN company-disclosures RSS | Valid feed, disclosure-grade items | **USE** |
| Google News RSS (AR, Saudi edition) | 50+ items/day, aggregates Argaam/Reuters/Asharq | **USE** |
| Yahoo `.SR` quotes | Live, delayed — fine for daily marks | **USE** (prices) |
| saudiexchange.sa (official) | WAF-blocked to every automated fetch, no RSS exists | dead for bots |
| Argaam sitemaps / /rss index page | Returns HTML masquerading as feeds | trap, skip |
| SAHMK API | Licensed, free tier 100 req/day, delayed, no news | backup (prices) |
| Mubasher, Zawya, Asharq Business, SPA, Al Eqtisadiah RSS | 403/404/dead endpoints | skip |
| Finnhub, TwelveData, EODHD, FMP, Alpha Vantage, marketaux | Free tiers exclude Tadawul or cap at toy limits | skip |

## Egypt market (EGX) — ~24 candidates tested

| Source | Result | Verdict |
|---|---|---|
| EnterpriseAM feed | Full-text RSS, live, survives site paywall | **USE** |
| Google News RSS (AR + EN, Egypt editions) | 30–50 items per query, catches bot-blocked outlets | **USE** |
| Yahoo quotes via ISIN symbols | Works — but `FWRY.CA` is a WRONG instrument; the equity is `EGS745L1C014.CA` (EGX Yahoo symbols are ISIN-based) | **USE** (prices, with care) |
| Daily News Egypt, Amwal Al Ghad, Al Borsa RSS | Valid feeds | backups |
| egx.com.eg (official, incl. bulletins) | F5 WAF rejects datacenter IPs entirely | dead for bots |
| Mubasher EG, Ahram, Zawya, Investing.com, egx.news, Hapi | 403/404 | skip |
| EODHD (20 req/day, no news), TwelveData (paid), Finnhub (absent) | Free tiers useless for EGX | skip |
| marketaux (`exchange=EGX`, 242 entities) | Works but 3 articles/request | optional 4th |

## Global / US — ~10 candidates tested

| Source | Result | Verdict |
|---|---|---|
| Yahoo per-ticker news feeds | Live for US tickers | **USE** |
| Yahoo chart endpoint (quotes) | Live, all markets | **USE** (prices) |
| Google News RSS (policy/macro query) | Live | **USE** |
| SEC EDGAR submissions + filings API | Free, official, User-Agent required — verified live | **USE** (13F) |
| Finnhub free | Good but US-only | backup |
| NewsAPI.org | 24h-delayed, production forbidden | skip |
| Tiingo, Polygon | News paywalled / rebranded | skip |

**Net: 9 sources in production (8 feeds + SEC EDGAR), everything else documented above so nobody re-tests dead ends.**
