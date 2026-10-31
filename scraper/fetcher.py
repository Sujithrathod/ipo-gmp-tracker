"""Page fetchers.

PlaywrightFetcher is the default (renders JS, so it keeps working if the site
moves the tables client-side). HttpFetcher is a lightweight alternative for
quick local runs since ipowatch currently serves the tables in static HTML.
Both are wrapped in PoliteFetcher, which enforces the randomized delay.
"""
from __future__ import annotations

import logging
import os
import random
import time
from pathlib import Path
from typing import Protocol
from urllib.parse import urlparse

log = logging.getLogger(__name__)

MAX_PAGE_BYTES = 5 * 1024 * 1024  # real pages are well under 1 MB

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36"
)


# The scraper only ever talks to these sites; links or redirects anywhere else are refused.
ALLOWED_HOSTS = frozenset({
    "ipowatch.in", "www.ipowatch.in",            # primary GMP source
    "investorgain.com", "www.investorgain.com",  # backup GMP source
    "groww.in",                                  # IPO list, read once a day for "Apply on Groww" links
})


class DisallowedURL(ValueError):
    pass


def check_url(url: str, allowed: frozenset[str] = ALLOWED_HOSTS) -> None:
    parts = urlparse(url)
    if parts.scheme != "https" or (parts.hostname or "").lower() not in allowed or parts.username or parts.port:
        raise DisallowedURL(f"Refusing to fetch {url!r}: not an allowed https host")


class Fetcher(Protocol):
    def get(self, url: str) -> str: ...
    def close(self) -> None: ...


class PlaywrightFetcher:
    def __init__(self, timeout_ms: int = 45_000, javascript: bool | None = None):
        from playwright.sync_api import sync_playwright

        # The GMP tables are server-rendered, so run with JavaScript off by default:
        # third-party page scripts never execute. SCRAPER_ENABLE_JS=1 turns it back on
        # if the site ever moves the tables client-side.
        if javascript is None:
            javascript = os.environ.get("SCRAPER_ENABLE_JS") == "1"

        self._timeout_ms = timeout_ms
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=True)
        self._context = self._browser.new_context(
            user_agent=USER_AGENT,
            locale="en-IN",
            timezone_id="Asia/Kolkata",
            viewport={"width": 1366, "height": 900},
            java_script_enabled=javascript,
            accept_downloads=False,
            service_workers="block",
        )
        # Tables are all we need; skip heavy assets to keep load on the site low.
        self._context.route(
            "**/*",
            lambda route: route.abort()
            if route.request.resource_type in {"image", "media", "font", "stylesheet"}
            else route.continue_(),
        )
        self._page = self._context.new_page()

    def get(self, url: str) -> str:
        resp = self._page.goto(url, wait_until="domcontentloaded", timeout=self._timeout_ms)
        if resp is None or resp.status >= 400:
            raise RuntimeError(f"HTTP {resp.status if resp else '??'} for {url}")
        check_url(self._page.url)  # a redirect must not take us off-site
        try:
            self._page.wait_for_selector("table", timeout=10_000)
        except Exception:
            log.debug("No <table> appeared on %s within 10s", url)
        return self._page.content()

    def close(self) -> None:
        for closer in (self._context.close, self._browser.close, self._pw.stop):
            try:
                closer()
            except Exception:  # pragma: no cover
                pass


class HttpFetcher:
    def __init__(self, timeout_s: float = 30.0):
        import httpx

        self._client = httpx.Client(
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-IN,en;q=0.9",
            },
            follow_redirects=True,
            max_redirects=5,
            timeout=timeout_s,
        )

    def get(self, url: str) -> str:
        resp = self._client.get(url)
        for hop in [*resp.history, resp]:  # every redirect hop must stay on allowed hosts
            check_url(str(hop.url))
        resp.raise_for_status()
        if len(resp.content) > MAX_PAGE_BYTES:
            raise RuntimeError(f"Response too large ({len(resp.content)} bytes) for {url}")
        return resp.text

    def close(self) -> None:
        self._client.close()


class FileFetcher:
    """Serves saved HTML fixtures; used by tests. Maps URL slug -> file."""

    def __init__(self, files: dict[str, Path]):
        self._files = files
        self.requested: list[str] = []

    def get(self, url: str) -> str:
        self.requested.append(url)
        if url not in self._files:
            raise RuntimeError(f"HTTP 404 for {url}")
        return Path(self._files[url]).read_text(encoding="utf-8")

    def close(self) -> None:
        pass


class PoliteFetcher:
    """Adds a randomized delay between requests and retries transient failures."""

    def __init__(
        self,
        inner: Fetcher,
        delay_range: tuple[float, float] = (2.0, 4.0),
        retries: int = 2,
        allowed_hosts: frozenset[str] = ALLOWED_HOSTS,
    ):
        self._inner = inner
        self._allowed = allowed_hosts
        self._delay_range = delay_range
        self._retries = retries
        self._last_request: float | None = None
        self.request_count = 0

    def _wait(self) -> None:
        if self._last_request is None:
            return
        target = random.uniform(*self._delay_range)
        remaining = target - (time.monotonic() - self._last_request)
        if remaining > 0:
            time.sleep(remaining)

    def get(self, url: str) -> str:
        check_url(url, self._allowed)
        last_error: Exception | None = None
        for attempt in range(self._retries + 1):
            self._wait()
            self.request_count += 1
            try:
                log.info("GET %s", url)
                return self._inner.get(url)
            except Exception as e:
                last_error = e
                if "404" in str(e):
                    break
                log.warning("Fetch failed (attempt %d/%d) for %s: %s", attempt + 1, self._retries + 1, url, e)
                time.sleep(2 ** attempt * 3 if self._delay_range[1] > 0 else 0)
            finally:
                # Delay counts from when the previous response finished, not when it started.
                self._last_request = time.monotonic()
        assert last_error is not None
        raise last_error

    def close(self) -> None:
        self._inner.close()

    def __enter__(self) -> "PoliteFetcher":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


def make_fetcher(kind: str) -> Fetcher:
    if kind == "playwright":
        return PlaywrightFetcher()
    if kind == "http":
        return HttpFetcher()
    raise ValueError(f"Unknown fetcher: {kind}")
