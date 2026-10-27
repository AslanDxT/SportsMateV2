"""Find SportsMates, profiles, account settings and connections."""

from flask import Blueprint, abort, flash, g, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from database import get_db, transaction
from helpers import (
    ACTIVITY_SELECT,
    LIMITS,
    SKILL_LEVELS,
    clean,
    clean_multiline,
    enrich_activity,
    notify,
    now_key,
    parse_int,
    password_problem,
    too_long,
)
from security import is_safe_next_url, limiter, login_required

bp = Blueprint("people", __name__)

PAGE_SIZE = 30
REQUESTS_PER_HOUR = 30

# Connection state between the current user (:me) and another user (u.id).
CONNECTION_COLUMNS = """
    (SELECT c.id FROM connections c
      WHERE (c.sender_id = :me AND c.receiver_id = u.id) OR (c.sender_id = u.id AND c.receiver_id = :me)
      ORDER BY c.status = 'accepted' DESC LIMIT 1) AS connection_id,
    (SELECT c.status FROM connections c
      WHERE (c.sender_id = :me AND c.receiver_id = u.id) OR (c.sender_id = u.id AND c.receiver_id = :me)
      ORDER BY c.status = 'accepted' DESC LIMIT 1) AS connection_status,
    (SELECT c.sender_id FROM connections c
      WHERE (c.sender_id = :me AND c.receiver_id = u.id) OR (c.sender_id = u.id AND c.receiver_id = :me)
      ORDER BY c.status = 'accepted' DESC LIMIT 1) AS connection_sender
"""

SPORTS_COLUMN = """
    (SELECT GROUP_CONCAT(s.name, '|') FROM user_sports us JOIN sports s ON s.id = us.sport_id
      WHERE us.user_id = u.id) AS sports_list
"""


def connection_state(row, me_id):
    """none, sent, received or connected (from the current user's point of view)."""
    if not row["connection_id"]:
        return "none"
    if row["connection_status"] == "accepted":
        return "connected"
    return "sent" if row["connection_sender"] == me_id else "received"


def _person(row, me_id, my_sports):
    person = dict(row)
    sports = sorted(filter(None, (row["sports_list"] or "").split("|")))
    person["sports"] = sports
    person["shared_sports"] = [sport for sport in sports if sport in my_sports]
    person["connection"] = connection_state(row, me_id)
    return person


def _my_sport_names(user_id):
    rows = get_db().execute(
        "SELECT s.name FROM user_sports us JOIN sports s ON s.id = us.sport_id WHERE us.user_id = ?",
        (user_id,),
    ).fetchall()
    return {row["name"] for row in rows}


def _redirect_back(default_endpoint="people.connections", **values):
    target = request.form.get("next", "")
    if is_safe_next_url(target):
        return redirect(target)
    return redirect(url_for(default_endpoint, **values))


# --------------------------------------------------
# Find SportsMates
# --------------------------------------------------

@bp.route("/mates")
@login_required
def mates():
    me = g.user["id"]
    filters = {
        "q": clean(request.args.get("q"), LIMITS["search"]),
        "location": clean(request.args.get("location"), LIMITS["search"]),
        "sport": clean(request.args.get("sport")),
    }
    page = max(parse_int(request.args.get("page"), 1) or 1, 1)

    where = ["u.id != :me"]
    params = {"me": me, "home": (g.user["location"] or "").strip().lower()}

    def like(value):
        return "%" + value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"

    if filters["q"]:
        where.append("u.name LIKE :q ESCAPE '\\'")
        params["q"] = like(filters["q"])
    if filters["location"]:
        where.append("u.location LIKE :location ESCAPE '\\'")
        params["location"] = like(filters["location"])
    if filters["sport"]:
        where.append(
            "EXISTS(SELECT 1 FROM user_sports us JOIN sports s ON s.id = us.sport_id "
            "WHERE us.user_id = u.id AND s.name = :sport)"
        )
        params["sport"] = filters["sport"]

    params["limit"] = PAGE_SIZE + 1
    params["offset"] = (page - 1) * PAGE_SIZE

    rows = get_db().execute(
        f"""
        SELECT u.id, u.name, u.location, u.bio, u.skill_level,
            {SPORTS_COLUMN},
            {CONNECTION_COLUMNS},
            (SELECT COUNT(*) FROM user_sports mine
               JOIN user_sports theirs ON theirs.sport_id = mine.sport_id
              WHERE mine.user_id = :me AND theirs.user_id = u.id) AS shared_count
        FROM users u
        WHERE {" AND ".join(where)}
        ORDER BY shared_count DESC,
                 (lower(trim(u.location)) = :home AND :home != '') DESC,
                 u.name COLLATE NOCASE
        LIMIT :limit OFFSET :offset
        """,
        params,
    ).fetchall()

    my_sports = _my_sport_names(me)
    people = [_person(row, me, my_sports) for row in rows[:PAGE_SIZE]]
    sports = get_db().execute("SELECT name FROM sports ORDER BY name = 'Other', name").fetchall()

    return render_template(
        "people/mates.html",
        people=people,
        sports=sports,
        filters=filters,
        active_filters=any(filters.values()),
        page=page,
        has_next=len(rows) > PAGE_SIZE,
        query_args={key: value for key, value in request.args.items() if key != "page"},
    )


# --------------------------------------------------
# Profiles
# --------------------------------------------------

@bp.route("/profile/<int:user_id>")
@login_required
def profile(user_id):
    db = get_db()
    me = g.user["id"]
    now = now_key()

    row = db.execute(
        f"""
        SELECT u.id, u.name, u.location, u.bio, u.skill_level, u.availability, u.created_at,
            {SPORTS_COLUMN},
            {CONNECTION_COLUMNS}
        FROM users u WHERE u.id = :id
        """,
        {"id": user_id, "me": me},
    ).fetchone()
    if row is None:
        abort(404)

    person = _person(row, me, _my_sport_names(me))

    hosting = db.execute(
        ACTIVITY_SELECT
        + """
        WHERE a.creator_id = :id AND a.status = 'open' AND (a.date || ' ' || a.time) >= :now
        ORDER BY a.date, a.time LIMIT 6
        """,
        {"id": user_id, "me": me, "now": now},
    ).fetchall()

    playing = db.execute(
        ACTIVITY_SELECT
        + """
        WHERE a.creator_id != :id AND a.status = 'open' AND (a.date || ' ' || a.time) >= :now
          AND EXISTS(SELECT 1 FROM activity_participants p WHERE p.activity_id = a.id AND p.user_id = :id)
        ORDER BY a.date, a.time LIMIT 6
        """,
        {"id": user_id, "me": me, "now": now},
    ).fetchall()

    stats = db.execute(
        """
        SELECT
            (SELECT COUNT(*) FROM activities WHERE creator_id = :id AND status != 'cancelled') AS hosted,
            (SELECT COUNT(*) FROM activity_participants p JOIN activities a ON a.id = p.activity_id
              WHERE p.user_id = :id AND a.status != 'cancelled' AND (a.date || ' ' || a.time) < :now) AS played,
            (SELECT COUNT(*) FROM connections
              WHERE status = 'accepted' AND (sender_id = :id OR receiver_id = :id)) AS mates
        """,
        {"id": user_id, "now": now},
    ).fetchone()

    return render_template(
        "people/profile.html",
        person=person,
        is_me=user_id == me,
        hosting=[enrich_activity(r, me, now) for r in hosting],
        playing=[enrich_activity(r, me, now) for r in playing],
        stats=stats,
    )


@bp.route("/profile/edit", methods=["GET", "POST"])
@login_required
def edit_profile():
    db = get_db()
    me = g.user["id"]
    sports = db.execute("SELECT id, name FROM sports ORDER BY name = 'Other', name").fetchall()
    selected = {
        row["sport_id"]
        for row in db.execute("SELECT sport_id FROM user_sports WHERE user_id = ?", (me,))
    }
    values = dict(g.user)
    errors = {}

    if request.method == "POST":
        values = {
            "name": clean(request.form.get("name")),
            "location": clean(request.form.get("location")),
            "bio": clean_multiline(request.form.get("bio")),
            "skill_level": request.form.get("skill_level", "Beginner"),
            "availability": clean(request.form.get("availability")),
        }
        chosen = {parse_int(value) for value in request.form.getlist("sports")}
        valid_ids = {sport["id"] for sport in sports}

        if not values["name"]:
            errors["name"] = "Enter your name."
        for field, limit_key in (("name", "name"), ("location", "location"), ("bio", "bio"), ("availability", "availability")):
            if field not in errors and too_long(values[field], limit_key):
                errors[field] = f"Use at most {LIMITS[limit_key]} characters."
        if values["skill_level"] not in SKILL_LEVELS:
            errors["skill_level"] = "Choose a skill level from the list."
        if not chosen <= valid_ids:
            errors["sports"] = "Choose sports from the list."
        selected = chosen & valid_ids

        if not errors:
            with transaction() as db:
                db.execute(
                    """
                    UPDATE users SET name = ?, location = ?, bio = ?, skill_level = ?, availability = ?
                    WHERE id = ?
                    """,
                    (values["name"], values["location"], values["bio"],
                     values["skill_level"], values["availability"], me),
                )
                db.execute("DELETE FROM user_sports WHERE user_id = ?", (me,))
                db.executemany(
                    "INSERT INTO user_sports (user_id, sport_id) VALUES (?, ?)",
                    [(me, sport_id) for sport_id in sorted(selected)],
                )
            flash("Profile saved.", "success")
            return redirect(url_for("people.profile", user_id=me))

        flash("Check the highlighted fields.", "error")

    return render_template(
        "people/edit_profile.html",
        values=values,
        errors=errors,
        sports=sports,
        selected=selected,
    )


@bp.route("/account/password", methods=["POST"])
@login_required
def change_password():
    me = g.user["id"]
    if limiter.hit(f"password-change:{me}", 10, 15 * 60):
        abort(429)

    current = request.form.get("current_password", "")
    new = request.form.get("new_password", "")
    confirm = request.form.get("confirm_password", "")

    row = get_db().execute("SELECT password_hash FROM users WHERE id = ?", (me,)).fetchone()
    if not check_password_hash(row["password_hash"], current):
        flash("Your current password is not correct.", "error")
        return redirect(url_for("people.edit_profile") + "#account")

    problem = password_problem(new, confirm)
    if problem:
        flash(problem, "error")
        return redirect(url_for("people.edit_profile") + "#account")

    get_db().execute("UPDATE users SET password_hash = ? WHERE id = ?", (generate_password_hash(new), me))
    flash("Password changed.", "success")
    return redirect(url_for("people.edit_profile"))


@bp.route("/account/delete", methods=["POST"])
@login_required
def delete_account():
    me = g.user["id"]
    if limiter.hit(f"account-delete:{me}", 10, 15 * 60):
        abort(429)

    row = get_db().execute("SELECT password_hash FROM users WHERE id = ?", (me,)).fetchone()
    if not check_password_hash(row["password_hash"], request.form.get("password", "")):
        flash("Your password is not correct, so your account was not deleted.", "error")
        return redirect(url_for("people.edit_profile") + "#account")

    with transaction() as db:
        hosted = db.execute(
            """
            SELECT a.id, a.title, p.user_id
            FROM activities a JOIN activity_participants p ON p.activity_id = a.id
            WHERE a.creator_id = ? AND p.user_id != ? AND a.status = 'open'
              AND (a.date || ' ' || a.time) >= ?
            """,
            (me, me, now_key()),
        ).fetchall()
        for item in hosted:
            notify(db, item["user_id"], "activity",
                   f"\"{item['title']}\" was cancelled because the host deleted their account.")
        # Activities, participations, connections, messages and notifications
        # of this user are removed by ON DELETE CASCADE.
        db.execute("DELETE FROM users WHERE id = ?", (me,))

    session.clear()
    flash("Your account and your data were deleted.", "success")
    return redirect(url_for("main.index"))


# --------------------------------------------------
# Connections
# --------------------------------------------------

@bp.route("/connections")
@login_required
def connections():
    db = get_db()
    me = g.user["id"]

    received = db.execute(
        """
        SELECT c.id, u.id AS user_id, u.name, u.location, u.skill_level
        FROM connections c JOIN users u ON u.id = c.sender_id
        WHERE c.receiver_id = ? AND c.status = 'pending'
        ORDER BY c.created_at DESC
        """,
        (me,),
    ).fetchall()

    sent = db.execute(
        """
        SELECT c.id, u.id AS user_id, u.name, u.location, u.skill_level
        FROM connections c JOIN users u ON u.id = c.receiver_id
        WHERE c.sender_id = ? AND c.status = 'pending'
        ORDER BY c.created_at DESC
        """,
        (me,),
    ).fetchall()

    accepted = db.execute(
        """
        SELECT c.id, u.id AS user_id, u.name, u.location, u.skill_level
        FROM connections c
        JOIN users u ON u.id = CASE WHEN c.sender_id = :me THEN c.receiver_id ELSE c.sender_id END
        WHERE (c.sender_id = :me OR c.receiver_id = :me) AND c.status = 'accepted'
        ORDER BY u.name COLLATE NOCASE
        """,
        {"me": me},
    ).fetchall()

    return render_template("people/connections.html", received=received, sent=sent, accepted=accepted)


@bp.route("/connections/request/<int:user_id>", methods=["POST"])
@login_required
def request_connection(user_id):
    me = g.user["id"]
    if user_id == me:
        flash("You can't connect with yourself.", "error")
        return _redirect_back("people.mates")

    with transaction() as db:
        other = db.execute("SELECT id, name FROM users WHERE id = ?", (user_id,)).fetchone()
        if other is None:
            abort(404)

        existing = db.execute(
            """
            SELECT id, sender_id, status FROM connections
            WHERE (sender_id = ? AND receiver_id = ?) OR (sender_id = ? AND receiver_id = ?)
            """,
            (me, user_id, user_id, me),
        ).fetchone()

        if existing and existing["status"] == "accepted":
            flash(f"You and {other['name']} are already SportsMates.", "info")
        elif existing and existing["sender_id"] == me:
            flash("You already sent a request. Wait for an answer.", "info")
        elif existing:
            # They already asked us: sending a request back means yes.
            db.execute("UPDATE connections SET status = 'accepted' WHERE id = ?", (existing["id"],))
            notify(db, user_id, "connection", f"{g.user['name']} accepted your SportsMate request.",
                   link=url_for("people.profile", user_id=me), related_id=me)
            flash(f"You and {other['name']} are now SportsMates.", "success")
        else:
            sent_last_hour = db.execute(
                "SELECT COUNT(*) FROM connections WHERE sender_id = ? AND created_at >= datetime('now', '-1 hour')",
                (me,),
            ).fetchone()[0]
            if sent_last_hour >= REQUESTS_PER_HOUR:
                flash("You sent a lot of requests. Try again in an hour.", "error")
            else:
                db.execute(
                    "INSERT INTO connections (sender_id, receiver_id, status) VALUES (?, ?, 'pending')",
                    (me, user_id),
                )
                notify(db, user_id, "connection", f"{g.user['name']} wants to be your SportsMate.",
                       link=url_for("people.connections"), related_id=me)
                flash(f"Request sent to {other['name']}.", "success")

    return _redirect_back("people.mates")


@bp.route("/connections/<int:connection_id>/<action>", methods=["POST"])
@login_required
def connection_action(connection_id, action):
    if action not in {"accept", "decline", "cancel", "remove"}:
        abort(404)
    me = g.user["id"]

    with transaction() as db:
        connection = db.execute(
            "SELECT id, sender_id, receiver_id, status FROM connections WHERE id = ?", (connection_id,)
        ).fetchone()
        if connection is None:
            flash("This request no longer exists.", "info")
            return _redirect_back()

        is_sender = connection["sender_id"] == me
        is_receiver = connection["receiver_id"] == me
        if not (is_sender or is_receiver):
            abort(403)

        pending = connection["status"] == "pending"

        if action == "accept":
            if not (is_receiver and pending):
                abort(403)
            db.execute("UPDATE connections SET status = 'accepted' WHERE id = ?", (connection_id,))
            notify(db, connection["sender_id"], "connection", f"{g.user['name']} accepted your SportsMate request.",
                   link=url_for("people.profile", user_id=me), related_id=me)
            flash("Request accepted. You can now send messages to each other.", "success")

        elif action == "decline":
            if not (is_receiver and pending):
                abort(403)
            db.execute("DELETE FROM connections WHERE id = ?", (connection_id,))
            flash("Request declined.", "success")

        elif action == "cancel":
            if not (is_sender and pending):
                abort(403)
            db.execute("DELETE FROM connections WHERE id = ?", (connection_id,))
            flash("Request withdrawn.", "success")

        elif action == "remove":
            if pending:
                abort(403)
            db.execute("DELETE FROM connections WHERE id = ?", (connection_id,))
            flash("SportsMate removed.", "success")

    return _redirect_back()
