"""Landing page, dashboard, notifications and app files."""

from datetime import timedelta

from flask import Blueprint, current_app, g, redirect, render_template, send_from_directory, url_for

from database import get_db
from helpers import ACTIVITY_SELECT, enrich_activity, now_key, now_local, notification_link
from security import login_required

bp = Blueprint("main", __name__)


@bp.route("/")
def index():
    if g.user is not None:
        return redirect(url_for("main.dashboard"))

    # Public overview without personal data: how many activities per sport
    # are planned in the next two weeks.
    until = (now_local() + timedelta(days=14)).strftime("%Y-%m-%d 23:59")
    board = get_db().execute(
        """
        SELECT s.name AS sport_name, COUNT(*) AS planned
        FROM activities a
        JOIN sports s ON s.id = a.sport_id
        WHERE a.status = 'open'
          AND (a.date || ' ' || a.time) >= ?
          AND (a.date || ' ' || a.time) <= ?
        GROUP BY s.name
        ORDER BY planned DESC, s.name
        LIMIT 6
        """,
        (now_key(), until),
    ).fetchall()

    return render_template("index.html", board=board, board_total=sum(row["planned"] for row in board))


@bp.route("/dashboard")
@login_required
def dashboard():
    db = get_db()
    me = g.user["id"]
    now = now_key()

    my_rows = db.execute(
        ACTIVITY_SELECT
        + """
        WHERE (a.date || ' ' || a.time) >= :now
          AND EXISTS(SELECT 1 FROM activity_participants p WHERE p.activity_id = a.id AND p.user_id = :me)
        ORDER BY a.date, a.time
        LIMIT 4
        """,
        {"me": me, "now": now},
    ).fetchall()

    # Suggestions: open activities the user has not joined, with their own
    # sports and home town first.
    suggestion_rows = db.execute(
        ACTIVITY_SELECT
        + """
        WHERE a.status = 'open'
          AND (a.date || ' ' || a.time) >= :now
          AND NOT EXISTS(SELECT 1 FROM activity_participants p WHERE p.activity_id = a.id AND p.user_id = :me)
          AND (SELECT COUNT(*) FROM activity_participants p WHERE p.activity_id = a.id) < a.max_participants
        ORDER BY
            EXISTS(SELECT 1 FROM user_sports us WHERE us.user_id = :me AND us.sport_id = a.sport_id) DESC,
            (lower(trim(a.location)) LIKE '%' || lower(trim(:home)) || '%' AND trim(:home) != '') DESC,
            a.date, a.time
        LIMIT 6
        """,
        {"me": me, "now": now, "home": g.user["location"] or ""},
    ).fetchall()

    has_sports = db.execute(
        "SELECT 1 FROM user_sports WHERE user_id = ? LIMIT 1", (me,)
    ).fetchone() is not None

    return render_template(
        "dashboard.html",
        my_activities=[enrich_activity(row, me, now) for row in my_rows],
        suggestions=[enrich_activity(row, me, now) for row in suggestion_rows],
        profile_incomplete=not has_sports or not g.user["location"],
    )


@bp.route("/notifications")
@login_required
def notifications():
    db = get_db()
    rows = db.execute(
        """
        SELECT id, type, message, related_id, link, is_read, created_at
        FROM notifications
        WHERE user_id = ?
        ORDER BY created_at DESC, id DESC
        LIMIT 100
        """,
        (g.user["id"],),
    ).fetchall()

    items = []
    for row in rows:
        item = dict(row)
        item["href"] = notification_link(row)
        items.append(item)

    db.execute("UPDATE notifications SET is_read = 1 WHERE user_id = ? AND is_read = 0", (g.user["id"],))

    return render_template("notifications.html", notifications=items)


@bp.route("/service-worker.js")
def service_worker():
    response = send_from_directory(current_app.static_folder, "service-worker.js", max_age=0)
    response.headers["Service-Worker-Allowed"] = "/"
    response.headers["Cache-Control"] = "no-cache"
    return response
