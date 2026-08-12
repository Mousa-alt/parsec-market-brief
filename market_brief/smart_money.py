"""Smart money — SEC EDGAR 13F-HR watcher for the daily market brief.

Institutional managers disclose their US equity book quarterly on Form 13F-HR.
This watches a small list of CIKs (Berkshire by default), notices when a NEW
filing appears, and extracts the top positions plus the biggest adds and exits
against the previous quarter's parse.

Cadence is quarterly, so on ~99% of days this returns nothing and costs one
cached JSON request per tracker. It is wired into the brief as a strictly
optional section: every entry point is try/excepted and a failure here can
never delay, shrink, or crash the daily brief.

REPORTING ONLY. A 13F is a stale, backward-looking regulatory disclosure — it
says what a manager HELD at quarter end, up to 45 days ago. Everything here is
phrased as a disclosure ("filed", "disclosed", "reported"), never as an action
to copy. See the compose guardrail in brief.py.
"""

import json
import logging
import re
import xml.etree.ElementTree as ET
from datetime import date, timedelta

import httpx

from . import config

logger = logging.getLogger(__name__)

# Persistent tracker state: {cik: {accession, filing_date, positions}}. Unlike
# the headline seen-set this is not a TTL cache — the previous quarter's
# positions ARE the diff baseline, so entries are replaced, never expired.
_STATE_FILE = config.DATA_DIR / "smart_money_seen.json"

# SEC requires a declared User-Agent with a contact address on every request
# and blocks generic clients outright. Rate limit is 10 req/s; this module
# makes at most 3 requests per tracker per quarter.
_SEC_UA_TEMPLATE = "parsec-market-brief {contact}"

_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
_ARCHIVE_DIR_URL = "https://www.sec.gov/Archives/edgar/data/{cik_int}/{accession_nodash}"
_FILING_INDEX_URL = _ARCHIVE_DIR_URL + "/{accession}-index.htm"

_HTTP_TIMEOUT = 20

#: How many positions to surface per filing.
_TOP_N = 10
#: How many adds/exits to surface per filing.
_MOVES_N = 3

# First run has no baseline, so the "latest" filing on file could be three
# months old. Reporting that as new would be a lie, and silently swallowing it
# would leave the feature looking dead for a quarter. Compromise: report it
# only if it is genuinely recent, otherwise record the baseline quietly and
# wait for the next filing.
_FIRST_RUN_MAX_AGE_DAYS = 14


def _sec_headers() -> dict:
    return {
        "User-Agent": _SEC_UA_TEMPLATE.format(contact=config.MARKET_BRIEF_SEC_CONTACT),
        "Accept": "application/json, text/xml, */*",
        "Accept-Encoding": "gzip, deflate",
    }


def _load_state() -> dict:
    """Load {cik: {...}} tracker state. Corrupt/missing file → start fresh."""
    if not _STATE_FILE.exists():
        return {}
    try:
        data = json.loads(_STATE_FILE.read_text(encoding="utf-8"))
        trackers = data.get("trackers", {})
        return trackers if isinstance(trackers, dict) else {}
    except Exception:
        return {}


def _save_state(state: dict):
    _STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    _STATE_FILE.write_text(
        json.dumps({"trackers": state, "updated": config.now().isoformat()},
                   indent=2),
        encoding="utf-8",
    )


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]  # drop XML namespace


def _pad_cik(cik) -> str:
    """EDGAR's submissions endpoint wants the zero-padded 10-digit CIK."""
    digits = re.sub(r"\D", "", str(cik or ""))
    return digits.zfill(10) if digits else ""


def _get(url: str):
    return httpx.get(
        url,
        timeout=_HTTP_TIMEOUT,
        follow_redirects=True,
        headers=_sec_headers(),
    )


def latest_13f(submissions: dict) -> dict | None:
    """Pull the most recent 13F-HR out of an EDGAR submissions payload.

    EDGAR ships the recent-filings block as parallel arrays, newest first.
    Amendments (13F-HR/A) count: a restated book is news too.
    """
    recent = ((submissions.get("filings") or {}).get("recent") or {})
    forms = recent.get("form") or []
    accessions = recent.get("accessionNumber") or []
    dates = recent.get("filingDate") or []
    if not (forms and accessions):
        return None

    for i, form in enumerate(forms):
        if not str(form).upper().startswith("13F-HR"):
            continue
        if i >= len(accessions):
            break
        accession = str(accessions[i])
        return {
            "form": str(form),
            "accession": accession,
            "accession_nodash": accession.replace("-", ""),
            "filing_date": str(dates[i]) if i < len(dates) else "",
        }
    return None


def _filing_url(cik: str, filing: dict) -> str:
    """Human-openable EDGAR index page for a filing."""
    return _FILING_INDEX_URL.format(
        cik_int=int(cik),
        accession_nodash=filing["accession_nodash"],
        accession=filing["accession"],
    )


def _information_table_url(cik: str, filing: dict) -> str:
    """Locate the information-table XML inside a filing's archive directory.

    The file name is not stable across filers or agents, so the directory
    listing is read and the table picked by name. primary_doc.xml is the cover
    page (fund name, totals) — never the holdings — so it is excluded
    explicitly rather than by ordering luck.
    """
    base = _ARCHIVE_DIR_URL.format(
        cik_int=int(cik), accession_nodash=filing["accession_nodash"]
    )
    resp = _get(f"{base}/index.json")
    resp.raise_for_status()
    items = ((resp.json().get("directory") or {}).get("item") or [])
    names = [str(i.get("name", "")) for i in items]
    xmls = [n for n in names
            if n.lower().endswith(".xml") and n.lower() != "primary_doc.xml"]
    if not xmls:
        return ""
    preferred = [n for n in xmls
                 if any(k in n.lower() for k in ("infotable", "informationtable", "table"))]
    return f"{base}/{(preferred or xmls)[0]}"


def parse_information_table(xml_text: str) -> list[dict]:
    """Parse a 13F information table into aggregated per-issuer positions.

    One issuer can appear on many rows (share classes, sub-managers, sole vs
    shared discretion), so rows are summed by issuer — otherwise a "top 10"
    would be ten rows of the same two names. Values are whatever unit the filer
    used (older filings report thousands); only ranking and relative change are
    used, never an absolute dollar claim.
    """
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        logger.warning(f"Smart money: information table is not parseable XML: {e}")
        return []

    totals: dict[str, float] = {}
    for node in root.iter():
        if _local(node.tag) != "infoTable":
            continue
        issuer = ""
        value = 0.0
        for child in node.iter():
            lt = _local(child.tag)
            if lt == "nameOfIssuer" and child.text and not issuer:
                issuer = child.text.strip()
            elif lt == "value" and child.text:
                try:
                    value = float(child.text.strip().replace(",", ""))
                except ValueError:
                    value = 0.0
        if not issuer:
            continue
        totals[issuer] = totals.get(issuer, 0.0) + value

    return [{"issuer": k, "value": v}
            for k, v in sorted(totals.items(), key=lambda kv: kv[1], reverse=True)]


def diff_positions(prev: dict, curr: list[dict]) -> dict:
    """Compare a parsed filing against the previous quarter's stored totals.

    Returns {"added": [...], "exited": [...]} — new/increased and gone/reduced
    names, biggest first. Without a baseline both lists are empty and the
    caller falls back to reporting the top holdings only.
    """
    if not prev or not curr:
        return {"added": [], "exited": []}

    current = {p["issuer"]: p["value"] for p in curr}
    added, exited = [], []

    for issuer, value in current.items():
        before = float(prev.get(issuer, 0) or 0)
        if value > before:
            added.append({
                "issuer": issuer,
                "delta": value - before,
                "is_new": before == 0,
            })
    for issuer, before in prev.items():
        value = float(current.get(issuer, 0) or 0)
        before = float(before or 0)
        if value < before:
            exited.append({
                "issuer": issuer,
                "delta": before - value,
                "is_gone": value == 0,
            })

    added.sort(key=lambda p: p["delta"], reverse=True)
    exited.sort(key=lambda p: p["delta"], reverse=True)
    return {"added": added[:_MOVES_N], "exited": exited[:_MOVES_N]}


def _check_tracker(tracker: dict, state: dict, today: date) -> dict | None:
    """Check one CIK for a new 13F. Returns an event dict, or None.

    Degrades in layers, and every layer is still useful: full parse with a diff
    → top holdings only → bare "a new filing exists, here is the link". Only a
    total failure to reach EDGAR returns None.
    """
    cik = _pad_cik(tracker.get("cik"))
    name = tracker.get("name") or cik
    if not cik:
        logger.warning(f"Smart money: tracker {name!r} has no usable CIK")
        return None

    resp = _get(_SUBMISSIONS_URL.format(cik=cik))
    resp.raise_for_status()
    filing = latest_13f(resp.json())
    if not filing:
        logger.info(f"Smart money: no 13F-HR on file for {name}")
        return None

    known = state.get(cik) or {}
    if known.get("accession") == filing["accession"]:
        return None  # already reported

    url = _filing_url(cik, filing)

    # First sighting: a filing already on file can be up to a quarter old, and
    # announcing it as new would be false. Record the baseline instead — the
    # positions are what makes NEXT quarter's diff possible.
    first_run = not known
    stale = _is_stale(filing.get("filing_date", ""), today)

    positions = []
    try:
        table_url = _information_table_url(cik, filing)
        if table_url:
            table = _get(table_url)
            table.raise_for_status()
            positions = parse_information_table(table.text)
    except Exception as e:
        logger.warning(f"Smart money: information table fetch/parse failed for {name}: {e}")

    moves = diff_positions(known.get("positions") or {}, positions)

    state[cik] = {
        "accession": filing["accession"],
        "filing_date": filing.get("filing_date", ""),
        "name": name,
        "positions": {p["issuer"]: p["value"] for p in positions[:50]},
    }

    if first_run and stale:
        logger.info(
            f"Smart money: baselined {name} at {filing['accession']} "
            f"({filing.get('filing_date')}) — too old to report as new"
        )
        return None

    return {
        "name": name,
        "cik": cik,
        "form": filing["form"],
        "filing_date": filing.get("filing_date", ""),
        "accession": filing["accession"],
        "url": url,
        "top": positions[:_TOP_N],
        "added": moves["added"],
        "exited": moves["exited"],
    }


def _is_stale(filing_date: str, today: date) -> bool:
    """True if a filing is older than the first-run reporting window."""
    try:
        filed = date.fromisoformat(filing_date)
    except (ValueError, TypeError):
        return True  # undated → treat as old, never announce it as new
    return filed < today - timedelta(days=_FIRST_RUN_MAX_AGE_DAYS)


def collect_events() -> list[dict]:
    """Check every configured tracker. Returns [] on any trouble.

    This is the ONLY entry point the brief calls, and it is total: a dead
    SEC endpoint, a malformed payload, or an unreadable state file all come
    back as "nothing new" rather than an exception the brief has to survive.
    """
    trackers = config.MARKET_BRIEF_TRACKERS
    if not trackers:
        return []

    try:
        state = _load_state()
    except Exception:
        logger.exception("Smart money: could not load tracker state")
        return []

    today = config.today()
    events = []
    dirty = False
    for tracker in trackers:
        try:
            before = json.dumps(state.get(_pad_cik(tracker.get("cik")), {}), sort_keys=True)
            event = _check_tracker(tracker, state, today)
            after = json.dumps(state.get(_pad_cik(tracker.get("cik")), {}), sort_keys=True)
            if before != after:
                dirty = True
            if event:
                events.append(event)
        except Exception as e:
            logger.warning(
                f"Smart money: check failed for {tracker.get('name', '?')}: {e}"
            )

    if dirty:
        try:
            _save_state(state)
        except Exception:
            logger.exception("Smart money: could not persist tracker state")

    if events:
        logger.info(f"Smart money: {len(events)} new 13F filing(s)")
    return events


def _short(issuer: str, width: int = 28) -> str:
    issuer = (issuer or "").strip()
    return issuer if len(issuer) <= width else issuer[: width - 3] + "..."


def format_events(events: list[dict]) -> str:
    """Render 13F events as disclosed FACTS, for the prompt and the fallback.

    Every line is past-tense reporting — "filed", "disclosed", "reported",
    "no longer listed". Nothing here may read as an instruction: a 13F is a
    backward-looking regulatory form, not a signal to act on, and the brief
    that repeats it must not imply otherwise.
    """
    if not events:
        return ""

    lines = []
    for e in events:
        lines.append(
            f"- {e.get('name', '')} filed {e.get('form', '13F-HR')} on "
            f"{e.get('filing_date', 'an unstated date')} (holdings as of the "
            f"reported quarter end): {e.get('url', '')}"
        )
        top = e.get("top") or []
        if top:
            names = ", ".join(_short(p["issuer"]) for p in top[:_TOP_N])
            lines.append(f"  Largest disclosed positions by value: {names}")
        for p in e.get("added") or []:
            verb = "newly disclosed" if p.get("is_new") else "reported larger"
            lines.append(f"  {_short(p['issuer'])}: {verb} vs the prior filing")
        for p in e.get("exited") or []:
            verb = "no longer listed" if p.get("is_gone") else "reported smaller"
            lines.append(f"  {_short(p['issuer'])}: {verb} vs the prior filing")
        if not top:
            lines.append(
                "  Position detail was not parseable — the filing link above "
                "is the source of record."
            )
    return "\n".join(lines)
