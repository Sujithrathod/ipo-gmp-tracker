"""End-to-end: scraper -> SQLite -> API -> digest, all offline against fixtures."""
import importlib
import uuid
from datetime import date, timedelta
from pathlib import Path

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient

from common import db
from scraper import main as scraper
from scraper.fetcher import FileFetcher, PoliteFetcher

FIX = Path(__file__).parent / "fixtures"
TODAY = date(2026, 10, 31)
LISTING = "https://ipowatch.in/ipo-grey-market-premium-latest-ipo-gmp/"
QUATEVEL_GMP = "https://ipowatch.in/quatevel-coated-special-steels-ipo-gmp-grey-market-premium/"
SHIVELRO_GMP = "https://ipowatch.in/shivelro-poly-fabs-ipo-gmp-today/"


@pytest.fixture
def env(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'test.db'}"
    monkeypatch.setenv("DATABASE_URL", url)
    engine = db.get_engine(url)
    files = {
        LISTING: FIX / "ipowatch_gmp_listing.html",
        QUATEVEL_GMP: FIX / "ipowatch_gmp_page.html",
        "https://ipowatch.in/quatevel-coated-special-steels-ipo/": FIX / "ipowatch_details_page.html",
        SHIVELRO_GMP: FIX / "ipowatch_gmp_page_no_gmp.html",
        # shivelro's details page is deliberately missing -> exercises the "keep going" path
    }
    return engine, files, tmp_path


def run_scraper(engine, files, tmp_path, **kw):
    inner = FileFetcher(files)
    fetcher = PoliteFetcher(inner, delay_range=(0, 0), retries=0)
    code = scraper.run(
        fetcher,
        engine=engine,
        output_dir=tmp_path / "out",
        failures_log=tmp_path / "failures.log",
        today=TODAY,
        listing_urls=[LISTING],
        calendar_urls=kw.pop("calendar_urls", []),
        backup_urls=kw.pop("backup_urls", []),
        broker_urls=kw.pop("broker_urls", []),
        **kw,
    )
    return code, inner


def test_full_pipeline(env, monkeypatch):
    engine, files, tmp_path = env
    code, inner = run_scraper(engine, files, tmp_path)
    # 15 IPOs listed, only 2 have fixtures -> 13 per-IPO failures, which is a systemic failure (exit 1)
    assert code == 1
    assert "tanfi-fine-ornaments" in (tmp_path / "failures.log").read_text()

    with engine.connect() as conn:
        quatevel = conn.execute(sa.select(db.ipos).where(db.ipos.c.slug == "quatevel-coated-special-steels")).one()
        assert (quatevel.status, quatevel.lot_size, quatevel.price_band_max) == ("current", 182, 82)
        assert quatevel.listing_date == date(2026, 11, 5)
        n_rows = conn.execute(sa.select(sa.func.count()).select_from(db.gmp_history)).scalar()
        shivelro = conn.execute(sa.select(db.ipos).where(db.ipos.c.slug == "shivelro-poly-fabs")).one()
        assert shivelro.status == "upcoming"

    # Normalized JSON output
    out = (tmp_path / "out" / "quatevel-coated-special-steels.json").read_text()
    assert '"date": "2026-10-31"' in out and '"trend": "down"' in out

    # Re-run immediately: IPOs are skipped (once a day per IPO) and nothing duplicates
    _, inner2 = run_scraper(engine, files, tmp_path)
    assert QUATEVEL_GMP not in inner2.requested
    # Forced re-run: details page not refetched (metadata complete), rows upserted not duplicated
    _, inner3 = run_scraper(engine, files, tmp_path, min_hours=0, only="quatevel-coated-special-steels")
    assert inner3.requested == [LISTING, QUATEVEL_GMP]
    with engine.connect() as conn:
        assert conn.execute(sa.select(sa.func.count()).select_from(db.gmp_history)).scalar() == n_rows

    # ---- API
    import backend.main as api
    api = importlib.reload(api)
    client = TestClient(api.app)

    current = client.get("/ipos", params={"status": "current"}).json()
    card = next(i for i in current if i["slug"] == "quatevel-coated-special-steels")
    assert card["latest_gmp"]["gmp"] == 7
    assert card["latest_gmp"]["change"] == -2
    assert card["latest_gmp"]["change_pct"] == -22.22
    assert card["estimated_listing_price"] == 89

    detail = client.get("/ipos/quatevel-coated-special-steels").json()
    dates = [p["date"] for p in detail["gmp_history"]]
    assert dates == sorted(dates) and dates[-1] == "2026-10-31"
    assert client.get("/ipos/quatevel-coated-special-steels/gmp/latest").json()["gmp"] == 7
    assert detail["about"].startswith("Founded in 1992")
    assert detail["about_summary"].startswith("Founded in 1992") and len(detail["about_summary"]) <= 220
    assert client.get("/ipos/shivelro-poly-fabs").json()["about"] is None  # details page missing in fixtures
    assert client.get("/ipos/nope").status_code == 404
    assert client.get("/ipos/shivelro-poly-fabs/gmp/latest").json()["gmp"] is None

    # ---- dashboard: quatevel is open today (29 Oct - 2 Nov); shivelro opens 2 Nov so it's excluded
    monkeypatch.setattr(api, "today_ist", lambda: TODAY)
    dash = client.get("/dashboard").json()
    assert dash["as_of"] == "2026-10-31" and "not a recommendation" in dash["disclaimer"]
    [item] = dash["open"]
    assert (item["slug"], item["rank"], item["est_gain_pct"]) == ("quatevel-coated-special-steels", 1, 8.54)
    assert (item["profit_per_lot"], item["min_investment"], item["days_to_close"]) == (7 * 182, 82 * 182, 2)
    assert [p["gmp"] for p in item["gmp_series"]][-2:] == [9, 7]
    assert dash["awaiting_listing"] == []

    # ---- users + tracking (each device authenticates with its own secret)
    TOKEN_A, TOKEN_B = "fcmA:" + "a" * 60, "fcmB:" + "b" * 60
    reg = client.post("/users/register-token", json={"fcm_token": TOKEN_A})
    assert reg.status_code == 201 and reg.headers["cache-control"] == "no-store"
    uid, secret = reg.json()["user_id"], reg.json()["user_secret"]
    auth = {"Authorization": f"Bearer {secret}"}
    # Token rotation keeps the same user
    assert client.put(f"/users/{uid}/token", json={"fcm_token": TOKEN_B}, headers=auth).status_code == 204
    assert client.post(f"/users/{uid}/track/quatevel-coated-special-steels", headers=auth).status_code == 204
    assert client.post(f"/users/{uid}/track/quatevel-coated-special-steels", headers=auth).status_code == 204  # idempotent
    assert client.post(f"/users/{uid}/track/shivelro-poly-fabs", headers=auth).status_code == 204
    assert client.get(f"/users/{uid}/tracked", headers=auth).json()["slugs"] == ["quatevel-coated-special-steels", "shivelro-poly-fabs"]
    assert client.delete(f"/users/{uid}/track/shivelro-poly-fabs", headers=auth).status_code == 204
    assert client.post(f"/users/{uid}/track/shivelro-poly-fabs", headers=auth).status_code == 204
    assert client.post(f"/users/{uid}/track/nope", headers=auth).status_code == 404

    # ---- digest (shivelro has no GMP yet, so only quatevel is reported)
    from notify import send_digest

    with engine.connect() as conn:
        digests = send_digest.build_digests(conn, db.utcnow(), TODAY)
        assert len(digests) == 1
        d = digests[0]
        assert d.token == TOKEN_B
        assert [m.slug for m in d.moves] == ["quatevel-coated-special-steels"]
        assert d.body == "▼ Quatevel Coated and Special Steels: ₹7 (−₹2, −22.2%)"
        assert d.data == {"type": "gmp_digest", "slugs": "quatevel-coated-special-steels", "slug": "quatevel-coated-special-steels"}

        # Stale data (no scrape in >30h) and listed IPOs produce no digest
        assert send_digest.build_digests(conn, db.utcnow() + timedelta(hours=31), TODAY) == []
        assert send_digest.build_digests(conn, db.utcnow(), date(2026, 11, 6)) == []


def test_listed_status_after_listing_date(env):
    engine, files, tmp_path = env
    run_scraper(engine, files, tmp_path, only="quatevel-coated-special-steels")
    with engine.connect() as conn:
        assert scraper.refresh_statuses(conn, date(2026, 11, 5)) == 1
        status = conn.execute(sa.select(db.ipos.c.status).where(db.ipos.c.slug == "quatevel-coated-special-steels")).scalar()
    assert status == "listed"


def test_dry_run_writes_json_only(env):
    _, files, tmp_path = env
    code, _ = run_scraper(None, files, tmp_path, only="quatevel-coated-special-steels")
    assert code == 0
    assert (tmp_path / "out" / "quatevel-coated-special-steels.json").exists()


def test_calendar_only_ipo_is_discovered_before_gmp_exists(env):
    engine, files, tmp_path = env
    cal = tmp_path / "calendar.html"
    cal.write_text("""<h2>Mainboard</h2><table>
      <tr><th>Company</th><th>IPO Date</th><th>IPO Size</th><th>IPO Price Band</th></tr>
      <tr><td><a href="/newco-ipo/">NewCo Ltd</a></td><td>5-7 November</td><td>₹100 Cr.</td><td>₹95 to ₹100</td></tr>
      <tr><td><a href="/oldco-ipo/">OldCo</a></td><td>1-3 October</td><td>₹1 Cr.</td><td>₹10</td></tr>
    </table>""", encoding="utf-8")
    details = tmp_path / "newco_details.html"
    details.write_text("""<div class="ipo-tabs-bar"><a href="https://ipowatch.in/newco-ipo-gmp-today/">GMP</a></div>
      <h2>NewCo IPO Dates</h2><table>
      <tr><td>IPO Open Date:</td><td>November 5, 2026</td></tr>
      <tr><td>IPO Close Date:</td><td>November 7, 2026</td></tr>
      <tr><td>IPO Listing Date:</td><td>November 12, 2026</td></tr>
      <tr><td>IPO Price Band</td><td>₹95 to ₹100 Per Share</td></tr></table>""", encoding="utf-8")
    calendar_url = "https://ipowatch.in/upcoming-ipo-list/"
    files = {**files, calendar_url: cal, "https://ipowatch.in/newco-ipo/": details}

    code, inner = run_scraper(engine, files, tmp_path, calendar_urls=[calendar_url], only="newco")
    assert code == 0
    # details page -> GMP link -> 404 (no GMP yet) is not a failure
    assert inner.requested[-2:] == ["https://ipowatch.in/newco-ipo/", "https://ipowatch.in/newco-ipo-gmp-today/"]
    assert "https://ipowatch.in/oldco-ipo/" not in inner.requested
    with engine.connect() as conn:
        ipo = conn.execute(sa.select(db.ipos).where(db.ipos.c.slug == "newco")).one()
    assert (ipo.name, ipo.status, ipo.listing_date, ipo.price_band_max) == ("NewCo Ltd", "upcoming", date(2026, 11, 12), 100)
    assert ipo.gmp_url is None  # retried via the details page tomorrow


IG_LIVE = "https://www.investorgain.com/report/live-ipo-gmp/331/"


def test_backup_fills_gaps_but_never_overrides_ipowatch(env):
    engine, files, tmp_path = env
    files = {**files, IG_LIVE: FIX / "investorgain_live.html"}
    # Only quatevel + shivelro have ipowatch fixtures; everything else 404s on ipowatch.
    code, inner = run_scraper(engine, files, tmp_path, backup_urls=[IG_LIVE])

    with engine.connect() as conn:
        def today_row(slug):
            return conn.execute(
                sa.select(db.gmp_history.c.gmp_value, db.gmp_history.c.source)
                .join(db.ipos, db.ipos.c.id == db.gmp_history.c.ipo_id)
                .where(db.ipos.c.slug == slug, db.gmp_history.c.date == TODAY)
            ).one()

        # ipowatch has ₹7 for quatevel, investorgain ₹10: ipowatch wins
        assert tuple(today_row("quatevel-coated-special-steels")) == (7, "ipowatch")
        # ipowatch shows "₹-" for shivelro; investorgain's ₹4.25 (rounded) fills the gap
        assert tuple(today_row("shivelro-poly-fabs")) == (4, "investorgain")
        # ipowatch page 404s for ZOROQUA: recovered from the backup instead of being lost
        assert tuple(today_row("zoroqua-india")) == (30, "investorgain")
        # investorgain has no GMP for Brimi ("--"): nothing invented
        brimi = conn.execute(sa.select(db.ipos.c.id).where(db.ipos.c.slug == "brimi-nerzo")).scalar()
        assert conn.execute(sa.select(sa.func.count()).where(db.gmp_history.c.ipo_id == brimi)).scalar() == 0
    # Most ipowatch pages failed but the backup recovered them: not a red run
    assert code == 0
    assert "investorgain.com/gmp" not in " ".join(inner.requested)  # no history pages for IPOs ipowatch knows

    # Next day ipowatch posts "₹-" again for shivelro: it must not wipe the backup value
    with engine.begin() as conn:
        vid = conn.execute(sa.select(db.ipos.c.id).where(db.ipos.c.slug == "shivelro-poly-fabs")).scalar()
        db.upsert_gmp_rows(conn, vid, [{"date": TODAY, "gmp_value": None, "trend": None, "gain_pct": None, "last_updated": "09:10"}])
        assert tuple(today_row("shivelro-poly-fabs")) == (4, "investorgain")
        # ...but a real ipowatch number replaces it
        db.upsert_gmp_rows(conn, vid, [{"date": TODAY, "gmp_value": 2, "trend": "up", "gain_pct": 2.1, "last_updated": "17:00"}])
        assert tuple(today_row("shivelro-poly-fabs")) == (2, "ipowatch")


def test_backup_only_ipo_when_ipowatch_is_down(env):
    engine, files, tmp_path = env
    files = {
        IG_LIVE: FIX / "investorgain_live.html",
        "https://www.investorgain.com/gmp/zoroqua-india-ipo/2241/": FIX / "investorgain_ipo_page.html",
    }  # no ipowatch pages at all
    code, inner = run_scraper(engine, files, tmp_path, backup_urls=[IG_LIVE])
    assert code == 1  # ipowatch down is still a red run, even though data kept flowing
    with engine.connect() as conn:
        zoroqua = conn.execute(sa.select(db.ipos).where(db.ipos.c.slug == "zoroqua-india")).one()
        assert (zoroqua.name, zoroqua.category, zoroqua.status, zoroqua.price_band_max, zoroqua.close_date) == (
            "ZOROQUA (India)", "sme", "current", 120, date(2026, 11, 3))
        rows = conn.execute(
            sa.select(db.gmp_history.c.date, db.gmp_history.c.gmp_value, db.gmp_history.c.source)
            .where(db.gmp_history.c.ipo_id == zoroqua.id).order_by(db.gmp_history.c.date)
        ).all()
    assert [tuple(r) for r in rows] == [(date(2026, 10, 30), 30, "investorgain"), (date(2026, 10, 31), 30, "investorgain")]
    # History pages are capped per run so a broken match can't crawl the whole site
    assert sum("investorgain.com/gmp/" in u for u in inner.requested) <= 8


def test_notifier_fails_loudly_when_scrape_is_stale(env):
    from notify import send_digest

    # Empty database: no scrape has ever written data -> red run (GitHub emails the owner)
    assert send_digest.main(["--dry-run"]) == 1
    engine, files, tmp_path = env
    run_scraper(engine, files, tmp_path, only="quatevel-coated-special-steels")
    assert send_digest.main(["--dry-run"]) == 0



# ---------------------------------------------------------------------------
# Security
# ---------------------------------------------------------------------------

@pytest.fixture
def client(env):
    import backend.main as api
    api = importlib.reload(api)
    return TestClient(api.app), api


def _register(c, token):
    r = c.post("/users/register-token", json={"fcm_token": token})
    assert r.status_code == 201, r.text
    body = r.json()
    return body["user_id"], {"Authorization": f"Bearer {body['user_secret']}"}


def test_user_endpoints_require_the_users_own_secret(client, env):
    c, api = client
    engine, files, tmp_path = env
    run_scraper(engine, files, tmp_path, only="quatevel-coated-special-steels")
    alice, alice_auth = _register(c, "alice:" + "a" * 60)
    bob, bob_auth = _register(c, "bob:" + "b" * 60)
    slug = "quatevel-coated-special-steels"
    for method, path in [("get", "/tracked"), ("post", f"/track/{slug}"), ("delete", f"/track/{slug}"), ("delete", "")]:
        url = f"/users/{alice}{path}"
        assert getattr(c, method)(url).status_code == 401  # no credentials
        assert getattr(c, method)(url, headers={"Authorization": "Bearer wrong"}).status_code == 401
        assert getattr(c, method)(url, headers=bob_auth).status_code == 401  # someone else's secret
    assert c.put(f"/users/{alice}/token", json={"fcm_token": "x" * 40}, headers=bob_auth).status_code == 401
    # Unknown user looks exactly like a wrong secret (no probing which ids exist)
    ghost = c.get("/users/00000000-0000-0000-0000-000000000000/tracked", headers=alice_auth)
    assert ghost.status_code == 401 and ghost.json() == c.get(f"/users/{alice}/tracked", headers=bob_auth).json()
    # The secret is never stored in plain text
    with engine.connect() as conn:
        stored = conn.execute(sa.select(db.users.c.secret_hash).where(db.users.c.id == uuid.UUID(alice))).scalar()
    assert stored and alice_auth["Authorization"].split()[1] not in stored


def test_registering_a_known_token_does_not_leak_the_owner(client, env):
    c, _ = client
    engine, _, _ = env
    token = "victim:" + "v" * 60
    victim, _ = _register(c, token)
    attacker, _ = _register(c, token)  # attacker somehow learned the victim's FCM token
    assert attacker != victim  # gets a fresh account, not the victim's id
    with engine.connect() as conn:
        owners = conn.execute(sa.select(db.users.c.id).where(db.users.c.fcm_token == token)).scalars().all()
    assert [str(o) for o in owners] == [attacker]  # one device, one owner


def test_input_validation_and_limits(client):
    c, api = client
    assert c.get("/ipos/..%2F..%2Fetc").status_code in (404, 422)
    assert c.get("/ipos/UPPER_and_symbols!").status_code == 422
    assert c.get("/ipos", params={"limit": 100000}).status_code == 422
    assert c.post("/users/register-token", json={"fcm_token": "short"}).status_code == 422
    assert c.post("/users/register-token", json={"fcm_token": "<script>alert(1)</script>" + "x" * 40}).status_code == 422
    assert c.post("/users/register-token", json={"fcm_token": "y" * 40, "user_id": "x"}).status_code == 422  # extra fields
    big = {"fcm_token": "z" * 20_000}
    assert c.post("/users/register-token", json=big).status_code == 413


def test_registration_is_rate_limited(client):
    c, _ = client
    codes = [c.post("/users/register-token", json={"fcm_token": f"rl{i:03d}:" + "r" * 40}).status_code for i in range(12)]
    assert codes[:10] == [201] * 10 and codes[10:] == [429, 429]


def test_tracking_is_capped_per_user(client, env, monkeypatch):
    c, api = client
    engine, files, tmp_path = env
    run_scraper(engine, files, tmp_path, only="quatevel-coated-special-steels")
    monkeypatch.setattr(api, "MAX_TRACKED_PER_USER", 0)
    uid, auth = _register(c, "cap:" + "c" * 60)
    assert c.post(f"/users/{uid}/track/quatevel-coated-special-steels", headers=auth).status_code == 409


def test_security_headers(client):
    c, _ = client
    api_resp = c.get("/health")
    assert api_resp.headers["x-content-type-options"] == "nosniff"
    assert api_resp.headers["x-frame-options"] == "DENY"
    assert "default-src 'none'" in api_resp.headers["content-security-policy"]
    page = c.get("/preview/")
    csp = page.headers["content-security-policy"]
    assert "script-src 'self'" in csp and "unsafe-inline" not in csp.split("script-src")[1].split(";")[0]
    assert "<script>" not in page.text  # no inline scripts, so the CSP can forbid them
    assert "strict-transport-security" in c.get("/health", headers={"x-forwarded-proto": "https"}).headers


def test_digest_body_is_capped():
    from notify.send_digest import Digest, IpoMove

    moves = [IpoMove(f"IPO {i}", f"ipo-{i}", TODAY, 10, "up", 1, 10.0) for i in range(30)]
    d = Digest("u", "t", moves)
    assert d.body.count("\n") == 8 and d.body.endswith("…and 22 more in the app")
    assert len(d.body.encode()) < 2000 and len(d.data["slugs"].split(",")) == 8


def test_buy_links(client, env):
    c, _ = client
    engine, files, tmp_path = env
    groww = "https://groww.in/ipo"
    files = {**files, groww: FIX / "groww_ipo_list.html"}
    run_scraper(engine, files, tmp_path, broker_urls=[groww])
    quatevel = c.get("/ipos/quatevel-coated-special-steels").json()["buy_links"]
    assert quatevel == {"groww": "https://groww.in/ipo/quatevel-coated-and-special-steels-ipo", "groww_exact": True,
                      "zerodha": "https://kite.zerodha.com/bids/ipo"}
    with engine.begin() as conn:  # a tampered/odd stored value is never handed out
        conn.execute(sa.update(db.ipos).where(db.ipos.c.slug == "shivelro-poly-fabs").values(groww_url="https://evil.example/x"))
        conn.execute(sa.update(db.ipos).where(db.ipos.c.slug == "quatevel-coated-special-steels").values(status="listed"))
    import backend.main as api
    api.cache.clear()
    shivelro = c.get("/ipos/shivelro-poly-fabs").json()["buy_links"]
    assert shivelro["groww"] == "https://groww.in/ipo" and shivelro["groww_exact"] is False
    assert c.get("/ipos/quatevel-coated-special-steels").json()["buy_links"] is None  # listed: nothing to apply for


def test_postgres_urls_use_the_installed_driver():
    # SQLAlchemy 2.1 maps plain postgresql:// to psycopg (v3), which we don't install.
    for raw in ("postgres://u:p@db.example:5432/postgres", "postgresql://u:p@db.example:5432/postgres"):
        url = db.normalize_url(raw)
        assert url == "postgresql+psycopg2://u:p@db.example:5432/postgres"
        engine = db.get_engine(raw)  # builds the engine (no connection) without ModuleNotFoundError
        assert engine.dialect.driver == "psycopg2"
    assert db.normalize_url("sqlite:///x.db") == "sqlite:///x.db"
