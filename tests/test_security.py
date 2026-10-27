"""CSRF, sessions, headers, error handling and other security checks."""

import pytest
from flask.sessions import SecureCookieSessionInterface

from app import create_app
from conftest import db, scalar
from database import transaction


@pytest.mark.parametrize("url", [
    "/logout", "/activities/create", "/activities/1/join", "/activities/1/leave",
    "/connections/request/2", "/messages/2", "/profile/edit", "/account/delete",
])
def test_posts_without_csrf_token_are_rejected(alice, url):
    response = alice.post(url, {"title": "x"}, csrf=False)
    assert response.status_code == 400
    assert "This form has expired" in response.get_data(as_text=True)


def test_wrong_csrf_token_is_rejected(alice, app):
    response = alice.post("/activities/create", {"csrf_token": "guess", "title": "x"})
    assert response.status_code == 400
    assert scalar(app, "SELECT COUNT(*) FROM activities") == 0


def test_registration_needs_csrf_token(browser, app):
    response = browser.post("/register", {"name": "A", "email": "a@example.com", "password": "abcdefgh1", "confirm_password": "abcdefgh1"}, csrf=False)
    assert response.status_code == 400
    assert scalar(app, "SELECT COUNT(*) FROM users") == 0


def test_old_hardcoded_secret_key_is_gone(alice, app):
    """With the old public key anyone could forge a login cookie."""
    assert app.secret_key != "sportsmate-development-secret-key"
    assert len(app.secret_key) >= 32

    forged_app = create_app({"DATABASE_PATH": app.config["DATABASE_PATH"], "SECRET_KEY": "sportsmate-development-secret-key"})
    serializer = SecureCookieSessionInterface().get_signing_serializer(forged_app)
    forged = app.test_client()
    forged.set_cookie("session", serializer.dumps({"user_id": 1}))
    assert forged.get("/dashboard").status_code == 302  # not logged in


def test_secret_key_is_kept_between_restarts(app, tmp_path):
    again = create_app({"DATABASE_PATH": app.config["DATABASE_PATH"]})
    assert again.secret_key == app.secret_key
    assert (tmp_path / "instance" / "secret_key").is_file()


def test_production_requires_secret_key(monkeypatch, tmp_path):
    monkeypatch.setenv("SPORTSMATE_ENV", "production")
    monkeypatch.delenv("SECRET_KEY", raising=False)
    with pytest.raises(RuntimeError):
        create_app({"DATABASE_PATH": str(tmp_path / "x.db")})


def test_security_headers(alice):
    response = alice.get("/dashboard")
    assert "default-src 'self'" in response.headers["Content-Security-Policy"]
    assert "frame-ancestors 'none'" in response.headers["Content-Security-Policy"]
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["Cache-Control"] == "no-store"  # private pages are not stored


def test_session_cookie_flags(make_browser):
    response = make_browser().register("Alice", "alice@example.com")
    cookie = response.headers["Set-Cookie"]
    assert "HttpOnly" in cookie
    assert "SameSite=Lax" in cookie


def test_no_inline_scripts_or_handlers(browser, alice):
    for client, url in ((browser, "/"), (browser, "/login"), (alice, "/dashboard"), (alice, "/activities/create")):
        page = client.get(url).get_data(as_text=True)
        assert "<script>" not in page
        assert "onclick=" not in page


def test_service_worker_never_caches_pages(browser):
    response = browser.get("/service-worker.js")
    assert response.status_code == 200
    assert response.headers["Service-Worker-Allowed"] == "/"
    script = response.get_data(as_text=True)
    assert 'url.pathname.startsWith("/static/")' in script
    assert "cache.put(event.request" not in script  # the old worker stored every page


def test_unexpected_error_shows_friendly_page_and_releases_database(tmp_path, monkeypatch):
    monkeypatch.setenv("SPORTSMATE_INSTANCE_DIR", str(tmp_path / "instance"))
    app = create_app({"DATABASE_PATH": str(tmp_path / "t.db")})

    @app.route("/boom")
    def boom():
        with transaction() as conn:
            conn.execute("INSERT INTO sports (name) VALUES ('Half written')")
            raise RuntimeError("secret internal detail")

    client = app.test_client()
    response = client.get("/boom")
    assert response.status_code == 500
    page = response.get_data(as_text=True)
    assert "Something went wrong" in page
    assert "secret internal detail" not in page and "Traceback" not in page

    # The failed write was rolled back and the database is not locked.
    conn = db(app)
    assert conn.execute("SELECT COUNT(*) FROM sports WHERE name = 'Half written'").fetchone()[0] == 0
    conn.execute("INSERT INTO sports (name) VALUES ('Still writable')")
    conn.close()


def test_404_page(browser):
    response = browser.get("/does-not-exist")
    assert response.status_code == 404
    assert "Page not found" in response.get_data(as_text=True)


def test_large_requests_are_refused(alice):
    response = alice.post("/activities/create", {"description": "x" * 300_000})
    assert response.status_code == 413
