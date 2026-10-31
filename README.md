# IPO GMP Tracker

[![Tests](https://github.com/Sujithrathod/ipo-gmp-tracker/actions/workflows/tests.yml/badge.svg)](https://github.com/Sujithrathod/ipo-gmp-tracker/actions/workflows/tests.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

A personal learning project: an Android app and a small backend that follow the
**grey market premium (GMP)** of Indian IPOs day by day, chart it, and send one
morning notification for the IPOs you choose to track.

> **Not investment advice.** GMP is unofficial, informally reported data that
> differs between sources and changes daily. This project shows it for
> information only; rankings are by GMP-implied gain, not recommendations.

## What's in the repo

| Part | What it does | Runs on |
|---|---|---|
| `scraper/` | Once a day, reads published GMP figures and IPO details from public pages, with a second source used only to fill gaps | GitHub Actions, 09:15 IST |
| `backend/` | FastAPI service: IPO lists, GMP history, a ranked dashboard, and per-device tracking. Serves a web preview at `/preview` | Render (free tier) |
| `notify/` | Sends one grouped 10:00 IST digest per device via Firebase Cloud Messaging | GitHub Actions |
| `db/` | Postgres schema and optional least-privilege roles | Supabase (free tier) |
| `android/` | Kotlin + Jetpack Compose app: tabs, GMP charts, tracking, home-screen widget | Android 8.0+ |
| `tests/` | Parser and API tests against small, **fictional** sample pages | CI on every push |

## Data sources and how they're used

GMP figures are collected from publicly viewable pages of
[ipowatch.in](https://ipowatch.in) (primary) and
[investorgain.com](https://www.investorgain.com) (fallback, only for days the
primary has none). The app's "Apply" buttons link to the IPO's public page on
[Groww](https://groww.in) or the IPO section of [Zerodha Kite](https://kite.zerodha.com).

The collector is deliberately light:

- runs **once a day**, about 35 page loads in total, with 2-4 s pauses between requests;
- fetches only from an allowlist of those hosts, over HTTPS, with page JavaScript disabled;
- keeps only the figures needed for the charts, and credits the source in the app.

This project is **not affiliated with or endorsed by** ipowatch, investorgain,
Groww or Zerodha; their names and trademarks belong to their owners. It is for
personal, non-commercial use. **Site owners:** if you'd like your site left out,
please [open an issue](../../issues) and it will be removed promptly.

## Privacy

The app has no accounts or logins. For notifications, the backend stores only:
a Firebase device token, a hash of a random per-device secret, and the IPO IDs
you track. No names, phone numbers, contacts or location. After you uninstall,
Firebase reports the token as invalid and the backend clears it; the device's
record can also be deleted with `DELETE /users/{id}` (using its secret).

## Install the Android app

1. Download the latest `ipo-gmp-*.apk` from [Releases](../../releases) on your phone.
2. Open it and allow "Install unknown apps" for your browser or files app when asked, then **Install**.
3. Allow notifications on first launch, open an IPO and tap **Track** for the 10 AM digest.
4. Optional widget: long-press the home screen > Widgets > **IPO GMP ranking**.

Release APKs are signed with the project's release key; the SHA-256 of each APK
is listed in its release notes.

## Run it yourself

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m playwright install chromium
.venv/bin/pytest -q                            # offline tests, fictional data
.venv/bin/python scraper/main.py               # writes to local.db (SQLite) when DATABASE_URL is unset
.venv/bin/uvicorn backend.main:app --reload    # http://localhost:8000/preview/ and /docs
```

Scraper flags: `--fetcher http` (no browser), `--dry-run`, `--only <slug>`, `--force`.

Android: `cd android && ./gradlew assembleRelease`. Needs the Android SDK, plus your own
`app/google-services.json` and `local.properties` with `api.baseUrl.release=` (both git-ignored).

## Deploy your own copy

1. **Supabase**: create a project and run `db/schema.sql` in the SQL editor (safe to re-run).
   Optionally run `db/roles.sql` (after setting its passwords) to give each component a restricted user.
2. **Firebase**: create a project, add an Android app with package `com.ipoanalyser.gmp`,
   put `google-services.json` in `android/app/`, and create a service-account key.
3. **GitHub secrets** (Settings > Secrets and variables > Actions): `DATABASE_URL` and
   `FIREBASE_SERVICE_ACCOUNT_JSON` (optional: `NOTIFY_DATABASE_URL`). Until they exist, the
   daily workflows skip themselves.
4. **Render**: New > Blueprint > your fork (uses `render.yaml`), then set `DATABASE_URL`.
   Choose the region nearest your database.
5. Run **Daily GMP scrape** once by hand (Actions > Run workflow) and check the data.

Never commit `.env`, `google-services.json`, service-account keys or keystores; `.gitignore` blocks them.

## Security

- Each device gets a random secret at registration; tracking calls must present it, and only its hash is stored.
- Rate limits, request-size limits, strict input validation and security headers (CSP, HSTS, etc.) on every response.
- Supabase's public REST API is blocked by row-level security.
- Dependencies are checked with `pip-audit` and updated through grouped monthly Dependabot PRs.

Found a vulnerability? Please report it privately: see [SECURITY.md](SECURITY.md).

## Reliability notes

- GitHub's scheduled jobs can start a few minutes late.
- Render's free tier sleeps when idle; the first request after a quiet period takes ~30-50 s.
- If a source changes its layout, the daily run fails loudly instead of saving bad data.

## License

[MIT](LICENSE) © 2026 Sujith Rathod M
