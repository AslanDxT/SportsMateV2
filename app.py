"""
SportsMate - find people, play sports, stay active.

Start the development server with:   python app.py
"""

import logging
import os

from flask import Flask, g, render_template, request, session
from werkzeug.exceptions import HTTPException

import database
import helpers
from config import build_config, env_bool, env_int
from security import apply_security_headers, csrf_token, verify_csrf


def create_app(overrides=None):
    app = Flask(__name__)
    app.config.update(build_config())
    if overrides:
        app.config.update(overrides)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    if app.config.get("TRUST_PROXY"):
        from werkzeug.middleware.proxy_fix import ProxyFix
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    backup = database.init_db(app.config["DATABASE_PATH"], app.config.get("BACKUP_DIR"))
    if backup:
        app.logger.info("Database upgraded. Backup of the old version: %s", backup)

    app.teardown_appcontext(database.close_db)

    from views import register_blueprints
    register_blueprints(app)

    _register_request_hooks(app)
    _register_template_helpers(app)
    _register_error_pages(app)

    return app


def _register_request_hooks(app):

    @app.before_request
    def load_user_and_check_csrf():
        g.user = None
        user_id = session.get("user_id")
        if user_id is not None:
            g.user = database.get_db().execute(
                """
                SELECT id, name, email, location, bio, skill_level, availability, created_at
                FROM users WHERE id = ?
                """,
                (user_id,),
            ).fetchone()
            if g.user is None:
                # The account no longer exists: forget the stale login.
                session.clear()
        verify_csrf()

    @app.after_request
    def security_headers(response):
        return apply_security_headers(response)


def _register_template_helpers(app):

    @app.context_processor
    def inject_globals():
        counts = {"notification_count": 0, "unread_messages": 0, "pending_requests": 0}
        if g.get("user") is not None:
            row = database.get_db().execute(
                """
                SELECT
                    (SELECT COUNT(*) FROM notifications WHERE user_id = :me AND is_read = 0) AS notification_count,
                    (SELECT COUNT(*) FROM messages WHERE receiver_id = :me AND is_read = 0) AS unread_messages,
                    (SELECT COUNT(*) FROM connections WHERE receiver_id = :me AND status = 'pending') AS pending_requests
                """,
                {"me": g.user["id"]},
            ).fetchone()
            counts = dict(row)
        return {
            "current_user": g.get("user"),
            "csrf_token": csrf_token,
            "limits": helpers.LIMITS,
            "skill_levels": helpers.SKILL_LEVELS,
            "app_version": app.config["APP_VERSION"],
            **counts,
        }

    app.jinja_env.filters["day_label"] = helpers.day_label
    app.jinja_env.filters["long_date"] = helpers.long_date
    app.jinja_env.filters["timestamp"] = helpers.timestamp_label
    app.jinja_env.filters["month_year"] = helpers.month_year
    app.jinja_env.filters["sport_image"] = helpers.sport_image
    app.jinja_env.filters["initial"] = lambda name: (name or "?").strip()[:1].upper() or "?"
    app.jinja_env.globals["notification_link"] = helpers.notification_link
    app.jinja_env.trim_blocks = True
    app.jinja_env.lstrip_blocks = True


ERROR_TEXT = {
    400: ("Something was wrong with that request", "Go back, reload the page and try again."),
    403: ("You can't do that", "This page or action belongs to someone else."),
    404: ("Page not found", "The page you're looking for doesn't exist or was removed."),
    405: ("That action isn't available here", "Use the buttons on the page instead of typing the address."),
    413: ("That was too much text", "Shorten what you entered and try again."),
    429: ("Too many attempts", "Wait a few minutes before you try again."),
    500: ("Something went wrong on our side", "Try again in a moment. If it keeps happening, tell the SportsMate team."),
}


def _register_error_pages(app):

    @app.errorhandler(HTTPException)
    def http_error(error):
        code = error.code or 500
        title, text = ERROR_TEXT.get(code, (error.name, error.description))
        if code == 400 and error.description == "csrf":
            title = "This form has expired"
            text = "For your safety, forms stop working after a while. Go back, reload the page and send it again."
        return render_template("error.html", code=code, title=title, text=text), code

    @app.errorhandler(Exception)
    def unexpected_error(error):
        app.logger.exception("Unhandled error on %s %s", request.method, request.path)
        title, text = ERROR_TEXT[500]
        return render_template("error.html", code=500, title=title, text=text), 500


if __name__ == "__main__":
    application = create_app()
    host = os.environ.get("SPORTSMATE_HOST", "127.0.0.1")
    debug = env_bool("SPORTSMATE_DEBUG", False)
    if debug and host not in {"127.0.0.1", "localhost", "::1"}:
        # The debugger can run Python code, so never expose it to a network.
        application.logger.warning("SPORTSMATE_DEBUG ignored because SPORTSMATE_HOST is %s.", host)
        debug = False
    application.run(host=host, port=env_int("SPORTSMATE_PORT", 5000), debug=debug)
