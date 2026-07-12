"""
All SQLite access lives here. Plain sqlite3 is used (no ORM) to keep the
project dependency-light and easy to inspect with DB Browser for SQLite.

If you outgrow SQLite later, this module is the only place you should
need to touch to swap in PostgreSQL (e.g. via SQLAlchemy).
"""

import sqlite3
import os
from contextlib import contextmanager
from datetime import datetime

import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS outages (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    suburb                  TEXT NOT NULL,
    area                    TEXT,
    date                    TEXT NOT NULL,       -- ISO date, e.g. 2026-07-06
    time_started            TEXT,                 -- e.g. "14:30"
    status                  TEXT NOT NULL,        -- see config.VALID_STATUSES
    outage_type             TEXT,                 -- Emergency | Planned Maintenance
    reason                  TEXT,
    estimated_restoration   TEXT,
    actual_restoration      TEXT,
    source                  TEXT,                 -- PNG Power | Post-Courier | Admin | User Report
    source_url              TEXT,
    latitude                REAL,
    longitude               REAL,
    external_ref            TEXT,                 -- de-dupe key derived from source content
    -- Weather snapshot at time of report, for correlation analysis --
    weather_condition       TEXT,
    weather_description     TEXT,
    weather_temp_c          REAL,
    weather_wind_kph        REAL,
    weather_rain_mm         REAL,
    -- Verification / confidence-scoring fields --
    confidence_score        INTEGER DEFAULT 0,
    report_count            INTEGER DEFAULT 0,
    verified_by_admin       INTEGER DEFAULT 0,    -- 0/1 boolean
    created_at              TEXT NOT NULL,
    last_updated            TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_outages_suburb ON outages(suburb);
CREATE INDEX IF NOT EXISTS idx_outages_status ON outages(status);
CREATE UNIQUE INDEX IF NOT EXISTS idx_outages_external_ref
    ON outages(external_ref) WHERE external_ref IS NOT NULL;

CREATE TABLE IF NOT EXISTS subscribers (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    suburb              TEXT NOT NULL,
    email               TEXT,
    phone               TEXT,
    unsubscribe_token   TEXT NOT NULL UNIQUE,
    created_at          TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_subscribers_suburb ON subscribers(suburb);

CREATE TABLE IF NOT EXISTS users (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    email           TEXT NOT NULL UNIQUE,
    password_hash   TEXT NOT NULL,
    created_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS favourites (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    suburb      TEXT NOT NULL,
    label       TEXT,                 -- e.g. "Home", "Work" -- optional nickname
    created_at  TEXT NOT NULL,
    UNIQUE(user_id, suburb)
);

CREATE TABLE IF NOT EXISTS report_log (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    outage_id           INTEGER NOT NULL REFERENCES outages(id) ON DELETE CASCADE,
    suburb              TEXT NOT NULL,
    description         TEXT,
    reporter_contact     TEXT,
    reporter_user_id     INTEGER REFERENCES users(id),
    photo_path           TEXT,
    created_at          TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_report_log_outage ON report_log(outage_id);

CREATE TABLE IF NOT EXISTS event_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    outage_id   INTEGER NOT NULL REFERENCES outages(id) ON DELETE CASCADE,
    event_type  TEXT NOT NULL,   -- created | report_merged | status_changed | verified | restored
    detail      TEXT,
    created_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_event_log_outage ON event_log(outage_id);

CREATE TABLE IF NOT EXISTS national_summary (
    id              INTEGER PRIMARY KEY CHECK (id = 1),  -- singleton row
    active          INTEGER,
    upcoming        INTEGER,
    maintenance     INTEGER,
    source_url      TEXT,
    fetched_at      TEXT NOT NULL
);
"""


@contextmanager
def get_connection():
    """Context-managed SQLite connection with row access by column name."""
    os.makedirs(os.path.dirname(config.DATABASE_PATH), exist_ok=True)
    conn = sqlite3.connect(config.DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# Columns that have been added to the outages table since this project's
# first version. CREATE TABLE IF NOT EXISTS is a no-op on a database that
# already exists from an older version -- it does NOT add new columns to
# an existing table. Without the migration below, every insert/update
# against a pre-existing outages.db would silently fail with "no such
# column", and every count would read as zero. This list is what
# init_db() checks for and adds if missing, so upgrading the code never
# requires deleting your existing database.
OUTAGE_COLUMNS_ADDED_OVER_TIME = {
    "weather_condition": "TEXT",
    "weather_description": "TEXT",
    "weather_temp_c": "REAL",
    "weather_wind_kph": "REAL",
    "weather_rain_mm": "REAL",
    "confidence_score": "INTEGER DEFAULT 0",
    "report_count": "INTEGER DEFAULT 0",
    "verified_by_admin": "INTEGER DEFAULT 0",
}


def _migrate_schema(conn):
    """
    Adds any columns to `outages` that exist in the current SCHEMA but
    not in the actual database file -- handles upgrading a database
    created by an older version of this project.
    """
    existing_columns = {row["name"] for row in conn.execute("PRAGMA table_info(outages)").fetchall()}
    for column, coltype in OUTAGE_COLUMNS_ADDED_OVER_TIME.items():
        if column not in existing_columns:
            conn.execute(f"ALTER TABLE outages ADD COLUMN {column} {coltype}")


def init_db():
    """Create the database file and tables if they don't already exist,
    and migrate any existing (older) database up to the current schema."""
    with get_connection() as conn:
        conn.executescript(SCHEMA)
        _migrate_schema(conn)


def _now():
    return datetime.utcnow().isoformat(timespec="seconds")


def upsert_outage(record: dict) -> dict:
    """
    Insert a new outage, or update it if a record with the same
    external_ref already exists (this is how re-running the scraper
    avoids creating duplicates for the same real-world event).

    `record` should contain any subset of the outages columns.
    Returns {"id": ..., "is_new": bool, "status_changed_to_restored": bool}
    so callers (scraper, admin routes) know whether to fire notifications.
    """
    record = dict(record)
    record.setdefault("created_at", _now())
    record["last_updated"] = _now()

    with get_connection() as conn:
        existing = None
        if record.get("external_ref"):
            existing = conn.execute(
                "SELECT id, status FROM outages WHERE external_ref = ?",
                (record["external_ref"],),
            ).fetchone()

        if existing:
            cols = [k for k in record.keys() if k != "created_at"]
            set_clause = ", ".join(f"{c} = :{c}" for c in cols)
            record["id"] = existing["id"]
            conn.execute(f"UPDATE outages SET {set_clause} WHERE id = :id", record)
            became_restored = (
                existing["status"] != "Restored" and record.get("status") == "Restored"
            )
            result = {"id": existing["id"], "is_new": False,
                      "status_changed_to_restored": became_restored}
        else:
            cols = list(record.keys())
            placeholders = ", ".join(f":{c}" for c in cols)
            cursor = conn.execute(
                f"INSERT INTO outages ({', '.join(cols)}) VALUES ({placeholders})",
                record,
            )
            result = {"id": cursor.lastrowid, "is_new": True,
                      "status_changed_to_restored": False}

    # log_event() opens its own connection -- it must run after the `with`
    # block above has committed and released its connection, or SQLite
    # will report "database is locked" (two connections, one still holding
    # an open write transaction).
    if result["is_new"]:
        log_event(result["id"], "created", f"First reported via {record.get('source', 'unknown')}")
    elif result["status_changed_to_restored"]:
        log_event(result["id"], "restored", f"Restored (source: {record.get('source', 'unknown')})")

    return result


def mark_restored(outage_id: int, actual_restoration: str = None):
    with get_connection() as conn:
        conn.execute(
            """UPDATE outages
               SET status = 'Restored',
                   actual_restoration = COALESCE(?, actual_restoration),
                   last_updated = ?
               WHERE id = ?""",
            (actual_restoration, _now(), outage_id),
        )
    log_event(outage_id, "restored", "Marked restored by admin")


def delete_outage(outage_id: int):
    with get_connection() as conn:
        conn.execute("DELETE FROM outages WHERE id = ?", (outage_id,))


def get_all_outages(status: str = None, suburb: str = None) -> list:
    query = "SELECT * FROM outages WHERE 1=1"
    params = []
    if status:
        query += " AND status = ?"
        params.append(status)
    if suburb:
        query += " AND suburb LIKE ?"
        params.append(f"%{suburb}%")
    query += " ORDER BY date DESC, time_started DESC"

    with get_connection() as conn:
        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]


def get_outage(outage_id: int) -> dict:
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM outages WHERE id = ?", (outage_id,)).fetchone()
        return dict(row) if row else None


def log_event(outage_id: int, event_type: str, detail: str = None):
    """
    Records a timeline entry for an outage -- e.g. "created", "verified",
    "restored". This is what powers the per-outage incident timeline
    (first report -> verified -> restored, with timestamps).
    """
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO event_log (outage_id, event_type, detail, created_at) VALUES (?, ?, ?, ?)",
            (outage_id, event_type, detail, _now()),
        )


def get_timeline(outage_id: int) -> list:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM event_log WHERE outage_id = ? ORDER BY created_at",
            (outage_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def get_stats() -> dict:
    with get_connection() as conn:
        total = conn.execute("SELECT COUNT(*) c FROM outages").fetchone()["c"]
        active = conn.execute(
            "SELECT COUNT(*) c FROM outages WHERE status = 'Active'"
        ).fetchone()["c"]
        planned = conn.execute(
            "SELECT COUNT(*) c FROM outages WHERE status = 'Planned'"
        ).fetchone()["c"]
        restored = conn.execute(
            "SELECT COUNT(*) c FROM outages WHERE status = 'Restored'"
        ).fetchone()["c"]
        emergency = conn.execute(
            "SELECT COUNT(*) c FROM outages WHERE outage_type = 'Emergency'"
        ).fetchone()["c"]

        top_suburb_row = conn.execute(
            """SELECT suburb, COUNT(*) c FROM outages
               GROUP BY suburb ORDER BY c DESC LIMIT 1"""
        ).fetchone()
        top_suburb = top_suburb_row["suburb"] if top_suburb_row else None

        worst_affected = conn.execute(
            """SELECT suburb, COUNT(*) AS count FROM outages
               GROUP BY suburb ORDER BY count DESC LIMIT 5"""
        ).fetchall()

        monthly = conn.execute(
            """SELECT strftime('%Y-%m', date) AS month, COUNT(*) AS count
               FROM outages GROUP BY month ORDER BY month DESC LIMIT 12"""
        ).fetchall()

        # Peak outage hour: SQLite can pull the hour straight out of the
        # "HH:MM" text without needing a full datetime parse.
        peak_hour_row = conn.execute(
            """SELECT CAST(substr(time_started, 1, 2) AS INTEGER) AS hour, COUNT(*) AS count
               FROM outages WHERE time_started IS NOT NULL AND time_started != ''
               GROUP BY hour ORDER BY count DESC LIMIT 1"""
        ).fetchone()
        peak_hour = peak_hour_row["hour"] if peak_hour_row else None

        # Average restoration time: computed in Python since comparing two
        # "HH:MM" text columns is awkward in raw SQL. Only counts outages
        # that have both a start time and an actual restoration time
        # recorded (same-day outages -- a reasonable simplification here).
        restoration_rows = conn.execute(
            """SELECT time_started, actual_restoration FROM outages
               WHERE status = 'Restored' AND time_started IS NOT NULL
               AND actual_restoration IS NOT NULL AND time_started != ''
               AND actual_restoration != ''"""
        ).fetchall()

    durations = []
    for row in restoration_rows:
        duration = _minutes_between(row["time_started"], row["actual_restoration"])
        if duration != float("inf") and duration >= 0:
            durations.append(duration)
    avg_restoration_minutes = round(sum(durations) / len(durations)) if durations else None

    return {
        "total": total,
        "active": active,
        "planned": planned,
        "restored": restored,
        "emergency": emergency,
        "planned_maintenance": total - emergency if total else 0,
        "most_affected_suburb": top_suburb,
        "worst_affected_suburbs": [dict(r) for r in worst_affected],
        "monthly_trends": [dict(m) for m in monthly],
        "peak_outage_hour": peak_hour,
        "average_restoration_minutes": avg_restoration_minutes,
    }


def get_last_updated() -> str:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT MAX(last_updated) AS ts FROM outages"
        ).fetchone()
        return row["ts"] if row else None


# --------------------------------------------------------------------------
# Subscribers (email / SMS notifications by suburb)
# --------------------------------------------------------------------------

def add_subscriber(suburb: str, email: str = None, phone: str = None) -> dict:
    import secrets

    with get_connection() as conn:
        existing = conn.execute(
            """SELECT unsubscribe_token FROM subscribers
               WHERE suburb = ? AND email IS ? AND phone IS ?""",
            (suburb, email or None, phone or None),
        ).fetchone()
        if existing:
            # Already subscribed with this exact suburb/email/phone combo --
            # return the existing token instead of creating a duplicate row
            # (which would otherwise double up every notification they get).
            return {"id": None, "unsubscribe_token": existing["unsubscribe_token"],
                     "already_subscribed": True}

        token = secrets.token_urlsafe(24)
        cursor = conn.execute(
            """INSERT INTO subscribers (suburb, email, phone, unsubscribe_token, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (suburb, email or None, phone or None, token, _now()),
        )
        return {"id": cursor.lastrowid, "unsubscribe_token": token, "already_subscribed": False}


def get_subscribers_for_suburb(suburb: str) -> list:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM subscribers WHERE suburb = ?", (suburb,)
        ).fetchall()
        return [dict(r) for r in rows]


def get_all_subscribers() -> list:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM subscribers ORDER BY suburb"
        ).fetchall()
        return [dict(r) for r in rows]


def remove_subscriber_by_token(token: str) -> bool:
    with get_connection() as conn:
        cursor = conn.execute(
            "DELETE FROM subscribers WHERE unsubscribe_token = ?", (token,)
        )
        return cursor.rowcount > 0


def subscriber_count() -> int:
    with get_connection() as conn:
        return conn.execute("SELECT COUNT(*) c FROM subscribers").fetchone()["c"]


# --------------------------------------------------------------------------
# User accounts
# --------------------------------------------------------------------------

def create_user(email: str, password_hash: str) -> dict:
    """Raises sqlite3.IntegrityError if the email is already registered."""
    with get_connection() as conn:
        cursor = conn.execute(
            "INSERT INTO users (email, password_hash, created_at) VALUES (?, ?, ?)",
            (email.lower().strip(), password_hash, _now()),
        )
        return {"id": cursor.lastrowid, "email": email}


def get_user_by_email(email: str) -> dict:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE email = ?", (email.lower().strip(),)
        ).fetchone()
        return dict(row) if row else None


def get_user_by_id(user_id: int) -> dict:
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return dict(row) if row else None


# --------------------------------------------------------------------------
# Favourite suburbs (per logged-in user)
# --------------------------------------------------------------------------

def add_favourite(user_id: int, suburb: str, label: str = None) -> bool:
    try:
        with get_connection() as conn:
            conn.execute(
                "INSERT INTO favourites (user_id, suburb, label, created_at) VALUES (?, ?, ?, ?)",
                (user_id, suburb, label, _now()),
            )
        return True
    except sqlite3.IntegrityError:
        return False  # already favourited -- not an error, just a no-op


def remove_favourite(user_id: int, suburb: str) -> bool:
    with get_connection() as conn:
        cursor = conn.execute(
            "DELETE FROM favourites WHERE user_id = ? AND suburb = ?", (user_id, suburb)
        )
        return cursor.rowcount > 0


def get_favourites(user_id: int) -> list:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM favourites WHERE user_id = ? ORDER BY suburb", (user_id,)
        ).fetchall()
        return [dict(r) for r in rows]


# --------------------------------------------------------------------------
# User-submitted outage reports, with duplicate detection + confidence score
# --------------------------------------------------------------------------

def _minutes_between(time_a: str, time_b: str) -> float:
    """Both are 'HH:MM' strings on the same date; returns absolute minutes apart."""
    try:
        from datetime import datetime as dt
        fmt = "%H:%M"
        ta, tb = dt.strptime(time_a, fmt), dt.strptime(time_b, fmt)
        return abs((ta - tb).total_seconds()) / 60
    except (ValueError, TypeError):
        return float("inf")


def find_matching_open_outage(suburb: str, date: str, time_started: str) -> dict:
    """
    Looks for an existing not-yet-restored outage in the same suburb,
    on the same date, within config.DUPLICATE_REPORT_WINDOW_MINUTES of
    the given start time -- this is the duplicate-report detection the
    project spec asks for ("10 people report the same location/time ->
    combine into one outage").
    """
    with get_connection() as conn:
        candidates = conn.execute(
            """SELECT * FROM outages
               WHERE suburb = ? AND date = ? AND status != 'Restored'
               ORDER BY id DESC""",
            (suburb, date),
        ).fetchall()

    for row in candidates:
        candidate = dict(row)
        if time_started and candidate.get("time_started"):
            if _minutes_between(time_started, candidate["time_started"]) <= config.DUPLICATE_REPORT_WINDOW_MINUTES:
                return candidate
        elif not time_started or not candidate.get("time_started"):
            # If either side is missing a time, still treat same-suburb/
            # same-day open outages as a match rather than creating dupes.
            return candidate
    return None


def recalculate_confidence(outage_id: int):
    """
    Recomputes confidence_score from report_count + verified_by_admin,
    per the weights in config.py. Called after every new report and
    every admin verification action.
    """
    with get_connection() as conn:
        row = conn.execute(
            "SELECT report_count, verified_by_admin FROM outages WHERE id = ?",
            (outage_id,),
        ).fetchone()
        if not row:
            return

        score = row["report_count"] * config.CONFIDENCE_PER_REPORT
        if row["report_count"] >= 2:
            score += config.CONFIDENCE_MULTI_REPORT_BONUS
        if row["verified_by_admin"]:
            score += config.CONFIDENCE_ADMIN_VERIFIED
        score = min(score, config.CONFIDENCE_MAX)

        conn.execute(
            "UPDATE outages SET confidence_score = ?, last_updated = ? WHERE id = ?",
            (score, _now(), outage_id),
        )


def submit_report(suburb: str, description: str, time_started: str = None,
                   date: str = None, reporter_contact: str = None,
                   reporter_user_id: int = None, photo_path: str = None,
                   latitude: float = None, longitude: float = None) -> dict:
    """
    Records a user-submitted outage report. If it matches an existing
    open outage for the same suburb/timeframe, it's merged in (report
    count incremented) rather than creating a duplicate record.
    Returns {"outage_id": ..., "is_new_outage": bool, "report_count": int}.
    """
    date = date or datetime.utcnow().date().isoformat()
    coords = config.SUBURBS.get(suburb, {})
    lat = latitude if latitude is not None else coords.get("lat")
    lon = longitude if longitude is not None else coords.get("lon")

    existing = find_matching_open_outage(suburb, date, time_started)

    with get_connection() as conn:
        if existing:
            outage_id = existing["id"]
            conn.execute(
                "UPDATE outages SET report_count = report_count + 1, last_updated = ? WHERE id = ?",
                (_now(), outage_id),
            )
            is_new_outage = False
        else:
            cursor = conn.execute(
                """INSERT INTO outages
                   (suburb, area, date, time_started, status, outage_type, reason,
                    source, latitude, longitude, report_count, created_at, last_updated)
                   VALUES (?, ?, ?, ?, 'Reported', 'Emergency', ?, 'User Report', ?, ?, 1, ?, ?)""",
                (suburb, None, date, time_started, description, lat, lon, _now(), _now()),
            )
            outage_id = cursor.lastrowid
            is_new_outage = True

        conn.execute(
            """INSERT INTO report_log
               (outage_id, suburb, description, reporter_contact, reporter_user_id, photo_path, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (outage_id, suburb, description, reporter_contact, reporter_user_id, photo_path, _now()),
        )

        report_count = conn.execute(
            "SELECT report_count FROM outages WHERE id = ?", (outage_id,)
        ).fetchone()["report_count"]

    if is_new_outage:
        log_event(outage_id, "created", f"First reported: {description[:100]}")
    else:
        log_event(outage_id, "report_merged", f"Report #{report_count}: {description[:100]}")

    recalculate_confidence(outage_id)
    return {"outage_id": outage_id, "is_new_outage": is_new_outage, "report_count": report_count}


def verify_outage(outage_id: int, new_status: str = "Verified"):
    """Admin action: marks a report as verified and promotes its status."""
    with get_connection() as conn:
        conn.execute(
            "UPDATE outages SET verified_by_admin = 1, status = ?, last_updated = ? WHERE id = ?",
            (new_status, _now(), outage_id),
        )
    log_event(outage_id, "verified", f"Verified by admin, status set to {new_status}")
    recalculate_confidence(outage_id)


def get_reports_for_outage(outage_id: int) -> list:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM report_log WHERE outage_id = ? ORDER BY created_at",
            (outage_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def set_weather_snapshot(outage_id: int, weather: dict):
    if not weather:
        return
    with get_connection() as conn:
        conn.execute(
            """UPDATE outages SET
               weather_condition = ?, weather_description = ?,
               weather_temp_c = ?, weather_wind_kph = ?, weather_rain_mm = ?
               WHERE id = ?""",
            (weather.get("condition"), weather.get("description"),
             weather.get("temperature_c"), weather.get("wind_kph"),
             weather.get("rain_1h_mm"), outage_id),
        )


def get_weather_correlation_stats() -> list:
    """
    Simple correlation view: outage counts grouped by weather condition,
    for the 'storms correlate with outages' analytics the spec asks for.
    """
    with get_connection() as conn:
        rows = conn.execute(
            """SELECT weather_condition, COUNT(*) as count
               FROM outages
               WHERE weather_condition IS NOT NULL
               GROUP BY weather_condition
               ORDER BY count DESC"""
        ).fetchall()
        return [dict(r) for r in rows]


def set_national_summary(active: int = None, upcoming: int = None,
                          maintenance: int = None, source_url: str = None):
    """
    Stores PNG Power's real national aggregate counts (from their
    network-map page). Singleton row -- always overwrites the previous
    reading rather than accumulating history, since this is a live
    snapshot, not a per-incident record.
    """
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO national_summary (id, active, upcoming, maintenance, source_url, fetched_at)
               VALUES (1, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                 active = excluded.active,
                 upcoming = excluded.upcoming,
                 maintenance = excluded.maintenance,
                 source_url = excluded.source_url,
                 fetched_at = excluded.fetched_at""",
            (active, upcoming, maintenance, source_url, _now()),
        )


def get_national_summary() -> dict:
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM national_summary WHERE id = 1").fetchone()
        return dict(row) if row else None
