"""
Scraper for Port Moresby power outage data.

IMPORTANT — read this before you plug this into production:

I checked www.pngpower.com.pg (and its old /index.php/... URLs, which
now redirect into the same app) while building this. The whole site
is a JavaScript-rendered app (built on Replit) that injects its
content after the page loads — there is no server-rendered HTML for
a plain `requests.get()` to see, on the outage pages OR the news
archive. I verified this directly, including re-checking after
initially hoping the news section might be older/static — it isn't.

Because of that, this scraper uses **Playwright** (a real headless
Chromium browser) to load the page, wait for its JavaScript to run,
and then read the fully-rendered HTML — the same thing your own
browser does when you visit the site. This is `fetch_png_power_outages()`
below.

One thing I could NOT do from my side: verify this against the real
pngpower.com.pg site, because my sandbox's network egress is
allowlisted and pngpower.com.pg isn't on it (confirmed: requests to it
get blocked with `host_not_allowed` before they even leave my
container). I built and tested the full Playwright pipeline against a
local mock page that behaves the same way (content injected via JS
after a delay) to confirm the harness itself — launching a browser,
waiting for content, reading the rendered DOM — genuinely works. But
I have not seen the real page's actual markup, so the CSS selectors
in `_parse_rendered_html()` below are an informed guess based on
common patterns (card/article-style layouts), not a confirmed match.

**What you need to do once, to finish this:** run the app locally
(where you have full internet access) and use the debug dump function
at the bottom of this file:

    python scraper.py --dump-html

This saves the real rendered HTML from both outage pages to
`debug_planned.html` and `debug_unplanned.html` in the project folder.
Open either one in a text editor or browser, find the repeating
element that wraps each outage entry (right-click → Inspect on the
live site works too), and update the CSS selector in
`_parse_rendered_html()` to match. Everything downstream — dedup,
notifications, the map, the API — already works off whatever that
function returns, so this is the only piece left.

If PNG Power's site has no outages at the time you run this, both
dump files will just show the "no outages" empty state, which is
still useful for confirming the selector for that case.
"""

import argparse
import random
import re
import logging
import shutil
from datetime import datetime, timedelta

import requests
from bs4 import BeautifulSoup

import config
import database
import notifications
import weather

import os
os.makedirs(config.LOG_DIR, exist_ok=True)

logging.basicConfig(
    filename=config.LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("scraper")


# --------------------------------------------------------------------------
# Browser rendering (Playwright)
# --------------------------------------------------------------------------

def _find_chrome_executable():
    """
    Playwright normally downloads its own Chromium via `playwright install`.
    If that's already been done, leave this returning None and Playwright
    will use its managed browser automatically. This fallback only matters
    in restricted environments where a system Chrome/Chromium is available
    but Playwright's own download step can't reach the internet.
    """
    for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser"):
        path = shutil.which(name)
        if path:
            return path
    return None


def render_page(url: str, wait_selector: str = None, timeout_ms: int = 20000) -> str:
    """
    Loads `url` in headless Chromium and returns the fully-rendered HTML,
    i.e. what you'd see via "Inspect Element" in a real browser -- not the
    raw server response. This is what lets us read JS-rendered sites like
    PNG Power's outage pages.

    `wait_selector`, if given, tells Playwright to wait until that element
    appears before grabbing the HTML (use this once you know the real CSS
    selector for an outage card -- see module docstring). Without it, we
    just wait for the network to go idle, which is a reasonable default.
    """
    from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

    try:
        with sync_playwright() as p:
            launch_kwargs = {"headless": True}
            chrome_path = _find_chrome_executable()
            if chrome_path:
                launch_kwargs["executable_path"] = chrome_path

            browser = p.chromium.launch(**launch_kwargs)
            page = browser.new_page(user_agent=config.REQUEST_HEADERS["User-Agent"])
            page.goto(url, timeout=timeout_ms, wait_until="networkidle")

            if wait_selector:
                try:
                    page.wait_for_selector(wait_selector, timeout=timeout_ms)
                except PlaywrightTimeout:
                    logger.warning(
                        f"Selector '{wait_selector}' never appeared on {url} "
                        "-- returning whatever rendered anyway."
                    )

            html = page.content()
            browser.close()
            return html
    except Exception as e:
        if "Executable doesn't exist" in str(e):
            logger.error(
                "Playwright's browser isn't installed. Run: "
                "playwright install chromium -- see README.md."
            )
        else:
            logger.error(f"Playwright render failed for {url}: {e}")
        return ""


# --------------------------------------------------------------------------
# Primary source: PNG Power
# --------------------------------------------------------------------------

def fetch_from_api(api_url: str) -> list:
    """
    If you find PNG Power's underlying JSON endpoint via browser DevTools
    (Network -> XHR/Fetch), use this instead of the Playwright path -- it's
    faster and lighter. Adjust the field names below to match whatever the
    real API actually returns.
    """
    try:
        resp = requests.get(api_url, headers=config.REQUEST_HEADERS,
                             timeout=config.REQUEST_TIMEOUT_SECONDS)
        resp.raise_for_status()
        payload = resp.json()
    except Exception as e:
        logger.error(f"API fetch failed for {api_url}: {e}")
        return []

    records = []
    for item in payload.get("data", []):
        records.append(_normalise_record(
            suburb=item.get("suburb") or item.get("location"),
            area=item.get("area"),
            status=item.get("status"),
            outage_type=item.get("type"),
            reason=item.get("reason") or item.get("cause"),
            time_started=item.get("start_time"),
            estimated_restoration=item.get("eta") or item.get("estimated_restoration"),
            date=item.get("date"),
            source="PNG Power",
            source_url=api_url,
        ))
    return records


def _parse_rendered_html(html: str, url: str) -> list:
    """
    Parses the fully-rendered HTML of a PNG Power outage page. The
    selectors here (`.outage-card, article, li.outage, tr`) are a
    reasonable guess at common card/list/table layouts, informed-but-
    unconfirmed against the real site -- see the module docstring for
    why, and use `python scraper.py --dump-html` to check and fix this
    against the real markup.
    """
    if not html:
        return []

    soup = BeautifulSoup(html, "html.parser")
    candidates = soup.select(
        ".outage-card, .outage-item, .outage, article, li.outage, tr"
    )

    records = []
    for card in candidates:
        text = card.get_text(separator=" ", strip=True)
        if not text:
            continue

        suburb = _extract_suburb(text)
        if not suburb:
            continue

        is_planned = (
            "/planned" in url and "/unplanned" not in url
        ) or "scheduled" in text.lower() or "maintenance" in text.lower()
        records.append(_normalise_record(
            suburb=suburb,
            area=None,
            status="Planned" if is_planned else "Active",
            outage_type="Planned Maintenance" if is_planned else "Emergency",
            reason=_extract_reason(text),
            time_started=_extract_time(text),
            estimated_restoration=None,
            date=datetime.utcnow().date().isoformat(),
            source="PNG Power",
            source_url=url,
        ))
    return records


def fetch_png_power_outages() -> list:
    """
    Renders each configured PNG Power outage page with a real headless
    browser (so its JavaScript actually runs) and parses the result.
    This is the main entry point the scraper uses -- see module
    docstring for the one remaining step (confirming/fixing the CSS
    selector against the real site).
    """
    all_records = []
    for source_name, url in config.SOURCES.items():
        html = render_page(url, wait_selector=None, timeout_ms=config.PLAYWRIGHT_TIMEOUT_MS)
        records = _parse_rendered_html(html, url)
        if not records:
            logger.info(
                f"No outage entries parsed from {url} -- either there are "
                "genuinely no current outages, or the CSS selector needs "
                "adjusting (run `python scraper.py --dump-html` to check)."
            )
        all_records.extend(records)
    return all_records


# --------------------------------------------------------------------------
# Additional sources: local news (used to corroborate major outages)
# --------------------------------------------------------------------------

def fetch_network_map_summary() -> dict:
    """
    PNG Power's /network-map page (their "National Grid Intelligence
    Platform") shows aggregate counts as rendered text: "Active 3",
    "Upcoming 7", "Maintenance 2", plus a separate Projects breakdown.
    This was confirmed from a real saved copy of that page -- the counts
    appear as plain text after JS renders, which is exactly what
    render_page() below captures.

    This does NOT give per-suburb detail (no outage list, no locations) --
    that's very likely rendered as map pins backed by a JSON API we
    haven't identified yet (see module docstring: run
    `python scraper.py --dump-html` and inspect Network/XHR in DevTools
    to find it). Until then, this function gets you real national
    totals, which is strictly better than nothing and completely honest
    about what it is: a summary, not a location-level feed.

    Returns None if the page didn't render as expected (structure may
    have changed, or the numbers weren't where this regex expects them).
    """
    html = render_page(config.NETWORK_MAP_URL, timeout_ms=config.PLAYWRIGHT_TIMEOUT_MS)
    if not html:
        return None

    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(separator=" ", strip=True)

    patterns = {
        "active": r"Active\s+(\d+)",
        "upcoming": r"Upcoming\s+(\d+)",
        "maintenance": r"Maintenance\s+(\d+)",
    }
    summary = {}
    for key, pattern in patterns.items():
        match = re.search(pattern, text)
        if match:
            summary[key] = int(match.group(1))

    if not summary:
        logger.warning(
            "Could not find Active/Upcoming/Maintenance counts on the "
            "network-map page -- its structure may have changed since "
            "this was written. Run `python scraper.py --dump-html` to check."
        )
        return None

    summary["fetched_at"] = datetime.utcnow().isoformat(timespec="seconds")
    summary["source_url"] = config.NETWORK_MAP_URL
    return summary


def fetch_news_confirmations(query: str = "power outage Port Moresby") -> list:
    """
    Placeholder for checking reputable local news sites (Post-Courier,
    NBC PNG, The National) for confirmation of major outages. Each of
    these sites has its own markup, so this needs a per-site parser
    once you decide which to support. Returns an empty list for now --
    wire this up the same way as fetch_png_power_outages() once you've
    picked a target site and inspected its markup.
    """
    logger.info("fetch_news_confirmations() is a stub -- no site wired up yet.")
    return []


# --------------------------------------------------------------------------
# Debug helper: dump real rendered HTML so selectors can be tuned by hand
# --------------------------------------------------------------------------

def dump_rendered_html():
    """
    Renders each configured PNG Power page (plus the network-map/NGIP
    page) with Playwright and saves the result to disk. Run this once
    from a machine with real internet access (`python scraper.py
    --dump-html`), then open the saved files to find the real repeating
    element for each outage entry and update the CSS selector in
    `_parse_rendered_html()` above.
    """
    for name, url in config.SOURCES.items():
        print(f"Rendering {name} ({url})...")
        html = render_page(url, timeout_ms=config.PLAYWRIGHT_TIMEOUT_MS)
        out_path = f"debug_{name}.html"
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(html or "<!-- render failed, check logs/app.log -->")
        print(f"  Saved to {out_path} ({len(html)} chars)")

    print(f"Rendering network_map ({config.NETWORK_MAP_URL})...")
    html = render_page(config.NETWORK_MAP_URL, timeout_ms=config.PLAYWRIGHT_TIMEOUT_MS)
    with open("debug_network_map.html", "w", encoding="utf-8") as f:
        f.write(html or "<!-- render failed, check logs/app.log -->")
    print(f"  Saved to debug_network_map.html ({len(html)} chars)")

    print(
        "\nOpen the saved files and find the element that wraps each "
        "outage entry, then update the selector in "
        "_parse_rendered_html() in scraper.py. For debug_network_map.html, "
        "look for a JSON request in your browser's Network/XHR tab while "
        "viewing the live page -- that's the real per-suburb data source, "
        "if one exists."
    )


# --------------------------------------------------------------------------
# Parsing helpers
# --------------------------------------------------------------------------

def _extract_suburb(text: str) -> str:
    for suburb in config.SUBURBS:
        if suburb.lower() in text.lower():
            return suburb
    return None


def _extract_time(text: str) -> str:
    match = re.search(r"\b(\d{1,2}[:.]\d{2}\s?(?:am|pm|AM|PM)?)\b", text)
    return match.group(1) if match else None


def _extract_reason(text: str) -> str:
    keywords = ["transformer", "maintenance", "fault", "storm", "upgrade",
                "vegetation", "cable", "substation", "pole", "line", "voltage"]
    lowered = text.lower()
    for kw in keywords:
        if kw not in lowered:
            continue
        idx = lowered.index(kw)
        # Expand outward to the nearest sentence-ish boundary rather than
        # cutting mid-word, so we don't return fragments like "duled
        # maintenance" from the middle of "scheduled maintenance".
        start = max(0, text.rfind(".", 0, idx) + 1 if text.rfind(".", 0, idx) != -1 else 0)
        end = text.find(".", idx)
        end = end + 1 if end != -1 else min(len(text), idx + 60)
        snippet = text[start:end].strip()
        return snippet if snippet else None
    return None


def _normalise_record(suburb, area, status, outage_type, reason,
                       time_started, estimated_restoration, date,
                       source, source_url) -> dict:
    coords = config.SUBURBS.get(suburb, {})
    external_ref = f"{source}:{suburb}:{date}:{time_started or 'na'}:{reason or 'na'}"

    return {
        "suburb": suburb,
        "area": area,
        "date": date,
        "time_started": time_started,
        "status": status,
        "outage_type": outage_type,
        "reason": reason,
        "estimated_restoration": estimated_restoration,
        "source": source,
        "source_url": source_url,
        "latitude": coords.get("lat"),
        "longitude": coords.get("lon"),
        "external_ref": external_ref,
    }


# --------------------------------------------------------------------------
# Demo data (keeps the app fully usable while the real scraper is stubbed)
# --------------------------------------------------------------------------

def generate_demo_data() -> list:
    """
    Produces a handful of realistic-looking outage records so the map,
    search, and stats dashboard have something to render out of the
    box. Safe to delete once the real scraper is producing live data --
    just remove the call to this function in run_scraper().
    """
    reasons_emergency = ["Transformer fault", "Fallen power line", "Storm damage",
                          "Cable fault", "Substation trip"]
    reasons_planned = ["Scheduled maintenance", "Network upgrade",
                        "Vegetation clearance", "Pole replacement"]

    records = []
    now = datetime.utcnow()

    for i in range(6):
        suburb = random.choice(list(config.SUBURBS.keys()))
        is_emergency = random.random() > 0.5
        started = now - timedelta(hours=random.randint(0, 5))
        eta = started + timedelta(hours=random.randint(1, 4))

        records.append(_normalise_record(
            suburb=suburb,
            area=None,
            status=random.choice(["Active", "Active", "Restored"]),
            outage_type="Emergency" if is_emergency else "Planned Maintenance",
            reason=random.choice(reasons_emergency if is_emergency else reasons_planned),
            time_started=started.strftime("%H:%M"),
            estimated_restoration=eta.strftime("%H:%M"),
            date=started.date().isoformat(),
            source="Demo data" ,
            source_url=None,
        ))

    return records


# --------------------------------------------------------------------------
# Entry point used by scheduler.py and the manual "Update now" admin button
# --------------------------------------------------------------------------

def run_scraper() -> dict:
    """
    Runs the full collection pass: PNG Power, then news corroboration,
    saves everything via database.upsert_outage, and returns a summary
    dict. This is the function the scheduler calls every N minutes.
    """
    logger.info("Starting scraper run")
    records = fetch_png_power_outages()
    records += fetch_news_confirmations()

    national_summary = fetch_network_map_summary()
    if national_summary:
        database.set_national_summary(
            active=national_summary.get("active"),
            upcoming=national_summary.get("upcoming"),
            maintenance=national_summary.get("maintenance"),
            source_url=national_summary.get("source_url"),
        )
        logger.info(f"National summary updated: {national_summary}")

    used_demo_data = False
    if not records:
        logger.info("No live records found -- generating demo data instead")
        records = generate_demo_data()
        used_demo_data = True

    inserted_or_updated = 0
    for record in records:
        try:
            result = database.upsert_outage(record)
            inserted_or_updated += 1

            if result["is_new"] and config.ENABLE_WEATHER:
                w = weather.get_weather_for_suburb(record["suburb"])
                if w:
                    database.set_weather_snapshot(result["id"], w)

            subscribers = database.get_subscribers_for_suburb(record["suburb"])
            if subscribers:
                saved = database.get_outage(result["id"])
                if result["is_new"] and saved.get("status") != "Restored":
                    notifications.notify_subscribers(saved, subscribers, event="new")
                elif result["status_changed_to_restored"]:
                    notifications.notify_subscribers(saved, subscribers, event="restored")
        except Exception as e:
            logger.error(f"Failed to save record {record}: {e}")

    summary = {
        "timestamp": datetime.utcnow().isoformat(timespec="seconds"),
        "records_processed": inserted_or_updated,
        "used_demo_data": used_demo_data,
    }
    logger.info(f"Scraper run complete: {summary}")
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="PNG Power outage scraper")
    parser.add_argument(
        "--dump-html", action="store_true",
        help="Render the real outage pages and save their HTML to disk for inspection, "
             "instead of running a normal scrape."
    )
    args = parser.parse_args()

    if args.dump_html:
        dump_rendered_html()
    else:
        database.init_db()
        print(run_scraper())
