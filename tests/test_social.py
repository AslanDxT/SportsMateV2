"""SportsMates (connections), messages, profiles, notifications and account settings."""

from conftest import PASSWORD, flashes, query, scalar, sport_id, user_id


def connection_rows(app):
    return query(app, "SELECT sender_id, receiver_id, status FROM connections")


def connect(app, sender, receiver_email):
    return sender.post(f"/connections/request/{user_id(app, receiver_email)}")


def make_mates(app, first, second, second_email):
    connect(app, first, second_email)
    connection_id = scalar(app, "SELECT id FROM connections ORDER BY id DESC LIMIT 1")
    second.post(f"/connections/{connection_id}/accept")
    return connection_id


# --------------------------------------------------
# Connections
# --------------------------------------------------

def test_connect_button_is_shown_and_request_flow_works(alice, bob, app):
    page = alice.get("/mates").get_data(as_text=True)
    assert "/connections/request/" in page  # the old version had no Connect button at all

    response = connect(app, alice, "bob@example.com")
    assert response.status_code == 302
    assert [tuple(r) for r in connection_rows(app)] == [(1, 2, "pending")]

    # Second request does not create a duplicate
    connect(app, alice, "bob@example.com")
    assert len(connection_rows(app)) == 1

    # Only the receiver can accept
    assert alice.post("/connections/1/accept").status_code == 403
    assert bob.post("/connections/1/accept").status_code == 302
    assert connection_rows(app)[0]["status"] == "accepted"


def test_request_back_accepts_existing_request(alice, bob, app):
    connect(app, alice, "bob@example.com")
    connect(app, bob, "alice@example.com")
    rows = connection_rows(app)
    assert len(rows) == 1 and rows[0]["status"] == "accepted"


def test_decline_cancel_and_remove(alice, bob, carol, app):
    connect(app, alice, "bob@example.com")
    assert bob.post("/connections/1/decline").status_code == 302
    assert connection_rows(app) == []

    connect(app, alice, "carol@example.com")
    cid = scalar(app, "SELECT id FROM connections")
    assert carol.post(f"/connections/{cid}/cancel").status_code == 403  # only the sender can withdraw
    assert alice.post(f"/connections/{cid}/cancel").status_code == 302
    assert connection_rows(app) == []

    cid = make_mates(app, alice, bob, "bob@example.com")
    assert carol.post(f"/connections/{cid}/remove").status_code == 403  # not her connection
    assert bob.post(f"/connections/{cid}/remove").status_code == 302
    assert connection_rows(app) == []


def test_unknown_connection_action_and_targets(alice, app):
    assert alice.post("/connections/1/hack").status_code == 404
    assert alice.post("/connections/request/999").status_code == 404
    response = alice.post(f"/connections/request/{user_id(app, 'alice@example.com')}", follow_redirects=True)
    assert "You can&#39;t connect with yourself." in flashes(response)


# --------------------------------------------------
# Messages
# --------------------------------------------------

def test_cannot_message_without_connection(alice, bob, app):
    response = alice.post(f"/messages/{user_id(app, 'bob@example.com')}", {"message": "Hi"})
    assert response.status_code == 302
    assert scalar(app, "SELECT COUNT(*) FROM messages") == 0


def test_messages_between_sportsmates(alice, bob, app):
    make_mates(app, alice, bob, "bob@example.com")
    bob_id = user_id(app, "bob@example.com")
    alice_id = user_id(app, "alice@example.com")

    assert alice.post(f"/messages/{bob_id}", {"message": "  "}).status_code == 302
    assert scalar(app, "SELECT COUNT(*) FROM messages") == 0

    too_long = alice.post(f"/messages/{bob_id}", {"message": "x" * 1001})
    assert too_long.status_code == 200
    assert scalar(app, "SELECT COUNT(*) FROM messages") == 0

    alice.post(f"/messages/{bob_id}", {"message": "See you on Sunday? <b>bold</b>"})
    assert scalar(app, "SELECT COUNT(*) FROM messages") == 1

    inbox = bob.get("/messages").get_data(as_text=True)
    assert "Alice" in inbox and 'aria-label="1 unread"' in inbox

    chat = bob.get(f"/messages/{alice_id}").get_data(as_text=True)
    assert "See you on Sunday?" in chat and "<b>bold</b>" not in chat
    assert scalar(app, "SELECT is_read FROM messages") == 1


def test_inbox_only_shows_own_sportsmates(alice, bob, carol, app):
    """Regression: the old inbox listed everyone who had any connection with anyone."""
    make_mates(app, alice, bob, "bob@example.com")
    inbox = carol.get("/messages").get_data(as_text=True)
    assert "Alice" not in inbox and "Bob" not in inbox
    assert "No conversations yet" in inbox


# --------------------------------------------------
# Profiles and people
# --------------------------------------------------

def test_profile_does_not_show_email(alice, bob, app):
    page = bob.get(f"/profile/{user_id(app, 'alice@example.com')}").get_data(as_text=True)
    assert "Alice" in page
    assert "alice@example.com" not in page


def test_missing_profile_is_404(alice):
    assert alice.get("/profile/999").status_code == 404


def test_edit_profile(alice, app):
    football, tennis = sport_id(app, "Football"), sport_id(app, "Tennis")
    response = alice.post("/profile/edit", {
        "name": "Alice B", "location": "Venlo", "bio": "Hi!", "skill_level": "Advanced",
        "availability": "Evenings", "sports": [str(football), str(tennis)],
    })
    assert response.status_code == 302
    row = query(app, "SELECT name, skill_level, availability FROM users")[0]
    assert tuple(row) == ("Alice B", "Advanced", "Evenings")
    assert scalar(app, "SELECT COUNT(*) FROM user_sports") == 2


def test_edit_profile_validation(alice, app):
    response = alice.post("/profile/edit", {"name": "", "skill_level": "Beginner"})
    assert response.status_code == 200 and "Enter your name." in response.get_data(as_text=True)

    response = alice.post("/profile/edit", {"name": "Alice", "skill_level": "Beginner", "sports": ["999"]})
    assert response.status_code == 200 and "Choose sports from the list." in response.get_data(as_text=True)
    assert scalar(app, "SELECT name FROM users") == "Alice"


def test_mates_shows_people_with_shared_sports_first(alice, bob, carol, app):
    football = str(sport_id(app, "Football"))
    for person, name in ((alice, "Alice"), (carol, "Carol")):
        person.post("/profile/edit", {"name": name, "skill_level": "Beginner", "sports": [football]})
    page = alice.get("/mates").get_data(as_text=True)
    assert page.index("Carol") < page.index("Bob")
    assert "You both play Football" in page
    assert ">Alice</a>" not in page  # you don't see yourself


# --------------------------------------------------
# Notifications
# --------------------------------------------------

def test_notifications_are_listed_with_links_and_marked_read(alice, bob, app):
    alice.create_activity()
    bob.post("/activities/1/join")
    page = alice.get("/notifications").get_data(as_text=True)
    assert "Bob joined" in page and 'href="/activities/1"' in page
    assert scalar(app, "SELECT COUNT(*) FROM notifications WHERE is_read = 0") == 0


# --------------------------------------------------
# Account settings
# --------------------------------------------------

def test_change_password(alice, make_browser):
    new = {"new_password": "new-pass-123", "confirm_password": "new-pass-123"}
    wrong = alice.post("/account/password", {"current_password": "nope", **new}, follow_redirects=True)
    assert "current password is not correct" in " ".join(flashes(wrong))

    ok = alice.post("/account/password", {"current_password": PASSWORD, **new}, follow_redirects=True)
    assert "Password changed." in flashes(ok)

    fresh = make_browser()
    assert fresh.login("alice@example.com", PASSWORD).status_code == 200
    assert fresh.login("alice@example.com", "new-pass-123").status_code == 302


def test_delete_account_removes_data(alice, bob, app):
    alice.create_activity()
    bob.post("/activities/1/join")
    make_mates(app, alice, bob, "bob@example.com")

    refused = alice.post("/account/delete", {"password": "wrong"})
    assert refused.status_code == 302
    assert scalar(app, "SELECT COUNT(*) FROM users") == 2

    assert alice.post("/account/delete", {"password": PASSWORD}).status_code == 302
    assert scalar(app, "SELECT COUNT(*) FROM users WHERE email = 'alice@example.com'") == 0
    assert scalar(app, "SELECT COUNT(*) FROM activities") == 0
    assert scalar(app, "SELECT COUNT(*) FROM connections") == 0
    bob_id = user_id(app, "bob@example.com")
    assert scalar(app, "SELECT COUNT(*) FROM notifications WHERE user_id = ? AND message LIKE '%deleted their account%'", (bob_id,)) == 1
    assert alice.get("/dashboard").status_code == 302
