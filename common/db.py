"""Shared database layer for the scraper, API and notifier.

Production runs on Postgres (Supabase); local development and tests run on
SQLite. Everything here sticks to SQLAlchemy Core constructs both support.
`db/schema.sql` is the canonical Postgres DDL and must stay in sync with the
tables below.
"""
from __future__ import annotations

import os
import uuid
from datetime import date, datetime, timezone
from typing import Any, Iterable

import sqlalchemy as sa
from sqlalchemy.engine import Connection, Engine

DEFAULT_SQLITE_URL = "sqlite:///local.db"

metadata = sa.MetaData()

ipos = sa.Table(
    "ipos",
    metadata,
    sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
    sa.Column("name", sa.Text, nullable=False),
    sa.Column("slug", sa.Text, nullable=False, unique=True),
    sa.Column("category", sa.Text),  # mainboard | sme
    sa.Column("status", sa.Text, nullable=False, server_default="upcoming"),
    sa.Column("price_band_min", sa.Numeric(12, 2, asdecimal=False)),
    sa.Column("price_band_max", sa.Numeric(12, 2, asdecimal=False)),
    sa.Column("open_date", sa.Date),
    sa.Column("close_date", sa.Date),
    sa.Column("listing_date", sa.Date),
    sa.Column("lot_size", sa.Integer),
    sa.Column("groww_url", sa.Text),  # https://groww.in/ipo/<id>, matched daily from Groww's IPO list
    sa.Column("about", sa.Text),  # "About the company" text from the IPO Details page; "" if the page has none
    sa.Column("gmp_url", sa.Text),
    sa.Column("details_url", sa.Text),
    sa.Column("details_scraped_at", sa.DateTime(timezone=True)),
    sa.Column("last_scraped_at", sa.DateTime(timezone=True)),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    sa.CheckConstraint("status in ('current', 'upcoming', 'listed')", name="ipos_status_check"),
)

gmp_history = sa.Table(
    "gmp_history",
    metadata,
    sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
    sa.Column("ipo_id", sa.Integer, sa.ForeignKey("ipos.id", ondelete="CASCADE"), nullable=False),
    sa.Column("date", sa.Date, nullable=False),
    sa.Column("gmp_value", sa.Integer),  # null when the site shows "₹-"
    sa.Column("trend", sa.Text),  # up | down | flat | null
    sa.Column("gain_pct", sa.Numeric(8, 2, asdecimal=False)),
    sa.Column("last_updated", sa.Text),  # site's "Last Updated" time, e.g. "09:10"
    sa.Column("source", sa.Text),  # ipowatch | investorgain (null = ipowatch, rows from before backups existed)
    sa.Column("scraped_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    sa.UniqueConstraint("ipo_id", "date", name="gmp_history_ipo_date_key"),
    sa.CheckConstraint("trend in ('up', 'down', 'flat')", name="gmp_history_trend_check"),
)

users = sa.Table(
    "users",
    metadata,
    sa.Column("id", sa.Uuid, primary_key=True, default=uuid.uuid4),
    sa.Column("fcm_token", sa.Text, unique=True),
    sa.Column("secret_hash", sa.Text),  # sha256 of the device's user_secret; the secret itself is never stored
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
)

user_tracked_ipos = sa.Table(
    "user_tracked_ipos",
    metadata,
    sa.Column("user_id", sa.Uuid, sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    sa.Column("ipo_id", sa.Integer, sa.ForeignKey("ipos.id", ondelete="CASCADE"), primary_key=True),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def normalize_url(url: str) -> str:
    """Pin the Postgres driver we install (psycopg2).

    Supabase/Heroku hand out "postgres://" or "postgresql://" URLs. SQLAlchemy
    rejects the first, and since 2.1 maps the second to psycopg (v3), so name
    the driver explicitly rather than depend on the library's default.
    """
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg2://" + url[len(prefix):]
    return url


def get_engine(url: str | None = None) -> Engine:
    url = normalize_url(url or os.environ.get("DATABASE_URL") or DEFAULT_SQLITE_URL)
    if url.startswith("sqlite"):
        engine = sa.create_engine(url)

        @sa.event.listens_for(engine, "connect")
        def _enable_sqlite_fks(dbapi_conn, _record):
            dbapi_conn.execute("PRAGMA foreign_keys=ON")

        metadata.create_all(engine)
        _add_missing_columns(engine)
        return engine
    return sa.create_engine(url, pool_pre_ping=True, pool_size=3, max_overflow=2)


def _add_missing_columns(engine: Engine) -> None:
    """create_all() never alters existing tables; add columns introduced after a DB was created."""
    insp = sa.inspect(engine)
    with engine.begin() as conn:
        for table in metadata.sorted_tables:
            if not insp.has_table(table.name):
                continue
            existing = {c["name"] for c in insp.get_columns(table.name)}
            for col in table.columns:
                if col.name not in existing and col.nullable and col.server_default is None:
                    conn.execute(sa.text(f'ALTER TABLE {table.name} ADD COLUMN {col.name} {col.type.compile(engine.dialect)}'))


def _insert(conn: Connection):
    if conn.dialect.name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert
    elif conn.dialect.name == "sqlite":
        from sqlalchemy.dialects.sqlite import insert
    else:  # pragma: no cover
        raise RuntimeError(f"Unsupported database dialect: {conn.dialect.name}")
    return insert


# Scraped text is untrusted: cap what we store.
TEXT_LIMITS = {"name": 200, "slug": 120, "category": 20, "about": 2000, "gmp_url": 500, "details_url": 500, "groww_url": 200}


def upsert_ipo(conn: Connection, values: dict[str, Any]) -> int:
    """Insert or update an IPO by slug and return its id.

    None values never overwrite stored data, so a run that fails to fetch the
    details page doesn't wipe previously scraped metadata.
    """
    now = utcnow()
    values = {**values, "updated_at": now}
    for key, limit in TEXT_LIMITS.items():
        if isinstance(values.get(key), str):
            values[key] = values[key][:limit]
    insert = _insert(conn)
    stmt = insert(ipos).values(**values)
    update_cols = {
        k: stmt.excluded[k] for k, v in values.items() if k != "slug" and v is not None
    }
    conn.execute(stmt.on_conflict_do_update(index_elements=["slug"], set_=update_cols))
    return conn.execute(sa.select(ipos.c.id).where(ipos.c.slug == values["slug"])).scalar_one()


PRIMARY_SOURCE = "ipowatch"


def upsert_gmp_rows(conn: Connection, ipo_id: int, rows: Iterable[dict[str, Any]], source: str = PRIMARY_SOURCE) -> int:
    """Upsert GMP rows keyed on (ipo_id, date). Returns number of rows written.

    Source priority, per day:
    - a primary (ipowatch) row replaces anything, except that a primary
      "no GMP" (null) never wipes a backup value already stored;
    - a backup row is only written where there is no row yet, or where the
      stored row has no GMP.
    """
    now = utcnow()
    payload = [
        {**r, "ipo_id": ipo_id, "scraped_at": now, "source": source,
         "last_updated": (r.get("last_updated") or None) and str(r["last_updated"])[:20]}
        for r in rows
    ]
    if not payload:
        return 0
    insert = _insert(conn)
    stmt = insert(gmp_history).values(payload)
    current = gmp_history.c
    if source == PRIMARY_SOURCE:
        only_if = sa.or_(
            stmt.excluded.gmp_value.is_not(None),
            current.gmp_value.is_(None),
            sa.func.coalesce(current.source, PRIMARY_SOURCE) == PRIMARY_SOURCE,
        )
    else:
        only_if = current.gmp_value.is_(None)
    stmt = stmt.on_conflict_do_update(
        index_elements=["ipo_id", "date"],
        set_={
            "gmp_value": stmt.excluded.gmp_value,
            "trend": stmt.excluded.trend,
            "gain_pct": stmt.excluded.gain_pct,
            "last_updated": stmt.excluded.last_updated,
            "scraped_at": stmt.excluded.scraped_at,
            "source": stmt.excluded.source,
        },
        where=only_if,
    )
    conn.execute(stmt)
    return len(payload)


def latest_gmp_date(conn: Connection, ipo_id: int) -> date | None:
    return conn.execute(
        sa.select(sa.func.max(gmp_history.c.date)).where(gmp_history.c.ipo_id == ipo_id)
    ).scalar()


def latest_two_gmp(ipo_ids: list[int] | None = None) -> sa.Select:
    """Select the two most recent GMP rows per IPO (rn=1 latest, rn=2 previous)."""
    rn = sa.func.row_number().over(
        partition_by=gmp_history.c.ipo_id, order_by=gmp_history.c.date.desc()
    ).label("rn")
    inner = sa.select(gmp_history, rn)
    if ipo_ids is not None:
        inner = inner.where(gmp_history.c.ipo_id.in_(ipo_ids))
    sub = inner.subquery()
    return sa.select(sub).where(sub.c.rn <= 2).order_by(sub.c.ipo_id, sub.c.rn)
