"""
Fill the database with demo members and activities, for testing or a presentation.

    python seed_demo.py                 # adds demo data to the configured database
    python seed_demo.py --password xyz  # choose the demo password

Demo accounts use @example.com addresses, so they are easy to recognise and
delete later. Running the script twice does not create duplicates.
"""

import argparse
from datetime import date, timedelta

from werkzeug.security import generate_password_hash

import database
from config import build_config

DEMO_USERS = [
    # name, email, town, level, sports, bio, availability
    ("Sanne de Vries", "sanne@example.com", "Venlo", "Intermediate", ["Running", "Cycling"],
     "Training for my first half marathon. Always happy to run with company.", "Weekday evenings"),
    ("Daan Janssen", "daan@example.com", "Venlo", "Advanced", ["Football", "Gym"],
     "Played club football for ten years. Now I organise kickabouts in the park.", "Weekends"),
    ("Noor Bakker", "noor@example.com", "Eindhoven", "Beginner", ["Tennis", "Padel", "Badminton"],
     "New to padel and looking for people at my level.", "Tuesday and Thursday evening"),
    ("Milan Peters", "milan@example.com", "Eindhoven", "Intermediate", ["Basketball", "Football"],
     "Streetball on Sunday mornings. Bring good energy.", "Sunday morning"),
    ("Lotte Smit", "lotte@example.com", "'s-Hertogenbosch", "Advanced", ["Hockey", "Running"],
     "Hockey player and trail runner.", "Saturday"),
    ("Yusuf Aydin", "yusuf@example.com", "Venlo", "Beginner", ["Football", "Volleyball"],
     "Just moved to Venlo and want to meet people through sport.", "Most evenings"),
]

# title, host email, sport, days from today, time, location, level, max, description, joiners
DEMO_ACTIVITIES = [
    ("Sunday 5-a-side", "daan@example.com", "Football", 3, "10:30", "Julianapark, Venlo", "Intermediate", 10,
     "Friendly game, mixed teams. Bring a dark and a light shirt.",
     ["yusuf@example.com", "milan@example.com"]),
    ("Easy 8 km along the Maas", "sanne@example.com", "Running", 1, "19:00", "Maasboulevard, Venlo", "Beginner", 8,
     "Conversation pace, around 6:30 per km. Nobody gets left behind.",
     ["yusuf@example.com", "lotte@example.com"]),
    ("Padel for beginners", "noor@example.com", "Padel", 5, "20:00", "Padelcentrum Eindhoven", "Beginner", 4,
     "Court is booked, we split the cost. Rackets can be rented there.",
     ["milan@example.com", "lotte@example.com", "sanne@example.com"]),
    ("Streetball 3x3", "milan@example.com", "Basketball", 6, "11:00", "Strijp-S courts, Eindhoven", "Intermediate", 6,
     "Half court 3x3. First to 21 wins, winners stay on.",
     ["daan@example.com"]),
    ("Saturday hockey training", "lotte@example.com", "Hockey", 9, "09:30", "Sportpark De Vliert, Den Bosch", "Advanced", 16,
     "Drills and a small game. Shin guards required.",
     []),
    ("Beach volleyball evening", "yusuf@example.com", "Volleyball", 12, "18:30", "Sportpark Venlo-Oost", "Beginner", 12,
     "Just for fun. Everybody welcome.",
     ["sanne@example.com", "daan@example.com", "noor@example.com"]),
    ("Gravel ride Maasduinen", "sanne@example.com", "Cycling", 15, "08:00", "Station Venlo (meeting point)", "Intermediate", 8,
     "About 60 km, mostly gravel. Coffee stop halfway.",
     ["lotte@example.com"]),
]

DEMO_CONNECTIONS = [
    ("daan@example.com", "yusuf@example.com", "accepted"),
    ("sanne@example.com", "lotte@example.com", "accepted"),
    ("milan@example.com", "noor@example.com", "pending"),
]


def seed(db_path, password):
    database.init_db(db_path)
    conn = database.connect(db_path)
    try:
        if conn.execute("SELECT 1 FROM users WHERE email = ?", (DEMO_USERS[0][1],)).fetchone():
            print("Demo data already exists. Nothing changed.")
            return

        conn.execute("BEGIN IMMEDIATE")
        sport_ids = {row["name"]: row["id"] for row in conn.execute("SELECT id, name FROM sports")}
        hashed = generate_password_hash(password)
        user_ids = {}

        for name, email, town, level, sports, bio, availability in DEMO_USERS:
            cursor = conn.execute(
                """INSERT INTO users (name, email, password_hash, location, skill_level, bio, availability)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (name, email, hashed, town, level, bio, availability),
            )
            user_ids[email] = cursor.lastrowid
            for sport in sports:
                conn.execute("INSERT INTO user_sports (user_id, sport_id) VALUES (?, ?)",
                             (cursor.lastrowid, sport_ids[sport]))

        for title, host, sport, days, time, place, level, maximum, text, joiners in DEMO_ACTIVITIES:
            day = (date.today() + timedelta(days=days)).isoformat()
            cursor = conn.execute(
                """INSERT INTO activities (creator_id, title, sport_id, description, date, time,
                                           location, skill_level, max_participants, status)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'open')""",
                (user_ids[host], title, sport_ids[sport], text, day, time, place, level, maximum),
            )
            for email in [host] + joiners:
                conn.execute("INSERT INTO activity_participants (activity_id, user_id) VALUES (?, ?)",
                             (cursor.lastrowid, user_ids[email]))

        for sender, receiver, status in DEMO_CONNECTIONS:
            conn.execute("INSERT INTO connections (sender_id, receiver_id, status) VALUES (?, ?, ?)",
                         (user_ids[sender], user_ids[receiver], status))

        conn.execute(
            "INSERT INTO messages (sender_id, receiver_id, message) VALUES (?, ?, ?)",
            (user_ids["daan@example.com"], user_ids["yusuf@example.com"],
             "Hey Yusuf, see you Sunday at the park? We still need one goalkeeper."),
        )
        conn.execute("COMMIT")
        print(f"Added {len(DEMO_USERS)} demo members and {len(DEMO_ACTIVITIES)} activities.")
        print(f"Log in with for example sanne@example.com and the password: {password}")
    except BaseException:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--password", default="sportsmate-demo", help="password for all demo accounts")
    args = parser.parse_args()
    seed(build_config()["DATABASE_PATH"], args.password)
