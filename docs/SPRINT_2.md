# Sprint 2 stories and verification

Scope confirmed by the requester on 15 November 2026: issues #18–#21 plus CI tests.
The screenshot also contains Sprint 1 issues; this PR does not close those.

## User stories (18 points)

| Issue | User story | Acceptance and executable evidence |
|---|---|---|
| #18 / PRJ-SR-002 (5) | As an administrator, I need restricted management access so ordinary users cannot change configuration or read other drivers' receipts. | TC-Sec-02: all admin routes reject ordinary users with 403; anonymous/deleted accounts cannot access protected pages; role revocation applies on the next request, including receipt access. Existing tests cover permitted admin CRUD. |
| #19 / PRJ-SR-004 (5) | As a user, I need data validated and displayed safely so malformed input, injection and forged requests cannot alter application data. | TC-Sec-04: validate names, email, password lengths, vehicles, time windows, slot fields and finite positive rates. ORM parameter binding and Jinja escaping remain enabled. All POST forms, including logout, require CSRF. Negative-path tests check database state. |
| #20 / PRJ-SR-005 (3) | As an account holder, I need temporary lockout after repeated failures to limit password guessing. | TC-Sec-05: failure five starts a 15-minute UTC lock; correct passwords are blocked during it; expiry and successful login reset the count. Atomic SQL increments prevent lost simultaneous failures. Existing SQLite databases receive the new columns without losing users. |
| #21 / PVT-F-014 (5) | As a paying driver, I need a persistent receipt with transaction ID, amount and timestamp. | TC-Pay-01: checkout creates a pending payment; confirmation completes it using the server-calculated fee. Repeat requests preserve one transaction and its original timestamp. Only the owner can confirm; only the owner/current administrator can retrieve a paid receipt. |

Tests: `tests/test_sprint2.py` and `tests/test_frontend_issues.py`.
Conditional database updates also prevent concurrent checkout/payment requests
from recording the same transition twice.

### Lockout clarification

Issue #20's title says five failures, while its original acceptance text and test
plan describe the sixth failed attempt. The requester explicitly selected
**lock immediately after five failures**. Failure five returns 429. Subsequent
attempts do not extend the original deadline. After expiry a wrong password
starts a new sequence at one; successful login resets the counter to zero.

### Sprint 1 grouping from the screenshot

| Group | Issues | Current status / remaining conflict |
|---|---|---|
| Foundation | #13 Flask/SQLite | Canonical `app/` package and `run.py` exist. Separate legacy `app.py` and root templates remain; use the canonical app. |
| Registration/sign-in | #14 registration; #15 login/JWT | Registration/password verification exist. Authentication uses signed Flask sessions; JWT/API acceptance remains open. |
| Session termination | #16 logout | CSRF-protected POST logout clears the session. JWT revocation is not implemented. |
| Password storage | #17 bcrypt | Werkzeug salted hashing exists. New passwords use its default scrypt, not bcrypt; do not claim bcrypt acceptance passed. |

## Historical audit recheck

This compares the current code with the supplied old audit, rather than claiming
all SRS requirements are complete.

| Audit item | Current assessment after this PR |
|---|---|
| 1. REST API/JWT | Still missing: the documented JSON interface and JWT are outside this PR. Browser form/session routes exist. |
| 2. RBAC/admin | Admin CRUD/reports already existed. This PR covers every admin route and removes reliance on cached roles for receipts. |
| 3. Login lockout | Addressed here, including persistent state, expiry/reset and parallel-failure tests. |
| 4. Reservations | Windows, zone/type filters, overlap checks and separate reserved/occupied states already exist. Atomic double-booking prevention, expiry and entry-window enforcement remain follow-ups. |
| 5. Billing/payment | Per-slot rates, fee preview, pending payment and printable receipts already existed. This PR tests persistence/access and hardens repeated/concurrent transitions. A central vehicle-type rate table and decimal-money migration remain follow-ups. |
| 6. Admin dashboard | CRUD, per-slot rates, live counts and daily/monthly reports exist. A dedicated entry/exit audit-log view is still missing. |
| 7. Security | Added validation, CSRF, POST logout, environment/random secret and HttpOnly/SameSite cookies; secure cookies are configurable. Deployment TLS and `run.py` debug-mode changes remain outside scope. |
| 8. Tests | Four integration tests already existed. This PR adds Sprint 2 positive/negative/concurrency tests and executes both suites in CI. It does not cover every test in the broad plan. |
| 9. Non-functional evidence | 50-session load/p90, actual desktop/mobile browser usability, deployed TLS and 99% uptime remain unverified; integration tests do not establish these results. |
| 10. Maintenance | Direct app/test dependencies are pinned; CI uploads evidence and setup is documented. Formal versioned migrations, centralized audit/monitoring, API errors and deployment configuration remain follow-ups. Existing additive SQLite upgrades are retained. |

## CI

The existing workflow only checked required documents. It now preserves those
checks and installs test dependencies, runs integration tests on Python 3.10/3.13,
requires 80% application line coverage and uploads JUnit/coverage XML per version,
including on failure. It runs on main pushes, PRs targeting main and manual
dispatch. No deployment job exists; this validates CI, not a CD deployment.

Most business-flow tests disable CSRF to isolate business assertions. A dedicated
test enables real CSRF, rejects missing/forged tokens and submits a token
obtained from the rendered login form. Each test uses a temporary SQLite file.

Local verification on Windows/Python 3.13: 24 tests passed with 89% application
line coverage. CI artifacts provide the independent Linux/Python matrix result.
These are integration-test results, not browser, uptime or deployment evidence.
