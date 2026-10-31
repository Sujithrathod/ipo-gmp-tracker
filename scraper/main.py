"""Daily ipowatch.in GMP scraper.

    python scraper/main.py                     # Playwright, writes to $DATABASE_URL (SQLite local.db if unset)
    python scraper/main.py --fetcher http      # plain HTTP, no browser needed
    python scraper/main.py --dry-run --limit 3 # no DB writes, JSON output only

Idempotent: IPOs scraped within the last --min-hours are skipped (so re-runs
don't hit the site twice a day), and GMP rows upsert on (ipo_id, date).
"""
from __future__ import annotations

import argparse
import json
import re
import logging
import os
import sys
from dataclasses import asdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import sqlalchemy as sa  # noqa: E402

from common import db  # noqa: E402
from scraper import brokers, investorgain  # noqa: E402
from scraper.fetcher import Fetcher, PoliteFetcher, make_fetcher  # noqa: E402
from scraper.parser import (  # noqa: E402
    BASE_URL,
    GmpRow,
    IpoMeta,
    ListingEntry,
    StructureChangedError,
    parse_details_page,
    parse_gmp_page,
    find_gmp_link,
    parse_listing,
    parse_upcoming_calendar,
)

IST = ZoneInfo("Asia/Kolkata")
LISTING_URLS = [
    "https://ipowatch.in/ipo-grey-market-premium-latest-ipo-gmp/",
    BASE_URL,
]
# Mainboard + SME calendar: catches newly announced IPOs before they get a GMP table row.
CALENDAR_URLS = ["https://ipowatch.in/upcoming-ipo-list/"]
MAX_NEW_FROM_CALENDAR = 10
# Backup source, used only where ipowatch has no data (see scraper/investorgain.py).
BACKUP_URLS = [investorgain.LIVE_URL]
MAX_BACKUP_HISTORY_PAGES = 8  # per run; only for IPOs ipowatch doesn't have at all
BROKER_URLS = [brokers.GROWW_LIST_URL]

log = logging.getLogger("scraper")


# --------------------------------------------------------------------------
# Logging helpers
# --------------------------------------------------------------------------

def setup_logging(log_dir: Path) -> Path:
    log_dir.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    for handler in (logging.StreamHandler(sys.stdout), logging.FileHandler(log_dir / "scraper.log", encoding="utf-8")):
        handler.setFormatter(fmt)
        root.addHandler(handler)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    return log_dir / "failures.log"


def record_failure(failures_log: Path, ipo_name: str, error: str) -> None:
    stamp = datetime.now(IST).isoformat(timespec="seconds")
    with failures_log.open("a", encoding="utf-8") as f:
        f.write(f"{stamp}\t{ipo_name}\t{error}\n")


def loud_warning(message: str) -> None:
    """Make site-structure changes impossible to miss (log + GitHub Actions annotation)."""
    banner = "!" * 72
    log.error("\n%s\n!! SITE STRUCTURE CHANGED? %s\n%s", banner, message, banner)
    if os.environ.get("GITHUB_ACTIONS"):
        print(f"::error title=ipowatch structure changed::{message}", flush=True)


# --------------------------------------------------------------------------
# Domain logic
# --------------------------------------------------------------------------

def derive_status(site_status: str | None, meta: IpoMeta | dict, today: date) -> str:
    get = meta.get if isinstance(meta, dict) else lambda k: getattr(meta, k)
    listing_date, open_date = get("listing_date"), get("open_date")
    if listing_date and listing_date <= today:
        return "listed"
    if site_status == "Listed":
        return "listed"
    if site_status == "Upcoming":
        return "upcoming"
    if site_status in ("Open", "Closed"):
        return "current"
    if open_date and open_date > today:
        return "upcoming"
    return "current"


def discover(fetcher: Fetcher, listing_urls: list[str], calendar_urls: list[str], today: date) -> list[ListingEntry]:
    """Collect IPOs from the GMP tables, then add not-yet-closed IPOs from the
    upcoming calendar that ipowatch hasn't put in a GMP table yet."""
    merged: dict[str, ListingEntry] = {}
    for url in listing_urls:
        try:
            entries = parse_listing(fetcher.get(url))
        except Exception as e:
            log.error("Failed to load listing page %s: %s", url, e)
            continue
        if not entries:
            loud_warning(f"No GMP tables found on listing page {url}")
        for entry in entries:
            merged.setdefault(entry.slug, entry)  # earlier (dedicated GMP) page wins
        log.info("Listing %s: %d IPOs", url, len(entries))
    for url in calendar_urls:
        try:
            entries = parse_upcoming_calendar(fetcher.get(url), today)
        except Exception as e:
            log.error("Failed to load upcoming calendar %s: %s", url, e)
            continue
        new = [e for e in entries if e.slug not in merged]
        if len(new) > MAX_NEW_FROM_CALENDAR:
            # A handful of IPOs get announced per week; dozens means we misread the page.
            loud_warning(f"Calendar {url} yielded {len(new)} new IPOs (max {MAX_NEW_FROM_CALENDAR}); ignoring it this run")
            continue
        for entry in new:
            merged[entry.slug] = entry
        log.info("Calendar %s: %d open/upcoming, %d not in GMP tables yet%s", url, len(entries), len(new),
                 f" ({', '.join(e.name for e in new)})" if new else "")
    return list(merged.values())


def to_output(entry: ListingEntry, status: str, meta: dict, rows: list[GmpRow]) -> dict:
    return {
        "ipo_name": entry.name,
        "slug": entry.slug,
        "category": entry.category,
        "status": status,
        "price_band_min": meta.get("price_band_min"),
        "price_band_max": meta.get("price_band_max"),
        "open_date": _iso(meta.get("open_date")),
        "close_date": _iso(meta.get("close_date")),
        "listing_date": _iso(meta.get("listing_date")),
        "lot_size": meta.get("lot_size"),
        "about": meta.get("about"),
        "gmp_history": [
            {
                "date": r.date.isoformat(),
                "gmp": r.gmp,
                "trend": r.trend,
                "gain_pct": r.gain_pct,
                "last_updated": r.last_updated,
            }
            for r in rows
        ],
    }


def _iso(d: date | None) -> str | None:
    return d.isoformat() if d else None


def scrape_ipo(
    fetcher: Fetcher,
    entry: ListingEntry,
    conn: sa.Connection | None,
    today: date,
    now: datetime,
    min_hours: float,
) -> dict | None:
    existing = None
    if conn is not None:
        existing = conn.execute(sa.select(db.ipos).where(db.ipos.c.slug == entry.slug)).mappings().first()
        last = _aware(existing["last_scraped_at"]) if existing else None
        if last and now - last < timedelta(hours=min_hours):
            log.info("Skip %s: already scraped %s ago", entry.name, now - last)
            return None

    details_url = entry.details_url or (existing["details_url"] if existing else None) or f"{BASE_URL}{entry.slug}-ipo/"
    gmp_url = entry.gmp_url or (existing["gmp_url"] if existing else None)
    details_html: str | None = None
    if gmp_url is None:
        # Calendar-only IPO: its details page links to the GMP page (if one exists yet).
        details_html = fetcher.get(details_url)
        gmp_url = find_gmp_link(details_html)

    rows: list[GmpRow] = []
    if gmp_url:
        try:
            rows, linked_details = parse_gmp_page(fetcher.get(gmp_url), today)
            details_url = entry.details_url or linked_details or details_url
            if not rows:
                log.warning("%s: GMP table present but empty", entry.name)
        except Exception as e:
            if not entry.from_calendar:
                raise
            log.info("%s: no GMP published yet (%s)", entry.name, e)
            gmp_url = None

    # Metadata rarely changes: fetch the details page once, then again only
    # while key fields (e.g. listing date) are still unannounced.
    meta: dict = dict(existing) if existing else {}
    for k in ("open_date", "close_date"):  # calendar dates fill gaps until the details page says otherwise
        if getattr(entry, k) and not meta.get(k):
            meta[k] = getattr(entry, k)
    need_details = (
        not existing
        or existing["details_scraped_at"] is None
        or existing["listing_date"] is None
        or existing["lot_size"] is None
        or existing["about"] is None  # rows scraped before the About section was collected
    )
    details_scraped = False
    if need_details:
        try:
            parsed = parse_details_page(details_html or fetcher.get(details_url))
            fields = {k: v for k, v in asdict(parsed).items() if k != "raw" and v is not None}
            meta.update(fields)
            details_scraped = True
            missing = [k for k in ("open_date", "close_date", "price_band_max", "lot_size") if not meta.get(k)]
            if missing:
                log.warning("%s: details page missing %s", entry.name, ", ".join(missing))
        except StructureChangedError as e:
            loud_warning(f"{entry.name} details page ({details_url}): {e}")
        except Exception as e:
            log.warning("%s: details page failed (%s); keeping existing metadata", entry.name, e)

    status = derive_status(entry.site_status, meta, today)

    if conn is not None:
        ipo_id = db.upsert_ipo(
            conn,
            {
                "name": entry.name,
                "slug": entry.slug,
                "category": entry.category,
                "status": status,
                "gmp_url": gmp_url,
                "details_url": details_url,
                "open_date": meta.get("open_date"),
                "close_date": meta.get("close_date"),
                "listing_date": meta.get("listing_date"),
                "price_band_min": meta.get("price_band_min"),
                "price_band_max": meta.get("price_band_max"),
                "lot_size": meta.get("lot_size"),
                "about": meta.get("about"),
                "details_scraped_at": now if details_scraped else None,
                "last_scraped_at": now,
            },
        )
        # Posted rows don't change, so only (re)write from the latest stored
        # date onward; today's row can still be revised during the day.
        known_latest = db.latest_gmp_date(conn, ipo_id)
        fresh = [r for r in rows if known_latest is None or r.date >= known_latest]
        written = db.upsert_gmp_rows(
            conn,
            ipo_id,
            [
                {"date": r.date, "gmp_value": r.gmp, "trend": r.trend, "gain_pct": r.gain_pct, "last_updated": r.last_updated}
                for r in fresh
            ],
        )
        conn.commit()
        log.info("%s [%s]: %d history rows parsed, %d upserted", entry.name, status, len(rows), written)

    return to_output(entry, status, meta, rows)


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)  # SQLite drops tzinfo


def refresh_statuses(conn: sa.Connection, today: date) -> int:
    """Mark IPOs as listed once their listing date passes (no site request needed)."""
    result = conn.execute(
        sa.update(db.ipos)
        .where(db.ipos.c.status != "listed", db.ipos.c.listing_date.is_not(None), db.ipos.c.listing_date <= today)
        .values(status="listed", updated_at=db.utcnow())
    )
    conn.commit()
    return result.rowcount or 0


# --------------------------------------------------------------------------
# Backup source (investorgain)
# --------------------------------------------------------------------------

def load_backup(fetcher: Fetcher, urls: list[str], today: date) -> list[investorgain.IgEntry]:
    out: list[investorgain.IgEntry] = []
    for url in urls:
        try:
            entries = investorgain.parse_live(fetcher.get(url), today)
        except StructureChangedError as e:
            loud_warning(f"Backup source {url}: {e}")
            continue
        except Exception as e:
            log.warning("Backup source %s unavailable: %s", url, e)
            continue
        log.info("Backup %s: %d active IPOs", url, len(entries))
        out.extend(entries)
    return out


def match_backup(
    backup: list[investorgain.IgEntry], entries: list[ListingEntry], conn: sa.Connection | None
) -> tuple[dict[str, investorgain.IgEntry], list[tuple[str, investorgain.IgEntry]]]:
    """Pair backup IPOs with ipowatch entries / stored IPOs.

    Returns ({ipowatch slug: backup entry}, [(slug to store under, backup entry)
    for IPOs not in this run's ipowatch list]).
    """
    candidates = {e.slug: e.name for e in entries}
    if conn is not None:
        for slug, name in conn.execute(sa.select(db.ipos.c.slug, db.ipos.c.name).where(db.ipos.c.status != "listed")):
            candidates.setdefault(slug, name)
    in_run = {e.slug for e in entries}
    paired: dict[str, investorgain.IgEntry] = {}
    backup_only: list[tuple[str, investorgain.IgEntry]] = []
    for ig in backup:
        slug = investorgain.find_match(ig, candidates)
        if slug in in_run:
            paired[slug] = ig
        else:
            backup_only.append((slug or ig.slug, ig))
    return paired, backup_only


def _ipo_id(conn: sa.Connection, slug: str) -> int | None:
    return conn.execute(sa.select(db.ipos.c.id).where(db.ipos.c.slug == slug)).scalar()


def fill_from_backup(conn: sa.Connection, ipo_id: int, ig: investorgain.IgEntry, today: date) -> bool:
    """Write today's GMP from the backup where ipowatch has none. True if the backup value was used."""
    if ig.gmp is None:
        return False
    prev = conn.execute(
        sa.select(db.gmp_history.c.gmp_value)
        .where(db.gmp_history.c.ipo_id == ipo_id, db.gmp_history.c.date < today, db.gmp_history.c.gmp_value.is_not(None))
        .order_by(db.gmp_history.c.date.desc())
        .limit(1)
    ).scalar()
    trend = None if prev is None else "up" if ig.gmp > prev else "down" if ig.gmp < prev else "flat"
    row = {"date": today, "gmp_value": ig.gmp, "trend": trend, "gain_pct": ig.gain_pct, "last_updated": None}
    db.upsert_gmp_rows(conn, ipo_id, [row], source=investorgain.SOURCE)
    conn.commit()
    used = conn.execute(
        sa.select(db.gmp_history.c.source).where(db.gmp_history.c.ipo_id == ipo_id, db.gmp_history.c.date == today)
    ).scalar()
    return used == investorgain.SOURCE


def scrape_backup_only(
    fetcher: Fetcher, slug: str, ig: investorgain.IgEntry, conn: sa.Connection, today: date, now: datetime, history_budget: list[int]
) -> None:
    """An IPO ipowatch didn't give us this run: keep it going from investorgain."""
    ipo_id = _ipo_id(conn, slug)
    if ipo_id is None:  # brand new to us: take investorgain's metadata
        ipo_id = db.upsert_ipo(conn, {
            "name": ig.name, "slug": slug, "category": ig.category,
            "status": derive_status(None, {"listing_date": ig.listing_date, "open_date": ig.open_date}, today),
            "price_band_max": ig.price, "lot_size": ig.lot_size,
            "open_date": ig.open_date, "close_date": ig.close_date, "listing_date": ig.listing_date,
            "last_scraped_at": now,
        })
        log.info("%s: added from backup source (not on ipowatch)", ig.name)
    has_rows = conn.execute(sa.select(sa.func.count()).where(db.gmp_history.c.ipo_id == ipo_id)).scalar()
    if not has_rows and history_budget[0] > 0:
        history_budget[0] -= 1
        try:
            rows = investorgain.parse_daily_trend(fetcher.get(ig.url), today)
            db.upsert_gmp_rows(conn, ipo_id, [
                {"date": r.date, "gmp_value": r.gmp, "trend": r.trend, "gain_pct": r.gain_pct, "last_updated": r.last_updated}
                for r in rows
            ], source=investorgain.SOURCE)
            log.info("%s: %d history rows from backup source", ig.name, len(rows))
        except Exception as e:
            log.warning("%s: backup history page failed: %s", ig.name, e)
    conn.commit()
    if fill_from_backup(conn, ipo_id, ig, today):
        log.info("%s: today's GMP ₹%s from backup source", ig.name, ig.gmp)


# --------------------------------------------------------------------------
# Broker links ("Apply on Groww")
# --------------------------------------------------------------------------

def link_brokers(fetcher: Fetcher, conn: sa.Connection, urls: list[str]) -> int:
    """Match our not-yet-listed IPOs to Groww's IPO pages. One request a day."""
    listings: list[tuple[str, str, str]] = []
    for url in urls:
        try:
            listings.extend(brokers.parse_groww_list(fetcher.get(url)))
        except Exception as e:
            log.warning("Broker list %s unavailable: %s", url, e)
    if not listings:
        return 0
    ours = dict(conn.execute(sa.select(db.ipos.c.slug, db.ipos.c.name).where(db.ipos.c.status != "listed")).all())
    updated = 0
    for name, gid, url in listings:
        slug = investorgain.match_name(name, re.sub(r"-ipo$", "", gid), ours)
        if slug is None:
            continue
        result = conn.execute(
            sa.update(db.ipos)
            .where(db.ipos.c.slug == slug, sa.or_(db.ipos.c.groww_url.is_(None), db.ipos.c.groww_url != url))
            .values(groww_url=url)
        )
        updated += result.rowcount or 0
        ours.pop(slug)  # one Groww page per IPO
    conn.commit()
    log.info("Groww links: %d updated; %d of our IPOs not on Groww's list", updated, len(ours))
    return updated


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------

def run(
    fetcher: Fetcher,
    *,
    engine: sa.Engine | None,
    output_dir: Path,
    failures_log: Path,
    today: date,
    listing_urls: list[str] = LISTING_URLS,
    calendar_urls: list[str] = CALENDAR_URLS,
    backup_urls: list[str] = BACKUP_URLS,
    broker_urls: list[str] = BROKER_URLS,
    limit: int | None = None,
    only: str | None = None,
    min_hours: float = 20.0,
) -> int:
    now = db.utcnow()
    entries = discover(fetcher, listing_urls, calendar_urls, today)
    backup = load_backup(fetcher, backup_urls, today)
    if not entries and not backup:
        loud_warning("No IPOs discovered on ipowatch or the backup source; nothing scraped")
        return 2
    if not entries:
        loud_warning("ipowatch returned no IPOs; running on the investorgain backup only")
    log.info("Discovered %d IPOs on ipowatch, %d on backup", len(entries), len(backup))

    conn = engine.connect() if engine is not None else None
    paired, backup_only = match_backup(backup, entries, conn)
    if only:
        entries = [e for e in entries if e.slug == only]
        backup_only = [(s, ig) for s, ig in backup_only if s == only]
    if limit:
        entries = entries[:limit]
        backup_only = backup_only[: max(0, limit - len(entries))]

    output_dir.mkdir(parents=True, exist_ok=True)
    results, failures, structure_failures, recovered = [], 0, 0, 0
    try:
        for entry in entries:
            ig = paired.get(entry.slug)
            try:
                out = scrape_ipo(fetcher, entry, conn, today, now, min_hours)
            except Exception as e:
                failures += 1
                if isinstance(e, StructureChangedError):
                    structure_failures += 1
                    loud_warning(f"{entry.name} ({entry.gmp_url}): {e}")
                    record_failure(failures_log, entry.name, f"STRUCTURE: {e}")
                else:
                    log.exception("Failed to scrape %s", entry.name)
                    record_failure(failures_log, entry.name, repr(e))
                    if os.environ.get("GITHUB_ACTIONS"):
                        print(f"::warning title=scrape failed::{entry.name}: {e}", flush=True)
                if conn is not None:
                    conn.rollback()
                    # ipowatch failed for this IPO: keep today's point from the backup if we have it.
                    if ig is not None and ig.gmp is not None:
                        try:
                            scrape_backup_only(fetcher, entry.slug, ig, conn, today, now, [0])
                            recovered += 1
                            log.info("%s: recovered today's GMP from backup source", entry.name)
                        except Exception:
                            log.exception("Backup recovery failed for %s", entry.name)
                            conn.rollback()
                continue
            if out is not None:
                results.append(out)
                (output_dir / f"{entry.slug}.json").write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
            # ipowatch shows no GMP for today ("₹-" or no row yet): use the backup's figure.
            if conn is not None and ig is not None:
                ipo_id = _ipo_id(conn, entry.slug)
                if ipo_id is not None and fill_from_backup(conn, ipo_id, ig, today):
                    log.info("%s: no GMP on ipowatch today; using backup ₹%s", entry.name, ig.gmp)

        if conn is not None:
            budget = [MAX_BACKUP_HISTORY_PAGES]
            for slug, ig in backup_only:
                try:
                    scrape_backup_only(fetcher, slug, ig, conn, today, now, budget)
                except Exception as e:
                    log.exception("Backup-only scrape failed for %s", ig.name)
                    record_failure(failures_log, ig.name, f"BACKUP: {e!r}")
                    conn.rollback()

            link_brokers(fetcher, conn, broker_urls)
            n = refresh_statuses(conn, today)
            if n:
                log.info("Marked %d IPO(s) as listed", n)
    finally:
        if conn is not None:
            conn.close()

    (output_dir / "all.json").write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    log.info(
        "Done: %d selected, %d scraped, %d failed (%d structure, %d recovered from backup), %d backup-only, %d requests",
        len(entries), len(results), failures, structure_failures, recovered, len(backup_only),
        getattr(fetcher, "request_count", -1),
    )
    # Fail the run (red in GitHub Actions) on systemic problems, not one odd page.
    # ipowatch failing everywhere is still a failure even if the backup kept data flowing.
    if not entries and backup:
        return 1
    if entries and structure_failures >= max(1, len(entries) // 2):
        return 1
    if entries and failures - recovered >= max(1, len(entries) // 2):
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--fetcher", choices=["playwright", "http"], default=os.environ.get("SCRAPER_FETCHER", "playwright"))
    p.add_argument("--dry-run", action="store_true", help="Don't write to the database")
    p.add_argument("--limit", type=int, help="Scrape at most N IPOs")
    p.add_argument("--only", help="Scrape only this slug")
    p.add_argument("--min-hours", type=float, default=20.0, help="Skip IPOs scraped more recently than this (default 20)")
    p.add_argument("--force", action="store_true", help="Ignore --min-hours")
    p.add_argument("--output-dir", type=Path, default=ROOT / "scraper" / "output")
    p.add_argument("--log-dir", type=Path, default=ROOT / "scraper" / "logs")
    args = p.parse_args(argv)

    failures_log = setup_logging(args.log_dir)
    today = datetime.now(IST).date()
    engine = None if args.dry_run else db.get_engine()
    log.info("Scrape start (IST date %s, fetcher=%s, db=%s)", today, args.fetcher,
             "none" if engine is None else engine.url.get_backend_name())  # never log hosts or credentials

    with PoliteFetcher(make_fetcher(args.fetcher)) as fetcher:
        return run(
            fetcher,
            engine=engine,
            output_dir=args.output_dir,
            failures_log=failures_log,
            today=today,
            limit=args.limit,
            only=args.only,
            min_hours=0 if args.force else args.min_hours,
        )


if __name__ == "__main__":
    sys.exit(main())
