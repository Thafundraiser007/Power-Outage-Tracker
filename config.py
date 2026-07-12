"""
Central configuration for the Port Moresby Power Outage Tracker.
Keep secrets, paths, and tunable settings here so nothing is hardcoded
deep inside app logic.
"""

import os

# Load a local .env file if present (see .env.example) -- lets you keep
# secrets out of your shell history / hosting dashboard while developing.
# Safe to skip entirely: if python-dotenv isn't installed or there's no
# .env file, this just does nothing and env vars/defaults still work.
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

# --- Paths -------------------------------------------------------------
DATABASE_PATH = os.path.join(BASE_DIR, "data", "outages.db")
LOG_DIR = os.path.join(BASE_DIR, "logs")
LOG_FILE = os.path.join(LOG_DIR, "app.log")

# --- Flask ---------------------------------------------------------------
SECRET_KEY = os.environ.get("SECRET_KEY", "dev-key-change-this-in-production")
DEBUG = os.environ.get("FLASK_DEBUG", "1") == "1"

# --- Admin (very simple protection for the manual-entry page) -----------
# For a real deployment, replace this with proper auth (Flask-Login, etc).
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "changeme")

# --- Scraper / scheduler --------------------------------------------------
# How often the automatic updater runs, in minutes.
UPDATE_INTERVAL_MINUTES = int(os.environ.get("UPDATE_INTERVAL_MINUTES", "30"))

# Data sources. NOTE: the PNG Power site currently renders its outage
# listings client-side (JavaScript), so a plain requests+BeautifulSoup
# fetch will not see the outage content in the raw HTML. See the big
# comment at the top of scraper.py for what to do about that -- this
# repo ships with a working scraper *architecture* plus a mock data
# generator so the rest of the app can be built and demoed today.
SOURCES = {
    "png_power_planned": "https://www.pngpower.com.pg/outages/planned",
    "png_power_unplanned": "https://www.pngpower.com.pg/outages/unplanned",
}

# Discovered from a saved copy of PNG Power's site: this is their "National
# Grid Intelligence Platform" (NGIP), a live map showing aggregate counts
# (Active/Upcoming/Maintenance/Restored outages, plus a Projects layer).
# It doesn't expose per-suburb detail in the static page text -- that's
# likely rendered as map pins requiring a JSON API we haven't found yet
# (see scraper.py's fetch_network_map_summary docstring) -- but the
# national totals are real and worth showing.
NETWORK_MAP_URL = "https://pngpower.com.pg/network-map"

REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; PortMoresbyOutageTracker/1.0; "
        "+https://github.com/yourusername/power-outage-tracker)"
    )
}
REQUEST_TIMEOUT_SECONDS = 15

# How long the Playwright browser will wait for a page to finish loading
# (including its JavaScript) before giving up, in milliseconds.
PLAYWRIGHT_TIMEOUT_MS = int(os.environ.get("PLAYWRIGHT_TIMEOUT_MS", "20000"))

# --- Suburbs -------------------------------------------------------------
# Approximate central coordinates for each tracked suburb, used to place
# markers on the Leaflet map and to resolve free-text suburb names scraped
# from source pages into a known location.
SUBURBS = {
    "Boroko":    {"lat": -9.4667, "lon": 147.1833},
    "Gerehu":    {"lat": -9.4167, "lon": 147.1333},
    "Gordons":   {"lat": -9.4744, "lon": 147.1758},
    "Waigani":   {"lat": -9.4453, "lon": 147.1811},
    "Tokarara":  {"lat": -9.4425, "lon": 147.1594},
    "Hohola":    {"lat": -9.4658, "lon": 147.1717},
    "Badili":    {"lat": -9.4869, "lon": 147.1783},
    "Town":      {"lat": -9.4780, "lon": 147.1500},
    "Six Mile":  {"lat": -9.4408, "lon": 147.2094},
    "Eight Mile":{"lat": -9.4300, "lon": 147.2350},
    "Nine Mile": {"lat": -9.4200, "lon": 147.2500},
}

# Default map center = Port Moresby
MAP_CENTER = {"lat": -9.4438, "lon": 147.1803}
MAP_DEFAULT_ZOOM = 12

# Valid values for outage records, used for validation everywhere.
# "Reported" -> "Under Review" -> "Verified" -> "Active" -> "Restored" is the
# pipeline a user-submitted report moves through. "Planned" is separate --
# it's for official scheduled maintenance, which skips verification since
# it comes from PNG Power directly (scraper or admin entry), not the public.
VALID_STATUSES = ["Reported", "Under Review", "Verified", "Active", "Planned", "Restored"]
VALID_TYPES = ["Emergency", "Planned Maintenance"]

# --- Notifications ---------------------------------------------------------
# EMAIL: works out of the box with any real SMTP account (Gmail, Outlook,
# your own mail server, SendGrid's SMTP relay, etc). Nothing to buy.
# Gmail users: you need an "App Password", not your normal login password
# -- https://myaccount.google.com/apppasswords (requires 2FA enabled).
EMAIL_HOST = os.environ.get("EMAIL_HOST", "smtp.gmail.com")
EMAIL_PORT = int(os.environ.get("EMAIL_PORT", "587"))
EMAIL_USER = os.environ.get("EMAIL_USER", "")
EMAIL_PASSWORD = os.environ.get("EMAIL_PASSWORD", "")
EMAIL_FROM = os.environ.get("EMAIL_FROM", EMAIL_USER)
# Notifications are only sent if EMAIL_USER/EMAIL_PASSWORD are actually set.
ENABLE_EMAIL_NOTIFICATIONS = bool(EMAIL_USER and EMAIL_PASSWORD)

# SMS: unlike email, there's no free way to send real text messages --
# every provider (Twilio, Vonage, AWS SNS...) is a paid API. This project
# is wired up for Twilio since it's the most common choice, but it will
# only activate once you've created a Twilio account and set these three
# variables. Until then, SMS sends are logged (not actually sent) so the
# rest of the app keeps working.
TWILIO_ACCOUNT_SID = os.environ.get("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN", "")
TWILIO_FROM_NUMBER = os.environ.get("TWILIO_FROM_NUMBER", "")
ENABLE_SMS_NOTIFICATIONS = bool(
    TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN and TWILIO_FROM_NUMBER
)

SITE_NAME = "Port Moresby Power Outage Tracker"
# Used to build unsubscribe links in notification emails -- update this to
# your real deployed URL once you have one.
SITE_BASE_URL = os.environ.get("SITE_BASE_URL", "http://127.0.0.1:5000")

# --- Weather (OpenWeather) --------------------------------------------------
# Used to snapshot weather conditions alongside each outage, so patterns
# like "storms correlate with outages in X suburb" become visible over time.
OPENWEATHER_API_KEY = os.environ.get("OPENWEATHER_API_KEY", "")
ENABLE_WEATHER = bool(OPENWEATHER_API_KEY)
OPENWEATHER_BASE_URL = "https://api.openweathermap.org/data/2.5/weather"

# --- Geocoding (LocationIQ) -------------------------------------------------
# Lets users type a free-text address ("Gordons Market") when reporting an
# outage instead of only picking from the fixed suburb list.
LOCATIONIQ_API_KEY = os.environ.get("LOCATIONIQ_API_KEY", "")
ENABLE_GEOCODING = bool(LOCATIONIQ_API_KEY)
LOCATIONIQ_BASE_URL = "https://us1.locationiq.com/v1/search"

# --- Email via Resend --------------------------------------------------
# Alternative to the SMTP-based email in notifications.py -- Resend is a
# simple HTTP API (no app passwords / SMTP setup needed). If both this and
# EMAIL_USER/PASSWORD are set, Resend takes priority since it's simpler
# and more reliable for transactional mail.
RESEND_API_KEY = os.environ.get("RESEND_API_KEY", "")
RESEND_FROM_ADDRESS = os.environ.get("RESEND_FROM_ADDRESS", "onboarding@resend.dev")
ENABLE_RESEND = bool(RESEND_API_KEY)

# --- User accounts -----------------------------------------------------
# Users can register, log in, save favourite suburbs, and get notified for
# just those -- on top of (not replacing) the anonymous email/SMS subscribe
# flow already in place.
SESSION_COOKIE_NAME = "outage_tracker_session"

# --- Outage verification workflow ---------------------------------------
# Public reports start as "Reported" and move through this pipeline (a
# subset of VALID_STATUSES -- excludes "Planned", which is official-only).
# Only an admin action (or enough independent reports) promotes a record to
# "Active", which is what actually shows on the public map by default.
REPORT_STATUSES = ["Reported", "Under Review", "Verified", "Active", "Restored"]

# Confidence score weights (see database.recalculate_confidence)
CONFIDENCE_PER_REPORT = 5
CONFIDENCE_ADMIN_VERIFIED = 50
CONFIDENCE_MULTI_REPORT_BONUS = 20  # awarded once, if 2+ independent reports exist
CONFIDENCE_MAX = 100

# Reports within this many minutes of each other, for the same suburb, are
# treated as the same real-world incident rather than separate outages.
DUPLICATE_REPORT_WINDOW_MINUTES = 120
