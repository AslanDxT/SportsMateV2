# SportsMate

SportsMate is a website where people find other people to play sports with.
You make a profile, find or host activities (for example a football game in the park),
join them, connect with other members and send messages.

Version 2.0 – a full check and rebuild of the first version.

---

## What you can do

| Area | Features |
|------|----------|
| Account | Create account, log in, log out, change password, delete account |
| Profile | Name, town, level, sports you play, bio, when you are free |
| Activities | Create, edit, cancel. Join and leave. Search by text, sport, level and day. Tabs for *Joined* and *Hosting*. Status: open, full, finished, cancelled |
| Team sheet | See who joined and how many places are left. The host can remove a person |
| SportsMates | Find people (people who play your sports come first), send a request, accept, decline, withdraw, remove |
| Messages | Private chat between SportsMates, unread counter |
| Notifications | Someone joined or left your activity, your activity changed or was cancelled, SportsMate requests |
| App | Works on phone, tablet and computer. Can be installed as an app (PWA) |

---

## Technology

- **Python 3.10 or newer** (tested with Python 3.13; Python 3.14 should also work)
- **Flask 3.1** – web framework
- **SQLite** – database (one file: `sportsmate.db`, no server needed)
- **Jinja2 templates**, plain **CSS** and a small amount of plain **JavaScript** (no build step)
- **pytest** – automated tests

No paid services and no external accounts are needed.

---

## Project structure

```
SportsMate/
├── app.py               Starts the app (python app.py) and connects all parts
├── config.py            Settings (read from environment variables / .env)
├── database.py          Database connection, tables and automatic upgrades
├── security.py          Login check, CSRF protection, rate limits, security headers
├── helpers.py           Form checks, dates, activity status, notifications
├── seed_demo.py         Optional: fills the database with demo people and activities
├── views/               All pages, grouped by area
│   ├── auth.py          Register, log in, log out
│   ├── main.py          Start page, dashboard, notifications
│   ├── activities.py    Find, create, edit, cancel, join, leave activities
│   ├── people.py        SportsMates, profiles, account settings, connections
│   └── messages.py      Inbox and chat
├── templates/           HTML pages (Jinja2)
├── static/              CSS, JavaScript, photos, icons, PWA files
├── tests/               Automated tests (pytest)
├── requirements.txt     Packages to run the app
├── requirements-dev.txt Packages to run the tests
└── .env.example         Example settings
```

---

## Install (first time)

You need Python. Check it with `python --version` (on Windows you can also use `py --version`).

**Windows (PowerShell or Command Prompt):**

```bat
cd SportsMate
py -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

**macOS / Linux:**

```bash
cd SportsMate
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

> The old project contained two copied virtual environments (`venv` and `.venv`).
> They are not included any more, because a virtual environment only works on the
> computer where it was made. The commands above make a new one in one minute.

---

## Settings (optional)

For your own computer you do not need to change anything.

To change settings, copy `.env.example` to `.env` and edit it. The most important ones:

| Setting | Meaning |
|---------|---------|
| `SECRET_KEY` | Secret for login cookies. **Required in production.** In development a random key is created automatically in `instance/secret_key`. |
| `SPORTSMATE_ENV` | `development` (default) or `production` |
| `DATABASE_PATH` | Where the database file is. Default: `sportsmate.db` |
| `SPORTSMATE_DEBUG` | `1` shows the Flask debugger. Only on your own computer. Default: `0` |
| `SESSION_COOKIE_SECURE` | `1` when the site uses HTTPS |

Never put the `.env` file or the `instance/` folder in Git.

---

## Database

You don't have to do anything. When the app starts it:

1. creates the tables if the database is new, or
2. upgrades an older SportsMate database to the new version.

Before an upgrade, a copy of the old database is saved in the `backups/` folder.
Existing users, activities and participants are kept.

**Demo data (optional):** to fill the database with 6 demo members and 7 activities:

```bash
python seed_demo.py
```

All demo accounts use the password `sportsmate-demo`, for example `sanne@example.com`.
Running it twice does not create duplicates.

**Start with an empty database:** stop the app, rename or delete `sportsmate.db`, start the app again.

---

## Start the app

```bash
python app.py
```

Open **http://127.0.0.1:5000** in your browser.

To test on your phone in the same Wi-Fi network, start it like this and open
`http://<your-computer-ip>:5000` on the phone:

```bat
set SPORTSMATE_HOST=0.0.0.0        (Windows)
export SPORTSMATE_HOST=0.0.0.0     (macOS / Linux)
python app.py
```

Do not turn on `SPORTSMATE_DEBUG` when the app is reachable from the network.

You can also use the Flask command: `flask --app app run`.

---

## Run the tests

```bash
pip install -r requirements-dev.txt
python -m pytest
```

The tests use their own temporary database. Your `sportsmate.db` is never touched.
They check registration, login, all activity actions, capacity limits (also when
many people press *Join* at the same time), permissions, CSRF protection, messages,
connections, account deletion and the database upgrade.

---

## Daily workflow

1. Activate the virtual environment (`.venv\Scripts\activate` or `source .venv/bin/activate`).
2. Start the app with `python app.py`.
3. Change code. Templates and CSS: reload the page. Python files: stop (Ctrl+C) and start again
   (or set `SPORTSMATE_DEBUG=1` on your own computer for automatic reload).
4. Run `python -m pytest` before you commit.
5. If you change the database tables: add a new step in `database.py`
   (`SCHEMA_VERSION` + a `_migrate_to_vN` function). Never edit old steps.

### Git: stop tracking the database

The old repository also stored `sportsmate.db` and `__pycache__` in Git. The database
contains email addresses and password hashes, so it should not be on GitHub.
The new `.gitignore` prevents this for new files. To remove the files that are already tracked
(your local files stay):

```bash
git rm --cached sportsmate.db
git rm -r --cached __pycache__
git commit -m "Stop tracking database and cache files"
```

The old database is still in the Git history. If the repository is public, consider
making it private or cleaning the history.

---

## Security in short

- Passwords are stored as hashes (never as plain text).
- Every form has a CSRF token. Logging out needs a form too.
- Login, registration, messages, activity creation and SportsMate requests have limits against abuse.
- Only the host can edit, cancel or remove people from an activity.
- Only SportsMates can send messages to each other. Your email is never shown to others.
- Security headers (Content Security Policy, no framing, no MIME sniffing).
- Private pages are not stored in the browser cache or by the service worker.
- Errors show a friendly page without technical details.

---

## Known limitations

- **Rate limits are kept in memory.** They reset when the app restarts and are not shared
  between several server processes. For a big deployment use a shared store (for example Redis).
- **SQLite** is fine for a school project and small groups. For many simultaneous users, move to PostgreSQL.
- **The development server is not for production.** Use a WSGI server such as
  `waitress` (Windows) or `gunicorn` (Linux) behind HTTPS, and set `SPORTSMATE_ENV=production`,
  `SECRET_KEY` and `SESSION_COOKIE_SECURE=1`.
- **No email.** There is no email verification and no "forgot password" link yet.
- **No admin role.** Hosts manage their own activities, but there is no site-wide moderation or "report" button.
- **Times are local time of the server.** Fine when the server and the users are in the same time zone (the Netherlands).
- **Fonts** (Teko and Montserrat) are loaded from Google Fonts. For stricter privacy (GDPR),
  download the font files, put them in `static/fonts/` and change the `<link>` in `templates/base.html`.
  Without internet the app falls back to system fonts.
- **No real-time updates.** New messages appear after reloading the page.
- **No profile photos.** Avatars show the first letter of the name.
