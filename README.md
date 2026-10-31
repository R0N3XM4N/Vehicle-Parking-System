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
python -m unittest discover -s tests -v
```

## Project Structure

- `app/` — Canonical application models, routes, and HTML templates.
- `static/` — CSS stylesheets.
- `tests/` — Automated acceptance-flow tests.
- `docs/` — Software requirements, design documentation, and test plan.
- `run.py` — Application entry point.
- `requirements.txt` — Python dependencies.
