"""Broker app links shared by the scraper and the API (no scraping deps here)."""
from __future__ import annotations

import re

GROWW_LIST_URL = "https://groww.in/ipo"
GROWW_IPO_PREFIX = "https://groww.in/ipo/"
# Zerodha has no per-IPO link; its own "Apply now" button points here (opens the Kite app).
KITE_IPO_URL = "https://kite.zerodha.com/bids/ipo"

GROWW_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,119}$")


def is_groww_ipo_url(url: str | None) -> bool:
    return bool(url) and url.startswith(GROWW_IPO_PREFIX) and bool(GROWW_ID.match(url[len(GROWW_IPO_PREFIX):]))
