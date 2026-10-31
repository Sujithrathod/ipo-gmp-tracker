"""Backup GMP source: investorgain.com.

ipowatch.in stays the primary source. investorgain is used to:
- discover active IPOs ipowatch doesn't list (or all of them if ipowatch is down),
- fill a day's GMP when ipowatch's page for that IPO fails or shows no GMP ("₹-").

The two sites often quote different GMPs for the same IPO on the same day, so
rows from here are tagged source="investorgain" and never overwrite an
ipowatch value.

Page structure (verified Oct 2026):
- Live list (/report/live-ipo-gmp/331/): one table. Name cell has the link
  (/gmp/<slug>-ipo/<id>/), an exchange badge ("IPO" = mainboard, "NSE SME",
  "BSE SME") and a status badge (U/O/C; none once listed). GMP cell is
  "₹<b>4.25</b> (4.52%)". Dates look like "2-Nov", sometimes followed by
  "GMP: 30" in a <small>.
- IPO page (/gmp/<slug>-ipo/<id>/): "Daily GMP Trend" table with
  GMP Date | GMP | Est. Listing Price | Est. Profit | Trend.
"""
from __future__ import annotations

import difflib
import re
from dataclasses import dataclass
from datetime import date, datetime
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup, Tag

from scraper.parser import GmpRow, StructureChangedError, parse_numbers

BASE_URL = "https://www.investorgain.com/"
LIVE_URL = "https://www.investorgain.com/report/live-ipo-gmp/331/"
SOURCE = "investorgain"

_STATUS = {"U": "upcoming", "O": "current", "C": "current"}


@dataclass
class IgEntry:
    name: str
    slug: str  # normalised like ipowatch slugs: "acme-steels"
    url: str
    category: str  # mainboard | sme
    status: str  # upcoming | current | listed
    gmp: int | None  # rounded to whole rupees; ipowatch quotes whole rupees
    gain_pct: float | None
    price: float | None
    lot_size: int | None
    open_date: date | None
    close_date: date | None
    listing_date: date | None


def _text(el: Tag | None) -> str:
    return el.get_text(" ", strip=True) if el else ""


def _first_text(cell: Tag) -> str:
    """Cell text without the trailing '<small>GMP: 30</small>' annotation."""
    for small in cell.find_all("small"):
        small.extract()
    return _text(cell)


def _round(value: float) -> int:
    return int(value + 0.5) if value >= 0 else -int(-value + 0.5)


def short_date(text: str, today: date) -> date | None:
    """'2-Nov' / '31-Oct 14:37' -> the date nearest to today in that day/month."""
    m = re.match(r"\s*(\d{1,2})[-\s]([A-Za-z]{3})", text)
    if not m:
        return None
    try:
        dm = datetime.strptime(f"{m.group(1)} {m.group(2).title()} 2000", "%d %b %Y")
    except ValueError:
        return None
    candidates = []
    for year in (today.year - 1, today.year, today.year + 1):
        try:
            candidates.append(dm.date().replace(year=year))
        except ValueError:  # 29 Feb
            continue
    return min(candidates, key=lambda d: abs((d - today).days)) if candidates else None


def slug_from_url(url: str) -> str:
    """'/gmp/acme-steels-ipo/1234/' -> 'acme-steels'."""
    parts = [p for p in urlparse(url).path.split("/") if p]
    slug = parts[1] if len(parts) >= 2 and parts[0] == "gmp" else (parts[-1] if parts else "")
    return re.sub(r"-ipo$", "", slug)


def parse_live(html: str, today: date) -> list[IgEntry]:
    """Active IPOs (upcoming, open, or closed but not yet listed) from the live GMP list."""
    soup = BeautifulSoup(html, "lxml")
    table = next(
        (t for t in soup.find_all("table") if "gmp" in _text(t.find("tr")).lower() and "name" in _text(t.find("tr")).lower()),
        None,
    )
    if table is None:
        raise StructureChangedError("investorgain live GMP table (Name | GMP | ...) not found")

    headers = [_text(c).lower() for c in table.find("tr").find_all(["th", "td"])]

    def col(name: str) -> int | None:
        return next((i for i, h in enumerate(headers) if h.startswith(name)), None)

    i_gmp, i_price, i_lot = col("gmp"), col("price"), col("lot")
    i_open, i_close, i_listing = col("open"), col("close"), col("listing")
    if None in (i_gmp, i_price, i_open, i_close, i_listing):
        raise StructureChangedError(f"investorgain live table columns changed: {headers}")

    out: list[IgEntry] = []
    for row in table.find_all("tr")[1:]:
        cells = row.find_all("td")
        if len(cells) <= max(i_gmp, i_price, i_open, i_close, i_listing):
            continue
        link = cells[0].find("a", href=True)
        if not link:
            continue
        badges = [_text(b) for b in cells[0].select(".badge")]
        status_badge = next((b for b in badges if b in _STATUS), None)
        listing_date = short_date(_first_text(cells[i_listing]), today)
        if status_badge is None and (listing_date is None or listing_date < today):
            continue  # already listed: not our concern
        gmp_text = _text(cells[i_gmp].find("b")) or _first_text(cells[i_gmp])
        gmp_nums = parse_numbers(gmp_text)
        pct = re.search(r"\((-?[\d.]+)%\)", _text(cells[i_gmp]))
        price = parse_numbers(_first_text(cells[i_price]))
        lot = parse_numbers(_first_text(cells[i_lot])) if i_lot is not None else []
        url = urljoin(BASE_URL, link["href"])
        if urlparse(url).scheme != "https" or urlparse(url).hostname not in ("www.investorgain.com", "investorgain.com"):
            continue
        out.append(
            IgEntry(
                name=link.get("title") or _text(link),
                slug=slug_from_url(url),
                url=url,
                category="sme" if any("SME" in b for b in badges) else "mainboard",
                status=_STATUS.get(status_badge or "", "current"),
                gmp=_round(gmp_nums[0]) if gmp_nums and "--" not in gmp_text else None,
                gain_pct=float(pct.group(1)) if pct and gmp_nums else None,
                price=price[0] if price else None,
                lot_size=int(lot[0]) if lot else None,
                open_date=short_date(_first_text(cells[i_open]), today),
                close_date=short_date(_first_text(cells[i_close]), today),
                listing_date=listing_date,
            )
        )
    return out


_TREND_WORDS = {"rising": "up", "up": "up", "falling": "down", "down": "down", "stable": "flat", "flat": "flat"}


def parse_daily_trend(html: str, today: date) -> list[GmpRow]:
    """Day-wise GMP rows (newest first) from an investorgain IPO page."""
    soup = BeautifulSoup(html, "lxml")
    table = next((t for t in soup.find_all("table") if _text(t.find("tr")).lower().startswith("gmp date")), None)
    if table is None:
        raise StructureChangedError("investorgain 'Daily GMP Trend' table not found")
    rows: dict[date, GmpRow] = {}
    for tr in table.find_all("tr")[1:]:
        cells = tr.find_all("td")
        if len(cells) < 2:
            continue
        stamp = _text(cells[0])
        d = short_date(stamp, today)
        if d is None or d > today:
            continue
        gmp_text = _text(cells[1])
        nums = parse_numbers(gmp_text.split("(")[0])
        pct = re.search(r"\((-?[\d.]+)%\)", gmp_text)
        trend_word = _text(cells[-1]).lower().split(" ")[0] if len(cells) > 2 else ""
        time_m = re.search(r"\b(\d{1,2}:\d{2})\b", stamp)
        rows.setdefault(  # first row per date is the latest update that day
            d,
            GmpRow(
                date=d,
                gmp=_round(nums[0]) if nums else None,
                trend=_TREND_WORDS.get(trend_word),
                gain_pct=float(pct.group(1)) if pct else None,
                last_updated=time_m.group(1) if time_m else None,
            ),
        )
    return sorted(rows.values(), key=lambda r: r.date, reverse=True)


# --------------------------------------------------------------------------
# Matching investorgain IPOs to ipowatch / database IPOs
# --------------------------------------------------------------------------

_NOISE = re.compile(r"\b(ltd|limited|ipo|the|and|india|pvt|private)\b")


def name_key(name: str) -> str:
    """'Acme Coated & Special Steels Ltd' -> 'acmecoatedspecialsteels'."""
    n = name.lower().replace("&", " and ").replace("-", " ")
    n = _NOISE.sub(" ", n)
    return re.sub(r"[^a-z0-9]", "", n)


def find_match(entry: IgEntry, candidates: dict[str, str]) -> str | None:
    """Return the slug in `candidates` ({slug: name}) that is the same IPO as `entry`."""
    return match_name(entry.name, entry.slug, candidates)


def match_name(name: str, slug: str, candidates: dict[str, str]) -> str | None:
    """Match an IPO from another site (its name and URL slug) to one of ours ({slug: name})."""
    if slug in candidates:
        return slug
    keys = {s: (name_key(n), name_key(s)) for s, n in candidates.items()}
    mine = {name_key(name), name_key(slug)}
    for cand, theirs in keys.items():
        if mine & set(theirs):
            return cand
    # "Acme Engineering" vs "Acme Engineering Solutions": one name extends the other
    for cand, (nk, _) in keys.items():
        for m in mine:
            if min(len(m), len(nk)) >= 8 and (m.startswith(nk) or nk.startswith(m)):
                return cand
    best, score = None, 0.0
    for cand, (nk, _) in keys.items():
        ratio = difflib.SequenceMatcher(None, name_key(name), nk).ratio()
        if ratio > score:
            best, score = cand, ratio
    return best if score >= 0.9 else None
