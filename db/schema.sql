-- IPO GMP tracker schema (Postgres / Supabase).
-- Run once in the Supabase SQL editor. Safe to re-run.
-- Keep in sync with common/db.py.

create extension if not exists pgcrypto;

create table if not exists ipos (
    id                 serial primary key,
    name               text not null,
    slug               text not null unique,
    category           text,                         -- mainboard | sme
    status             text not null default 'upcoming'
                       constraint ipos_status_check check (status in ('current', 'upcoming', 'listed')),
    price_band_min     numeric(12, 2),
    price_band_max     numeric(12, 2),
    open_date          date,
    close_date         date,
    listing_date       date,
    lot_size           integer,
    about              text,                         -- company description from the IPO Details page
    groww_url          text,                         -- https://groww.in/ipo/<id> for the Apply on Groww button
    gmp_url            text,
    details_url        text,
    details_scraped_at timestamptz,
    last_scraped_at    timestamptz,
    created_at         timestamptz not null default now(),
    updated_at         timestamptz not null default now()
);

-- Added after the first release; harmless on a fresh database.
alter table ipos add column if not exists about text;
alter table ipos add column if not exists groww_url text;

create index if not exists ipos_status_idx on ipos (status);

create table if not exists gmp_history (
    id           serial primary key,
    ipo_id       integer not null references ipos (id) on delete cascade,
    date         date not null,
    gmp_value    integer,                            -- null when the site shows "₹-"
    trend        text constraint gmp_history_trend_check check (trend in ('up', 'down', 'flat')),
    gain_pct     numeric(8, 2),
    last_updated text,                               -- site's "Last Updated" time, e.g. '09:10'
    source       text,                               -- ipowatch | investorgain (null = ipowatch)
    scraped_at   timestamptz not null default now(),
    constraint gmp_history_ipo_date_key unique (ipo_id, date)
);

-- Added after the first release; harmless on a fresh database.
alter table gmp_history add column if not exists source text;

create table if not exists users (
    id         uuid primary key default gen_random_uuid(),
    fcm_token  text unique,
    secret_hash text,                                -- sha256 of the device secret (never the secret)
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

alter table users add column if not exists secret_hash text;

create table if not exists user_tracked_ipos (
    user_id    uuid not null references users (id) on delete cascade,
    ipo_id     integer not null references ipos (id) on delete cascade,
    created_at timestamptz not null default now(),
    primary key (user_id, ipo_id)
);

create index if not exists user_tracked_ipos_ipo_idx on user_tracked_ipos (ipo_id);

-- Supabase exposes the public schema over its REST API with the anon key.
-- Enabling RLS with no policies blocks that path; the scraper, API and
-- notifier connect as the postgres role via DATABASE_URL, which bypasses RLS.
alter table ipos enable row level security;
alter table gmp_history enable row level security;
alter table users enable row level security;
alter table user_tracked_ipos enable row level security;
