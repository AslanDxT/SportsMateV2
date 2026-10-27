"""Creating, editing, joining, leaving and cancelling activities."""

import threading
from datetime import date, timedelta

import pytest

from conftest import db, flashes, future, query, scalar, sport_id, user_id


def activity_count(app):
    return scalar(app, "SELECT COUNT(*) FROM activities")


def participants(app, activity_id=1):
    return scalar(app, "SELECT COUNT(*) FROM activity_participants WHERE activity_id = ?", (activity_id,))


def set_start(app, activity_id, day, time="10:00"):
    conn = db(app)
    conn.execute("UPDATE activities SET date = ?, time = ? WHERE id = ?", (day, time, activity_id))
    conn.close()


# --------------------------------------------------
# Create
# --------------------------------------------------

def test_create_activity(alice, app):
    response = alice.create_activity()
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/activities/1")

    row = query(app, "SELECT * FROM activities")[0]
    assert row["title"] == "Sunday kickabout"
    assert row["status"] == "open"
    assert participants(app) == 1  # the host is in the activity

    page = alice.get("/activities/1").get_data(as_text=True)
    assert "Sunday kickabout" in page
    assert "You host this activity." in page


@pytest.mark.parametrize("changes, message", [
    ({"title": ""}, "Give your activity a title."),
    ({"title": "x" * 81}, "Use at most 80 characters."),
    ({"sport_id": "999"}, "Choose a sport from the list."),
    ({"sport_id": "abc"}, "Choose a sport from the list."),
    ({"date": "2020-01-01"}, "Choose a date and time in the future."),
    ({"date": (date.today() + timedelta(days=400)).isoformat()}, "Plan at most one year ahead."),
    ({"date": "not-a-date"}, "Enter a valid date and time."),
    ({"time": "25:99"}, "Enter a valid date and time."),
    ({"location": ""}, "Tell people where to meet."),
    ({"skill_level": "Wizard"}, "Choose a skill level from the list."),
    ({"max_participants": "1"}, "Allow at least 2 people."),
    ({"max_participants": "99999"}, "The limit is 100 people."),
    ({"max_participants": "ten"}, "Enter a number."),
])
def test_create_activity_validation(alice, app, changes, message):
    response = alice.create_activity(**changes)
    assert response.status_code == 200
    assert message in response.get_data(as_text=True)
    assert activity_count(app) == 0


def test_create_form_keeps_values_after_error(alice):
    response = alice.create_activity(title="Padel night", location="")
    page = response.get_data(as_text=True)
    assert 'value="Padel night"' in page


def test_create_limit_per_day(alice, app):
    for number in range(10):
        assert alice.create_activity(title=f"Game {number}").status_code == 302
    response = alice.create_activity(title="One too many")
    assert response.status_code == 302
    assert activity_count(app) == 10


def test_html_in_title_is_escaped(alice, bob):
    alice.create_activity(title="<script>alert(1)</script>", description="<img src=x onerror=alert(1)>")
    for url in ("/activities", "/activities/1"):
        page = bob.get(url).get_data(as_text=True)
        assert "<script>alert(1)</script>" not in page
        assert "&lt;script&gt;" in page
        assert "<img src=x" not in page


# --------------------------------------------------
# Join and leave
# --------------------------------------------------

def test_join_and_leave(alice, bob, app):
    alice.create_activity()
    response = bob.post("/activities/1/join", follow_redirects=True)
    assert "You&#39;re in! See you there." in flashes(response)
    assert participants(app) == 2
    assert "You're in this activity." in response.get_data(as_text=True)

    # The host was told
    assert scalar(app, "SELECT COUNT(*) FROM notifications WHERE user_id = ?", (user_id(app, "alice@example.com"),)) == 1

    again = bob.post("/activities/1/join", follow_redirects=True)
    assert "already in this activity" in again.get_data(as_text=True)
    assert participants(app) == 2

    left = bob.post("/activities/1/leave", follow_redirects=True)
    assert "You left the activity." in flashes(left)
    assert participants(app) == 1


def test_leave_when_not_joined(alice, bob, app):
    alice.create_activity()
    response = bob.post("/activities/1/leave", follow_redirects=True)
    assert "You&#39;re not in this activity." in flashes(response)


def test_host_cannot_leave(alice, app):
    alice.create_activity()
    response = alice.post("/activities/1/leave", follow_redirects=True)
    assert "Cancel it instead" in " ".join(flashes(response))
    assert participants(app) == 1


def test_activity_becomes_full(alice, bob, carol, app):
    alice.create_activity(max_participants="2")
    assert bob.post("/activities/1/join").status_code == 302
    response = carol.post("/activities/1/join", follow_redirects=True)
    assert "Sorry, this activity is full." in flashes(response)
    assert participants(app) == 2
    page = carol.get("/activities/1").get_data(as_text=True)
    assert "This activity is full" in page


def test_cannot_join_past_activity(alice, bob, app):
    alice.create_activity()
    set_start(app, 1, "2020-01-01")
    response = bob.post("/activities/1/join", follow_redirects=True)
    assert "already started" in " ".join(flashes(response))
    assert participants(app) == 1


def test_join_missing_activity_is_404(bob):
    assert bob.post("/activities/42/join").status_code == 404
    assert bob.get("/activities/42").status_code == 404


def test_last_spot_goes_to_one_person_only(alice, make_browser, app):
    """Many people press Join at the same moment for the last free spot."""
    alice.create_activity(max_participants="2")
    people = []
    for number in range(8):
        person = make_browser()
        person.register(f"Player {number}", f"player{number}@example.com")
        person.token()
        people.append(person)

    results = []

    def press_join(person):
        results.append(person.post("/activities/1/join").status_code)

    threads = [threading.Thread(target=press_join, args=(person,)) for person in people]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert results == [302] * 8
    assert participants(app) == 2


# --------------------------------------------------
# Edit, cancel and remove (host only)
# --------------------------------------------------

def test_only_host_can_edit(alice, bob, app):
    alice.create_activity()
    assert bob.get("/activities/1/edit").status_code == 403
    assert bob.post("/activities/1/edit", {"title": "Hacked"}).status_code == 403
    assert scalar(app, "SELECT title FROM activities") == "Sunday kickabout"


def test_host_edits_and_participants_are_notified(alice, bob, app):
    alice.create_activity()
    bob.post("/activities/1/join")
    response = alice.post("/activities/1/edit", {
        "title": "Sunday kickabout (new time)",
        "sport_id": str(sport_id(app, "Football")),
        "description": "",
        "date": future(4),
        "time": "11:00",
        "location": "Julianapark, Venlo",
        "skill_level": "Intermediate",
        "max_participants": "12",
    })
    assert response.status_code == 302
    row = query(app, "SELECT * FROM activities")[0]
    assert row["title"] == "Sunday kickabout (new time)" and row["time"] == "11:00"
    assert row["max_participants"] == 12
    bob_id = user_id(app, "bob@example.com")
    assert scalar(app, "SELECT COUNT(*) FROM notifications WHERE user_id = ? AND message LIKE '%changed%'", (bob_id,)) == 1


def test_limit_cannot_go_below_participants(alice, bob, carol, app):
    alice.create_activity(max_participants="5")
    bob.post("/activities/1/join")
    carol.post("/activities/1/join")
    response = alice.post("/activities/1/edit", {
        "title": "Sunday kickabout", "sport_id": str(sport_id(app, "Football")),
        "date": future(), "time": "10:30", "location": "Park",
        "skill_level": "Beginner", "max_participants": "2",
    })
    assert response.status_code == 200
    assert "3 people already joined" in response.get_data(as_text=True)
    assert scalar(app, "SELECT max_participants FROM activities") == 5


def test_cancel_activity(alice, bob, carol, app):
    alice.create_activity()
    bob.post("/activities/1/join")

    assert bob.post("/activities/1/cancel").status_code == 403
    response = alice.post("/activities/1/cancel", follow_redirects=True)
    assert "Activity cancelled." in " ".join(flashes(response))
    assert scalar(app, "SELECT status FROM activities") == "cancelled"

    bob_id = user_id(app, "bob@example.com")
    assert scalar(app, "SELECT COUNT(*) FROM notifications WHERE user_id = ? AND message LIKE '%cancelled%'", (bob_id,)) == 1

    # Nobody can join a cancelled activity
    join = carol.post("/activities/1/join", follow_redirects=True)
    assert "was cancelled" in " ".join(flashes(join))

    # Hidden from people who were not part of it, still visible to participants
    assert "Sunday kickabout" not in carol.get("/activities").get_data(as_text=True)
    assert "Sunday kickabout" in bob.get("/activities").get_data(as_text=True)


def test_host_removes_participant(alice, bob, carol, app):
    alice.create_activity()
    bob.post("/activities/1/join")
    bob_id = user_id(app, "bob@example.com")

    assert carol.post(f"/activities/1/participants/{bob_id}/remove").status_code == 403
    response = alice.post(f"/activities/1/participants/{bob_id}/remove", follow_redirects=True)
    assert "Participant removed." in flashes(response)
    assert participants(app) == 1
    assert scalar(app, "SELECT COUNT(*) FROM notifications WHERE user_id = ? AND message LIKE '%removed you%'", (bob_id,)) == 1


# --------------------------------------------------
# Browsing
# --------------------------------------------------

def test_browse_filters(alice, bob, app):
    alice.create_activity(title="Morning run", sport_id=str(sport_id(app, "Running")), skill_level="Advanced")
    alice.create_activity(title="Padel night", sport_id=str(sport_id(app, "Padel")), location="Eindhoven")
    bob.create_activity(title="Bob's football")
    bob.post("/activities/1/join")

    def titles(url):
        page = alice.get(url).get_data(as_text=True)
        return {t for t in ("Morning run", "Padel night", "Bob&#39;s football") if t in page}

    assert titles("/activities") == {"Morning run", "Padel night", "Bob&#39;s football"}
    assert titles("/activities?sport=Running") == {"Morning run"}
    assert titles("/activities?skill=Advanced") == {"Morning run"}
    assert titles("/activities?q=eindhoven") == {"Padel night"}
    assert titles("/activities?show=hosting") == {"Morning run", "Padel night"}
    assert titles("/activities?q=%25") == set()  # % is searched literally, not as a wildcard
    assert titles("/activities?q=' OR 1=1 --") == set()

    bob_page = bob.get("/activities?show=joined").get_data(as_text=True)
    assert "Morning run" in bob_page and "Padel night" not in bob_page


def test_past_activities_are_not_upcoming(alice, app):
    """Regression: the old dashboard showed finished activities as 'upcoming'."""
    alice.create_activity(title="Old game")
    set_start(app, 1, "2020-01-01")
    alice.create_activity(title="New game")

    assert "Old game" not in alice.get("/dashboard").get_data(as_text=True)
    assert "Old game" not in alice.get("/activities").get_data(as_text=True)
    past = alice.get("/activities?when=past").get_data(as_text=True)
    assert "Old game" in past and "New game" not in past


def test_open_only_filter_hides_full_activities(alice, bob, carol, app):
    alice.create_activity(title="Tiny game", max_participants="2")
    bob.post("/activities/1/join")
    page = carol.get("/activities?open_only=1").get_data(as_text=True)
    assert "Tiny game" not in page


def test_pagination(alice, app):
    conn = db(app)
    host = user_id(app, "alice@example.com")
    for number in range(30):
        conn.execute(
            "INSERT INTO activities (creator_id, title, sport_id, date, time, location) VALUES (?, ?, 1, ?, '10:00', 'Venlo')",
            (host, f"Game number {number:02d}", future(1 + number % 20)),
        )
    conn.close()
    first = alice.get("/activities").get_data(as_text=True)
    second = alice.get("/activities?page=2").get_data(as_text=True)
    assert first.count('class="fixture ') == 24
    assert second.count('class="fixture ') == 6
    assert "Next" in first and "Previous" in second
