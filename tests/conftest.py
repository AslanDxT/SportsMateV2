"""Shared test setup: a fresh app and database for every test."""

import re
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import create_app  # noqa: E402
from database import connect  # noqa: E402
from security import limiter  # noqa: E402

PASSWORD = "goal-keeper-77"


def future(days=3):
    return (date.today() + timedelta(days=days)).isoformat()


class Browser:
    """A test client that behaves like a person using a browser (with CSRF tokens)."""

    def __init__(self, app):
        self.app = app
        self.client = app.test_client()

    def token(self):
        with self.client.session_transaction() as session:
            token = session.get("_csrf_token")
        if not token:
            # Any page with a form creates a token, like in a real browser.
            self.client.get("/login")
            self.client.get("/dashboard")
            with self.client.session_transaction() as session:
                token = session.get("_csrf_token")
        return token

    def get(self, url, **kwargs):
        return self.client.get(url, **kwargs)

    def post(self, url, data=None, csrf=True, **kwargs):
        data = dict(data or {})
        if csrf:
            data.setdefault("csrf_token", self.token())
        return self.client.post(url, data=data, **kwargs)

    def register(self, name="Alice", email="alice@example.com", password=PASSWORD, **extra):
        data = {
            "name": name,
            "email": email,
            "password": password,
            "confirm_password": extra.pop("confirm_password", password),
            "location": extra.pop("location", "Venlo"),
            "skill_level": extra.pop("skill_level", "Beginner"),
            "sport_id": extra.pop("sport_id", ""),
        }
        data.update(extra)
        return self.post("/register", data)

    def login(self, email, password=PASSWORD):
        return self.post("/login", {"email": email, "password": password})

    def create_activity(self, **overrides):
        data = {
            "title": "Sunday kickabout",
            "sport_id": str(sport_id(self.app, "Football")),
            "description": "Bring water.",
            "date": future(),
            "time": "10:30",
            "location": "Julianapark, Venlo",
            "skill_level": "Beginner",
            "max_participants": "10",
        }
        data.update(overrides)
        return self.post("/activities/create", data)


def db(app):
    return connect(app.config["DATABASE_PATH"])


def query(app, sql, params=()):
    conn = db(app)
    try:
        return conn.execute(sql, params).fetchall()
    finally:
        conn.close()


def scalar(app, sql, params=()):
    rows = query(app, sql, params)
    return rows[0][0] if rows else None


def sport_id(app, name):
    return scalar(app, "SELECT id FROM sports WHERE name = ?", (name,))


def user_id(app, email):
    return scalar(app, "SELECT id FROM users WHERE email = ?", (email,))


def flashes(response):
    return re.findall(r'<div class="flash flash--\w+"[^>]*>.*?<p>(.*?)</p>', response.get_data(as_text=True), re.S)


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("SPORTSMATE_INSTANCE_DIR", str(tmp_path / "instance"))
    monkeypatch.delenv("SECRET_KEY", raising=False)
    monkeypatch.delenv("SPORTSMATE_ENV", raising=False)
    application = create_app({
        "TESTING": True,
        "DATABASE_PATH": str(tmp_path / "test.db"),
        "BACKUP_DIR": str(tmp_path / "backups"),
    })
    limiter._events.clear()
    yield application
    limiter._events.clear()


@pytest.fixture
def browser(app):
    return Browser(app)


@pytest.fixture
def make_browser(app):
    def factory():
        return Browser(app)
    return factory


@pytest.fixture
def alice(make_browser):
    b = make_browser()
    b.register("Alice", "alice@example.com", sport_id="")
    return b


@pytest.fixture
def bob(make_browser):
    b = make_browser()
    b.register("Bob", "bob@example.com")
    return b


@pytest.fixture
def carol(make_browser):
    b = make_browser()
    b.register("Carol", "carol@example.com", location="Eindhoven")
    return b
