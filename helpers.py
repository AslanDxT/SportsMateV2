"""
Shared helpers: input validation, dates, activity status and notifications.
"""

import re
from datetime import date, datetime, timedelta, timezone

SKILL_LEVELS = ("Beginner", "Intermediate", "Advanced")

# Field length limits (characters). Used by forms and templates (maxlength).
LIMITS = {
    "name": 60,
    "email": 254,
    "password_min": 8,
    "password_max": 128,
    "location": 80,
    "bio": 500,
    "availability": 120,
    "title": 80,
    "description": 1000,
    "activity_location": 120,
    "message": 1000,
    "search": 80,
}

MIN_PARTICIPANTS = 2
MAX_PARTICIPANTS = 100
MAX_DAYS_AHEAD = 365

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# Photo used for each sport (files in static/Images).
SPORT_IMAGES = {
    "Badminton": "tennis.jpg",
    "Basketball": "basketball3.jpg",
    "Cycling": "bike3.jpg",
    "Football": "football2.jpg",
    "Gym": "pexels-cottonbro-7324633.jpg",
    "Hockey": "krk.jpg",
    "Padel": "tennis.jpg",
    "Running": "run.jpg",
    "Swimming": "seilling.jpg",
    "Tennis": "tennis.jpg",
    "Volleyball": "basketball4.jpg",
}
DEFAULT_SPORT_IMAGE = "foortball3.jpg"


def sport_image(sport_name):
    return SPORT_IMAGES.get(sport_name or "", DEFAULT_SPORT_IMAGE)


# --------------------------------------------------
# Text input
# --------------------------------------------------

def clean(value, max_length=None):
    """Trim a form value and collapse inner whitespace on single-line fields."""
    value = (value or "").strip()
    value = re.sub(r"[ \t]+", " ", value)
    if max_length is not None:
        value = value[:max_length]
    return value


def clean_multiline(value, max_length=None):
    value = (value or "").replace("\r\n", "\n").strip()
    value = re.sub(r"\n{3,}", "\n\n", value)
    if max_length is not None:
        value = value[:max_length]
    return value


def too_long(value, field):
    return len((value or "").strip()) > LIMITS[field]


def valid_email(email):
    return bool(email) and len(email) <= LIMITS["email"] and bool(EMAIL_RE.match(email))


def password_problem(password, confirm=None):
    """Return an error message, or None when the password is acceptable."""
    if len(password) < LIMITS["password_min"]:
        return f"Use at least {LIMITS['password_min']} characters for your password."
    if len(password) > LIMITS["password_max"]:
        return f"Use at most {LIMITS['password_max']} characters for your password."
    if password.strip() == "" or len(set(password)) < 3:
        return "Choose a password that is harder to guess."
    if confirm is not None and password != confirm:
        return "The two passwords are not the same."
    return None


def parse_int(value, default=None):
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


# --------------------------------------------------
# Dates and times
# --------------------------------------------------

def now_local():
    """Local time of the server. Activity dates/times are stored in local time."""
    return datetime.now().replace(second=0, microsecond=0)


def now_key():
    """Current time as 'YYYY-MM-DD HH:MM', comparable with date || ' ' || time."""
    return now_local().strftime("%Y-%m-%d %H:%M")


def parse_activity_start(date_text, time_text):
    try:
        return datetime.strptime(f"{date_text} {time_text}", "%Y-%m-%d %H:%M")
    except (TypeError, ValueError):
        return None


def parse_utc(timestamp):
    """SQLite CURRENT_TIMESTAMP values are UTC; convert them to local time."""
    if not timestamp:
        return None
    if isinstance(timestamp, datetime):
        value = timestamp
    else:
        try:
            value = datetime.fromisoformat(str(timestamp).replace("T", " ")[:19])
        except ValueError:
            return None
    return value.replace(tzinfo=timezone.utc).astimezone().replace(tzinfo=None)


def day_label(value):
    """'Today', 'Tomorrow' or e.g. 'Sat 25 Oct'."""
    if isinstance(value, str):
        try:
            value = datetime.strptime(value, "%Y-%m-%d").date()
        except ValueError:
            return value
    if isinstance(value, datetime):
        value = value.date()
    today = date.today()
    if value == today:
        return "Today"
    if value == today + timedelta(days=1):
        return "Tomorrow"
    label = f"{value:%a} {value.day} {value:%b}"
    if value.year != today.year:
        label += f" {value.year}"
    return label


def long_date(value):
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return value
    return f"{parsed:%A} {parsed.day} {parsed:%B %Y}"


def date_parts(value):
    """Pieces for the date block on activity cards."""
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return {"weekday": "", "day": "?", "month": ""}
    return {"weekday": f"{parsed:%a}", "day": str(parsed.day), "month": f"{parsed:%b}"}


def month_year(timestamp):
    value = parse_utc(timestamp)
    return f"{value:%B %Y}" if value else "Unknown"


def timestamp_label(timestamp):
    """Readable local time for messages and notifications."""
    value = parse_utc(timestamp)
    if value is None:
        return ""
    now = datetime.now()
    delta = now - value
    if delta < timedelta(minutes=1):
        return "Just now"
    if delta < timedelta(hours=1):
        return f"{int(delta.total_seconds() // 60)} min ago"
    if value.date() == now.date():
        return f"Today {value:%H:%M}"
    if value.date() == (now - timedelta(days=1)).date():
        return f"Yesterday {value:%H:%M}"
    if value.year == now.year:
        return f"{value.day} {value:%b}, {value:%H:%M}"
    return f"{value.day} {value:%b %Y}"


# --------------------------------------------------
# Activities
# --------------------------------------------------

ACTIVITY_SELECT = """
    SELECT
        a.*,
        s.name AS sport_name,
        u.name AS host_name,
        (SELECT COUNT(*) FROM activity_participants p WHERE p.activity_id = a.id) AS participant_count,
        EXISTS(
            SELECT 1 FROM activity_participants p
            WHERE p.activity_id = a.id AND p.user_id = :me
        ) AS is_joined
    FROM activities a
    JOIN sports s ON s.id = a.sport_id
    JOIN users u ON u.id = a.creator_id
"""

STATUS_TEXT = {
    "open": "Open",
    "full": "Full",
    "past": "Finished",
    "cancelled": "Cancelled",
}


def activity_status(activity, now=None):
    """open, full, past or cancelled."""
    if activity["status"] == "cancelled":
        return "cancelled"
    start = f"{activity['date']} {activity['time']}"
    if start < (now or now_key()):
        return "past"
    if activity["participant_count"] >= activity["max_participants"]:
        return "full"
    return "open"


def enrich_activity(row, me_id, now=None):
    """Turn a database row into a dict with everything the templates need."""
    activity = dict(row)
    activity["is_host"] = activity["creator_id"] == me_id
    activity["is_joined"] = bool(activity.get("is_joined")) or activity["is_host"]
    activity["state"] = activity_status(activity, now)
    activity["state_text"] = STATUS_TEXT[activity["state"]]
    activity["spots_left"] = max(activity["max_participants"] - activity["participant_count"], 0)
    activity["image"] = sport_image(activity.get("sport_name"))
    activity["day_label"] = day_label(activity["date"])
    # The date box already shows the date, so cards only repeat it for today/tomorrow.
    if activity["day_label"] in ("Today", "Tomorrow"):
        activity["when_label"] = f"{activity['day_label']}, {activity['time']}"
    else:
        activity["when_label"] = activity["time"]
    activity["date_parts"] = date_parts(activity["date"])
    return activity


def validate_activity(form, sport_ids, current_participants=1, existing_start=None):
    """
    Check the activity form. Returns (values, errors).

    `existing_start` is the current start time when editing, so an activity
    that keeps its date is not rejected for being too close to now.
    """
    values = {
        "title": clean(form.get("title")),
        "sport_id": parse_int(form.get("sport_id")),
        "description": clean_multiline(form.get("description")),
        "date": clean(form.get("date")),
        "time": clean(form.get("time")),
        "location": clean(form.get("location")),
        "skill_level": clean(form.get("skill_level")) or "Beginner",
        "max_participants": parse_int(form.get("max_participants")),
    }
    errors = {}

    if not values["title"]:
        errors["title"] = "Give your activity a title."
    elif len(values["title"]) < 3:
        errors["title"] = "Use at least 3 characters for the title."
    elif too_long(values["title"], "title"):
        errors["title"] = f"Use at most {LIMITS['title']} characters."

    if values["sport_id"] not in sport_ids:
        errors["sport_id"] = "Choose a sport from the list."

    if too_long(values["description"], "description"):
        errors["description"] = f"Use at most {LIMITS['description']} characters."

    if not values["location"]:
        errors["location"] = "Tell people where to meet."
    elif too_long(values["location"], "activity_location"):
        errors["location"] = f"Use at most {LIMITS['activity_location']} characters."

    if values["skill_level"] not in SKILL_LEVELS:
        errors["skill_level"] = "Choose a skill level from the list."

    start = parse_activity_start(values["date"], values["time"])
    if start is None:
        errors["date"] = "Enter a valid date and time."
    else:
        unchanged = existing_start is not None and start == existing_start
        if start < now_local() and not unchanged:
            errors["date"] = "Choose a date and time in the future."
        elif start > now_local() + timedelta(days=MAX_DAYS_AHEAD):
            errors["date"] = "Plan at most one year ahead."

    lowest = max(MIN_PARTICIPANTS, current_participants)
    maximum = values["max_participants"]
    if maximum is None:
        errors["max_participants"] = "Enter a number."
    elif maximum < lowest:
        if current_participants > MIN_PARTICIPANTS and maximum < current_participants:
            errors["max_participants"] = (
                f"{current_participants} people already joined, so the limit must be at least {current_participants}."
            )
        else:
            errors["max_participants"] = f"Allow at least {MIN_PARTICIPANTS} people."
    elif maximum > MAX_PARTICIPANTS:
        errors["max_participants"] = f"The limit is {MAX_PARTICIPANTS} people."

    return values, errors


# --------------------------------------------------
# Notifications
# --------------------------------------------------

def notify(db, user_id, kind, message, link="", related_id=None):
    db.execute(
        """
        INSERT INTO notifications (user_id, type, message, related_id, link)
        VALUES (?, ?, ?, ?, ?)
        """,
        (user_id, kind, message, related_id, link),
    )


def notification_link(notification):
    """Links for notifications, including ones made by the old version."""
    if notification["link"]:
        return notification["link"]
    related = notification["related_id"]
    if notification["type"] == "activity" and related:
        return f"/activities/{related}"
    if notification["type"] == "message" and related:
        return f"/messages/{related}"
    if notification["type"] == "connection":
        return "/connections"
    return ""
