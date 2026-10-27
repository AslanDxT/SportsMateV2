"""Registration, login, logout and access to protected pages."""

import pytest

from conftest import PASSWORD, flashes, query, scalar


def test_register_creates_account_and_logs_in(browser, app):
    response = browser.register("Alice", "Alice@Example.com", sport_id="1")
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/dashboard")

    row = query(app, "SELECT name, email, password_hash FROM users")[0]
    assert row["email"] == "alice@example.com"  # stored in lower case
    assert row["password_hash"] != PASSWORD and row["password_hash"].startswith(("scrypt:", "pbkdf2:"))
    assert scalar(app, "SELECT COUNT(*) FROM user_sports") == 1

    assert browser.get("/dashboard").status_code == 200


@pytest.mark.parametrize("changes, field_message", [
    ({"name": ""}, "Enter your name."),
    ({"name": "x" * 61}, "Use at most 60 characters."),
    ({"email": "not-an-email"}, "Enter a valid email address"),
    ({"password": "short", "confirm_password": "short"}, "at least 8 characters"),
    ({"password": "aaaaaaaa", "confirm_password": "aaaaaaaa"}, "harder to guess"),
    ({"confirm_password": "different-password"}, "not the same"),
    ({"skill_level": "Wizard"}, "Choose a skill level"),
    ({"sport_id": "999"}, "Choose a sport from the list."),
])
def test_register_validation(browser, app, changes, field_message):
    data = {"name": "Alice", "email": "alice@example.com", "password": PASSWORD}
    data.update(changes)
    response = browser.register(**data)
    assert response.status_code == 200
    assert field_message in response.get_data(as_text=True)
    assert scalar(app, "SELECT COUNT(*) FROM users") == 0


def test_register_duplicate_email_is_refused(make_browser, app):
    make_browser().register("Alice", "alice@example.com")
    response = make_browser().register("Other", "ALICE@example.com")
    assert response.status_code == 200
    assert "already has an account" in response.get_data(as_text=True)
    assert scalar(app, "SELECT COUNT(*) FROM users") == 1


def test_login_and_logout(make_browser):
    make_browser().register("Alice", "alice@example.com")
    browser = make_browser()

    bad = browser.login("alice@example.com", "wrong-password")
    assert bad.status_code == 200
    assert "Email or password is incorrect." in flashes(bad)

    good = browser.login("ALICE@example.com")
    assert good.status_code == 302 and good.headers["Location"].endswith("/dashboard")
    assert browser.get("/dashboard").status_code == 200

    # A plain GET (for example a link from another site) does not log out.
    browser.get("/logout")
    assert browser.get("/dashboard").status_code == 200

    out = browser.post("/logout")
    assert out.status_code == 302
    assert browser.get("/dashboard").status_code == 302


def test_unknown_email_gets_same_message(browser):
    response = browser.login("nobody@example.com", "whatever-123")
    assert "Email or password is incorrect." in flashes(response)


def test_login_redirects_back_to_requested_page(make_browser):
    make_browser().register("Alice", "alice@example.com")
    browser = make_browser()
    first = browser.get("/mates?sport=Tennis")
    assert first.status_code == 302 and "/login?next=" in first.headers["Location"]

    response = browser.post("/login", {"email": "alice@example.com", "password": PASSWORD, "next": "/mates?sport=Tennis"})
    assert response.headers["Location"].endswith("/mates?sport=Tennis")


@pytest.mark.parametrize("target", ["https://evil.example/", "//evil.example/", "/\\evil.example"])
def test_login_ignores_external_next_urls(make_browser, target):
    make_browser().register("Alice", "alice@example.com")
    browser = make_browser()
    response = browser.post("/login", {"email": "alice@example.com", "password": PASSWORD, "next": target})
    assert response.headers["Location"].endswith("/dashboard")


def test_login_is_rate_limited(make_browser):
    make_browser().register("Alice", "alice@example.com")
    browser = make_browser()
    for attempt in range(8):
        assert browser.login("alice@example.com", f"wrong-{attempt}").status_code == 200
    blocked = browser.login("alice@example.com")  # even the right password
    assert blocked.status_code == 429


@pytest.mark.parametrize("url", [
    "/dashboard", "/activities", "/activities/create", "/activities/1", "/mates",
    "/profile/1", "/profile/edit", "/connections", "/messages", "/messages/1", "/notifications",
])
def test_protected_pages_need_login(browser, url):
    response = browser.get(url)
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


def test_deleted_user_session_is_forgotten(alice, app):
    conn = __import__("conftest").db(app)
    conn.execute("DELETE FROM users")
    conn.close()
    response = alice.get("/dashboard")
    assert response.status_code == 302 and "/login" in response.headers["Location"]
    assert alice.get("/").status_code == 200


def test_logged_in_user_skips_landing_and_auth_pages(alice):
    assert alice.get("/").headers["Location"].endswith("/dashboard")
    assert alice.get("/login").headers["Location"].endswith("/dashboard")
    assert alice.get("/register").headers["Location"].endswith("/dashboard")
