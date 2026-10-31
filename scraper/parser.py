"""HTML parsers for ipowatch.in pages.

Pure functions (HTML string in, dataclasses out) so they can be unit-tested
against saved fixtures without touching the network.

Page structure (verified Oct 2026):
- Listing (/ipo-grey-market-premium-latest-ipo-gmp/ and the homepage): one
  TablePress table per section ("Current Mainboard IPO", "Current SME IPO")
  with columns Company | GMP* | Trend | Price Band | Est. Gain | Date. The
  Company cell holds the GMP-page link plus a <span> status (Open/Closed/
  Upcoming).
- GMP page (/<slug>-ipo-gmp-grey-market-premium/ or /<slug>-ipo-gmp-today/):
  first table is Date | IPO GMP | GMP Trend | Gain | Last Updated, newest row
  first. Trend is an emoji dot (🟢 up, 🔴 down, 🟡 flat, "–" none).
- IPO Details tab (/<slug>-ipo/): "IPO Dates" table (open/close/listing),
  "IPO Details" table (price band), "Market Lot" table (lot size).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup, Tag

BASE_URL = "https://ipowatch.in/"


class StructureChangedError(Exception):
    """The page no longer has the structure the parser expects."""


@dataclass
class ListingEntry:
    name: str
    slug: str
    gmp_url: str | None  # None for calendar-only IPOs: found via their details page
    category: str  # mainboard | sme
    site_status: str | None  # Open | Closed | Upcoming | Listed, as shown on the site
    details_url: str | None = None
    open_date: date | None = None
    close_date: date | None = None
    from_calendar: bool = False


@dataclass
class GmpRow:
    date: date
    gmp: int | None
    trend: str | None  # up | down | flat | None
    gain_pct: float | None
    last_updated: str | None


@dataclass
class IpoMeta:
    open_date: date | None = None
    close_date: date | None = None
    listing_date: date | None = None
    price_band_min: float | None = None
    price_band_max: float | None = None
    lot_size: int | None = None
    about: str | None = None  # "" when the page has no About section
    raw: dict[str, str] = field(default_factory=dict)


# --------------------------------------------------------------------------
# Small value parsers
# --------------------------------------------------------------------------

_SITE_STATUSES = ("Open", "Closed", "Upcoming", "Listed")
_IPOWATCH_HOSTS = {"ipowatch.in", "www.ipowatch.in"}


def _on_ipowatch(url: str) -> bool:
    parts = urlparse(url)
    return parts.scheme == "https" and (parts.hostname or "") in _IPOWATCH_HOSTS
_SLUG_SUFFIX = re.compile(r"-ipo(?:-gmp.*)?$")
_NUMBER = re.compile(r"-?\d[\d,]*(?:\.\d+)?")


def _text(el: Tag | None) -> str:
    return el.get_text(" ", strip=True) if el else ""


def slug_from_url(url: str) -> str:
    """'/acme-steels-ipo-gmp-grey-market-premium/' -> 'acme-steels'."""
    path = urlparse(url).path.strip("/").split("/")[-1]
    return _SLUG_SUFFIX.sub("", path)


def parse_rupees(text: str) -> int | None:
    """'₹247' -> 247, '₹-12' -> -12, '₹-' / '' -> None."""
    cleaned = text.replace("₹", "").replace(",", "").strip()
    m = re.fullmatch(r"-?\d+(?:\.\d+)?", cleaned)
    return round(float(m.group())) if m else None


def parse_percent(text: str) -> float | None:
    """'22.07%' -> 22.07, '-%' -> None."""
    cleaned = text.replace("%", "").replace(",", "").strip()
    m = re.fullmatch(r"-?\d+(?:\.\d+)?", cleaned)
    return float(m.group()) if m else None


def parse_numbers(text: str) -> list[float]:
    return [float(n.replace(",", "")) for n in _NUMBER.findall(text)]


_TREND_SYMBOLS = {
    "up": ("🟢", "▲", "⬆", "↑", "🔼"),
    "down": ("🔴", "▼", "⬇", "↓", "🔽"),
    "flat": ("🟡", "🟠", "⚪", "⚫"),
}
_TREND_CLASS_HINTS = {
    "up": ("green", "up", "positive", "rise", "gain"),
    "down": ("red", "down", "negative", "fall", "loss"),
    "flat": ("yellow", "amber", "neutral", "flat", "orange"),
}
_TREND_STYLE_COLORS = {
    "up": ("green", "#0f0", "#00ff00", "#008000", "#28a745", "#16a34a", "#22c55e", "rgb(0, 128, 0)"),
    "down": ("red", "#f00", "#ff0000", "#dc3545", "#dc2626", "#ef4444", "rgb(255, 0, 0)"),
    "flat": ("yellow", "orange", "#ffc107", "#facc15", "#eab308"),
}


def parse_trend(cell: Tag) -> str | None:
    """Read the trend indicator from the GMP Trend cell.

    ipowatch currently renders the dot as an emoji; we also check CSS classes
    and inline color styles on the cell and its descendants so a switch to a
    styled <span> dot keeps working.
    """
    text = cell.get_text("", strip=True)
    for trend, symbols in _TREND_SYMBOLS.items():
        if any(s in text for s in symbols):
            return trend

    for el in [cell, *cell.find_all(True)]:
        classes = " ".join(el.get("class") or []).lower()
        style = (el.get("style") or "").lower().replace(" ", "")
        for trend, hints in _TREND_CLASS_HINTS.items():
            if any(re.search(rf"(^|[-_\s]){h}($|[-_\s])", classes) for h in hints):
                return trend
        if style:
            for trend, colors in _TREND_STYLE_COLORS.items():
                for c in colors:
                    c = c.replace(" ", "")
                    if re.search(rf"(^|;)(background-)?colou?r:{re.escape(c)}(;|$|!)", style):
                        return trend
    return None


_DATE_FORMATS_WITH_YEAR = ("%B %d, %Y", "%b %d, %Y", "%d %B %Y", "%d %b %Y", "%d-%b-%Y", "%d-%B-%Y", "%Y-%m-%d")
_DATE_FORMATS_NO_YEAR = ("%d %B", "%d %b", "%B %d", "%b %d")


def parse_full_date(text: str) -> date | None:
    """'October 29, 2026' -> date(2026, 10, 29). Returns None for '[.]', 'TBA', etc."""
    text = re.sub(r"\s+", " ", text.replace("Sept ", "Sep ")).strip().rstrip(".")
    text = re.sub(r"^[A-Za-z]+day,\s*", "", text)  # drop leading weekday
    for fmt in _DATE_FORMATS_WITH_YEAR:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def parse_history_date(text: str, today: date) -> date | None:
    """Parse '28 October' and infer the year.

    History rows are never in the future, so pick the year that puts the date
    on or before today (with a few days' slack for timezone skew). This makes
    a "30 December" row scraped on 2 January resolve to the previous year.
    """
    full = parse_full_date(text)
    if full:
        return full
    text = re.sub(r"\s+", " ", text.replace("Sept", "Sep")).strip()
    for fmt in _DATE_FORMATS_NO_YEAR:
        try:
            parsed = datetime.strptime(f"{text} 2000", f"{fmt} %Y")  # 2000 is a leap year, so 29 Feb parses
        except ValueError:
            continue
        for year in (today.year, today.year - 1):
            try:
                candidate = parsed.date().replace(year=year)
            except ValueError:  # 29 Feb in a non-leap year
                continue
            if candidate <= today + timedelta(days=3):
                return candidate
    return None


# --------------------------------------------------------------------------
# Page parsers
# --------------------------------------------------------------------------

def _header_cells(table: Tag) -> list[str]:
    first = table.find("tr")
    return [_text(c).lower() for c in first.find_all(["th", "td"])] if first else []


def _heading_before(table: Tag) -> str:
    h = table.find_previous(["h1", "h2", "h3", "h4"])
    return _text(h)


def parse_listing(html: str, base_url: str = BASE_URL) -> list[ListingEntry]:
    """Parse the live GMP tables from the GMP listing page or homepage."""
    soup = BeautifulSoup(html, "lxml")
    entries: dict[str, ListingEntry] = {}
    for table in soup.find_all("table"):
        headers = _header_cells(table)
        if not headers or "company" not in headers[0] or not any("gmp" in h for h in headers):
            continue
        category = "sme" if "sme" in _heading_before(table).lower() else "mainboard"
        for row in table.find_all("tr")[1:]:
            cells = row.find_all("td")
            if not cells:
                continue
            link = cells[0].find("a", href=True)
            if not link:
                continue
            url = urljoin(base_url, link["href"])
            slug = slug_from_url(url)
            if not slug or "gmp" not in urlparse(url).path or not _on_ipowatch(url):
                continue
            status_el = cells[0].find("span")
            status_text = _text(status_el)
            site_status = next((s for s in _SITE_STATUSES if status_text.startswith(s)), None)
            entries.setdefault(
                slug,
                ListingEntry(
                    name=_text(link),
                    slug=slug,
                    gmp_url=url,
                    category=category,
                    site_status=site_status,
                ),
            )
    return list(entries.values())


_DATE_RANGE = re.compile(r"(\d{1,2})\s*[-–]\s*(\d{1,2})\s+([A-Za-z]+)")


def parse_date_range(text: str, today: date, not_after: date | None = None) -> tuple[date, date] | None:
    """'29-2 November' -> (29 Oct, 2 Nov); '27-29 October' -> (27 Oct, 29 Oct).

    The calendar omits the year, so take the latest year whose close date
    isn't after `not_after` (default: 60 days from today, since IPOs are
    announced a few weeks ahead at most).
    """
    m = _DATE_RANGE.search(text)
    if not m:
        return None
    start_day, end_day, month_name = int(m.group(1)), int(m.group(2)), m.group(3)[:3].title()
    try:
        month = datetime.strptime(month_name, "%b").month
    except ValueError:
        return None
    limit = not_after or today + timedelta(days=60)
    candidates = []
    for year in (today.year - 1, today.year, today.year + 1):
        try:
            close = date(year, month, end_day)
            if start_day <= end_day:
                open_ = date(year, month, start_day)
            else:  # range crosses a month boundary
                prev = close.replace(day=1) - timedelta(days=1)
                open_ = prev.replace(day=start_day)
        except ValueError:
            continue
        if close <= limit:
            candidates.append((open_, close))
    return max(candidates, key=lambda c: c[1]) if candidates else None


def parse_upcoming_calendar(html: str, today: date, base_url: str = BASE_URL) -> list[ListingEntry]:
    """Parse /upcoming-ipo-list/ (Mainboard + SME tables of IPO dates).

    Only IPOs that haven't closed yet are returned; the page also keeps
    months of past IPOs (newest first).
    """
    soup = BeautifulSoup(html, "lxml")
    entries: dict[str, ListingEntry] = {}
    for table in soup.find_all("table"):
        headers = _header_cells(table)
        if not headers or not any("date" in h for h in headers) or any("gmp" in h for h in headers):
            continue
        i_date = next(i for i, h in enumerate(headers) if "date" in h)
        category = "sme" if "sme" in _heading_before(table).lower() or "platform" in headers else "mainboard"
        # Rows run newest first, so each row can't be much newer than the one
        # above it. That stops last January's rows reading as next January.
        bound: date | None = None
        for row in table.find_all("tr")[1:]:
            cells = row.find_all("td")
            if len(cells) <= i_date:
                continue
            link = cells[0].find("a", href=True)
            dates = parse_date_range(_text(cells[i_date]), today, bound)
            if dates:
                bound = dates[1] + timedelta(days=15)
            if not link or not dates or dates[1] < today:
                continue
            url = urljoin(base_url, link["href"])
            slug = slug_from_url(url)
            if not slug or not _on_ipowatch(url):
                continue
            open_, close = dates
            entries.setdefault(
                slug,
                ListingEntry(
                    name=_text(link),
                    slug=slug,
                    gmp_url=None,
                    category=category,
                    site_status="Upcoming" if open_ > today else "Open",
                    details_url=url,
                    open_date=open_,
                    close_date=close,
                    from_calendar=True,
                ),
            )
    return list(entries.values())


def find_gmp_link(html: str) -> str | None:
    """GMP tab link from the tab bar on an IPO's details page."""
    soup = BeautifulSoup(html, "lxml")
    for a in soup.select(".ipo-tabs-bar a[href]"):
        url = urljoin(BASE_URL, a["href"])
        if _text(a).strip().lower() == "gmp" and _on_ipowatch(url):
            return url
    return None


def _find_gmp_table(soup: BeautifulSoup) -> Tag | None:
    for table in soup.find_all("table"):
        headers = _header_cells(table)
        if len(headers) >= 3 and headers[0].startswith("date") and any("gmp" in h for h in headers):
            return table
    return None


def parse_gmp_page(html: str, today: date) -> tuple[list[GmpRow], str | None]:
    """Parse the GMP history table. Returns (rows newest-first, IPO Details tab URL).

    Raises StructureChangedError if the history table can't be found.
    """
    soup = BeautifulSoup(html, "lxml")
    table = _find_gmp_table(soup)
    if table is None:
        raise StructureChangedError("GMP history table (Date | IPO GMP | GMP Trend | ...) not found")

    headers = _header_cells(table)

    def col(*names: str) -> int | None:
        for i, h in enumerate(headers):
            if any(n in h for n in names):
                return i
        return None

    i_date = 0
    i_gmp = col("ipo gmp", "gmp")
    i_trend = col("trend")
    i_gain = col("gain")
    i_updated = col("updated", "time")
    if i_gmp is None:
        raise StructureChangedError(f"GMP column missing; headers={headers}")

    rows: list[GmpRow] = []
    for tr in table.find_all("tr")[1:]:
        cells = tr.find_all("td")
        if len(cells) <= i_gmp:
            continue
        d = parse_history_date(_text(cells[i_date]), today)
        if d is None:
            continue
        rows.append(
            GmpRow(
                date=d,
                gmp=parse_rupees(_text(cells[i_gmp])),
                trend=parse_trend(cells[i_trend]) if i_trend is not None and i_trend < len(cells) else None,
                gain_pct=parse_percent(_text(cells[i_gain])) if i_gain is not None and i_gain < len(cells) else None,
                last_updated=(_text(cells[i_updated]) or None) if i_updated is not None and i_updated < len(cells) else None,
            )
        )

    if table.find_all("tr")[1:] and not rows:
        raise StructureChangedError("GMP history table has rows but none could be parsed")

    rows.sort(key=lambda r: r.date, reverse=True)
    _fill_missing_trends(rows)

    details_url = None
    for a in soup.select(".ipo-tabs-bar a[href]"):
        if "detail" in _text(a).lower() and _on_ipowatch(urljoin(BASE_URL, a["href"])):
            details_url = urljoin(BASE_URL, a["href"])
            break
    return rows, details_url


def _fill_missing_trends(rows_newest_first: list[GmpRow]) -> None:
    """Where the site gives no trend dot, derive it from the previous day's GMP."""
    for newer, older in zip(rows_newest_first, rows_newest_first[1:]):
        if newer.trend is None and newer.gmp is not None and older.gmp is not None:
            newer.trend = "up" if newer.gmp > older.gmp else "down" if newer.gmp < older.gmp else "flat"


def _key_value_tables(soup: BeautifulSoup) -> dict[str, str]:
    """Flatten every 2-column table into {normalized label: value}."""
    out: dict[str, str] = {}
    for table in soup.find_all("table"):
        for tr in table.find_all("tr"):
            cells = tr.find_all(["td", "th"])
            if len(cells) == 2:
                key = re.sub(r"[^a-z ]", "", _text(cells[0]).lower()).strip()
                key = re.sub(r"\s+", " ", key)
                if key and key not in out:
                    out[key] = _text(cells[1])
    return out


def _lot_size(soup: BeautifulSoup) -> int | None:
    for table in soup.find_all("table"):
        headers = _header_cells(table)
        if "shares" not in headers or not any("application" in h or "lot" in h for h in headers):
            continue
        i_shares = headers.index("shares")
        for tr in table.find_all("tr")[1:]:
            cells = tr.find_all("td")
            if len(cells) > i_shares and "min" in _text(cells[0]).lower():
                nums = parse_numbers(_text(cells[i_shares]))
                if nums:
                    return int(nums[0])
    return None


def parse_details_page(html: str) -> IpoMeta:
    soup = BeautifulSoup(html, "lxml")
    kv = _key_value_tables(soup)
    if not kv:
        raise StructureChangedError("IPO Details page has no key/value tables")

    def find(*labels: str) -> str | None:
        for label in labels:
            for k, v in kv.items():
                if label in k:
                    return v
        return None

    meta = IpoMeta(raw=kv)
    meta.open_date = parse_full_date(find("ipo open date", "open date") or "")
    meta.close_date = parse_full_date(find("ipo close date", "close date") or "")
    meta.listing_date = parse_full_date(find("ipo listing date", "listing date") or "")

    band = find("price band", "issue price")
    if band:
        nums = [n for n in parse_numbers(band) if n > 0]
        if nums:
            meta.price_band_min, meta.price_band_max = min(nums), max(nums)

    meta.lot_size = _lot_size(soup)
    meta.about = _about(soup)
    return meta


def _about(soup: BeautifulSoup, max_chars: int = 1500) -> str:
    """Paragraphs under the "About <company> IPO" heading ("" if there's none)."""
    heading = next(
        (h for h in soup.find_all(["h2", "h3"]) if _text(h).lower().startswith("about")), None
    )
    if heading is None:
        return ""
    paras: list[str] = []
    for el in heading.find_next_siblings():
        if el.name in ("h1", "h2", "h3"):
            break
        if el.name == "p" and _text(el):
            paras.append(_text(el))
        elif el.name in ("ul", "ol"):
            paras.extend(_text(li) for li in el.find_all("li") if _text(li))
    if not paras:  # content wrapped in a container instead of being siblings
        nxt = heading.find_next(["h2", "h3"])
        for p in heading.find_all_next("p", limit=6):
            if nxt is not None and p.find_previous(["h2", "h3"]) is not heading:
                break
            paras.append(_text(p))
    about = "\n\n".join(p for p in paras if p)
    return about[:max_chars].rsplit(" ", 1)[0] + "…" if len(about) > max_chars else about
