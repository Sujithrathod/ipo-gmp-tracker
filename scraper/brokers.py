"""Links that open an IPO in a broker's app.

- Groww has a page per IPO (https://groww.in/ipo/<id>); Android opens it in the
  Groww app when installed. The <id> doesn't follow our slugs reliably
  ("acme-engineering-ipo" vs our "acme-engineering-solutions"), so we read
  Groww's public IPO list once a day and match by company name.
- Zerodha has no per-IPO link: its own "Apply now" button goes to Kite's IPO
  section, which opens in the Kite app.
"""
from __future__ import annotations

import json

from bs4 import BeautifulSoup

from common.brokers import GROWW_ID, GROWW_IPO_PREFIX, GROWW_LIST_URL, KITE_IPO_URL, is_groww_ipo_url  # noqa: F401


def parse_groww_list(html: str) -> list[tuple[str, str, str]]:
    """[(company name, groww id, url)] for open, upcoming and recently closed IPOs."""
    soup = BeautifulSoup(html, "lxml")
    script = soup.find("script", id="__NEXT_DATA__")
    if script is None or not script.string:
        return []
    try:
        props = json.loads(script.string)["props"]["pageProps"]
    except (ValueError, KeyError, TypeError):
        return []
    out: list[tuple[str, str, str]] = []
    for key in ("openDataList", "upcomingDataList", "closedDataList"):
        for item in props.get(key) or []:
            if not isinstance(item, dict):
                continue
            gid, name = item.get("searchId"), item.get("companyName") or item.get("growwShortName")
            if isinstance(gid, str) and isinstance(name, str) and GROWW_ID.match(gid):
                out.append((name[:200], gid, GROWW_IPO_PREFIX + gid))
    return out

