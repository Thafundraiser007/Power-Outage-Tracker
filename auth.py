"""
Thin authentication helpers on top of Flask's session cookie and
Werkzeug's password hashing (already a Flask dependency, so no new
package is needed for this).

This is intentionally simple -- suitable for a portfolio project, not
a drop-in for something handling real customer PII at scale. If this
ever needs to harden further: add email verification, rate-limit login
attempts, and consider Flask-Login for remember-me / more session
plumbing.
"""

from functools import wraps

from flask import session, redirect, url_for, request, jsonify
from werkzeug.security import generate_password_hash, check_password_hash

import database


def hash_password(password: str) -> str:
    return generate_password_hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return check_password_hash(password_hash, password)


def register_user(email: str, password: str) -> dict:
    """
    Returns {"success": True, "user": {...}} or {"success": False, "error": "..."}.
    Basic validation only -- this is a portfolio project, not a bank.
    """
    email = (email or "").strip().lower()
    if not email or "@" not in email:
        return {"success": False, "error": "Enter a valid email address."}
    if not password or len(password) < 8:
        return {"success": False, "error": "Password must be at least 8 characters."}
    if database.get_user_by_email(email):
        return {"success": False, "error": "An account with that email already exists."}

    user = database.create_user(email, hash_password(password))
    return {"success": True, "user": user}


def login_user(email: str, password: str) -> dict:
    user = database.get_user_by_email((email or "").strip().lower())
    if not user or not verify_password(password or "", user["password_hash"]):
        return {"success": False, "error": "Incorrect email or password."}
    session["user_id"] = user["id"]
    session["user_email"] = user["email"]
    return {"success": True, "user": user}


def logout_user():
    session.pop("user_id", None)
    session.pop("user_email", None)


def current_user() -> dict:
    """Returns the logged-in user's row, or None if nobody's logged in."""
    user_id = session.get("user_id")
    if not user_id:
        return None
    return database.get_user_by_id(user_id)


def login_required(view_func):
    """
    Route decorator: redirects to /login (or returns 401 for JSON/API
    requests) if nobody's logged in.
    """
    @wraps(view_func)
    def wrapped(*args, **kwargs):
        if not session.get("user_id"):
            if request.path.startswith("/api/"):
                return jsonify({"error": "Login required."}), 401
            return redirect(url_for("login", next=request.path))
        return view_func(*args, **kwargs)
    return wrapped
