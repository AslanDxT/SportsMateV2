"""
Database access for SportsMate (SQLite).

- One connection per request, stored on flask.g and always closed afterwards
  (also when a request fails), so a crash can never leave the database locked.
- `transaction()` wraps several writes so they succeed or fail together.
- `init_db()` creates the tables and upgrades older databases step by step.
  Before an upgrade it writes a backup copy into the backups/ folder.
"""

import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from flask import current_app, g

log = logging.getLogger(__name__)

# Bump this number and add a step in `_MIGRATIONS` when the schema changes.
SCHEMA_VERSION = 2

SPORTS = [
    "Badminton",
    "Basketball",
    "Cycling",
    "Football",
    "Gym",
    "Hockey",
    "Padel",
    "Running",
    "Swimming",
    "Tennis",
    "Volleyball",
    "Other",
]

# Version 1 = the original SportsMate schema (unchanged, so old databases match).
_SCHEMA_V1 = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    location TEXT DEFAULT '',
    bio TEXT DEFAULT '',
    skill_level TEXT DEFAULT 'Beginner',
    availability TEXT DEFAULT '',
    profile_image TEXT DEFAULT '',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS sports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS user_sports (
    user_id INTEGER NOT NULL,
    sport_id INTEGER NOT NULL,
    PRIMARY KEY (user_id, sport_id),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (sport_id) REFERENCES sports(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS activities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    creator_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    sport_id INTEGER NOT NULL,
    description TEXT DEFAULT '',
    date TEXT NOT NULL,
    time TEXT NOT NULL,
    location TEXT NOT NULL,
    skill_level TEXT DEFAULT 'Beginner',
    max_participants INTEGER DEFAULT 10,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (creator_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (sport_id) REFERENCES sports(id)
);

CREATE TABLE IF NOT EXISTS activity_participants (
    activity_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (activity_id, user_id),
    FOREIGN KEY (activity_id) REFERENCES activities(id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS connections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sender_id INTEGER NOT NULL,
    receiver_id INTEGER NOT NULL,
    status TEXT DEFAULT 'pending',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(sender_id, receiver_id),
    FOREIGN KEY (sender_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (receiver_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sender_id INTEGER NOT NULL,
    receiver_id INTEGER NOT NULL,
    message TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    is_read INTEGER DEFAULT 0,
    FOREIGN KEY (sender_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (receiver_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    type TEXT NOT NULL,
    message TEXT NOT NULL,
    related_id INTEGER,
    is_read INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);
"""


# --------------------------------------------------
# Connections
# --------------------------------------------------

def connect(path):
    """Open a SQLite connection with the settings SportsMate relies on."""
    conn = sqlite3.connect(path, timeout=10, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def get_db():
    """Return the connection for the current request (opened on first use)."""
    if "db" not in g:
        g.db = connect(current_app.config["DATABASE_PATH"])
    return g.db


def close_db(_error=None):
    db = g.pop("db", None)
    if db is None:
        return
    if db.in_transaction:
        db.rollback()
    db.close()


@contextmanager
def transaction():
    """
    Run several statements as one unit.

    BEGIN IMMEDIATE takes the write lock straight away, so two people joining
    the last free spot at the same moment cannot both get it.
    """
    db = get_db()
    db.execute("BEGIN IMMEDIATE")
    try:
        yield db
    except BaseException:
        db.execute("ROLLBACK")
        raise
    else:
        db.execute("COMMIT")


# --------------------------------------------------
# Schema creation and upgrades
# --------------------------------------------------

def _columns(conn, table):
    return {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}


def _run_script(conn, script):
    # executescript() would COMMIT the open transaction, so run statements one by one.
    for statement in script.split(";"):
        if statement.strip():
            conn.execute(statement)


def _migrate_to_v1(conn):
    _run_script(conn, _SCHEMA_V1)


def _migrate_to_v2(conn):
    """Activity status, notification links, indexes and integrity fixes."""
    activity_columns = _columns(conn, "activities")
    if "status" not in activity_columns:
        conn.execute("ALTER TABLE activities ADD COLUMN status TEXT NOT NULL DEFAULT 'open'")
    if "updated_at" not in activity_columns:
        conn.execute("ALTER TABLE activities ADD COLUMN updated_at TIMESTAMP")

    if "link" not in _columns(conn, "notifications"):
        conn.execute("ALTER TABLE notifications ADD COLUMN link TEXT NOT NULL DEFAULT ''")

    _run_script(conn, """
        CREATE INDEX IF NOT EXISTS idx_activities_start ON activities(date, time);
        CREATE INDEX IF NOT EXISTS idx_activities_creator ON activities(creator_id);
        CREATE INDEX IF NOT EXISTS idx_participants_user ON activity_participants(user_id);
        CREATE INDEX IF NOT EXISTS idx_user_sports_sport ON user_sports(sport_id);
        CREATE INDEX IF NOT EXISTS idx_connections_receiver ON connections(receiver_id, status);
        CREATE INDEX IF NOT EXISTS idx_messages_pair ON messages(sender_id, receiver_id, created_at);
        CREATE INDEX IF NOT EXISTS idx_messages_unread ON messages(receiver_id, is_read);
        CREATE INDEX IF NOT EXISTS idx_notifications_user ON notifications(user_id, is_read);
    """)

    # Only one connection per pair of people, in either direction.
    try:
        conn.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_connections_pair
            ON connections(min(sender_id, receiver_id), max(sender_id, receiver_id))
        """)
    except sqlite3.IntegrityError:
        log.warning(
            "Existing duplicate connections found; the unique pair index was not "
            "created. The application still prevents new duplicates."
        )

    # The host of an activity is always one of its participants.
    conn.execute("""
        INSERT OR IGNORE INTO activity_participants (activity_id, user_id)
        SELECT id, creator_id FROM activities
    """)

    # Unknown skill levels (possible in the old version) become Beginner.
    conn.execute("""
        UPDATE activities SET skill_level = 'Beginner'
        WHERE skill_level NOT IN ('Beginner', 'Intermediate', 'Advanced') OR skill_level IS NULL
    """)
    conn.execute("""
        UPDATE users SET skill_level = 'Beginner'
        WHERE skill_level NOT IN ('Beginner', 'Intermediate', 'Advanced') OR skill_level IS NULL
    """)


_MIGRATIONS = {
    1: _migrate_to_v1,
    2: _migrate_to_v2,
}


def _backup(conn, db_path, backup_dir, from_version):
    backup_dir = Path(backup_dir)
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = backup_dir / f"{Path(db_path).stem}-{stamp}-before-v{SCHEMA_VERSION}.db"
    backup_conn = sqlite3.connect(target)
    try:
        conn.backup(backup_conn)
    finally:
        backup_conn.close()
    log.info("Database backup written to %s (schema v%s)", target, from_version)
    return target


def init_db(db_path, backup_dir=None):
    """Create or upgrade the database. Safe to run on every start."""
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = connect(db_path)
    try:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        has_data = conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table' AND name = 'users'"
        ).fetchone()[0]

        backup_path = None
        if version < SCHEMA_VERSION and has_data and backup_dir:
            backup_path = _backup(conn, db_path, backup_dir, version)

        for target in range(version + 1, SCHEMA_VERSION + 1):
            conn.execute("BEGIN IMMEDIATE")
            try:
                _MIGRATIONS[target](conn)
                conn.execute(f"PRAGMA user_version = {int(target)}")
            except BaseException:
                conn.execute("ROLLBACK")
                raise
            else:
                conn.execute("COMMIT")

        for sport in SPORTS:
            conn.execute("INSERT OR IGNORE INTO sports (name) VALUES (?)", (sport,))

        return backup_path
    finally:
        conn.close()
