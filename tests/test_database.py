"""Database creation and upgrading old SportsMate databases without losing data."""

import sqlite3

from database import SCHEMA_VERSION, SPORTS, _SCHEMA_V1, init_db


def make_old_database(path):
    """A database exactly like the first SportsMate version created."""
    conn = sqlite3.connect(path)
    conn.executescript(_SCHEMA_V1)
    conn.execute("INSERT INTO sports (name) VALUES ('Football')")
    conn.execute("INSERT INTO users (name, email, password_hash, skill_level) VALUES ('Aslan', 'a@example.com', 'hash', 'Beginner')")
    conn.execute("INSERT INTO users (name, email, password_hash, skill_level) VALUES ('Blue', 'b@example.com', 'hash', 'Wizard')")
    conn.execute("""INSERT INTO activities (creator_id, title, sport_id, date, time, location, skill_level, max_participants)
                    VALUES (1, 'marathon', 1, '2026-10-13', '08:00', 'Venlo', 'Beginner', 10)""")
    # The host is missing from the participants on purpose.
    conn.execute("INSERT INTO activity_participants (activity_id, user_id) VALUES (1, 2)")
    conn.execute("INSERT INTO notifications (user_id, type, message, related_id) VALUES (1, 'activity', 'Blue joined', 1)")
    conn.commit()
    conn.close()


def test_upgrade_keeps_data_and_makes_backup(tmp_path):
    path = tmp_path / "sportsmate.db"
    make_old_database(path)

    backup = init_db(str(path), str(tmp_path / "backups"))
    assert backup is not None and backup.is_file()

    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    assert conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 2
    assert conn.execute("SELECT status FROM activities").fetchone()[0] == "open"
    assert conn.execute("SELECT link FROM notifications").fetchone()[0] == ""
    assert conn.execute("SELECT COUNT(*) FROM activity_participants WHERE user_id = 1").fetchone()[0] == 1
    assert conn.execute("SELECT skill_level FROM users WHERE id = 2").fetchone()[0] == "Beginner"
    assert conn.execute("SELECT id FROM sports WHERE name = 'Football'").fetchone()[0] == 1  # ids unchanged
    assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    conn.close()

    # The backup still holds the old version.
    old = sqlite3.connect(backup)
    assert old.execute("PRAGMA user_version").fetchone()[0] == 0
    assert old.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 2
    old.close()

    # Running again changes nothing and makes no second backup.
    assert init_db(str(path), str(tmp_path / "backups")) is None
    assert len(list((tmp_path / "backups").iterdir())) == 1


def test_fresh_database(tmp_path):
    path = tmp_path / "new.db"
    assert init_db(str(path), str(tmp_path / "backups")) is None  # nothing to back up
    conn = sqlite3.connect(path)
    names = {row[0] for row in conn.execute("SELECT name FROM sports")}
    assert names == set(SPORTS)
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert {"users", "activities", "activity_participants", "connections", "messages", "notifications"} <= tables
    conn.close()


def test_one_connection_per_pair(tmp_path):
    path = tmp_path / "pair.db"
    init_db(str(path))
    conn = sqlite3.connect(path)
    conn.execute("INSERT INTO users (name, email, password_hash) VALUES ('A', 'a@x.nl', 'h'), ('B', 'b@x.nl', 'h')")
    conn.execute("INSERT INTO connections (sender_id, receiver_id) VALUES (1, 2)")
    try:
        conn.execute("INSERT INTO connections (sender_id, receiver_id) VALUES (2, 1)")
        raised = False
    except sqlite3.IntegrityError:
        raised = True
    conn.close()
    assert raised
