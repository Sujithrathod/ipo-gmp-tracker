"""Send the daily 10 AM IST GMP digest to every user with tracked IPOs.

    python notify/send_digest.py             # send via FCM
    python notify/send_digest.py --dry-run   # print digests, send nothing

One grouped notification per user. Firebase credentials come from
FIREBASE_SERVICE_ACCOUNT_JSON (the JSON itself; used in GitHub Actions) or
GOOGLE_APPLICATION_CREDENTIALS (a file path).
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import sqlalchemy as sa  # noqa: E402

from common import db  # noqa: E402

IST = ZoneInfo("Asia/Kolkata")
CHANNEL_ID = "gmp_digest"
FRESH_WITHIN = timedelta(hours=30)
MAX_DIGEST_LINES = 8  # only report GMP rows written by the latest daily scrape

log = logging.getLogger("notify")


@dataclass
class IpoMove:
    name: str
    slug: str
    date: date
    gmp: int
    trend: str | None
    change: int | None
    change_pct: float | None

    def line(self) -> str:
        # A day with no change reads "▶" even if the source marked it "up"/"down".
        trend = "flat" if self.change == 0 else self.trend
        arrow = {"up": "▲", "down": "▼", "flat": "▶"}.get(trend or "", "•")
        text = f"{arrow} {self.name}: ₹{self.gmp}"
        if self.change is not None:
            sign = "+" if self.change > 0 else "−" if self.change < 0 else "±"
            text += f" ({sign}₹{abs(self.change)}"
            if self.change_pct is not None and self.change != 0:
                text += f", {sign}{abs(self.change_pct):.1f}%"
            text += ")"
        return text


@dataclass
class Digest:
    user_id: str
    token: str
    moves: list[IpoMove]

    @property
    def title(self) -> str:
        day = max(m.date for m in self.moves)
        if len(self.moves) == 1:
            return f"{self.moves[0].name} GMP · {day:%d %b}"
        return f"IPO GMP update · {day:%d %b} ({len(self.moves)} IPOs)"

    @property
    def body(self) -> str:
        # FCM payloads max out at 4 KB; a long list is unreadable on a lock screen anyway.
        lines = [m.line()[:120] for m in self.moves[:MAX_DIGEST_LINES]]
        if len(self.moves) > MAX_DIGEST_LINES:
            lines.append(f"…and {len(self.moves) - MAX_DIGEST_LINES} more in the app")
        return "\n".join(lines)

    @property
    def data(self) -> dict[str, str]:
        # FCM data values must be strings. A single IPO opens its detail
        # screen; a multi-IPO digest opens the list.
        payload = {"type": "gmp_digest", "slugs": ",".join(m.slug for m in self.moves[:MAX_DIGEST_LINES])}
        if len(self.moves) == 1:
            payload["slug"] = self.moves[0].slug
        return payload


def build_digests(conn: sa.Connection, now: datetime, today: date) -> list[Digest]:
    t, u, i = db.user_tracked_ipos, db.users, db.ipos
    tracked = conn.execute(
        sa.select(u.c.id.label("user_id"), u.c.fcm_token, i.c.id.label("ipo_id"), i.c.name, i.c.slug, i.c.listing_date)
        .join(t, t.c.user_id == u.c.id)
        .join(i, i.c.id == t.c.ipo_id)
        .where(u.c.fcm_token.is_not(None))
        # Stop notifying the day after listing; GMP is meaningless then.
        .where(sa.or_(i.c.listing_date.is_(None), i.c.listing_date >= today))
        .order_by(u.c.id, i.c.name)
    ).all()
    if not tracked:
        return []

    rows_by_ipo: dict[int, list] = {}
    for row in conn.execute(db.latest_two_gmp(sorted({r.ipo_id for r in tracked}))):
        rows_by_ipo.setdefault(row.ipo_id, []).append(row)

    moves: dict[int, IpoMove] = {}
    for r in tracked:
        rows = rows_by_ipo.get(r.ipo_id) or []
        if not rows or rows[0].gmp_value is None:
            continue
        latest = rows[0]
        scraped_at = latest.scraped_at if latest.scraped_at.tzinfo else latest.scraped_at.replace(tzinfo=timezone.utc)
        if now - scraped_at > FRESH_WITHIN:
            continue  # not touched by the latest scrape; nothing new to say
        prev = rows[1].gmp_value if len(rows) > 1 else None
        change = latest.gmp_value - prev if prev is not None else None
        moves[r.ipo_id] = IpoMove(
            name=r.name,
            slug=r.slug,
            date=latest.date,
            gmp=latest.gmp_value,
            trend=latest.trend,
            change=change,
            change_pct=round(change / abs(prev) * 100, 2) if change is not None and prev else None,
        )

    digests: dict[str, Digest] = {}
    for r in tracked:
        if r.ipo_id in moves:
            d = digests.setdefault(str(r.user_id), Digest(str(r.user_id), r.fcm_token, []))
            d.moves.append(moves[r.ipo_id])
    return list(digests.values())


def init_firebase():
    import firebase_admin
    from firebase_admin import credentials

    raw = os.environ.get("FIREBASE_SERVICE_ACCOUNT_JSON")
    if raw:
        cred = credentials.Certificate(json.loads(raw))
    elif os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"):
        cred = credentials.Certificate(os.environ["GOOGLE_APPLICATION_CREDENTIALS"])
    else:
        raise SystemExit("Set FIREBASE_SERVICE_ACCOUNT_JSON or GOOGLE_APPLICATION_CREDENTIALS")
    return firebase_admin.initialize_app(cred)


def send(digests: list[Digest], conn: sa.Connection) -> tuple[int, int]:
    from firebase_admin import messaging

    messages = [
        messaging.Message(
            token=d.token,
            notification=messaging.Notification(title=d.title, body=d.body),
            data=d.data,
            android=messaging.AndroidConfig(
                priority="high",
                collapse_key=CHANNEL_ID,
                notification=messaging.AndroidNotification(channel_id=CHANNEL_ID, tag=CHANNEL_ID),
            ),
        )
        for d in digests
    ]
    sent = failed = 0
    for start in range(0, len(messages), 500):  # FCM batch limit
        batch = messages[start:start + 500]
        resp = messaging.send_each(batch)
        for d, r in zip(digests[start:start + 500], resp.responses):
            if r.success:
                sent += 1
                continue
            failed += 1
            log.warning("Send failed for one device: %s", type(r.exception).__name__)
            if isinstance(r.exception, (messaging.UnregisteredError, messaging.SenderIdMismatchError)):
                # App uninstalled or token invalid: stop sending to it.
                conn.execute(sa.update(db.users).where(db.users.c.fcm_token == d.token).values(fcm_token=None))
    conn.commit()
    return sent, failed


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--dry-run", action="store_true", help="Print digests instead of sending")
    args = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s: %(message)s")

    now = db.utcnow()
    today = now.astimezone(IST).date()
    engine = db.get_engine()
    with engine.connect() as conn:
        last_scrape = conn.execute(sa.select(sa.func.max(db.gmp_history.c.scraped_at))).scalar()
        if last_scrape is not None and last_scrape.tzinfo is None:
            last_scrape = last_scrape.replace(tzinfo=timezone.utc)
        stale = last_scrape is None or now - last_scrape > FRESH_WITHIN
        if stale:
            # Fail loudly (GitHub emails the repo owner on a failed scheduled run).
            msg = f"No GMP data scraped since {last_scrape or 'ever'}; check the daily scrape workflow"
            log.error(msg)
            if os.environ.get("GITHUB_ACTIONS"):
                print(f"::error title=Scrape is stale::{msg}", flush=True)
        digests = build_digests(conn, now, today)
        log.info("%d user digest(s) to send", len(digests))
        if args.dry_run:
            # Logs of a public repo are public: number the devices, never print their ids.
            for n, d in enumerate(digests, 1):
                print(f"--- device {n}\n{d.title}\n{d.body}\ndata={d.data}\n")
            return 1 if stale else 0
        if not digests:
            return 1 if stale else 0
        init_firebase()
        sent, failed = send(digests, conn)
    log.info("Sent %d, failed %d", sent, failed)
    return 1 if stale or (digests and sent == 0) else 0


if __name__ == "__main__":
    sys.exit(main())
