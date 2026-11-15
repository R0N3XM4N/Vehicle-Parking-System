# PR #52 user stories and demonstration guide

Scope: the eleven existing stories in the requester's screenshot, #14–#17 and
#27–#33. Total: **37 story points**. They are grouped into five demonstration
sections below; the original issues remain the individual user stories.
These are implementation/test targets, not a claim that unmerged changes are
already available on main. Run the PR branch for the demonstration.

## Group A — Secure accounts (12 points)

| Story | User story | Acceptance criteria | Demo |
|---|---|---|---|
| #14 / PVT-F-001 (3) | As a vehicle owner, I want to register with my name, email and password so I can use the parking system. | Valid input creates one ordinary-user account; duplicate/malformed input is rejected; registration redirects the browser to login. Submitted roles cannot grant admin access. | Register a fresh account, show the login page, then try the same email again. |
| #15 / PVT-F-002 (5) | As a registered user, I want to sign in with email and password and receive a JWT so I can access protected parking features. | Correct credentials issue an expiring signed JWT with issuer/audience checks; invalid, expired or tampered tokens are rejected. Browser sessions use the same JWT validation. | Sign in through the UI; use the API login and show token type/expiry, then access `/slots` with the bearer token. Do not display the full token in slides or logs. |
| #16 / PVT-F-003 (2) | As a signed-in user, I want logout to revoke my authentication token so that session cannot be reused. | Logout clears the browser cookie and persistently revokes the JWT identifier; replaying a copied pre-logout cookie/token fails. Other independently issued sessions remain active. | Log out, revisit a protected page, and demonstrate an old bearer token receiving 401. |
| #17 / PVT-NF-005 / PRJ-SR-001 (2) | As an account holder, I want my password stored as a salted bcrypt hash so plaintext passwords are never stored. | Newly created passwords use bcrypt with independent random salts; authentication verifies the hash; legacy Werkzeug hashes upgrade after successful login. | Show the test result for two equal passwords yielding different bcrypt hashes. Never reveal a real user's password/hash. |

## Group B — Reliable time-window reservations (8 points)

| Story | User story | Acceptance criteria | Demo |
|---|---|---|---|
| #32 / PVT-F-006 (3) | As a driver, I want occupied and overlapping reserved slots rejected so my booking cannot conflict with another vehicle. | Physical occupancy blocks booking; overlapping windows return 409; concurrent conflicting requests save exactly one reservation; adjacent windows are allowed. | Reserve a window, repeat it from another session and show the conflict. Explain the concurrency regression test. |
| #33 / PVT-F-007 (5) | As a signed-in driver, I want to reserve an available slot for a selected start/end window so I have a confirmed parking space. | Validate vehicle/time input; create a confirmed reservation; display Available/Reserved/Occupied correctly; entry is allowed only inside the window; unused bookings expire at the window end. | Reserve a current window, show Reserved, enter the vehicle and show Occupied. Demonstrate early/expired entry rejection using the tests. |

## Group C — Live zone occupancy (3 points)

| Story | User story | Acceptance criteria | Demo |
|---|---|---|---|
| #27 / PVT-F-010 (3) | As an operator, I want current occupancy counts for each zone so I can monitor parking capacity. | Each zone shows total/available/reserved/occupied counts consistent with the underlying slots; entry/exit changes are reflected; visible pages refresh every 15 seconds without exposing JWTs to JavaScript. | Keep parking/admin open, enter or exit a vehicle from another session and show the zone table updating. |

## Group D — Entry/exit audit trail (3 points)

| Story | User story | Acceptance criteria | Demo |
|---|---|---|---|
| #28 / PVT-F-011 (3) | As an administrator, I want retrievable entry/exit events with timestamps so I can audit parking activity. | Admin-only paginated view/API show visit ID, vehicle, slot, zone, entry and exit; ordinary users are denied; timestamps correspond to persisted records. | Open Admin → Audit logs after a completed visit; compare entry/exit to the receipt. Try the page as a normal user and show access denied. |

## Group E — Vehicle-type pricing and fee preview (11 points)

| Story | User story | Acceptance criteria | Demo |
|---|---|---|---|
| #29 / PVT-F-012 (5) | As a driver, I want the fee calculated from my parking duration and vehicle type so I am charged the correct configured rate. | Use integer cents, type-level hourly pricing and whole-hour ceiling with a one-hour minimum; snapshot the rate at entry so later admin changes cannot alter an active visit. | Configure different two-/four-wheeler rates and show the corresponding fee. Show boundary tests for 60 versus 61 minutes. |
| #30 / PVT-F-013 (3) | As a driver, I want to review the exact fee before confirming exit so I know what I will pay. | Preview shows duration, rate and amount before exit; a signed five-minute quote is required; confirmation charges that preview amount; tampered/expired/other-user quotes fail. | Open Preview Fee and Exit, inspect amount, then confirm and show the same amount on payment/receipt. |
| #31 / PVT-F-016 (3) | As an administrator, I want to configure hourly rates per vehicle type so new visits use consistent pricing. | Admin can update both supported type rates; values must be finite positive amounts with at most two decimals; all slots of that type show the shared rate; active visits keep their snapshot; normal users cannot edit rates. | Change a type rate in Admin, show matching slots and a new visit using it, then show an already active visit retaining its original rate. |

## Agreed rules and scope

- Confirmed by the requester: round up to whole hours, minimum one hour; freeze
  the rate at entry; allow entry only during the reserved window; expire unused
  bookings at its end; use Asia/Kolkata for browser times. Store timestamps in UTC.
- Reserved means the current instant falls in a live reservation window.
  A future reservation does not mark a slot occupied now; its overlapping windows
  remain unavailable to another booking.
- Entry/exit remain manual or simulated. Existing checkout/payment/receipt flows
  are preserved. No external payment gateway or hardware is introduced.
- Keep the existing Admin/User role model. Registration never creates admins.
- PR #51's five-failure, 15-minute lockout, RBAC and CSRF protections must continue
  to pass their regression tests.
- Deployment, TLS/uptime verification, broad performance testing, profile
  management and unrelated reporting expansion are outside this narrowed PR.

## Suggested demonstration sequence

1. Register and log in (stories #14/#15); explain bcrypt tests (#17).
2. Reserve a current time window and attempt a duplicate (#33/#32).
3. Record entry; show the per-zone occupancy update (#27).
4. As admin, show rates and change one type's rate (#31).
5. Preview the current visit fee; explain duration rounding and frozen rate
   (#29/#30), then complete the existing exit/payment flow.
6. Show timestamped admin audit logs (#28).
7. Log out and show protected-page/token rejection (#16).

Use two independent browser sessions for User and Admin. Seed demo accounts with
synthetic data. Use UTC-offset ISO timestamps for API requests and local
Asia/Kolkata times in the HTML reservation form. Automated tests provide the
time-boundary/concurrency evidence without waiting an hour during the demo.

## Executable acceptance mapping

| Story | Main acceptance tests in `tests/test_user_stories.py` |
|---|---|
| #14 | `test_us14_registration_validation_duplicate_and_no_admin_escalation` |
| #15 | `test_us15_signed_jwt_claims_and_invalid_tokens` |
| #16 | `test_us16_api_logout_revokes_only_the_current_token`, `test_us16_browser_logout_rejects_copied_cookie` |
| #17 | `test_us17_bcrypt_unique_salts_and_legacy_hash_upgrade` |
| #27 | `test_us27_zone_counts_follow_reservation_entry_and_exit` |
| #28 | `test_us28_admin_audit_timestamps_zone_filter_and_rbac` |
| #29 | `test_us29_us31_type_rates_frozen_at_entry_and_billing_boundaries` |
| #30 | `test_us30_signed_quote_exact_amount_tamper_expiry_and_ownership` |
| #31 | `test_us29_us31_type_rates_frozen_at_entry_and_billing_boundaries` |
| #32 | `test_us32_occupied_overlap_and_adjacent_windows`, `test_us32_parallel_booking_saves_one_reservation` |
| #33 | `test_us33_time_validation_entry_window_expiry_and_reserved_state`, `test_us33_parallel_entry_records_one_visit` |

The existing `test_frontend_issues.py` and `test_sprint2.py` retain the earlier
browser/payment/RBAC/CSRF/lockout regression coverage, adapted for JWT sessions,
UTC storage and required signed exit quotes. `test_migrations.py` checks legacy
history conversion, rate/amount preservation and atomic refusal of duplicates.
`python -m scripts.browser_smoke` runs real Chromium flows at three sizes and
verifies a live zone-count update without a manual reload.

Local verification on 15 November 2026: **43 integration tests passed, 93%
application line coverage**. Real Chromium passed the story flow at 1200×800,
768×900 and 390×844 with no page errors or horizontal document overflow; the
desktop run also verified the automatic occupancy refresh. CI repeats both
Python versions and the browser checks; its results/artifacts are linked in PR #52.
