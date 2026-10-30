# Vehicle Parking System

## Sprint 1 — Member 2: Parking Management Module

This module addresses five core Sprint 1 requirements outlined in the Software Requirements Specification (SRS):

- **PVT-F-004:** Real-time parking slot availability grouped by zone.
- **PVT-F-005:** Filter parking slots by two-wheeler and four-wheeler.
- **PVT-F-015:** Admin interface to add, edit, and remove parking slots.
- **PVT-F-008:** Record vehicle entry and update parking slot status.
- **PVT-F-009:** Record vehicle exit and free the parking slot without fee processing.

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

## Project Structure

- `app/` — Application models, routes, and HTML templates.
- `static/` — CSS stylesheets.
- `docs/` — Software requirements, design documentation, and test plan.
- `run.py` — Application entry point.
- `requirements.txt` — Python dependencies.