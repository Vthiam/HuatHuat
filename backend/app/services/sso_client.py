"""Client for Singapore Statutes Online (sso.agc.gov.sg) -- the actual
government source of truth for Singapore legislation.

SSO's Terms of Use, clause 13(d), permits automated extraction of
legislation subject to three conditions: (i) only between 3am-7am
Singapore time, (ii) not abusive/intrusive, (iii) must not disrupt SSO's
performance. `should_run_now()` enforces (i) for any automated/scheduled
caller; feature/cli-reports-review's manual "check now" command bypasses
this deliberately and must label that in its own output as an override,
not the scheduled run.

Known limitation: SSO's Act pages are a knockout.js single-page app that
lazy-loads each Part of an Act via an internal `/Details/GetLazyLoadContent`
endpoint after the initial page load. We deliberately don't reverse-engineer
that endpoint -- the plain page load already returns the Act's first Part in
full, clean, parseable HTML, which is enough real content to prove the
integration and drive the demo. Tracking more Parts of an Act is a
TRACKED_ACTS config change (more clause_refs), not an architecture change.
"""
import datetime
import re
import zoneinfo
from dataclasses import dataclass
from typing import List, Optional

import requests
from bs4 import BeautifulSoup

from ..config import SSO_BASE_URL, SSO_SCRAPE_WINDOW_END_HOUR_SGT, SSO_SCRAPE_WINDOW_START_HOUR_SGT, SSO_USER_AGENT

SGT = zoneinfo.ZoneInfo("Asia/Singapore")


@dataclass
class ScrapedClause:
    clause_ref: str
    heading: Optional[str]
    text: str


def should_run_now(now: Optional[datetime.datetime] = None) -> bool:
    """True if the current time falls inside SSO ToU's permitted automated
    extraction window (3am-7am Singapore time)."""
    now_sgt = (now or datetime.datetime.now(tz=datetime.timezone.utc)).astimezone(SGT)
    return SSO_SCRAPE_WINDOW_START_HOUR_SGT <= now_sgt.hour < SSO_SCRAPE_WINDOW_END_HOUR_SGT


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": SSO_USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    })
    return s


class SSOFetchError(Exception):
    """Raised when SSO returns a response that isn't a real page load --
    e.g. an HTTP 202 with an empty body, observed in practice during this
    project after enough rapid requests to trip rate-limiting/bot
    detection. `resp.raise_for_status()` alone does NOT catch this: a 202
    is not an error status, so without this check an empty/incomplete
    response would silently look identical to "fetched successfully, and
    nothing has changed" -- exactly the failure mode this tool exists to
    prevent elsewhere. Callers should back off and retry later, not retry
    immediately (see SSO_SCRAPE_WINDOW_* in config.py)."""


def _validate_html(html: str, url: str) -> None:
    if len(html) < 1000 or "legisContent" not in html:
        raise SSOFetchError(
            f"SSO returned an incomplete response for {url} ({len(html)} bytes). This usually "
            "means the request was rate-limited or blocked rather than a genuine page load -- "
            "back off and retry later rather than immediately retrying."
        )


def fetch_act_html(act_id: str) -> str:
    """Fetch the current version of an Act's first Part."""
    url = f"{SSO_BASE_URL}/Act/{act_id}"
    resp = _session().get(url, timeout=20)
    resp.raise_for_status()
    _validate_html(resp.text, url)
    return resp.text


def fetch_historical_act_html(act_id: str, valid_date: str, doc_date: str) -> str:
    """Fetch a past version of an Act as it stood on `valid_date`
    (YYYYMMDD). `doc_date` is the SSO-assigned identifier for that
    consolidation -- found on the Act's page under its version timeline."""
    url = f"{SSO_BASE_URL}/Act/{act_id}/Historical/{valid_date}"
    resp = _session().get(url, params={"DocDate": doc_date, "ValidDate": valid_date}, timeout=20)
    resp.raise_for_status()
    _validate_html(resp.text, url)
    return resp.text


def parse_clauses(html: str) -> List[ScrapedClause]:
    """Parse top-level numbered provisions (`div.prov1`) out of an Act
    page's HTML into structured clauses."""
    soup = BeautifulSoup(html, "html.parser")
    content = soup.select_one("#legisContent") or soup
    clauses: List[ScrapedClause] = []

    for prov in content.select(".prov1"):
        hdr_td = prov.select_one(".prov1Hdr")
        txt_td = prov.select_one(".prov1Txt")
        if txt_td is None:
            continue

        heading = hdr_td.get_text(" ", strip=True) if hdr_td else None

        clause_ref = None
        if hdr_td is not None and hdr_td.get("id"):
            m = re.match(r"pr([^-]+)-", hdr_td["id"])
            if m:
                clause_ref = m.group(1)
        if clause_ref is None:
            strong = txt_td.find("strong")
            if strong:
                clause_ref = strong.get_text(strip=True).rstrip(".")
        if clause_ref is None:
            continue

        text = txt_td.get_text(" ", strip=True)
        text = re.sub(r"\s+", " ", text).strip()

        clauses.append(ScrapedClause(clause_ref=clause_ref, heading=heading, text=text))

    return clauses


def fetch_tracked_clauses(act_id: str, clause_refs: List[str]) -> List[ScrapedClause]:
    """Fetch the current text of just the clauses this library tracks for
    the given Act."""
    html = fetch_act_html(act_id)
    all_clauses = parse_clauses(html)
    wanted = set(clause_refs)
    return [c for c in all_clauses if c.clause_ref in wanted]


def fetch_tracked_historical_clauses(
    act_id: str, clause_refs: List[str], valid_date: str, doc_date: str
) -> List[ScrapedClause]:
    """Same as fetch_tracked_clauses, but for a historical snapshot. Used
    only to seed a realistic starting point (e.g. a real 2013 version of
    PDPA) -- normal ongoing sync always uses the current text."""
    html = fetch_historical_act_html(act_id, valid_date, doc_date)
    all_clauses = parse_clauses(html)
    wanted = set(clause_refs)
    return [c for c in all_clauses if c.clause_ref in wanted]
