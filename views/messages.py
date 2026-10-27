"""Private messages between connected SportsMates."""

from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for

from database import get_db
from helpers import LIMITS, clean_multiline
from security import limiter, login_required

bp = Blueprint("messages", __name__, url_prefix="/messages")

HISTORY_LIMIT = 200
MESSAGES_PER_MINUTE = 20


def _are_connected(db, me, other):
    return db.execute(
        """
        SELECT 1 FROM connections
        WHERE status = 'accepted'
          AND ((sender_id = ? AND receiver_id = ?) OR (sender_id = ? AND receiver_id = ?))
        """,
        (me, other, other, me),
    ).fetchone() is not None


@bp.route("")
@login_required
def inbox():
    me = g.user["id"]
    # Only the current user's own SportsMates, newest conversation first.
    rows = get_db().execute(
        """
        WITH mates AS (
            SELECT CASE WHEN sender_id = :me THEN receiver_id ELSE sender_id END AS mate_id
            FROM connections
            WHERE status = 'accepted' AND (sender_id = :me OR receiver_id = :me)
        )
        SELECT
            u.id, u.name, u.location,
            last.message AS last_message,
            last.sender_id AS last_sender,
            last.created_at AS last_at,
            (SELECT COUNT(*) FROM messages m
              WHERE m.sender_id = u.id AND m.receiver_id = :me AND m.is_read = 0) AS unread
        FROM mates
        JOIN users u ON u.id = mates.mate_id
        LEFT JOIN messages last ON last.id = (
            SELECT m.id FROM messages m
            WHERE (m.sender_id = :me AND m.receiver_id = u.id) OR (m.sender_id = u.id AND m.receiver_id = :me)
            ORDER BY m.created_at DESC, m.id DESC LIMIT 1
        )
        GROUP BY u.id
        ORDER BY last.created_at IS NULL, last.created_at DESC, last.id DESC, u.name COLLATE NOCASE
        """,
        {"me": me},
    ).fetchall()

    return render_template("messages/inbox.html", conversations=rows)


@bp.route("/<int:user_id>", methods=["GET", "POST"])
@login_required
def conversation(user_id):
    db = get_db()
    me = g.user["id"]

    if user_id == me:
        return redirect(url_for("messages.inbox"))

    other = db.execute(
        "SELECT id, name, location FROM users WHERE id = ?", (user_id,)
    ).fetchone()
    if other is None:
        abort(404)

    if not _are_connected(db, me, user_id):
        flash(f"Connect with {other['name']} first. Then you can send messages.", "info")
        return redirect(url_for("people.profile", user_id=user_id))

    draft = ""

    if request.method == "POST":
        text = clean_multiline(request.form.get("message"))
        if not text:
            flash("Write a message first.", "error")
        elif len(text) > LIMITS["message"]:
            flash(f"Messages can have at most {LIMITS['message']} characters.", "error")
            draft = text
        elif limiter.hit(f"message:{me}", MESSAGES_PER_MINUTE, 60):
            flash("You're sending messages very fast. Wait a moment.", "error")
            draft = text
        else:
            db.execute(
                "INSERT INTO messages (sender_id, receiver_id, message) VALUES (?, ?, ?)",
                (me, user_id, text),
            )
            return redirect(url_for("messages.conversation", user_id=user_id) + "#latest")

        if not draft:
            return redirect(url_for("messages.conversation", user_id=user_id))

    history = db.execute(
        """
        SELECT * FROM (
            SELECT id, sender_id, message, created_at FROM messages
            WHERE (sender_id = ? AND receiver_id = ?) OR (sender_id = ? AND receiver_id = ?)
            ORDER BY created_at DESC, id DESC
            LIMIT ?
        ) ORDER BY created_at, id
        """,
        (me, user_id, user_id, me, HISTORY_LIMIT),
    ).fetchall()

    db.execute(
        "UPDATE messages SET is_read = 1 WHERE sender_id = ? AND receiver_id = ? AND is_read = 0",
        (user_id, me),
    )
    # Old versions also created a notification per message; mark those read too.
    db.execute(
        "UPDATE notifications SET is_read = 1 WHERE user_id = ? AND type = 'message' AND related_id = ? AND is_read = 0",
        (me, user_id),
    )

    return render_template("messages/conversation.html", other=other, history=history, draft=draft)
