# Security policy

## Reporting a vulnerability

Please **don't open a public issue** for security problems. Use GitHub's
private reporting instead: **Security > Report a vulnerability** on this
repository. I'll acknowledge within a few days and fix confirmed issues as
soon as I can.

Useful details: what's affected (API, scraper, Android app, workflows), how
to reproduce it, and the impact you expect.

## Scope

- The FastAPI backend (`backend/`) and its device authentication
- The scraper and notifier (`scraper/`, `notify/`) and the GitHub Actions workflows
- The Android app (`android/`)

Secrets (database URL, Firebase key, signing key) are never stored in this
repository; if you find one, please report it privately.
