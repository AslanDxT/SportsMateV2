# SportsMate – audit and rebuild report

Date: 21 October 2026 · Version 1 (uploaded `Web.zip`) → version 2.0

This report explains what was wrong in the first version, what was changed, and how it was tested.
Problems marked **confirmed** were reproduced by running the original code with test requests.

---

## 1. Overall assessment of the original project

The first version had a good idea and a strong visual style (dark theme, orange and cyan logo
colours, sports photos). The basic flows (register, log in, create and join an activity) worked
on a happy path. The main weaknesses were:

- **Security:** a public, hard-coded secret key, no CSRF protection, debug mode open to the network,
  a privacy leak in Messages and a service worker that stored private pages.
- **Reliability:** one server error could lock the database for every later write.
- **Missing or disconnected features:** there was no button to connect with people, so messages could
  never be used. Activities could not be edited or cancelled. Past activities were shown as upcoming.
- **No server-side validation:** wrong form values caused crashes or bad data.
- **Phone layout:** on phones there was no way to log out, find SportsMates or see notifications.
- **Performance:** photos were 1–8 MB each (78 MB in total).
- **No tests, no README, no `.gitignore`.**

---

## 2. Security findings

| # | Problem | Severity | Evidence | Fix |
|---|---------|----------|----------|-----|
| S1 | Secret key hard-coded in `app.py` (`sportsmate-development-secret-key`). Anyone who reads the code can make a login cookie for any user. | Critical when deployed | **Confirmed:** a forged cookie with `user_id = 1` opened Alice's dashboard. | Key comes from `SECRET_KEY`. In development a random key is stored in `instance/secret_key`. Production refuses to start without it. Test: `test_old_hardcoded_secret_key_is_gone`. |
| S2 | `app.run(debug=True, host="0.0.0.0")`: the Werkzeug debugger (can run Python code) was reachable from the network. | High | Seen in source. | Debug is off by default, host is `127.0.0.1`. Debug is ignored if the host is not local. |
| S3 | No CSRF protection. Another website could make a logged-in user join activities, send requests or messages, or change the profile. | High | **Confirmed:** all POST forms worked without any token. | Token per session on every form, checked for every POST. Logout is a POST too. `SameSite=Lax` cookies. Tests: `test_posts_without_csrf_token_are_rejected` and others. |
| S4 | Messages page showed **everyone who had a connection with anybody**, not only your own SportsMates. | Medium (privacy) | **Confirmed:** a user without connections saw "Alice" and "Bob". | Query only uses the current user's accepted connections. Test: `test_inbox_only_shows_own_sportsmates`. |
| S5 | Service worker cached **every page** (also messages and notifications). They stayed on the device after logout and were shown offline. | Medium (privacy) | Seen in `service-worker.js`. | New worker only caches public `/static/` files, deletes old caches, shows an offline page. Private pages get `Cache-Control: no-store`. |
| S6 | No limit on login attempts (password guessing). | Medium | **Confirmed:** 30 wrong passwords, then the right one still worked. | Limits per account and per IP (HTTP 429). Also limits for registration, messages, activity creation and requests. |
| S7 | No security headers (clickjacking, MIME sniffing, no Content Security Policy). | Low–Medium | **Confirmed:** no headers in responses. | CSP, `X-Frame-Options: DENY`, `nosniff`, `Referrer-Policy`, `Permissions-Policy`, HSTS on HTTPS. All inline scripts and `onclick` removed so the CSP can block injected scripts. |
| S8 | Old dependency versions: Flask 3.1.2 (CVE-2026-27205, cache privacy, low) and Werkzeug 3.1.3 (CVE-2025-66221 and CVE-2026-27199: special Windows file names can hang the server – relevant because you use Windows). | Medium on Windows | Public advisories (NVD, GitLab advisory DB). | Pinned Flask 3.1.3 and Werkzeug 3.1.9. |
| S9 | `sportsmate.db` (emails and password hashes) and `__pycache__` are tracked in Git, and the repository has a GitHub remote. | Medium if the repository is public | Seen with `git ls-files`. Whether the GitHub repository is public could not be checked. | `.gitignore` added. README explains `git rm --cached`. Git history was **not** changed (your decision). |
| S10 | Weak passwords allowed (6 characters). Logout with a plain link (GET). | Low | Seen in source. | Minimum 8 characters and not trivial; logout needs POST. Old passwords keep working. |
| S11 | Templates received complete user rows including password hash and email (not shown, but risky). | Low | Seen in source. | Queries select only the columns that are shown. Other members never see emails. |
| S12 | Login error timing could reveal if an email exists. | Low | Seen in source. | Same password check time for unknown emails. (Registration still says an email is taken – normal for most sites.) |

**Checked and not found:**
- **SQL injection:** all queries already used parameters. New code keeps this. Search text with `%` or `'` is handled safely (`test_browse_filters`).
- **XSS:** Jinja auto-escaping was on. Tests put `<script>` in titles, descriptions and messages and check it is escaped.
- **IDOR on connections:** accepting a request already checked the receiver. It is now checked for every action (accept, decline, withdraw, remove).

---

## 3. Functional bugs found

| # | Problem | Evidence | Fix |
|---|---------|----------|-----|
| B1 | After any crash during a request, the database connection stayed open with a write lock. **Every later save failed** with "database is locked". | **Confirmed** (two different scenarios). | One connection per request, always closed and rolled back. Test: `test_unexpected_error_shows_friendly_page_and_releases_database`. |
| B2 | The connect route existed, but **no page had a Connect button**. The "Message" button on SportsMates always failed. Messages could never be used. | **Confirmed.** | Connect / Request sent / Accept / Message buttons on people cards and profiles, plus a connections page with decline, withdraw and remove. |
| B3 | Activities could be created in the past and joined after they happened. The dashboard "Upcoming" list showed past activities. | **Confirmed** (date 2020-01-01). | Date must be in the future (max 1 year). Joining closes at the start time. "Finished" filter for past activities. |
| B4 | No server-side checks: unknown sport → crash (500), empty name saved, level "Wizard", 99 999 participants. | **Confirmed.** | Full validation with clear messages next to each field. Form values are kept after an error. |
| B5 | Leaving an activity you never joined said "You left the activity". | **Confirmed.** | Correct messages for every case. |
| B6 | Two people joining the last spot at the same time could both get in (or get a crash). | Proven with a test: with an extra delay added and no locking, the test fails; with the new locking it passes. | Join runs in a locked transaction (`BEGIN IMMEDIATE`). Test: `test_last_spot_goes_to_one_person_only`. |
| B7 | Logo path used `images/` but the folder is `Images/` → broken logo on Linux/macOS servers. The PWA icons were deleted but `manifest.json` still used them. | **Confirmed** (404). | Paths fixed; new icons (192, 512, maskable, Apple, favicon). |
| B8 | On phones the top menu was hidden: no logout, no SportsMates, no notifications. | Seen in CSS. | Bottom tab bar (Home, Activities, Create, Mates, Messages) plus bell and account menu (profile, edit, connections, log out). |
| B9 | Activities could not be edited or cancelled; the detail page did not show places left or "full". | Seen. | Edit, cancel (with notifications), remove participant, status and places on every card and page. |
| B10 | Connecting to a user id that does not exist → crash. | **Confirmed.** | 404 page. |
| B11 | Photos were 1–8 MB each (78 MB). The start page loaded about 20 MB. | Measured. | Resized and compressed (7 MB in total incl. small card versions). The start page now loads less than 1.5 MB of photos. |
| B12 | `requirments.txt` (spelling) → `pip install -r requirements.txt` fails. | Seen. | Renamed and updated. |

---

## 4. Improvements implemented

**Structure**
- `app.py` was one 1 300-line file. Now: `app.py` (start), `config.py`, `database.py`, `security.py`, `helpers.py` and `views/` (one file per area). Templates are grouped in folders and share macros.
- Automatic database upgrades with a version number and a backup before each upgrade. Existing users, activities and participants are kept.
- New indexes for faster lists. One connection per pair of people (both directions).

**Activities**
- Search by text, sport, level and day (today, next 7 days, all upcoming, finished), "only with free spots", tabs *All / Joined / Hosting*, pages of 24.
- Cards show date block, time, place, level, a "place" marker for every spot (taken / free), and badges: *You host*, *Joined*, *Full*, *Finished*, *Cancelled*.
- Detail page with a numbered team sheet (players and open spots) and one clear action box (Join / Leave / Edit / Cancel).
- Host can edit (participants are told when time or place changes), cancel (everyone is told) and remove a participant (that person is told).
- Anti-spam: maximum 10 new activities per day per person.

**People and messages**
- People who play your sports and live in your town come first; "You both play …" line.
- Requests: send, accept, decline, withdraw, remove. Sending a request back accepts the open request.
- Inbox with the last message, time and unread count. Enter sends a message. Unread counter in the menu.

**Profile and account**
- Profile with stats (hosted, played, SportsMates), sports, availability, member since.
- Change password, delete account (with password; hosts' upcoming participants are told).

**Design and accessibility**
- Same identity (navy, orange, cyan, Teko and Montserrat, real sports photos), but calmer: fewer glows, clear active page in the menu, readable text on photos, sentence-case labels.
- Primary buttons use dark text on orange (white on orange did not have enough contrast).
- Skip link, visible keyboard focus, labels for every field, error messages linked to fields, screen-reader text for icons, reduced-motion support.
- Responsive from 360 px phones to wide screens. Friendly error pages (400, 403, 404, 405, 413, 429, 500) and an offline page.

---

## 5. Testing

**Automated tests (pytest): 101 passed, 0 failed.**

| File | What it checks |
|------|----------------|
| `tests/test_auth.py` | Register (+ 8 validation cases, duplicate email), login, logout needs POST, safe redirect after login, open-redirect attempts, login rate limit, all private pages need login, deleted user session |
| `tests/test_activities.py` | Create (+ 13 validation cases), daily limit, HTML escaping, join/leave, full, past, missing activity, **8 people joining the last spot at once**, host-only edit/cancel/remove, notifications, filters, pagination, past activities not "upcoming" |
| `tests/test_social.py` | Connect flow and all permission checks, messages only between SportsMates, inbox privacy regression, emails not shown, profile editing, people ordering, notifications, change password, delete account |
| `tests/test_security.py` | CSRF on 9 actions, old secret key cannot forge a login, secret key kept between restarts, production needs `SECRET_KEY`, headers, cookie flags, no inline scripts, service worker rule, friendly 500 page that also frees the database, 404, request size limit |
| `tests/test_database.py` | Upgrade of an original-format database (data kept, backup made, host added as participant, ids unchanged), fresh database, one connection per pair |

**Database upgrade on your real database:** a copy of your uploaded `sportsmate.db` was upgraded:
4 users, 1 activity and 3 participants were kept, `integrity_check` = ok, foreign keys ok, a backup
was written, and a second start made no changes.

**Browser tests (Playwright, Chromium):** 10 flows passed with two real browser sessions – register,
edit profile, create activity (first with errors), second user finds and joins it, connect request,
accept from the dashboard, chat with the Enter key and unread badge, host cancels and the participant
is notified, phone layout (tab bar, chat, account menu, logout), keyboard skip link and focus.
No JavaScript errors and no Content Security Policy errors. Screenshots were checked at 1366 px and 390 px.

**Not tested (could not be done here):**
- Running on Windows and on Python 3.14 (tests ran on Linux with Python 3.13).
- The real Teko and Montserrat fonts: Google Fonts was blocked in the test environment, so screenshots used fallback fonts.
- A real HTTPS production deployment, a screen reader, Safari and Firefox.

---

## 6. Most important files

| File | What changed |
|------|--------------|
| `app.py` | Now only starts the app: settings, database upgrade, user loading, CSRF check, headers, error pages. |
| `config.py` *(new)* | All settings from environment variables / `.env`, secret key handling. |
| `database.py` | Per-request connections, transactions, versioned upgrades with backup, indexes. |
| `security.py` *(new)* | `login_required`, safe redirects, CSRF, rate limiter, security headers. |
| `helpers.py` *(new)* | Validation, date formatting, activity status, notifications. |
| `views/*.py` *(new)* | All routes, split by area (auth, main, activities, people, messages). |
| `templates/` | All pages rewritten; shared `macros.html`; one `error.html` replaces 403/404/500. |
| `static/css/style.css` | New responsive stylesheet with the same colours and fonts. |
| `static/js/app.js` | Password toggle, confirm dialogs, double-submit protection, chat helpers, character counters. |
| `static/service-worker.js` | Only caches public files; offline page. |
| `static/Images/` | Same photos, resized; `thumbs/` for cards; logo cropped to its content. |
| `static/icons/`, `manifest.json` | New app icons. |
| `seed_demo.py` *(new)* | Optional demo data for presentations. |
| `tests/` *(new)* | 101 automated tests. |
| `README.md`, `.env.example`, `.gitignore`, `requirements*.txt`, `pytest.ini` *(new)* | Setup and documentation. |

Removed: the two copied Windows virtual environments (`venv`, `.venv`) and `__pycache__`. They can be
made again with one command (see README). The original high-resolution photos are still in your
original `Web.zip`.

---

## 7. Is it production-ready?

**Not yet.** It is a solid, tested version for a school project, demos and a small test group.
Before real public use you still need:

1. A production server (waitress or gunicorn) behind **HTTPS**, with `SPORTSMATE_ENV=production`,
   a strong `SECRET_KEY` and `SESSION_COOKIE_SECURE=1`.
2. Regular database backups (the app only makes a backup before upgrades).
3. Email verification and a "forgot password" flow.
4. Moderation: a report button and an admin role.
5. A privacy statement and cookie information (GDPR). Consider self-hosting the fonts.
6. Shared rate limiting (for example Redis) if you run more than one server process.
7. Monitoring and error logging.
8. PostgreSQL instead of SQLite when there are many users at the same time.
