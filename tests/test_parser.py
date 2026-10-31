from datetime import date
from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from scraper.parser import (
    StructureChangedError,
    parse_details_page,
    parse_gmp_page,
    parse_history_date,
    parse_listing,
    parse_percent,
    parse_rupees,
    parse_trend,
    slug_from_url,
)

FIXTURES = Path(__file__).parent / "fixtures"
TODAY = date(2026, 10, 31)


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def cell(html: str):
    return BeautifulSoup(f"<table><tr>{html}</tr></table>", "lxml").find("td")


def test_slug_from_url_handles_both_url_patterns():
    assert slug_from_url("/quatevel-coated-special-steels-ipo-gmp-grey-market-premium/") == "quatevel-coated-special-steels"
    assert slug_from_url("https://ipowatch.in/shivelro-poly-fabs-ipo-gmp-today/") == "shivelro-poly-fabs"
    assert slug_from_url("https://ipowatch.in/zoroqua-india-ipo/") == "zoroqua-india"


@pytest.mark.parametrize("text,expected", [("₹247", 247), ("₹-12", -12), ("₹1,250", 1250), ("₹-", None), ("", None)])
def test_parse_rupees(text, expected):
    assert parse_rupees(text) == expected


@pytest.mark.parametrize("text,expected", [("22.07%", 22.07), ("-3.5%", -3.5), ("-%", None)])
def test_parse_percent(text, expected):
    assert parse_percent(text) == expected


@pytest.mark.parametrize(
    "html,expected",
    [
        ("<td>🟢</td>", "up"),
        ("<td>🔴</td>", "down"),
        ("<td>🟡</td>", "flat"),
        ("<td>–</td>", None),
        ('<td><span class="dot green"></span></td>', "up"),
        ('<td><span class="trend-down"></span></td>', "down"),
        ('<td><span style="background-color: #dc3545"></span></td>', "down"),
        ('<td><i style="color:green;">●</i></td>', "up"),
        ('<td class="has-text-align-center">–</td>', None),
    ],
)
def test_parse_trend_from_emoji_class_and_style(html, expected):
    assert parse_trend(cell(html)) == expected


def test_history_date_infers_year_across_new_year():
    assert parse_history_date("28 October", TODAY) == date(2026, 10, 28)
    assert parse_history_date("30 December", date(2027, 1, 2)) == date(2026, 12, 30)
    assert parse_history_date("2 January", date(2027, 1, 2)) == date(2027, 1, 2)
    assert parse_history_date("garbage", TODAY) is None


def test_parse_listing_page():
    entries = parse_listing(fixture("ipowatch_gmp_listing.html"))
    by_slug = {e.slug: e for e in entries}
    assert len(entries) == 15
    quatevel = by_slug["quatevel-coated-special-steels"]
    assert quatevel.name == "Quatevel Coated and Special Steels"
    assert quatevel.category == "mainboard"
    assert quatevel.site_status == "Open"
    assert quatevel.gmp_url == "https://ipowatch.in/quatevel-coated-special-steels-ipo-gmp-grey-market-premium/"
    assert by_slug["shivelro-poly-fabs"].category == "sme"
    assert by_slug["shivelro-poly-fabs"].site_status == "Upcoming"
    # Malformed nested markup in this row still yields a clean status
    assert by_slug["tanfi-fine-ornaments"].site_status == "Closed"


def test_homepage_ignores_non_gmp_tables():
    entries = parse_listing(fixture("ipowatch_homepage.html"))
    assert entries and all("gmp" in e.gmp_url for e in entries)


def test_parse_gmp_page():
    rows, details_url = parse_gmp_page(fixture("ipowatch_gmp_page.html"), TODAY)
    assert details_url == "https://ipowatch.in/quatevel-coated-special-steels-ipo/"
    latest = rows[0]
    assert latest.date == date(2026, 10, 31)
    assert (latest.gmp, latest.trend, latest.gain_pct, latest.last_updated) == (7, "down", 8.54, "09:10")
    assert rows[1].date == date(2026, 10, 30) and rows[1].gmp == 9 and rows[1].trend == "up"
    assert [r.date for r in rows] == sorted((r.date for r in rows), reverse=True)


def test_parse_gmp_page_without_gmp_yet():
    rows, _ = parse_gmp_page(fixture("ipowatch_gmp_page_no_gmp.html"), TODAY)
    assert rows and all(r.gmp is None and r.trend is None and r.gain_pct is None for r in rows)


def test_gmp_page_missing_table_raises():
    with pytest.raises(StructureChangedError):
        parse_gmp_page("<html><body><p>Redesigned!</p></body></html>", TODAY)


def test_missing_trend_derived_from_previous_day():
    html = """<table>
      <tr><th>Date</th><th>IPO GMP</th><th>GMP Trend</th><th>Gain</th><th>Last Updated</th></tr>
      <tr><td>31 October</td><td>₹12</td><td></td><td>5%</td><td>09:10</td></tr>
      <tr><td>30 October</td><td>₹10</td><td></td><td>4%</td><td>17:00</td></tr>
      <tr><td>29 October</td><td>₹10</td><td>🔴</td><td>4%</td><td>17:00</td></tr>
    </table>"""
    rows, _ = parse_gmp_page(html, TODAY)
    assert [r.trend for r in rows] == ["up", "flat", "down"]


def test_parse_details_page():
    meta = parse_details_page(fixture("ipowatch_details_page.html"))
    assert meta.open_date == date(2026, 10, 29)
    assert meta.close_date == date(2026, 11, 2)
    assert meta.listing_date == date(2026, 11, 5)
    assert (meta.price_band_min, meta.price_band_max) == (78, 82)
    assert meta.lot_size == 182


def test_polite_fetcher_delays_after_response_completes():
    import time
    from scraper.fetcher import PoliteFetcher

    class Slow:
        def get(self, url):
            time.sleep(0.2)
            return "ok"

        def close(self):
            pass

    f = PoliteFetcher(Slow(), delay_range=(0.3, 0.3), retries=0)
    start = time.monotonic()
    f.get("https://ipowatch.in/a")
    f.get("https://ipowatch.in/b")
    assert time.monotonic() - start >= 0.2 + 0.3 + 0.2


def test_parse_date_range_infers_months_and_years():
    from scraper.parser import parse_date_range

    assert parse_date_range("27-29 October", TODAY) == (date(2026, 10, 27), date(2026, 10, 29))
    assert parse_date_range("29-2 November", TODAY) == (date(2026, 10, 29), date(2026, 11, 2))
    assert parse_date_range("30-2 January", date(2026, 12, 28)) == (date(2026, 12, 30), date(2027, 1, 2))
    assert parse_date_range("TBA", TODAY) is None
    # Old calendar rows stay in the past instead of jumping to next year
    assert parse_date_range("24-26 February", TODAY) == (date(2026, 2, 24), date(2026, 2, 26))
    assert parse_date_range("1-3 December", TODAY) == (date(2026, 12, 1), date(2026, 12, 3))


def test_parse_upcoming_calendar_keeps_only_not_yet_closed():
    from scraper.parser import parse_upcoming_calendar

    entries = {e.slug: e for e in parse_upcoming_calendar(fixture("ipowatch_upcoming_calendar.html"), TODAY)}
    assert entries["shivelro-poly-fabs"].site_status == "Upcoming"
    assert entries["shivelro-poly-fabs"].category == "sme"
    assert entries["shivelro-poly-fabs"].details_url == "https://ipowatch.in/shivelro-poly-fabs-ipo/"
    quatevel = entries["quatevel-coated-special-steels"]
    assert (quatevel.site_status, quatevel.category) == ("Open", "mainboard")
    assert (quatevel.open_date, quatevel.close_date) == (date(2026, 10, 29), date(2026, 11, 2))
    assert all(e.gmp_url is None and e.from_calendar for e in entries.values())
    assert "tanfi-fine-ornaments" not in entries  # closed 30 Oct
    assert "velte-platforms" not in entries


def test_upcoming_calendar_old_january_rows_stay_in_the_past():
    from scraper.parser import parse_upcoming_calendar

    html = """<h2>Mainboard</h2><table>
      <tr><th>Company</th><th>IPO Date</th></tr>
      <tr><td><a href="/new-ipo/">New</a></td><td>3-5 November</td></tr>
      <tr><td><a href="/mid-ipo/">Mid</a></td><td>20-22 October</td></tr>
      <tr><td><a href="/old-ipo/">Old</a></td><td>20-22 January</td></tr>
    </table>"""
    entries = parse_upcoming_calendar(html, TODAY)
    assert [(e.slug, e.close_date) for e in entries] == [("new", date(2026, 11, 5))]
    # Late December: a newly announced January IPO at the top is next year's
    dec = parse_upcoming_calendar(html.replace("3-5 November", "5-7 January"), date(2026, 12, 28))
    assert [(e.slug, e.close_date) for e in dec] == [("new", date(2027, 1, 7))]


def test_find_gmp_link_on_details_page():
    from scraper.parser import find_gmp_link

    assert find_gmp_link(fixture("ipowatch_details_page.html")) == "https://ipowatch.in/quatevel-coated-special-steels-ipo-gmp-today/"
    assert find_gmp_link("<html></html>") is None


def test_details_page_about_section():
    meta = parse_details_page(fixture("ipowatch_details_page.html"))
    assert meta.about.startswith("Founded in 1992, Quatevel Coated & Special Steels is one of the leading steel producers.")
    assert "\n\n" in meta.about  # paragraphs kept apart
    assert parse_details_page("<table><tr><td>IPO Open Date</td><td>May 1, 2026</td></tr></table>").about == ""


def test_summarize_keeps_whole_sentences():
    from common.text import summarize

    text = ("Founded in 1992, Acme makes steel coils for appliance makers. It runs four plants in Maharashtra. "
            "Its customers include large OEMs across India and abroad, served from regional depots.")
    assert summarize(text) == text
    assert summarize(text, max_chars=120) == "Founded in 1992, Acme makes steel coils for appliance makers. It runs four plants in Maharashtra."
    assert summarize("word " * 100).endswith("…") and len(summarize("word " * 100)) <= 220
    assert summarize("") is None and summarize(None) is None



def test_investorgain_live_list():
    from scraper import investorgain

    entries = {e.slug: e for e in investorgain.parse_live(fixture("investorgain_live.html"), TODAY)}
    assert len(entries) == 14  # active only: Tedorbri (listed 30 Oct) and older rows are dropped
    assert "tedorbri-engineers" not in entries
    v = entries["shivelro-poly-fabs"]
    assert (v.status, v.category, v.gmp, v.gain_pct, v.price, v.lot_size) == ("upcoming", "sme", 4, 4.52, 94, 1200)
    assert (v.open_date, v.close_date, v.listing_date) == (date(2026, 11, 2), date(2026, 11, 4), date(2026, 11, 9))
    assert entries["zoroqua-india"].open_date == date(2026, 10, 30)  # "30-Oct GMP: 30" annotation ignored
    assert entries["quatevel-coated-and-special-steels"].category == "mainboard"
    assert entries["brimi-nerzo"].gmp is None
    assert entries["tanfi-fine-ornaments"].status == "current"  # closed, awaiting listing


def test_investorgain_daily_trend():
    from scraper import investorgain

    rows = investorgain.parse_daily_trend(fixture("investorgain_ipo_page.html"), TODAY)
    assert [(r.date, r.gmp, r.gain_pct, r.trend) for r in rows] == [
        (date(2026, 10, 31), 30, 25.0, "flat"),
        (date(2026, 10, 30), 30, 25.0, None),  # "Initial"
    ]


def test_investorgain_matching_to_ipowatch_names():
    from scraper.investorgain import IgEntry, find_match

    def ig(name, slug):
        return IgEntry(name, slug, "", "mainboard", "current", None, None, None, None, None, None, None)

    ipowatch = {
        "quatevel-coated-special-steels": "Quatevel Coated and Special Steels",
        "velrosa-engineering-solutions": "Velrosa Engineering",
        "tanfi-fine-ornaments": "Tan.Fi Fine Ornaments",
        "zoroqua-india": "ZOROQUA (India)",
    }
    assert find_match(ig("Quatevel Coated and Special Steels", "quatevel-coated-and-special-steels"), ipowatch) == "quatevel-coated-special-steels"
    assert find_match(ig("Velrosa Engineering Solutions", "velrosa-engineering-solutions"), ipowatch) == "velrosa-engineering-solutions"
    assert find_match(ig("Tan.Fi Fine Ornaments", "tanfi-fine-ornaments"), ipowatch) == "tanfi-fine-ornaments"
    assert find_match(ig("Velrosa Pharma", "velrosa-pharma"), ipowatch) is None
    assert find_match(ig("Briqua Imaging India", "briqua-imaging-india"), ipowatch) is None


def test_fetcher_refuses_off_site_urls():
    from scraper.fetcher import DisallowedURL, FileFetcher, PoliteFetcher, check_url

    f = PoliteFetcher(FileFetcher({}), delay_range=(0, 0), retries=0)
    for bad in ["http://ipowatch.in/x", "https://evil.example/x", "https://ipowatch.in.evil.example/",
                "https://user@ipowatch.in/", "https://ipowatch.in:8443/", "file:///etc/passwd", "https://169.254.169.254/"]:
        with pytest.raises(DisallowedURL):
            f.get(bad)
    check_url("https://ipowatch.in/ipo-gmp/")
    check_url("https://www.investorgain.com/report/live-ipo-gmp/331/")


def test_parsers_drop_off_site_links():
    html = """<h2>Current Mainboard IPO</h2><table>
      <tr><th>Company</th><th>GMP*</th></tr>
      <tr><td><a href="https://evil.example/fake-ipo-gmp-today/">Fake</a></td><td>₹9</td></tr>
      <tr><td><a href="/real-ipo-gmp-today/">Real</a></td><td>₹9</td></tr></table>"""
    assert [e.slug for e in parse_listing(html)] == ["real"]
    from scraper.parser import find_gmp_link
    assert find_gmp_link('<div class="ipo-tabs-bar"><a href="https://evil.example/x-ipo-gmp/">GMP</a></div>') is None



def test_groww_list_and_name_matching():
    from scraper.brokers import is_groww_ipo_url, parse_groww_list
    from scraper.investorgain import match_name

    listing = {gid: (name, url) for name, gid, url in parse_groww_list(fixture("groww_ipo_list.html"))}
    assert listing["zoroqua-india-ipo"][1] == "https://groww.in/ipo/zoroqua-india-ipo"
    ours = {"velrosa-engineering-solutions": "Velrosa Engineering", "quatevel-coated-special-steels": "Quatevel Coated and Special Steels",
            "tanfi-fine-ornaments": "Tan.Fi Fine Ornaments", "zoroqua-india": "ZOROQUA (India)", "shivelro-poly-fabs": "Shivelro Poly Fabs"}
    assert match_name("Velrosa Engineering", "velrosa-engineering", ours) == "velrosa-engineering-solutions"
    assert match_name("Quatevel Coated & Special Steels", "quatevel-coated-and-special-steels", ours) == "quatevel-coated-special-steels"
    assert match_name("Tan. Fi Fine Ornaments", "tanfi-fine-ornaments", ours) == "tanfi-fine-ornaments"
    assert match_name("Shivelro Poly Fabs Solutions", "shivelro-poly-fabs", ours) == "shivelro-poly-fabs"
    assert match_name("Kasaqua", "kasaqua", ours) is None
    # Only well-formed Groww IPO links are ever exposed
    assert is_groww_ipo_url("https://groww.in/ipo/zoroqua-india-ipo")
    for bad in ["https://evil.example/ipo/x", "javascript:alert(1)", "https://groww.in/ipo/../../x", "https://groww.in/ipo/", None]:
        assert not is_groww_ipo_url(bad)
    hostile = '<script id="__NEXT_DATA__">{"props":{"pageProps":{"openDataList":[{"companyName":"X","searchId":"../../evil"},{"companyName":"Y","searchId":"javascript:alert(1)"}]}}}</script>'
    assert parse_groww_list(hostile) == []
    assert parse_groww_list("<html>no data</html>") == []
