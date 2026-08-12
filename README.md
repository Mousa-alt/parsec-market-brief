# parsec-market-brief

A daily pre-market monitor for a fixed watchlist spanning Tadawul (Saudi), EGX
(Egypt), US, and UK-listed instruments. Once a day it fetches close prices,
sweeps Arabic and English news feeds, checks SEC EDGAR for new institutional
13F filings, and prints one short brief: **what moved, what changed, what to
ignore.**

It is a monitoring tool. It does not produce signals, and that is a design
constraint rather than a missing feature — see [Guardrails](#guardrails).

---

## Why it exists

Watching four markets across three languages and two alphabets is a daily
half-hour of tab-flipping, and the failure mode is not missing a headline —
it is reading forty and retaining none. This collapses that into one screen:
only the names you actually hold or watch, only the moves past a threshold
that matters for that instrument, only the headlines that name something on
the list, and nothing you were already shown this fortnight.

The hard part is not fetching. It is **suppression** — the layers below exist
to keep a quiet day looking quiet.

---

## Architecture

```
                     ┌─────────────────────────────────────────┐
                     │              config.yaml                │
                     │   watchlist · macro keywords · trackers │
                     └────────────────────┬────────────────────┘
                                          │
              ┌───────────────────────────┼───────────────────────────┐
              │                           │                           │
       ┌──────▼───────┐          ┌────────▼────────┐         ┌────────▼────────┐
       │  PRICE LAYER │          │   NEWS LAYER    │         │  SMART MONEY    │
       │              │          │                 │         │                 │
       │ Yahoo chart  │          │ 9 RSS/Atom feeds│         │ SEC EDGAR 13F   │
       │ last vs prev │          │ Argaam · Google │         │ quarterly, and  │
       │ close        │          │ News · Yahoo ·  │         │ silent on ~99%  │
       │              │          │ EnterpriseAM    │         │ of days         │
       │ EGX fallback:│          │                 │         │                 │
       │ single bar → │          │ require_xml     │         │ parse info table│
       │ read meta    │          │ guard rejects   │         │ diff vs stored  │
       │ marks        │          │ HTML-at-200     │         │ quarter         │
       └──────┬───────┘          └────────┬────────┘         └────────┬────────┘
              │                           │                           │
              │                  ┌────────▼────────┐                  │
              │                  │  DEDUPE (14d)   │                  │
              │                  │  url hash → TTL │                  │
              │                  └────────┬────────┘                  │
              │                           │                           │
              │                  ┌────────▼────────┐                  │
              │                  │  ENTITY FILTER  │                  │
              │                  │ whole-token     │                  │
              │                  │ match, AR + EN  │                  │
              │                  │ rank: disclosure│                  │
              │                  │ > ticker > macro│                  │
              │                  └────────┬────────┘                  │
              │                           │                           │
              └───────────────┬───────────┴───────────────────────────┘
                              │
                    ┌─────────▼──────────┐
                    │    COMPOSE         │
                    │                    │
                    │  claude CLI?  ──── yes ──▶ narrative brief
                    │       │                     │
                    │       no                    ▼
                    │       │              header check: does it
                    │       │              start with "*📊"?
                    │       │                     │
                    │       │              no ────┘
                    │       ▼              │
                    │  STATIC DIGEST ◀─────┘
                    │  (plain data dump) │
                    └─────────┬──────────┘
                              │
                    ┌─────────▼──────────┐
                    │      SENDER        │
                    │ ConsoleSender      │  ← default
                    │ WhatsAppSender     │  ← documented stub
                    └─────────┬──────────┘
                              │
                    ┌─────────▼──────────┐
                    │  ARCHIVE           │
                    │  data/briefs/*.md  │──┐
                    └────────────────────┘  │
                              ▲             │
                              └─────────────┘
                        last 3 briefs feed back into
                        the prompt — kills the story
                        that resurfaces under a new
                        headline (URL hashing can't)
```

Every stage degrades instead of failing. One dead feed loses one source; a bad
symbol loses one quote and prints `price unavailable`; a dead SEC endpoint
means "nothing new"; a missing model loses the prose but never the data.

---

## Quickstart

```bash
pip install -r requirements.txt
cp config.example.yaml config.yaml     # then edit the watchlist
python -m market_brief --once
```

That prints today's brief to the console and exits. There is no daemon on
purpose — scheduling belongs to cron or a systemd timer, and a monitor you
cannot run by hand is a monitor you cannot trust.

| Flag | Effect |
|---|---|
| `--once` | Run the pipeline once and print the brief (the default). |
| `--no-compose` | Skip the narrative composer; print the static digest. |
| `--verbose` / `-v` | Log every feed, quote, and fallback to stderr. |

Tests:

```bash
pytest          # 98 tests, no network — every fetch is mocked
```

### Configuration

`config.yaml` is the only input. If it is absent, `config.example.yaml` is read
instead (with a warning) so a fresh clone runs before it is configured.

A watchlist entry is either **priced** (has a `symbol`, gets a daily quote and
can be flagged as a mover) or **news-only** (has a `name` and aliases, is
matched in headlines, and is never quoted). News-only exists because EGX
symbols on Yahoo are ISIN-based and easy to get wrong, and **a wrong symbol is
worse than no symbol** — it prints a confident number for a different
instrument.

Environment overrides: `MARKET_BRIEF_CONFIG` (config path),
`MARKET_BRIEF_DATA_DIR` (state directory).

---

## Guardrails

The philosophy is **monitoring, not signals**. The tool reports what the market
did and what was published about it. It never says what to do about any of it.

This is enforced in four places, not one:

1. **The compose prompt** forbids buy/sell/hold calls in any wording, price
   targets, fair values, entry/exit levels, forecasts, and conviction language
   ("attractive", "cheap", "overvalued"). Every claim must attribute to a price
   move or a headline; if an item cannot be written without a recommendation,
   it is dropped.

2. **A positive header check** on the model's output. Blocklisting error text
   is leaky — a runner's failure modes return plain prose with assorted
   prefixes, and any of them would otherwise ship *as the brief*. So output is
   accepted **only** if it is shaped like the brief the prompt mandates, and
   anything else falls through to the static digest.

3. **The static digest** — the real output, and what you get with no model
   installed — is a plain data dump with no interpretation in it at all. It
   cannot drift into advice because it never writes a sentence.

4. **13F framing.** A 13F is a backward-looking regulatory disclosure of what a
   manager held at a past quarter end, published up to 45 days late. Every line
   is rendered in past tense as a filed fact ("disclosed", "no longer listed"),
   never as a move to mirror. A test asserts the rendered output contains no
   advice-flavoured verb.

The ordering matters: a model that cannot be reached costs you prose, never
correctness, and never an unreviewed sentence about money.

---

## Layout

```
market_brief/
  brief.py         pipeline: scan → compose → deliver, plus the prompt
  smart_money.py   SEC EDGAR 13F watcher (isolated; cannot sink the brief)
  config.py        config.yaml loader + watchlist/tracker normalisation
  senders.py       ConsoleSender (default) · WhatsAppSender (stub)
  claude.py        optional narrative composer via the `claude` CLI
  __main__.py      the CLI
tests/             98 tests, fully mocked
docs/
  partner-brief.pdf
```

Dependencies are `httpx`, `PyYAML`, and `tzdata`. There is no market-data SDK,
no broker integration, and no database.

---

## Notes for whoever runs this next

- **All dates are market-local**, not server-local (`timezone:` in config). On
  a UTC host the date would otherwise roll at 22:00 local and the dedupe window
  would compare against tomorrow.
- **`tzdata` is a real dependency**, not padding: `zoneinfo` ships no bundled
  IANA database, so Windows hosts and slim containers have none.
- **The Argaam feeds answer a bad path with HTML at HTTP 200**, not an error.
  Those two feeds assert their content-type before parsing; without that the
  disclosure feed would fail silently and look like a transient outage.
- **Matching is whole-token, not substring.** The watchlist carries names like
  `stc`, `SNB`, and `9404` that occur inside ordinary words and numbers, and
  every false positive costs a slot in a capped brief. Arabic terms also match
  with the attached definite article, because the press writes `الأسمدة` and
  never the bare `أسمدة`.
- **The seen-set has a 14-day TTL**, so a headline cannot resurface for a
  fortnight but nothing is blocklisted permanently.
- **`WhatsAppSender` is a deliberate stub.** The gateway is deployment-specific
  and shipping a half-configured one invites sending a brief to the wrong
  number. The HTTP contract is documented in its docstring; secrets belong in
  the environment, never in `config.yaml`.

---

All rights reserved © 2026 ParSec / Omar Mosallam. Proprietary — see `LICENSE`.
Not investment advice.
