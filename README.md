# Vehicle Parking System

Flask/SQLite parking application with browser forms and a JWT JSON API.
Run the canonical `run.py`; the former `app.py` is now only a compatibility
launcher for the same authenticated application.

## User stories for the demonstration

[All 11 user stories, acceptance criteria and demo steps](docs/USER_STORIES.md)
are grouped into five sections: secure accounts, reliable reservations, live
zone occupancy, entry/exit audit, and pricing/billing. Scope: #14–#17 and #27–#33,
37 story points. [API requests and rules](docs/API.md) describe the corresponding
JSON interfaces. Existing PR #51 security/payment protections are retained.

## Local setup

Python 3.10 or 3.13:

```bash
python -m venv .venv
# Activate .venv in your shell, then:
python -m pip install -r requirements.txt
python run.py
```

Open `http://127.0.0.1:5000`. Fresh databases and two vehicle-type rates are
initialized on startup. Register an ordinary user through the UI.

Create an administrator with a new email (password is entered interactively):

```bash
python -m flask --app run create-admin --email admin@example.com
```

Existing users are never silently promoted. Use a synthetic admin/user pair for
class demonstrations. No demo or production credentials are seeded into the app.

Set `VPS_SECRET_KEY` to a stable random secret before startup; otherwise a random
process key invalidates sessions on restart. Never commit it. Browser cookies
are HttpOnly and SameSite=Lax. `VPS_COOKIE_SECURE=1` is available when HTTPS is
provided externally; leave it unset for local HTTP. Deployment/TLS/uptime
verification are outside this PR's scope. Debug mode is disabled by default.
`VPS_DATABASE_URL` can select a different SQLite database.

## Existing databases

**Back up `instance/parking.db` before running the branch on existing data.**
Read [migration instructions](migrations/README.md), including the required
`VPS_LEGACY_TIMEZONE` declaration if historical reservations exist. For an old
prototype whose timestamps were India local time:

```powershell
$env:VPS_LEGACY_TIMEZONE = "Asia/Kolkata"
python -m flask --app run db-upgrade
```

Use `UTC` if historical records were already UTC. Mixed historical timezones
need manual review. Alembic revisions preserve users, fees and active visit rate
snapshots. Duplicate historical payments/active logs cause a refusal, not data
deletion. Review both new type-wide rates in Admin after migration.

## Behavior

- Registration uses salted bcrypt. Legacy Werkzeug hashes upgrade on successful
  login. Passwords must have at least 8 characters and at most 72 UTF-8 bytes.
- Login issues a one-hour JWT. Browser sessions contain the same JWT inside the
  signed HttpOnly cookie; API calls require a bearer header and never accept
  browser cookies. Logout persistently revokes the current token, including copies.
- PR #51's five consecutive failures/15-minute lockout and CSRF checks remain.
- Reserve a half-open time window up to 24 hours. Occupied or overlapping slots
  return a conflict, including under competing requests. Entry is permitted only
  within the reserved window; unused bookings expire at its end.
- Available/Reserved/Occupied status and per-zone counts are shown. Zone counts
  refresh every 15 seconds on visible parking/admin pages.
- Admin rates apply to all slots of a vehicle type. Entry freezes that rate for
  the visit. Billing uses integer cents, whole-hour ceiling and a one-hour minimum.
- Preview the fee before exit. The signed quote lasts five minutes and confirmation
  honors that amount. Exit frees the slot and creates one pending simulated payment.
- Admin → Audit logs shows paginated vehicle/slot/zone/entry/exit records. New
  timestamps are UTC in storage/API and Asia/Kolkata in browser forms/displays.

Optional expiry sweep (normal reads also reconcile expired reservations):

```bash
python -m flask --app run expire-reservations
```

## Tests and CI

```bash
python -m pip install -r requirements-dev.txt
python -m unittest discover -s tests -v
python -m coverage run --source=app -m xmlrunner discover -s tests -o test-results
python -m coverage report --fail-under=80
python -m coverage xml
```

Real browser story checks at 1200×800, 768×900 and 390×844:

```bash
python -m pip install -r requirements-browser.txt
python -m playwright install chromium
python -m scripts.browser_smoke
```

The browser script uses disposable data and a loopback server. It checks complete
registration→reservation→entry→preview→exit→receipt flows, logout, admin rates and
audit screens; screenshots/results are in `test-results/browser/`. Tests use a
reduced bcrypt cost explicitly for speed; the application's default is cost 12.
CI runs Python 3.10/3.13 integration tests and a Chromium browser job, uploading
JUnit/coverage and browser evidence.

## Structure

- `app/auth.py`: bcrypt, JWT validation/revocation, lockout and role guards.
- `app/services.py`: serialized booking, entry, billing, payment, rates and occupancy.
- `app/routes.py`, `app/api.py`: browser and JSON adapters for the same rules.
- `app/models.py`, `migrations/`: persistence and versioned upgrades.
- `docs/USER_STORIES.md`: story grouping, criteria, demonstration and test mapping.
- `docs/SPRINT_2.md`: historical PR #51 scope/audit notes, superseded where this PR implements a gap.
