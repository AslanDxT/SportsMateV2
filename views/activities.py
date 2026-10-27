"""Find, create, edit, join and leave activities."""

from datetime import timedelta

from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for

from database import get_db, transaction
from helpers import (
    ACTIVITY_SELECT,
    LIMITS,
    MAX_DAYS_AHEAD,
    MAX_PARTICIPANTS,
    SKILL_LEVELS,
    clean,
    enrich_activity,
    notify,
    now_key,
    now_local,
    parse_activity_start,
    parse_int,
    validate_activity,
)
from security import login_required

bp = Blueprint("activities", __name__, url_prefix="/activities")

PAGE_SIZE = 24
CREATE_LIMIT_PER_DAY = 10


def _sports():
    return get_db().execute(
        "SELECT id, name FROM sports ORDER BY name = 'Other', name"
    ).fetchall()


def _load(activity_id):
    """Activity with counts for the current user, or a 404 page."""
    row = get_db().execute(
        ACTIVITY_SELECT + " WHERE a.id = :id",
        {"id": activity_id, "me": g.user["id"]},
    ).fetchone()
    if row is None:
        abort(404)
    return enrich_activity(row, g.user["id"])


def _back_to(activity_id):
    return redirect(url_for("activities.detail", activity_id=activity_id))


def _form_limits():
    today = now_local().date()
    return {
        "min_date": today.isoformat(),
        "max_date": (today + timedelta(days=MAX_DAYS_AHEAD)).isoformat(),
        "max_participants": MAX_PARTICIPANTS,
    }


# --------------------------------------------------
# Browse
# --------------------------------------------------

@bp.route("")
@login_required
def browse():
    me = g.user["id"]
    now = now_key()

    filters = {
        "q": clean(request.args.get("q"), LIMITS["search"]),
        "sport": clean(request.args.get("sport")),
        "skill": clean(request.args.get("skill")),
        "when": request.args.get("when", "upcoming"),
        "show": request.args.get("show", "all"),
        "open_only": request.args.get("open_only") == "1",
    }
    if filters["when"] not in {"upcoming", "today", "week", "past"}:
        filters["when"] = "upcoming"
    if filters["show"] not in {"all", "joined", "hosting"}:
        filters["show"] = "all"
    if filters["skill"] not in SKILL_LEVELS:
        filters["skill"] = ""

    page = max(parse_int(request.args.get("page"), 1) or 1, 1)

    where = []
    params = {"me": me, "now": now}

    start = "(a.date || ' ' || a.time)"
    if filters["when"] == "past":
        where.append(f"{start} < :now")
    else:
        where.append(f"{start} >= :now")
        if filters["when"] == "today":
            where.append("a.date = :today")
            params["today"] = now_local().date().isoformat()
        elif filters["when"] == "week":
            where.append("a.date <= :week_end")
            params["week_end"] = (now_local().date() + timedelta(days=7)).isoformat()

    if filters["show"] == "joined":
        where.append("EXISTS(SELECT 1 FROM activity_participants p WHERE p.activity_id = a.id AND p.user_id = :me)")
    elif filters["show"] == "hosting":
        where.append("a.creator_id = :me")
    else:
        # Cancelled activities only matter to people who were part of them.
        where.append(
            "(a.status != 'cancelled' OR EXISTS(SELECT 1 FROM activity_participants p "
            "WHERE p.activity_id = a.id AND p.user_id = :me))"
        )

    if filters["sport"]:
        where.append("s.name = :sport")
        params["sport"] = filters["sport"]
    if filters["skill"]:
        where.append("a.skill_level = :skill")
        params["skill"] = filters["skill"]
    if filters["q"]:
        where.append("(a.title LIKE :q ESCAPE '\\' OR a.location LIKE :q ESCAPE '\\' OR a.description LIKE :q ESCAPE '\\')")
        escaped = filters["q"].replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        params["q"] = f"%{escaped}%"
    if filters["open_only"]:
        where.append("a.status = 'open'")
        where.append("(SELECT COUNT(*) FROM activity_participants p WHERE p.activity_id = a.id) < a.max_participants")

    order = "a.date DESC, a.time DESC" if filters["when"] == "past" else "a.date, a.time"
    params["limit"] = PAGE_SIZE + 1
    params["offset"] = (page - 1) * PAGE_SIZE

    rows = get_db().execute(
        ACTIVITY_SELECT + " WHERE " + " AND ".join(where) + f" ORDER BY {order} LIMIT :limit OFFSET :offset",
        params,
    ).fetchall()

    has_next = len(rows) > PAGE_SIZE
    activities = [enrich_activity(row, me, now) for row in rows[:PAGE_SIZE]]

    active_filters = any([filters["q"], filters["sport"], filters["skill"], filters["open_only"]])
    query_args = {key: value for key, value in request.args.items() if key != "page" and value}
    tab_args = {key: filters[key] for key in ("q", "sport", "skill") if filters[key]}
    if filters["when"] != "upcoming":
        tab_args["when"] = filters["when"]

    return render_template(
        "activities/list.html",
        activities=activities,
        sports=_sports(),
        filters=filters,
        active_filters=active_filters,
        page=page,
        has_next=has_next,
        query_args=query_args,
        tab_args=tab_args,
    )


# --------------------------------------------------
# Create and edit
# --------------------------------------------------

@bp.route("/create", methods=["GET", "POST"])
@login_required
def create():
    sports = _sports()
    values = {"skill_level": "Beginner", "max_participants": 10}
    errors = {}

    if request.method == "POST":
        db = get_db()
        created_today = db.execute(
            """
            SELECT COUNT(*) FROM activities
            WHERE creator_id = ? AND created_at >= datetime('now', '-1 day')
            """,
            (g.user["id"],),
        ).fetchone()[0]
        if created_today >= CREATE_LIMIT_PER_DAY:
            flash(f"You can create up to {CREATE_LIMIT_PER_DAY} activities per day. Try again tomorrow.", "error")
            return redirect(url_for("activities.browse", show="hosting"))

        values, errors = validate_activity(request.form, {sport["id"] for sport in sports})

        if not errors:
            with transaction() as db:
                cursor = db.execute(
                    """
                    INSERT INTO activities
                        (creator_id, title, sport_id, description, date, time,
                         location, skill_level, max_participants, status)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'open')
                    """,
                    (
                        g.user["id"], values["title"], values["sport_id"], values["description"],
                        values["date"], values["time"], values["location"],
                        values["skill_level"], values["max_participants"],
                    ),
                )
                activity_id = cursor.lastrowid
                db.execute(
                    "INSERT INTO activity_participants (activity_id, user_id) VALUES (?, ?)",
                    (activity_id, g.user["id"]),
                )
            flash("Your activity is live. Share it with your SportsMates!", "success")
            return _back_to(activity_id)

        flash("Check the highlighted fields.", "error")

    return render_template(
        "activities/form.html",
        editing=False,
        sports=sports,
        values=values,
        errors=errors,
        limits_form=_form_limits(),
    )


@bp.route("/<int:activity_id>/edit", methods=["GET", "POST"])
@login_required
def edit(activity_id):
    activity = _load(activity_id)
    if not activity["is_host"]:
        abort(403)
    if activity["state"] in {"cancelled", "past"}:
        flash("Finished or cancelled activities can't be changed.", "error")
        return _back_to(activity_id)

    sports = _sports()
    values = dict(activity)
    errors = {}

    if request.method == "POST":
        values, errors = validate_activity(
            request.form,
            {sport["id"] for sport in sports},
            current_participants=activity["participant_count"],
            existing_start=parse_activity_start(activity["date"], activity["time"]),
        )

        if not errors:
            changed_meeting = (
                values["date"] != activity["date"]
                or values["time"] != activity["time"]
                or values["location"] != activity["location"]
            )
            with transaction() as db:
                # Check the participant count again inside the transaction.
                count = db.execute(
                    "SELECT COUNT(*) FROM activity_participants WHERE activity_id = ?", (activity_id,)
                ).fetchone()[0]
                if values["max_participants"] < count:
                    errors["max_participants"] = f"{count} people already joined, so the limit must be at least {count}."
                else:
                    db.execute(
                        """
                        UPDATE activities
                        SET title = ?, sport_id = ?, description = ?, date = ?, time = ?,
                            location = ?, skill_level = ?, max_participants = ?,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE id = ? AND creator_id = ?
                        """,
                        (
                            values["title"], values["sport_id"], values["description"],
                            values["date"], values["time"], values["location"],
                            values["skill_level"], values["max_participants"],
                            activity_id, g.user["id"],
                        ),
                    )
                    if changed_meeting:
                        participants = db.execute(
                            "SELECT user_id FROM activity_participants WHERE activity_id = ? AND user_id != ?",
                            (activity_id, g.user["id"]),
                        ).fetchall()
                        for participant in participants:
                            notify(
                                db, participant["user_id"], "activity",
                                f"The time or place of \"{values['title']}\" changed. Check the new details.",
                                link=url_for("activities.detail", activity_id=activity_id),
                                related_id=activity_id,
                            )
            if not errors:
                flash("Changes saved.", "success")
                return _back_to(activity_id)

        flash("Check the highlighted fields.", "error")

    return render_template(
        "activities/form.html",
        editing=True,
        activity=activity,
        sports=sports,
        values=values,
        errors=errors,
        limits_form=_form_limits(),
    )


@bp.route("/<int:activity_id>/cancel", methods=["POST"])
@login_required
def cancel(activity_id):
    activity = _load(activity_id)
    if not activity["is_host"]:
        abort(403)
    if activity["state"] == "cancelled":
        flash("This activity is already cancelled.", "info")
        return _back_to(activity_id)
    if activity["state"] == "past":
        flash("This activity already took place.", "error")
        return _back_to(activity_id)

    with transaction() as db:
        db.execute(
            "UPDATE activities SET status = 'cancelled', updated_at = CURRENT_TIMESTAMP WHERE id = ? AND creator_id = ?",
            (activity_id, g.user["id"]),
        )
        participants = db.execute(
            "SELECT user_id FROM activity_participants WHERE activity_id = ? AND user_id != ?",
            (activity_id, g.user["id"]),
        ).fetchall()
        for participant in participants:
            notify(
                db, participant["user_id"], "activity",
                f"{g.user['name']} cancelled \"{activity['title']}\".",
                link=url_for("activities.detail", activity_id=activity_id),
                related_id=activity_id,
            )

    flash("Activity cancelled. Everyone who joined got a notification.", "success")
    return _back_to(activity_id)


# --------------------------------------------------
# Detail, join and leave
# --------------------------------------------------

@bp.route("/<int:activity_id>")
@login_required
def detail(activity_id):
    activity = _load(activity_id)
    participants = get_db().execute(
        """
        SELECT u.id, u.name, u.skill_level, u.location
        FROM activity_participants p
        JOIN users u ON u.id = p.user_id
        WHERE p.activity_id = ?
        ORDER BY u.id = ? DESC, p.joined_at, u.name
        """,
        (activity_id, activity["creator_id"]),
    ).fetchall()

    return render_template("activities/detail.html", activity=activity, participants=participants)


@bp.route("/<int:activity_id>/join", methods=["POST"])
@login_required
def join(activity_id):
    me = g.user["id"]

    with transaction() as db:
        row = db.execute(ACTIVITY_SELECT + " WHERE a.id = :id", {"id": activity_id, "me": me}).fetchone()
        if row is None:
            abort(404)
        activity = enrich_activity(row, me)

        if activity["is_joined"]:
            flash("You're already in this activity.", "info")
            return _back_to(activity_id)
        if activity["state"] == "cancelled":
            flash("This activity was cancelled, so you can't join it.", "error")
            return _back_to(activity_id)
        if activity["state"] == "past":
            flash("This activity already started, so you can't join anymore.", "error")
            return _back_to(activity_id)
        if activity["state"] == "full":
            flash("Sorry, this activity is full.", "error")
            return _back_to(activity_id)

        db.execute(
            "INSERT OR IGNORE INTO activity_participants (activity_id, user_id) VALUES (?, ?)",
            (activity_id, me),
        )
        notify(
            db, activity["creator_id"], "activity",
            f"{g.user['name']} joined \"{activity['title']}\".",
            link=url_for("activities.detail", activity_id=activity_id),
            related_id=activity_id,
        )

    flash("You're in! See you there.", "success")
    return _back_to(activity_id)


@bp.route("/<int:activity_id>/leave", methods=["POST"])
@login_required
def leave(activity_id):
    me = g.user["id"]

    with transaction() as db:
        row = db.execute(ACTIVITY_SELECT + " WHERE a.id = :id", {"id": activity_id, "me": me}).fetchone()
        if row is None:
            abort(404)
        activity = enrich_activity(row, me)

        if activity["is_host"]:
            flash("You host this activity. Cancel it instead of leaving.", "error")
            return _back_to(activity_id)
        if not activity["is_joined"]:
            flash("You're not in this activity.", "info")
            return _back_to(activity_id)
        if activity["state"] == "past":
            flash("This activity already started.", "error")
            return _back_to(activity_id)

        db.execute(
            "DELETE FROM activity_participants WHERE activity_id = ? AND user_id = ?",
            (activity_id, me),
        )
        if activity["state"] != "cancelled":
            notify(
                db, activity["creator_id"], "activity",
                f"{g.user['name']} left \"{activity['title']}\".",
                link=url_for("activities.detail", activity_id=activity_id),
                related_id=activity_id,
            )

    flash("You left the activity.", "success")
    return _back_to(activity_id)


@bp.route("/<int:activity_id>/participants/<int:user_id>/remove", methods=["POST"])
@login_required
def remove_participant(activity_id, user_id):
    activity = _load(activity_id)
    if not activity["is_host"]:
        abort(403)
    if user_id == g.user["id"]:
        flash("You can't remove yourself. Cancel the activity instead.", "error")
        return _back_to(activity_id)
    if activity["state"] == "past":
        flash("This activity already took place.", "error")
        return _back_to(activity_id)

    with transaction() as db:
        removed = db.execute(
            "DELETE FROM activity_participants WHERE activity_id = ? AND user_id = ?",
            (activity_id, user_id),
        ).rowcount
        if removed:
            notify(
                db, user_id, "activity",
                f"The host removed you from \"{activity['title']}\".",
                link=url_for("activities.detail", activity_id=activity_id),
                related_id=activity_id,
            )

    if removed:
        flash("Participant removed.", "success")
    else:
        flash("That person is not in this activity.", "info")
    return _back_to(activity_id)
