"""Create account, log in and log out."""

import sqlite3

from flask import Blueprint, abort, flash, g, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from database import get_db, transaction
from helpers import LIMITS, SKILL_LEVELS, clean, parse_int, password_problem, too_long, valid_email
from security import client_ip, is_safe_next_url, limiter

bp = Blueprint("auth", __name__)

# Used when the email is unknown, so a wrong email takes as long as a wrong password.
_DUMMY_HASH = generate_password_hash("sportsmate-timing-protection")

# (attempts, seconds). Per-IP limits are generous because a whole classroom
# or office can share one IP address.
LOGIN_LIMIT_PER_IP = (40, 15 * 60)       # failed logins
LOGIN_LIMIT_PER_EMAIL = (8, 15 * 60)     # failed logins for one account
REGISTER_LIMIT_PER_IP = (20, 60 * 60)


def _sports():
    return get_db().execute(
        "SELECT id, name FROM sports ORDER BY name = 'Other', name"
    ).fetchall()


def _start_session(user_id):
    session.clear()
    session.permanent = True
    session["user_id"] = user_id


@bp.route("/register", methods=["GET", "POST"])
def register():
    if g.user is not None:
        return redirect(url_for("main.dashboard"))

    sports = _sports()
    values = {"skill_level": "Beginner"}
    errors = {}

    if request.method == "POST":
        if limiter.hit(f"register:{client_ip()}", *REGISTER_LIMIT_PER_IP):
            abort(429)

        values = {
            "name": clean(request.form.get("name")),
            "email": clean(request.form.get("email")).lower(),
            "location": clean(request.form.get("location")),
            "skill_level": request.form.get("skill_level", "Beginner"),
            "sport_id": parse_int(request.form.get("sport_id")),
        }
        password = request.form.get("password", "")
        confirm = request.form.get("confirm_password", "")

        if not values["name"]:
            errors["name"] = "Enter your name."
        elif too_long(values["name"], "name"):
            errors["name"] = f"Use at most {LIMITS['name']} characters."

        if not valid_email(values["email"]):
            errors["email"] = "Enter a valid email address, like you@example.com."

        problem = password_problem(password, confirm)
        if problem:
            errors["password"] = problem

        if too_long(values["location"], "location"):
            errors["location"] = f"Use at most {LIMITS['location']} characters."

        if values["skill_level"] not in SKILL_LEVELS:
            errors["skill_level"] = "Choose a skill level from the list."

        sport_ids = {sport["id"] for sport in sports}
        if values["sport_id"] is not None and values["sport_id"] not in sport_ids:
            errors["sport_id"] = "Choose a sport from the list."

        if not errors:
            try:
                with transaction() as db:
                    cursor = db.execute(
                        """
                        INSERT INTO users (name, email, password_hash, location, skill_level)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (
                            values["name"],
                            values["email"],
                            generate_password_hash(password),
                            values["location"],
                            values["skill_level"],
                        ),
                    )
                    user_id = cursor.lastrowid
                    if values["sport_id"]:
                        db.execute(
                            "INSERT INTO user_sports (user_id, sport_id) VALUES (?, ?)",
                            (user_id, values["sport_id"]),
                        )
            except sqlite3.IntegrityError:
                errors["email"] = "This email already has an account. Log in instead."
            else:
                _start_session(user_id)
                flash("Welcome to SportsMate! Add your sports so people can find you.", "success")
                return redirect(url_for("main.dashboard"))

        flash("Check the highlighted fields.", "error")

    return render_template("auth/register.html", sports=sports, values=values, errors=errors)


@bp.route("/login", methods=["GET", "POST"])
def login():
    next_url = request.values.get("next", "")
    if not is_safe_next_url(next_url):
        next_url = ""

    if g.user is not None:
        return redirect(next_url or url_for("main.dashboard"))

    email = ""

    if request.method == "POST":
        email = clean(request.form.get("email")).lower()
        password = request.form.get("password", "")

        ip_key = f"login-ip:{client_ip()}"
        email_key = f"login-email:{email}"
        if limiter.is_limited(ip_key, *LOGIN_LIMIT_PER_IP) or limiter.is_limited(email_key, *LOGIN_LIMIT_PER_EMAIL):
            abort(429)

        user = get_db().execute(
            "SELECT id, password_hash FROM users WHERE email = ?", (email,)
        ).fetchone()

        password_ok = check_password_hash(user["password_hash"] if user else _DUMMY_HASH, password)

        if user and password_ok:
            limiter.reset(email_key)
            _start_session(user["id"])
            flash("Welcome back!", "success")
            return redirect(next_url or url_for("main.dashboard"))

        limiter.add(ip_key)
        limiter.add(email_key)
        flash("Email or password is incorrect.", "error")

    return render_template("auth/login.html", email=email, next_url=next_url)


@bp.route("/logout", methods=["GET", "POST"])
def logout():
    # GET only shows where to go; logging out needs a POST with a CSRF token,
    # so other websites cannot log people out.
    if request.method == "GET":
        return redirect(url_for("main.dashboard") if g.user else url_for("main.index"))

    session.clear()
    flash("You are logged out. See you on the field!", "success")
    return redirect(url_for("main.index"))
