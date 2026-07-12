# Port Moresby Power Outage Tracker

A Flask + MapLibre GL JS web app that tracks power outages across Port Moresby
suburbs on an interactive map, with search, a stats dashboard, and an
admin page for manually-verified updates.

## Quick start

```bash
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium     # downloads the headless browser the scraper uses
python app.py
```

Then open http://127.0.0.1:5000

Default admin password is `changeme` (set via the `ADMIN_PASSWORD`
environment variable before deploying anywhere real — see below).

## A note on API keys

This project's `.env` currently has real API keys in it (OpenWeather,
LocationIQ, Resend, Twilio SID/token). They were shared in a chat
conversation, which means they should be treated as semi-exposed —
regenerate the Twilio auth token in particular (it can be used to send
paid SMS) once you're confident nobody else has them. `.env` is
gitignored, so it won't get committed, but it's still worth rotating
anything that passed through a chat log.

Facebook's API isn't wired up here at all, deliberately — Meta doesn't
allow reading posts from a Facebook page you don't own without going
through App Review, so there was nothing useful to build with those
credentials. The admin verification workflow (see below) is the
practical substitute.

## What's implemented

- Flask app with a JSON API (`/api/outages`, `/api/stats`, etc.)
- SQLite database with de-duplication (`upsert_outage`), restore/delete
- **Real browser-based scraper**: uses Playwright (headless Chromium)
  to load PNG Power's outage pages, run their JavaScript, and read the
  actual rendered content — see "About the scraper" below for the one
  step left to finish this
- APScheduler background job that re-runs the scraper on an interval
- Vector-tile map (MapLibre GL JS + OpenFreeMap) with colour-coded
  markers per suburb — same rendering engine lineage as the Mapbox GL
  map on PNG Power's own site, but completely free (no API key, no
  signup, no usage limits) since it uses OpenFreeMap's public tiles
  instead of a paid Mapbox account
- Suburb search, status filter tabs (All/Active/Planned/Restored)
- Stats dashboard (total/active/planned/emergency, most-affected
  suburb, monthly trend query)
- Admin page: password-gated manual entry, mark-restored, delete,
  "run update now" button, subscriber count + notification status,
  pending-report verification queue, weather correlation view
- Email and SMS notifications: subscribe by suburb, get alerted
  when a new outage is reported and when it's restored (see below)
- **User accounts**: register/login, saved favourite suburbs, a
  personal dashboard showing outages in those suburbs
- **Public outage reporting**: anyone can report an outage with a
  description, time, optional photo, and optional address (geocoded
  via LocationIQ to the nearest known suburb). Matching reports for
  the same suburb/timeframe are automatically merged instead of
  creating duplicates.
- **Verification & confidence scoring**: reports move through
  Reported → Under Review → Verified → Active → Restored. Confidence
  score = report count + admin verification bonus (see
  `config.CONFIDENCE_*` to tune the weights).
- **Weather snapshots** (OpenWeather): every outage — scraped or
  reported — gets the current weather conditions attached, and the
  admin page shows an outage-count-by-weather-condition breakdown so
  storm correlations become visible over time.
- **Geocoding** (LocationIQ): free-text addresses in outage reports
  resolve to coordinates and snap to the nearest known suburb.
- **Email via Resend**: simpler alternative to SMTP — just an API key,
  no app passwords. Takes priority over SMTP if both are configured.
- **Incident timeline**: every outage records a full history (created,
  reports merged, verified, restored, each with a timestamp) — visible
  on a per-outage detail page (`/outage/<id>`, linked from the map
  cards and admin table).
- **Extended analytics**: average restoration time, worst-affected
  suburbs ranking, and peak outage hour, all shown on the admin page.

## Setting up notifications

Subscribers pick a suburb and give an email and/or phone number via
the "Get alerts" button on the homepage. When a new outage appears (or
one gets marked restored, whether by the scraper or the admin page),
everyone subscribed to that suburb gets notified. Nothing else in the
app changes if you don't set these up — subscriptions still save, and
`notifications.py` just logs what it *would* have sent to
`logs/app.log`.

**Email — works with any real account, no cost.** Set these
environment variables before running the app:

```bash
export EMAIL_HOST=smtp.gmail.com      # or your provider's SMTP host
export EMAIL_PORT=587
export EMAIL_USER=youraddress@gmail.com
export EMAIL_PASSWORD=your-app-password
```

For Gmail specifically, `EMAIL_PASSWORD` needs to be an **App
Password**, not your normal login password — generate one at
https://myaccount.google.com/apppasswords (requires 2-Step
Verification to be turned on first). Other providers (Outlook,
SendGrid's SMTP relay, your own mail server) just need their own SMTP
host/port/credentials in the same variables.

**SMS — requires a paid provider, there's no free option.** This app
is wired up for Twilio (the most common choice). Create a free-trial
Twilio account, buy/verify a number, then set:

```bash
export TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
export TWILIO_AUTH_TOKEN=your_auth_token
export TWILIO_FROM_NUMBER=+1415XXXXXXX
```

Until those three are set, SMS "sends" are just logged, so you can
build and test everything else for free.

**Where this project's `.env` currently stands:** it has your Resend,
OpenWeather, and LocationIQ keys filled in (so email, weather, and
geocoding are live once you deploy this somewhere with real internet
access — I can't reach any of these APIs from where I build, so I
tested each integration against mocked responses instead of the real
thing). Your Twilio Account SID and Auth Token are in there too, but
`TWILIO_FROM_NUMBER` is blank because you didn't share a Twilio phone
number — SMS stays in "logged, not sent" mode until you add one from
your Twilio console.

On Windows PowerShell, set variables like this instead:
```powershell
$env:EMAIL_USER="youraddress@gmail.com"
$env:EMAIL_PASSWORD="your-app-password"
```

## About the scraper

PNG Power's website (`pngpower.com.pg`, including the old `/index.php/...`
URLs, which now redirect into the same app) is a JavaScript-rendered
site — a plain HTTP request sees an empty page shell, not the outage
listings. So `scraper.py` uses **Playwright**, a real headless
browser, to load the page, let its JavaScript run, and then read the
actual rendered content — the same thing your own browser does.

I built and tested this rendering pipeline against a local mock page
that behaves the same way (content injected via JS after a delay), and
confirmed the whole chain — launching the browser, waiting for
content, parsing it into outage records, saving to the database,
firing notifications — genuinely works, including running correctly
from the scheduler's background thread. **What I could not do** is
test it against the real pngpower.com.pg site, because I don't have
open internet access to it from where I build (confirmed: requests to
it are blocked before they leave my sandbox). The CSS selectors in
`_parse_rendered_html()` (in `scraper.py`) are an informed guess at a
common card/article layout, not a confirmed match to PNG Power's real
markup.

**One step to finish this, and it's quick:**

```bash
python scraper.py --dump-html
```

This renders the real outage pages and saves them to `debug_planned.html`,
`debug_unplanned.html`, and `debug_network_map.html`. Open any of them,
find the repeating element that wraps each outage entry (or right-click
→ Inspect on the live site), and update the selector at the top of
`_parse_rendered_html()` in `scraper.py` to match. Everything downstream
— dedup, notifications, the map, the API — already works off whatever
that function returns.

### The network-map page (real finding, from a saved copy of the site)

A saved copy of `pngpower.com.pg/network-map` showed this is PNG Power's
"National Grid Intelligence Platform" — a live map showing aggregate
counts (Active/Upcoming/Maintenance/Restored outages, plus a separate
Projects layer). The per-suburb detail isn't in the static page text —
it's very likely rendered as map pins backed by a JSON API that hasn't
been identified yet — but the **national totals** ("Active 3", "Upcoming
7", "Maintenance 2") are plain rendered text, and `scraper.py` now reads
them via `fetch_network_map_summary()`, storing them separately from
your own tracked outages (`/api/national-summary`, shown as a banner on
the homepage). This is real data, clearly labeled as PNG Power's own
figures rather than folded into this site's own outage count.

If you find the JSON API backing their map pins (DevTools → Network →
XHR while viewing `/network-map`), that would unlock real per-suburb
data directly — send me the URL and response shape and I'll wire it in.

If no selector matches (or PNG Power genuinely has no current
outages), `run_scraper()` falls back to generating demo data, so the
app stays fully functional while you do this.

If PNG Power's Facebook page ever turns out to be more reliable in
practice, the admin page's manual-entry form is still there for that
workflow too — the two aren't mutually exclusive.

## Project structure

```
power-outage-tracker/
├── app.py            Flask routes + JSON API
├── config.py         Settings, suburb coordinates, source URLs
├── database.py       SQLite schema + all queries
├── scraper.py        Playwright-based scraper (see "About the scraper")
├── scheduler.py       APScheduler background job wrapper
├── notifications.py   Email (smtplib) + SMS (Twilio) sending
├── requirements.txt
├── data/outages.db    Created automatically on first run
├── templates/         index.html, base.html, admin.html, unsubscribe.html
├── static/            style.css, script.js, map.js
└── logs/app.log        Created automatically on first run
```

## Troubleshooting: stats showing all zeros

If `/api/stats` (and the homepage) show 0 for everything, this was a
real bug in earlier versions of this project: `data/outages.db` from a
version before certain columns existed (weather, confidence score,
report count) would silently fail every insert, since SQLite's
`CREATE TABLE IF NOT EXISTS` doesn't add columns to a table that
already exists. `database.init_db()` now checks for and adds any
missing columns automatically on startup, so this shouldn't recur —
but if you're still seeing it, delete `data/outages.db` and restart;
it'll be recreated with demo data (or real data, if the scraper's
selectors are tuned) on the next launch.

## Deploying

**Option A — Docker (recommended, handles Playwright automatically).**
A `Dockerfile` is included, based on Playwright's official image which
already ships Chromium and every OS-level dependency it needs — this
sidesteps the "browser deps fail to install on the host" problem that
`playwright install --with-deps` can hit on some platforms.

```bash
docker build -t outage-tracker .
docker run -p 5000:5000 --env-file .env outage-tracker
```

Both Render and Railway support deploying directly from a Dockerfile —
just point them at this repo and they'll pick it up.

**Option B — plain Python, no Docker.**
1. Push to GitHub.
2. Deploy on Render or Railway, start command `gunicorn app:application`
   (or `app:app` — both point at the same Flask app; module import
   already runs setup either way). Add
   `playwright install --with-deps chromium` as a build step after
   `pip install -r requirements.txt`.
3. Set `SECRET_KEY` and `ADMIN_PASSWORD` as environment variables —
   don't leave the defaults in config.py for a public deployment. See
   `.env.example` for the full list of variables the app reads (email/
   SMS credentials, update interval, etc) — copy it to `.env` for local
   dev, or set them directly in your host's dashboard for production.
4. SQLite is fine to start; if you outgrow it, `database.py` is the
   only file you'll need to touch to move to PostgreSQL.

A `.gitignore` is included so `venv/`, `data/*.db`, `logs/*.log`, and
any local `.env` file won't accidentally get committed.

## Roadmap ideas (not yet built)

- Confirm the real CSS selector for outage cards (see "About the scraper")
- Historical outage graphs, weather overlay
- Public REST API docs
- User accounts + saved favourite suburbs
- Automated test suite (pytest) for database/scraper logic
