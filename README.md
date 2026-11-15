# Vehicle Parking System

## Integrated Vehicle Parking System

The canonical application is the authenticated Flask app started by `run.py`. It includes:

- Responsive shared templates, login, registration, and session-aware navigation.
- Slot search and filters for zone, vehicle type, and availability.
- Reservation time windows with overlap prevention and confirmation.
- Vehicle entry, fee preview, exit, simulated payment, and printable receipts.
- Role-protected admin slot/rate management.
- Daily and monthly occupancy/revenue reports.

## Prerequisites

- Python 3.10 or a compatible version.
- pip (Python package installer).

## Setup Instructions

1. Install the required dependencies:

   ```bash
   pip install -r requirements.txt
   ```

2. Start the application using the appropriate entry point for this module:

   ```bash
   python run.py
   ```

3. Open the application in your browser at:

   `http://127.0.0.1:5000`

## Create an admin account

Set the following environment variables before the first run. No credentials are stored in the repository.

PowerShell:

```powershell
$env:VPS_ADMIN_EMAIL = "admin@example.com"
$env:VPS_ADMIN_PASSWORD = "choose-a-secure-password"
python run.py
```

If the email already belongs to a registered user, that user is promoted to the admin role on startup.

## Run the automated tests

```bash
pip install -r requirements-dev.txt
python -m unittest discover -s tests -v
```

Run the same coverage commands as CI:

```bash
python -m coverage run --source=app -m xmlrunner discover -s tests -o test-results
python -m coverage report --fail-under=80
python -m coverage xml
```

CI tests Python 3.10 and 3.13 and uploads JUnit/coverage XML artifacts.
See [Sprint 2 stories and audit recheck](docs/SPRINT_2.md) for acceptance/test
mapping, the five-failure lockout decision and outstanding SRS gaps.

## Session and form configuration

Set `VPS_SECRET_KEY` to a stable random secret before startup. If absent, a
random key is generated for that process; restarts invalidate sessions and
multiple workers require a shared configured key. Never commit secrets.
Cookies are HttpOnly with SameSite=Lax. Set `VPS_COOKIE_SECURE=1` when serving
through HTTPS; leave it unset for local HTTP. TLS is a deployment responsibility.

Every POST form requires a CSRF token. Logout uses POST. Authentication still
uses Flask sessions rather than JWT. Five consecutive wrong passwords lock the
account for 15 minutes. Existing SQLite databases receive new lockout columns
at startup. Payments are simulated; no external gateway is contacted.

## Project Structure

- `app/` — Canonical application models, routes, and HTML templates.
- `static/` — CSS stylesheets.
- `tests/` — Automated acceptance-flow tests.
- `docs/` — Software requirements, design documentation, and test plan.
- `run.py` — Application entry point.
- `requirements.txt` — Python dependencies.
