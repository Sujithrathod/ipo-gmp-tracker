"""IPO GMP API.

    uvicorn backend.main:app --reload          # from the repo root

Reads DATABASE_URL (Supabase Postgres in production, SQLite local.db by default).

Security model
- IPO data is public and read-only.
- Each device registers once and gets a random `user_secret` (shown only in
  that response; only its SHA-256 is stored). Every /users/{id}/... call must
  send it as `Authorization: Bearer <user_secret>`. Unknown user and wrong
  secret both return 401, so user ids can't be probed.
- Per-IP rate limits, request-size limits, strict input validation and
  security headers (CSP etc.) on every response.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import sys
import threading
import time
import uuid
from collections import deque
from datetime import date, datetime
from pathlib import Path
from typing import Annotated, Any, Callable, Literal
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import sqlalchemy as sa  # noqa: E402
from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response  # noqa: E402
from fastapi import Path as PathParam  # noqa: E402
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from pydantic import BaseModel, ConfigDict, Field  # noqa: E402
from starlette.middleware.trustedhost import TrustedHostMiddleware  # noqa: E402

from common import db  # noqa: E402
from common.text import summarize  # noqa: E402
from common.brokers import GROWW_LIST_URL, KITE_IPO_URL, is_groww_ipo_url  # noqa: E402

CACHE_TTL_SECONDS = 300
MAX_BODY_BYTES = 8 * 1024
MAX_TRACKED_PER_USER = 100
IST = ZoneInfo("Asia/Kolkata")


def _env_flag(name: str, default: bool) -> bool:
    return os.environ.get(name, "1" if default else "0").strip().lower() in ("1", "true", "yes")


def today_ist() -> date:
    return datetime.now(IST).date()


ENABLE_DOCS = _env_flag("ENABLE_DOCS", True)
app = FastAPI(
    title="IPO GMP Tracker API",
    description="Unofficial grey market premium data scraped daily from ipowatch.in. Not investment advice.",
    version="1.1.0",
    docs_url="/docs" if ENABLE_DOCS else None,
    redoc_url=None,
    openapi_url="/openapi.json" if ENABLE_DOCS else None,
)
engine = db.get_engine()

# Web preview of the Android screens (handy for checking data on any phone browser).
if _env_flag("ENABLE_PREVIEW", True):
    app.mount("/preview", StaticFiles(directory=Path(__file__).parent / "preview", html=True), name="preview")


# --------------------------------------------------------------------------
# Middleware: request-size limit, security headers, optional host allowlist
# --------------------------------------------------------------------------

class _BodyTooLarge(Exception):
    pass


class BodySizeLimit:
    """Reject request bodies over `max_bytes`, whether or not Content-Length is sent."""

    def __init__(self, app: Any, max_bytes: int):
        self.app, self.max_bytes = app, max_bytes

    async def __call__(self, scope: dict, receive: Callable, send: Callable) -> None:
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        length = dict(scope["headers"]).get(b"content-length")
        try:
            if length is not None and int(length) > self.max_bytes:
                return await _plain(send, 413, b"Request body too large")
        except ValueError:
            return await _plain(send, 400, b"Bad Content-Length")
        seen = 0

        async def limited_receive() -> dict:
            nonlocal seen
            message = await receive()
            if message["type"] == "http.request":
                seen += len(message.get("body", b""))
                if seen > self.max_bytes:
                    raise _BodyTooLarge
            return message

        try:
            await self.app(scope, limited_receive, send)
        except _BodyTooLarge:
            await _plain(send, 413, b"Request body too large")


async def _plain(send: Callable, status: int, body: bytes) -> None:
    await send({"type": "http.response.start", "status": status,
                "headers": [(b"content-type", b"text/plain; charset=utf-8"), (b"content-length", str(len(body)).encode())]})
    await send({"type": "http.response.body", "body": body})


PREVIEW_CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
    "connect-src 'self'; object-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
)
API_CSP = "default-src 'none'; frame-ancestors 'none'; base-uri 'none'"


@app.middleware("http")
async def security_headers(request: Request, call_next: Callable) -> Response:
    response = await call_next(request)
    path = request.url.path
    h = response.headers
    h.setdefault("X-Content-Type-Options", "nosniff")
    h.setdefault("Referrer-Policy", "no-referrer")
    h.setdefault("X-Frame-Options", "DENY")
    h.setdefault("Cross-Origin-Opener-Policy", "same-origin")
    h.setdefault("Cross-Origin-Resource-Policy", "same-origin")
    h.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=(), payment=()")
    if path.startswith("/preview"):
        h.setdefault("Content-Security-Policy", PREVIEW_CSP)
    elif path not in ("/docs", "/openapi.json"):  # Swagger UI loads its own assets
        h.setdefault("Content-Security-Policy", API_CSP)
    if path.startswith("/users"):
        h["Cache-Control"] = "no-store"  # secrets and personal data must never be cached
    forwarded_proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    if forwarded_proto == "https":
        h.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    return response


app.add_middleware(BodySizeLimit, max_bytes=MAX_BODY_BYTES)
if os.environ.get("ALLOWED_HOSTS"):  # e.g. "ipo-gmp-api.onrender.com,localhost"
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=[h.strip() for h in os.environ["ALLOWED_HOSTS"].split(",")])


# --------------------------------------------------------------------------
# Rate limiting (in-process sliding window; Render's free tier runs one worker)
# --------------------------------------------------------------------------

class RateLimiter:
    def __init__(self, max_keys: int = 50_000):
        self._hits: dict[tuple[str, str], deque[float]] = {}
        self._lock = threading.Lock()
        self._max_keys = max_keys

    def allow(self, bucket: str, key: str, limit: int, window: float) -> bool:
        now = time.monotonic()
        with self._lock:
            if len(self._hits) > self._max_keys:  # bound memory under a flood of distinct IPs
                self._hits = {k: q for k, q in self._hits.items() if q and now - q[-1] < window}
            q = self._hits.setdefault((bucket, key), deque())
            while q and now - q[0] >= window:
                q.popleft()
            if len(q) >= limit:
                return False
            q.append(now)
            return True


limiter = RateLimiter()


def rate_limit(bucket: str, limit: int, window: float) -> Any:
    def check(request: Request) -> None:
        ip = request.client.host if request.client else "unknown"
        if not limiter.allow(bucket, ip, limit, window):
            raise HTTPException(429, "Too many requests; slow down", headers={"Retry-After": str(int(window))})

    return Depends(check)


READ_LIMIT = rate_limit("read", 300, 60)
REGISTER_LIMIT = rate_limit("register", 10, 3600)
USER_WRITE_LIMIT = rate_limit("user-write", 120, 60)


# --------------------------------------------------------------------------
# Tiny in-process TTL cache (data changes once a day), bounded in size
# --------------------------------------------------------------------------

class TTLCache:
    def __init__(self, ttl: float, max_entries: int = 512):
        self.ttl = ttl
        self.max_entries = max_entries
        self._data: dict[str, tuple[float, Any]] = {}
        self._lock = threading.Lock()

    def get_or_set(self, key: str, fn: Callable[[], Any]) -> Any:
        now = time.monotonic()
        with self._lock:
            hit = self._data.get(key)
            if hit and now - hit[0] < self.ttl:
                return hit[1]
        value = fn()
        with self._lock:
            if len(self._data) >= self.max_entries:
                self._data = {k: v for k, v in self._data.items() if now - v[0] < self.ttl}
                while len(self._data) >= self.max_entries:
                    self._data.pop(next(iter(self._data)))
            self._data[key] = (now, value)
        return value

    def clear(self) -> None:
        with self._lock:
            self._data.clear()


cache = TTLCache(CACHE_TTL_SECONDS)


def _cache_headers(response: Response) -> None:
    response.headers["Cache-Control"] = f"public, max-age={CACHE_TTL_SECONDS}"


# --------------------------------------------------------------------------
# Schemas and validated parameters
# --------------------------------------------------------------------------

Status = Literal["current", "upcoming", "listed"]
Slug = Annotated[str, PathParam(pattern=r"^[a-z0-9][a-z0-9-]{0,119}$", description="IPO slug, e.g. acme-steels")]
# FCM registration tokens are ~150-200 chars of [A-Za-z0-9:_-].
FcmToken = Annotated[str, Field(min_length=32, max_length=1024, pattern=r"^[A-Za-z0-9:_\-]+$")]


class GmpPoint(BaseModel):
    date: date
    gmp: int | None
    trend: Literal["up", "down", "flat"] | None
    gain_pct: float | None
    last_updated: str | None
    source: str = Field("ipowatch", description="Site this day's GMP came from: ipowatch (primary) or investorgain (backup)")


class LatestGmp(GmpPoint):
    change: int | None = Field(None, description="GMP change vs the previous day's row")
    change_pct: float | None = Field(None, description="% change of GMP vs the previous day's row")


class IpoSummary(BaseModel):
    name: str
    slug: str
    category: str | None
    status: Status
    price_band_min: float | None
    price_band_max: float | None
    open_date: date | None
    close_date: date | None
    listing_date: date | None
    lot_size: int | None
    estimated_listing_price: float | None
    latest_gmp: LatestGmp | None


class BuyLinks(BaseModel):
    groww: str = Field(description="Groww page for this IPO (opens the Groww app if installed); Groww's IPO list if unmatched")
    groww_exact: bool = Field(description="True when `groww` is this IPO's own page")
    zerodha: str = Field(description="Kite's IPO section (Zerodha has no per-IPO link); opens the Kite app if installed")


class IpoDetail(IpoSummary):
    buy_links: BuyLinks | None = Field(None, description="Absent once the IPO has listed")
    source_url: str | None
    about: str | None = Field(None, description="What the company does (from ipowatch's IPO Details page)")
    about_summary: str | None = Field(None, description="First 2-3 lines of `about`, for the card on the detail screen")
    sources: list[str] = Field(default_factory=list, description="Sites the GMP history came from, primary first")
    gmp_history: list[GmpPoint] = Field(description="Oldest first, ready for charting")


class FcmTokenIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    fcm_token: FcmToken


class RegisterOut(BaseModel):
    user_id: uuid.UUID
    user_secret: str = Field(description="Send as 'Authorization: Bearer <user_secret>' on /users/{id}/... calls. Shown once; store it on the device.")


class TrackedOut(BaseModel):
    user_id: uuid.UUID
    slugs: list[str]


class DashboardItem(IpoSummary):
    rank: int
    buy_links: BuyLinks | None = None
    est_gain_pct: float | None = Field(description="Latest GMP as % of the upper price band")
    profit_per_lot: float | None = Field(description="Latest GMP × lot size, in ₹")
    min_investment: float | None = Field(description="Lot size × upper price band, in ₹")
    days_to_close: int | None
    days_to_listing: int | None
    gmp_series: list[GmpPoint] = Field(description="Oldest first; days without a GMP are omitted")


class Dashboard(BaseModel):
    as_of: date
    open: list[DashboardItem] = Field(description="Open for bidding today, highest GMP-implied gain first")
    awaiting_listing: list[DashboardItem] = Field(description="Bidding closed, not listed yet")
    disclaimer: str


# --------------------------------------------------------------------------
# Authentication
# --------------------------------------------------------------------------

_bearer = HTTPBearer(auto_error=False)


def hash_secret(secret: str) -> str:
    # The secret is 256 random bits, so a fast hash is enough (no password-style KDF needed).
    return hashlib.sha256(secret.encode()).hexdigest()


def authed_user(
    user_id: uuid.UUID,
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> uuid.UUID:
    """The {user_id} in the path, if the request carries that user's secret."""
    denied = HTTPException(401, "Invalid or missing credentials", headers={"WWW-Authenticate": "Bearer"})
    if creds is None or not creds.credentials or len(creds.credentials) > 256:
        raise denied
    with engine.connect() as conn:
        stored = conn.execute(sa.select(db.users.c.secret_hash).where(db.users.c.id == user_id)).scalar()
    # Compare even when the user doesn't exist, so timing doesn't reveal which ids are real.
    if not hmac.compare_digest(stored or "0" * 64, hash_secret(creds.credentials)) or stored is None:
        raise denied
    return user_id


AuthedUser = Annotated[uuid.UUID, Depends(authed_user)]


# --------------------------------------------------------------------------
# Query helpers
# --------------------------------------------------------------------------

def _point(row: Any) -> dict:
    return {
        "date": row.date,
        "gmp": row.gmp_value,
        "trend": row.trend,
        "gain_pct": row.gain_pct,
        "last_updated": row.last_updated,
        "source": getattr(row, "source", None) or db.PRIMARY_SOURCE,
    }


def _latest(rows: list[Any]) -> dict | None:
    """rows: up to two gmp rows for one IPO, newest first."""
    if not rows:
        return None
    latest = _point(rows[0])
    prev = rows[1].gmp_value if len(rows) > 1 else None
    cur = rows[0].gmp_value
    latest["change"] = cur - prev if cur is not None and prev is not None else None
    latest["change_pct"] = (
        round((cur - prev) / abs(prev) * 100, 2) if cur is not None and prev not in (None, 0) else None
    )
    return latest


def _summary(ipo: Any, latest: dict | None) -> dict:
    gmp = latest["gmp"] if latest else None
    return {
        "name": ipo.name,
        "slug": ipo.slug,
        "category": ipo.category,
        "status": ipo.status,
        "price_band_min": ipo.price_band_min,
        "price_band_max": ipo.price_band_max,
        "open_date": ipo.open_date,
        "close_date": ipo.close_date,
        "listing_date": ipo.listing_date,
        "lot_size": ipo.lot_size,
        "estimated_listing_price": (ipo.price_band_max + gmp) if ipo.price_band_max is not None and gmp is not None else None,
        "latest_gmp": latest,
    }


def _buy_links(ipo: Any) -> dict | None:
    if ipo.status == "listed":
        return None
    exact = is_groww_ipo_url(ipo.groww_url)  # only ever hand out links we built ourselves
    return {"groww": ipo.groww_url if exact else GROWW_LIST_URL, "groww_exact": exact, "zerodha": KITE_IPO_URL}


def _latest_by_ipo(conn: sa.Connection, ipo_ids: list[int]) -> dict[int, list[Any]]:
    out: dict[int, list[Any]] = {}
    if not ipo_ids:
        return out
    for row in conn.execute(db.latest_two_gmp(ipo_ids)):
        out.setdefault(row.ipo_id, []).append(row)
    return out


def _get_ipo(conn: sa.Connection, slug: str) -> Any:
    ipo = conn.execute(sa.select(db.ipos).where(db.ipos.c.slug == slug)).first()
    if ipo is None:
        raise HTTPException(404, "IPO not found")
    return ipo


# --------------------------------------------------------------------------
# Public, read-only routes
# --------------------------------------------------------------------------

@app.get("/health")
def health() -> dict:
    with engine.connect() as conn:
        conn.execute(sa.text("select 1"))
    return {"ok": True}


@app.get("/ipos", response_model=list[IpoSummary], dependencies=[READ_LIMIT])
def list_ipos(
    response: Response,
    status: Status | None = Query(None, description="Filter by status"),
    limit: int = Query(100, ge=1, le=500),
) -> list[dict]:
    _cache_headers(response)

    def load() -> list[dict]:
        q = sa.select(db.ipos)
        if status:
            q = q.where(db.ipos.c.status == status)
        c = db.ipos.c
        if status == "listed":
            q = q.order_by(c.listing_date.desc().nulls_last(), c.id.desc())
        elif status == "upcoming":
            q = q.order_by(c.open_date.asc().nulls_last(), c.id)
        else:
            q = q.order_by(c.close_date.asc().nulls_last(), c.id)
        with engine.connect() as conn:
            ipos = conn.execute(q.limit(limit)).all()
            latest = _latest_by_ipo(conn, [i.id for i in ipos])
        return [_summary(i, _latest(latest.get(i.id, []))) for i in ipos]

    return cache.get_or_set(f"ipos:{status}:{limit}", load)


@app.get("/ipos/{slug}", response_model=IpoDetail, dependencies=[READ_LIMIT])
def get_ipo(slug: Slug, response: Response) -> dict:
    _cache_headers(response)

    def load() -> dict:
        with engine.connect() as conn:
            ipo = _get_ipo(conn, slug)
            history = conn.execute(
                sa.select(db.gmp_history).where(db.gmp_history.c.ipo_id == ipo.id).order_by(db.gmp_history.c.date.asc())
            ).all()
        latest = _latest(list(reversed(history[-2:])))
        return {
            **_summary(ipo, latest),
            "buy_links": _buy_links(ipo),
            "source_url": ipo.gmp_url,
            "about": ipo.about or None,
            "about_summary": summarize(ipo.about),
            "gmp_history": [_point(r) for r in history],
            "sources": sorted({r.source or db.PRIMARY_SOURCE for r in history}, key=lambda x: x != db.PRIMARY_SOURCE),
        }

    return cache.get_or_set(f"ipo:{slug}", load)


@app.get("/ipos/{slug}/gmp/latest", response_model=LatestGmp, dependencies=[READ_LIMIT])
def get_latest_gmp(slug: Slug, response: Response) -> dict:
    _cache_headers(response)

    def load() -> dict:
        with engine.connect() as conn:
            ipo = _get_ipo(conn, slug)
            rows = _latest_by_ipo(conn, [ipo.id]).get(ipo.id, [])
        latest = _latest(rows)
        if latest is None:
            raise HTTPException(404, "No GMP data yet for this IPO")
        return latest

    return cache.get_or_set(f"latest:{slug}", load)


DISCLAIMER = (
    "Ranked by GMP-implied listing gain only. GMP is unofficial grey-market data from ipowatch.in, "
    "changes daily and is often wrong; this is not a recommendation to buy."
)


def _dashboard_item(ipo: Any, rows: list[Any], today: date) -> dict:
    latest = _latest(list(reversed(rows[-2:])))
    gmp = latest["gmp"] if latest else None
    price, lot = ipo.price_band_max, ipo.lot_size
    if gmp is not None and price:
        gain = round(gmp / price * 100, 2)
    else:
        gain = latest["gain_pct"] if latest else None
    return {
        **_summary(ipo, latest),
        "rank": 0,
        "buy_links": _buy_links(ipo),
        "est_gain_pct": gain,
        "profit_per_lot": gmp * lot if gmp is not None and lot else None,
        "min_investment": price * lot if price and lot else None,
        "days_to_close": (ipo.close_date - today).days if ipo.close_date else None,
        "days_to_listing": (ipo.listing_date - today).days if ipo.listing_date else None,
        "gmp_series": [_point(r) for r in rows if r.gmp_value is not None],
    }


def _ranked(items: list[dict]) -> list[dict]:
    items.sort(key=lambda i: (i["est_gain_pct"] is None, -(i["est_gain_pct"] or 0), i["name"]))
    for n, item in enumerate(items, 1):
        item["rank"] = n
    return items


@app.get("/dashboard", response_model=Dashboard, dependencies=[READ_LIMIT])
def dashboard(response: Response) -> dict:
    """IPOs open for bidding today (and those awaiting listing), ranked by GMP-implied gain."""
    _cache_headers(response)
    today = today_ist()

    def load() -> dict:
        with engine.connect() as conn:
            ipos = conn.execute(sa.select(db.ipos).where(db.ipos.c.status.in_(["current", "upcoming"]))).all()
            ids = [i.id for i in ipos]
            history = conn.execute(
                sa.select(db.gmp_history).where(db.gmp_history.c.ipo_id.in_(ids)).order_by(db.gmp_history.c.date)
            ).all() if ids else []
        by_ipo: dict[int, list[Any]] = {}
        for row in history:
            by_ipo.setdefault(row.ipo_id, []).append(row)

        open_now, awaiting = [], []
        for ipo in ipos:
            if ipo.open_date and ipo.close_date and ipo.open_date <= today <= ipo.close_date:
                open_now.append(_dashboard_item(ipo, by_ipo.get(ipo.id, []), today))
            elif ipo.close_date and ipo.close_date < today and (ipo.listing_date is None or ipo.listing_date >= today):
                awaiting.append(_dashboard_item(ipo, by_ipo.get(ipo.id, []), today))
        return {"as_of": today, "open": _ranked(open_now), "awaiting_listing": _ranked(awaiting), "disclaimer": DISCLAIMER}

    return cache.get_or_set(f"dashboard:{today}", load)


# --------------------------------------------------------------------------
# Users (each call authenticated with the device's user_secret)
# --------------------------------------------------------------------------

def _release_token(conn: sa.Connection, fcm_token: str, keep: uuid.UUID | None = None) -> None:
    """An FCM token belongs to one device: detach it from any other user (e.g. after a reinstall)."""
    q = sa.update(db.users).where(db.users.c.fcm_token == fcm_token)
    if keep is not None:
        q = q.where(db.users.c.id != keep)
    conn.execute(q.values(fcm_token=None, updated_at=db.utcnow()))


@app.post("/users/register-token", response_model=RegisterOut, status_code=201, dependencies=[REGISTER_LIMIT])
def register_token(body: FcmTokenIn) -> dict:
    """Register this device. Always creates a new user and never reveals existing user ids."""
    now = db.utcnow()
    user_id, user_secret = uuid.uuid4(), secrets.token_urlsafe(32)
    with engine.begin() as conn:
        _release_token(conn, body.fcm_token)
        conn.execute(sa.insert(db.users).values(
            id=user_id, fcm_token=body.fcm_token, secret_hash=hash_secret(user_secret), created_at=now, updated_at=now,
        ))
    return {"user_id": user_id, "user_secret": user_secret}


@app.put("/users/{user_id}/token", status_code=204, dependencies=[USER_WRITE_LIMIT])
def update_token(user_id: AuthedUser, body: FcmTokenIn) -> Response:
    """FCM rotated this device's token (FirebaseMessagingService.onNewToken)."""
    with engine.begin() as conn:
        _release_token(conn, body.fcm_token, keep=user_id)
        conn.execute(sa.update(db.users).where(db.users.c.id == user_id).values(fcm_token=body.fcm_token, updated_at=db.utcnow()))
    return Response(status_code=204)


@app.delete("/users/{user_id}", status_code=204, dependencies=[USER_WRITE_LIMIT])
def delete_user(user_id: AuthedUser) -> Response:
    """Forget this device: its token and tracked IPOs."""
    with engine.begin() as conn:
        conn.execute(sa.delete(db.user_tracked_ipos).where(db.user_tracked_ipos.c.user_id == user_id))
        conn.execute(sa.delete(db.users).where(db.users.c.id == user_id))
    return Response(status_code=204)


@app.get("/users/{user_id}/tracked", response_model=TrackedOut, dependencies=[USER_WRITE_LIMIT])
def list_tracked(user_id: AuthedUser) -> dict:
    with engine.connect() as conn:
        slugs = conn.execute(
            sa.select(db.ipos.c.slug)
            .join(db.user_tracked_ipos, db.user_tracked_ipos.c.ipo_id == db.ipos.c.id)
            .where(db.user_tracked_ipos.c.user_id == user_id)
            .order_by(db.ipos.c.name)
        ).scalars().all()
    return {"user_id": user_id, "slugs": slugs}


@app.post("/users/{user_id}/track/{ipo_slug}", status_code=204, dependencies=[USER_WRITE_LIMIT])
def track(user_id: AuthedUser, ipo_slug: Slug) -> Response:
    t = db.user_tracked_ipos
    with engine.begin() as conn:
        ipo = _get_ipo(conn, ipo_slug)
        if conn.execute(sa.select(t.c.ipo_id).where(t.c.user_id == user_id, t.c.ipo_id == ipo.id)).first():
            return Response(status_code=204)
        count = conn.execute(sa.select(sa.func.count()).select_from(t).where(t.c.user_id == user_id)).scalar()
        if count >= MAX_TRACKED_PER_USER:
            raise HTTPException(409, f"You can track at most {MAX_TRACKED_PER_USER} IPOs")
        conn.execute(sa.insert(t).values(user_id=user_id, ipo_id=ipo.id, created_at=db.utcnow()))
    return Response(status_code=204)


@app.delete("/users/{user_id}/track/{ipo_slug}", status_code=204, dependencies=[USER_WRITE_LIMIT])
def untrack(user_id: AuthedUser, ipo_slug: Slug) -> Response:
    t = db.user_tracked_ipos
    with engine.begin() as conn:
        ipo = _get_ipo(conn, ipo_slug)
        conn.execute(sa.delete(t).where(t.c.user_id == user_id, t.c.ipo_id == ipo.id))
    return Response(status_code=204)
