"""
Port Moresby Power Outage Tracker -- Flask entry point.

Run with:  python app.py
Then visit http://127.0.0.1:5000
"""

import os
import uuid

from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from werkzeug.utils import secure_filename

import config
import database
import scraper
import scheduler
import notifications
import auth
import weather
import geocode

app = Flask(__name__)
app.secret_key = config.SECRET_KEY

UPLOAD_FOLDER = os.path.join(config.BASE_DIR, "static", "uploads")
ALLOWED_PHOTO_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp"}
MAX_PHOTO_SIZE_BYTES = 5 * 1024 * 1024  # 5 MB
os.makedirs(UPLOAD_FOLDER, exist_ok=True)


def _save_report_photo(file_storage):
    """
    Saves an uploaded report photo if present and valid, returning the
    relative static path to store on the report, or None. Never raises --
    a bad/oversized photo just means the report is saved without one.
    """
    if not file_storage or not file_storage.filename:
        return None

    ext = file_storage.filename.rsplit(".", 1)[-1].lower() if "." in file_storage.filename else ""
    if ext not in ALLOWED_PHOTO_EXTENSIONS:
        return None

    file_storage.seek(0, os.SEEK_END)
    size = file_storage.tell()
    file_storage.seek(0)
    if size > MAX_PHOTO_SIZE_BYTES:
        return None

    filename = secure_filename(f"{uuid.uuid4().hex}.{ext}")
    file_storage.save(os.path.join(UPLOAD_FOLDER, filename))
    return f"uploads/{filename}"


# --------------------------------------------------------------------------
# Pages
# --------------------------------------------------------------------------

@app.route("/")
def index():
    return render_template(
        "index.html",
        suburbs=sorted(config.SUBURBS.keys()),
        map_center=config.MAP_CENTER,
        map_zoom=config.MAP_DEFAULT_ZOOM,
    )


@app.route("/admin", methods=["GET", "POST"])
def admin():
    if request.method == "POST":
        if request.form.get("password") == config.ADMIN_PASSWORD:
            session["is_admin"] = True
        else:
            return render_template("admin.html", error="Incorrect password",
                                    is_admin=False, suburbs=sorted(config.SUBURBS.keys()))

    is_admin = session.get("is_admin", False)
    outages = database.get_all_outages() if is_admin else []
    pending_reports = [o for o in outages if o["status"] in ("Reported", "Under Review")]

    return render_template(
        "admin.html",
        is_admin=is_admin,
        outages=outages,
        pending_reports=pending_reports,
        suburbs=sorted(config.SUBURBS.keys()),
        statuses=config.VALID_STATUSES,
        types=config.VALID_TYPES,
        subscriber_count=database.subscriber_count() if is_admin else 0,
        email_enabled=config.ENABLE_EMAIL_NOTIFICATIONS or config.ENABLE_RESEND,
        sms_enabled=config.ENABLE_SMS_NOTIFICATIONS,
        weather_enabled=config.ENABLE_WEATHER,
        geocoding_enabled=config.ENABLE_GEOCODING,
        weather_correlation=database.get_weather_correlation_stats() if is_admin else [],
        stats=database.get_stats() if is_admin else {},
    )


@app.route("/admin/logout")
def admin_logout():
    session.pop("is_admin", None)
    return redirect(url_for("admin"))


# --------------------------------------------------------------------------
# User accounts (separate from the admin login above -- these are regular
# public users who want saved favourite suburbs and reporting history)
# --------------------------------------------------------------------------

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        result = auth.register_user(request.form.get("email"), request.form.get("password"))
        if result["success"]:
            auth.login_user(request.form.get("email"), request.form.get("password"))
            return redirect(url_for("dashboard"))
        return render_template("register.html", error=result["error"])
    return render_template("register.html", error=None)


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        result = auth.login_user(request.form.get("email"), request.form.get("password"))
        if result["success"]:
            next_url = request.args.get("next") or url_for("dashboard")
            return redirect(next_url)
        return render_template("login.html", error=result["error"])
    return render_template("login.html", error=None)


@app.route("/logout")
def logout():
    auth.logout_user()
    return redirect(url_for("index"))


@app.route("/dashboard")
@auth.login_required
def dashboard():
    user = auth.current_user()
    favourites = database.get_favourites(user["id"])
    favourite_suburbs = [f["suburb"] for f in favourites]
    recent_outages = database.get_all_outages()
    relevant_outages = [o for o in recent_outages if o["suburb"] in favourite_suburbs]

    return render_template(
        "dashboard.html",
        user=user,
        favourites=favourites,
        all_suburbs=sorted(config.SUBURBS.keys()),
        relevant_outages=relevant_outages,
    )


@app.route("/favourites/add", methods=["POST"])
@auth.login_required
def favourites_add():
    user = auth.current_user()
    suburb = request.form.get("suburb")
    label = (request.form.get("label") or "").strip() or None
    if suburb in config.SUBURBS:
        database.add_favourite(user["id"], suburb, label)
    return redirect(url_for("dashboard"))


@app.route("/favourites/remove/<suburb>", methods=["POST"])
@auth.login_required
def favourites_remove(suburb):
    user = auth.current_user()
    database.remove_favourite(user["id"], suburb)
    return redirect(url_for("dashboard"))


# --------------------------------------------------------------------------
# Notification subscriptions
# --------------------------------------------------------------------------

@app.route("/subscribe", methods=["POST"])
def subscribe():
    suburb = request.form.get("suburb")
    email = (request.form.get("email") or "").strip()
    phone = (request.form.get("phone") or "").strip()

    if not suburb or suburb not in config.SUBURBS:
        return jsonify({"error": "Please choose a valid suburb."}), 400
    if not email and not phone:
        return jsonify({"error": "Enter an email or phone number."}), 400

    result = database.add_subscriber(suburb, email=email or None, phone=phone or None)
    if result.get("already_subscribed"):
        return jsonify({"success": True, "already_subscribed": True})
    return jsonify({"success": True})


@app.route("/unsubscribe/<token>")
def unsubscribe(token):
    removed = database.remove_subscriber_by_token(token)
    return render_template("unsubscribe.html", removed=removed)


# --------------------------------------------------------------------------
# Public outage reporting
# --------------------------------------------------------------------------

@app.route("/report", methods=["GET", "POST"])
def report():
    if request.method == "GET":
        return render_template(
            "report.html",
            suburbs=sorted(config.SUBURBS.keys()),
            geocoding_enabled=config.ENABLE_GEOCODING,
        )

    address = (request.form.get("address") or "").strip()
    suburb = request.form.get("suburb")
    description = (request.form.get("description") or "").strip()
    time_noticed = request.form.get("time_noticed")
    contact = (request.form.get("contact") or "").strip() or None

    # If the user typed a free-text address, try to geocode it and slot
    # it into the nearest known suburb; otherwise use their dropdown pick.
    latitude = longitude = None
    if address and config.ENABLE_GEOCODING:
        geocoded = geocode.geocode_address(address)
        if geocoded:
            latitude, longitude = geocoded["latitude"], geocoded["longitude"]
            suburb = geocode.nearest_suburb(latitude, longitude)

    if not suburb or suburb not in config.SUBURBS:
        return render_template(
            "report.html", suburbs=sorted(config.SUBURBS.keys()),
            geocoding_enabled=config.ENABLE_GEOCODING,
            error="Please choose or enter a valid location.",
        )
    if not description:
        return render_template(
            "report.html", suburbs=sorted(config.SUBURBS.keys()),
            geocoding_enabled=config.ENABLE_GEOCODING,
            error="Please describe what you're seeing.",
        )

    photo_path = _save_report_photo(request.files.get("photo"))
    user = auth.current_user()

    result = database.submit_report(
        suburb=suburb,
        description=description,
        time_started=time_noticed or None,
        reporter_contact=contact,
        reporter_user_id=user["id"] if user else None,
        photo_path=photo_path,
        latitude=latitude,
        longitude=longitude,
    )

    # Snapshot current weather against the outage (new or merged-into) --
    # this is what powers the weather-correlation view in analytics.
    if config.ENABLE_WEATHER:
        w = weather.get_weather_for_suburb(suburb)
        if w:
            database.set_weather_snapshot(result["outage_id"], w)

    return render_template(
        "report.html", suburbs=sorted(config.SUBURBS.keys()),
        geocoding_enabled=config.ENABLE_GEOCODING,
        success=True, is_new_outage=result["is_new_outage"],
        report_count=result["report_count"],
    )


# --------------------------------------------------------------------------
# Admin actions (manual data entry -- e.g. from confirmed Facebook posts)
# --------------------------------------------------------------------------

@app.route("/admin/add", methods=["POST"])
def admin_add():
    if not session.get("is_admin"):
        return redirect(url_for("admin"))

    suburb = request.form.get("suburb")
    coords = config.SUBURBS.get(suburb, {})

    record = {
        "suburb": suburb,
        "area": request.form.get("area"),
        "date": request.form.get("date"),
        "time_started": request.form.get("time_started"),
        "status": request.form.get("status"),
        "outage_type": request.form.get("outage_type"),
        "reason": request.form.get("reason"),
        "estimated_restoration": request.form.get("estimated_restoration"),
        "source": "Admin (manual entry)",
        "latitude": coords.get("lat"),
        "longitude": coords.get("lon"),
    }
    result = database.upsert_outage(record)

    subscribers = database.get_subscribers_for_suburb(suburb)
    if subscribers and record["status"] != "Restored":
        saved = database.get_outage(result["id"])
        notifications.notify_subscribers(saved, subscribers, event="new")

    return redirect(url_for("admin"))


@app.route("/admin/verify/<int:outage_id>", methods=["POST"])
def admin_verify(outage_id):
    if not session.get("is_admin"):
        return redirect(url_for("admin"))
    new_status = request.form.get("new_status", "Verified")
    database.verify_outage(outage_id, new_status=new_status)

    outage = database.get_outage(outage_id)
    if outage and new_status == "Active":
        subscribers = database.get_subscribers_for_suburb(outage["suburb"])
        notifications.notify_subscribers(outage, subscribers, event="new")

    return redirect(url_for("admin"))


@app.route("/admin/restore/<int:outage_id>", methods=["POST"])
def admin_restore(outage_id):
    if not session.get("is_admin"):
        return redirect(url_for("admin"))
    database.mark_restored(outage_id)

    outage = database.get_outage(outage_id)
    if outage:
        subscribers = database.get_subscribers_for_suburb(outage["suburb"])
        notifications.notify_subscribers(outage, subscribers, event="restored")

    return redirect(url_for("admin"))


@app.route("/admin/delete/<int:outage_id>", methods=["POST"])
def admin_delete(outage_id):
    if not session.get("is_admin"):
        return redirect(url_for("admin"))
    database.delete_outage(outage_id)
    return redirect(url_for("admin"))


@app.route("/admin/update-now", methods=["POST"])
def admin_update_now():
    if not session.get("is_admin"):
        return redirect(url_for("admin"))
    scraper.run_scraper()
    return redirect(url_for("admin"))


# --------------------------------------------------------------------------
# JSON API (consumed by static/script.js and map.js, and reusable as a
# public REST API later per the project plan's "Future Features")
# --------------------------------------------------------------------------

@app.route("/health")
def health():
    """
    Basic health check for deployment platforms (Render/Railway) to poll.
    Confirms the app can actually talk to its own database, not just that
    the process is alive.
    """
    try:
        database.get_last_updated()
        return jsonify({"status": "ok"})
    except Exception as e:
        return jsonify({"status": "error", "detail": str(e)}), 503


@app.route("/api/national-summary")
def api_national_summary():
    summary = database.get_national_summary()
    if not summary:
        return jsonify({"available": False})
    return jsonify({"available": True, **summary})


@app.route("/api/weather/<suburb>")
def api_weather(suburb):
    if suburb not in config.SUBURBS:
        return jsonify({"error": "Unknown suburb"}), 404
    w = weather.get_weather_for_suburb(suburb)
    if not w:
        return jsonify({"available": False})
    return jsonify({
        "available": True,
        **w,
        "summary": weather.weather_summary_line(w),
        "severe": weather.is_severe_weather(w),
    })


@app.route("/api/outages")
def api_outages():
    status = request.args.get("status")
    suburb = request.args.get("suburb")
    return jsonify(database.get_all_outages(status=status, suburb=suburb))


@app.route("/outage/<int:outage_id>")
def outage_detail(outage_id):
    outage = database.get_outage(outage_id)
    if not outage:
        return render_template("outage_detail.html", outage=None), 404

    timeline = database.get_timeline(outage_id)
    reports = database.get_reports_for_outage(outage_id)
    # Reporter contact details are only shown to logged-in admins --
    # public visitors see the report descriptions/photos but not contacts.
    is_admin = session.get("is_admin", False)
    if not is_admin:
        reports = [{**r, "reporter_contact": None} for r in reports]

    return render_template(
        "outage_detail.html",
        outage=outage,
        timeline=timeline,
        reports=reports,
        is_admin=is_admin,
        weather_summary=weather.weather_summary_line({
            "description": outage.get("weather_description"),
            "temperature_c": outage.get("weather_temp_c"),
            "wind_kph": outage.get("weather_wind_kph"),
        }) if outage.get("weather_condition") else None,
    )


@app.route("/api/outages/<int:outage_id>")
def api_outage_detail(outage_id):
    outage = database.get_outage(outage_id)
    if not outage:
        return jsonify({"error": "not found"}), 404
    return jsonify(outage)


@app.route("/api/stats")
def api_stats():
    return jsonify(database.get_stats())


@app.route("/api/last-updated")
def api_last_updated():
    return jsonify({"last_updated": database.get_last_updated()})


@app.route("/api/suburbs")
def api_suburbs():
    return jsonify(config.SUBURBS)


# --------------------------------------------------------------------------
# Startup
# --------------------------------------------------------------------------
#
# This runs at import time -- not just inside `if __name__ == "__main__"` --
# because a production server (gunicorn, etc) imports this module and looks
# for a WSGI object directly; it never executes the __main__ block. Doing
# init here means `gunicorn app:application` and `python app.py` both
# correctly set up the database, background scheduler, and first scrape.

def create_app():
    database.init_db()
    scheduler.start_scheduler()
    # Run once immediately on startup so the app isn't empty for the
    # first UPDATE_INTERVAL_MINUTES.
    scraper.run_scraper()
    return app


application = create_app()

if __name__ == "__main__":
    application.run(debug=config.DEBUG, host="0.0.0.0", port=5000)
