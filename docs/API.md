# User-story API

All bodies and success responses are JSON. Success is `{"data": ...}`; errors
are `{"error":{"code":"...","message":"..."}}`. Use 400 for invalid input,
401 for invalid authentication, 403 for wrong roles, 404 for missing/private
resources, 409 for state conflicts and 429 for the existing login lockout.

Except register/login, API operations require `Authorization: Bearer <token>`.
The API never accepts browser cookies as credentials, so cookie-based CSRF
cannot authorize its operations. Browser POST forms retain CSRF protection.
Browser login stores a JWT inside its HttpOnly signed session cookie and checks
the same persistent session record as bearer requests. Default expiry: one hour.

## Account stories #14–#17

| Method / path | Request | Result |
|---|---|---|
| POST `/auth/register` | `name`, `email`, `password` | 201 ordinary-user account; duplicate email 409. Password: 8+ characters, at most 72 UTF-8 bytes. Submitted role is ignored. |
| POST `/auth/login` | `email`, `password` | `access_token`, `token_type`, `expires_in`, user summary. Existing five-failure/15-minute lockout is retained. |
| POST `/auth/logout` | No body required | Revokes this JWT's `jti` persistently; replay gets 401. Other independently issued sessions are unaffected. |

JWTs use HS256 with fixed allowed algorithm, issuer/audience, required claims,
expiry and database-backed revocation. Roles are read from the current User row,
not trusted from token claims. Tokens and password hashes are never returned in
audit logs. New passwords use salted bcrypt with cost 12 by default. Valid
legacy Werkzeug hashes are upgraded on successful login without losing users.

## Parking stories #27–#33

| Method / path | Request / query | Result |
|---|---|---|
| GET `/slots` | Optional `zone`, `vehicle_type`, `state`; optional paired `start_time`/`end_time`; `page`, `per_page` (1–100) | Matching slot IDs, state and type rate in cents. |
| GET `/occupancy` | None | Total, Available, Reserved and Occupied counts per zone. |
| POST `/reservations` | `slot_id`, `vehicle_number`, `start_time`, `end_time` | 201 reservation; overlapping/occupied conflict 409. Times require ISO 8601 offsets, e.g. `2026-11-16T10:00:00+05:30`. Window ≤24 hours. |
| GET `/reservations` | Pagination | Current user's reservations. |
| POST `/entries` | `reservation_id` | 201 entry event during the reservation window; snapshots the current vehicle-type rate. |
| GET `/entries` | Pagination | Current user's visit records. |
| GET `/entries/{id}/quote` | None | `quote_token`, billed hours, rate and amount in cents; valid for five minutes. |
| POST `/entries/{id}/exit` | `quote_token` | Persists actual exit, releases slot and creates one pending payment for the exact signed preview amount. Repeats are idempotent while the quote is valid. |
| GET `/admin/logs` | Optional `zone`; pagination | Admin-only vehicle/slot/zone/entry/exit audit records with UTC timestamps. |
| GET `/admin/rates` | None | Supported vehicle types and `cents_per_hour`. |
| PUT `/admin/rates` | `vehicle_type`, `hourly_rate` (decimal string) | Type-wide rate update; existing active visits retain their snapshot. POST and PUT `/admin/rates/{vehicle_type}` also supported. |

Existing checkout/payment functionality remains available through browser forms.
Its shared API adapters are POST `/payments` with `payment_id` and GET
`/receipts/{payment_id}`. The existing slot-management forms have equivalent
admin-only JSON GET/POST `/admin/slots` and PUT/DELETE `/admin/slots/{id}`.

## Policies and consistency

- Rates are positive finite amounts, at most 1,000,000 INR/hour, with at most two
  decimals. Store billing in integer cents; legacy float fields remain compatibility
  mirrors only. Whole-hour ceiling applies, minimum one hour.
- `BEGIN IMMEDIATE` acquires the SQLite writer lock **before** validation reads.
  Booking, entry, checkout and payment changes commit atomically. Database
  uniqueness also prevents duplicate payments and simultaneous active visit logs.
- Windows are half-open: start ≤ entry < end. Adjacent windows do not overlap.
  An occupied slot always blocks booking. Unused reservations expire at their
  scheduled end; reads/mutations reconcile expiry, and a CLI sweep is available.
- Current Reserved state means a reservation covers the current instant. Future
  reservations block overlapping windows without marking the slot occupied now.
- Store all new timestamps in UTC. Browser forms/displays use Asia/Kolkata.
  See the migration notes before upgrading an existing prototype database.
- Fee previews are signed, owner/visit-bound and expire after five minutes.
  Exit records its real confirmation timestamp but honors the preview's fee.
  Client-supplied amounts cannot override billing.
- JSON adapters share the same services as HTML routes. Existing report pages
  remain HTML; this PR does not expand the separate reporting/deployment scope.
