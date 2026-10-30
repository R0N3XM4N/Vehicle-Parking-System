# Software Test Plan

## Vehicle Parking System (VPS)

**Project:** Vehicle Parking System  
**Document:** Software Test Plan  
**Version:** 1.0  
**Date:** 17-09-2026  
**Source SRS:** Version 1.0, dated 03-09-2026  
**Team:** Team 10

### 1. Purpose

This test plan defines the testing approach for the Vehicle Parking System (VPS). It covers the functional, non-functional, and security requirements defined in the SRS and maps each requirement to its corresponding test case.

The VPS is a web-based application for user registration/login, parking-slot availability and reservation, vehicle entry/exit tracking, fee calculation, payment recording, and administration. The SRS states that physical hardware such as barriers, cameras, and sensors is outside the base project scope; entry and exit are simulated or entered manually.

### 2. Test Objectives

The objectives are to verify that:

1. All high-priority functional requirements work according to their acceptance criteria.
2. Medium- and low-priority requirements behave as specified.
3. Parking availability, reservations, entry/exit, billing, payment, and reporting produce correct results.
4. Performance, scalability, responsiveness, and password-storage requirements meet the SRS targets.
5. Security controls for authentication, authorization, TLS, input validation, and failed-login lockout work as specified.
6. All planned tests are traceable to the SRS through the RTM.

### 3. Scope

#### 3.1 In scope

- User registration, login, logout, and authentication-token handling.
- Parking-slot availability display and filtering.
- Slot reservation and duplicate-booking prevention.
- Vehicle entry/exit logging and slot occupancy updates.
- Occupancy counting and audit logs.
- Fee calculation and fee display.
- Simulated payment recording and receipt generation.
- Admin slot management and hourly-rate configuration.
- Occupancy and revenue reporting.
- Response-time and concurrent-user testing.
- Responsive UI testing on desktop and mobile screen sizes.
- Password hashing, role-based access control, HTTPS/TLS, input validation, and account lockout.

#### 3.2 Out of scope

- Physical boom barriers.
- ANPR cameras and real parking sensors.
- Real external payment-gateway integration.
- Multi-city or franchise-level administration.

### 4. References

- Software Requirements Specification (SRS), Vehicle Parking System, Version 1.0, 03-09-2026.
- SRS Section 4: System features and acceptance criteria.
- SRS Section 5: Non-functional and security requirements.
- SRS Section 6: Quality attributes and acceptance-test exit criteria.
- SRS Section 8: Requirements Traceability Matrix (RTM).

### 5. System Under Test

The SRS describes the VPS as a standalone web application consisting of:

- Client-facing responsive web UI.
- Flask backend REST API.
- SQLite database.
- JWT-based session authentication.
- JSON data interchange.
- Simulated payments rather than an external gateway.

### 6. Test Environment

| Item | Planned environment |
|---|---|
| Client | Modern browser: Chrome, Firefox, or Edge |
| Client devices | Desktop and mobile screen sizes |
| Server | Python + Flask on local or suitable cloud environment |
| Database | SQLite |
| API format | JSON |
| Authentication | JWT |
| Communication | HTTPS/TLS |
| Test data | Dedicated test users, vehicles, slots, reservations, rates, entry/exit records, and transactions |
| Performance testing | Test environment capable of generating up to at least 50 concurrent sessions |

### 7. Test Strategy

Testing will combine manual functional testing, API/database verification, security testing, UI testing, and performance/load testing.

#### 7.1 Functional testing

Functional test cases verify user-facing and admin operations against the SRS acceptance criteria. Positive and negative cases are included where the requirement specifies both valid and invalid behavior.

#### 7.2 Integration testing

Integration checks verify that related modules exchange and persist correct data, for example:

- Authentication with protected routes.
- Reservation with slot status.
- Vehicle exit with fee calculation.
- Payment with receipt generation.
- Admin rate updates with later billing calculations.
- Transaction data with occupancy/revenue reports.

#### 7.3 Security testing

Security tests verify password hashing, role-based authorization, TLS usage, input validation/sanitization, injection/XSS resistance, and failed-login lockout.

#### 7.4 Performance and scalability testing

Performance tests verify the SRS targets of 90th-percentile page/API response time of no more than 2 seconds under normal load and stable operation for at least 50 concurrent users.

#### 7.5 Usability testing

The responsive interface will be checked at desktop and mobile screen sizes to ensure that the layout and controls remain usable.

### 8. Entry Criteria

Testing starts when:

- The test build is available and deployable.
- Required database schema and test data are available.
- Core pages/API endpoints needed by a test case are implemented.
- Test environment and browser access are available.

### 9. Exit Criteria

The SRS states that acceptance is complete when all high-priority functional requirements are implemented and verified, there are no critical NFR failures, and the RTM shows all test cases passed.

### 10. Test Case Format

Each test case contains:

- Test Case ID
- Requirement ID
- Objective
- Preconditions
- Test Steps
- Expected Result
- Priority

### 11. Functional Test Cases

#### 11.1 Authentication

| TC ID | Req ID | Objective | Preconditions | Test Steps | Expected Result | Priority |
|---|---|---|---|---|---|---|
| TC-Auth-01 | PVT-F-001 | Verify valid user registration | Registration page available; test email unused | Enter valid name, email, and password; submit | Account is created and user is redirected to login | High |
| TC-Auth-02 | PVT-F-002 | Verify login for valid and invalid credentials | Registered test user exists | Enter valid credentials and log in; repeat with invalid password | Valid credentials issue a JWT/session token; invalid credentials display an error | High |
| TC-Auth-03 | PVT-F-003 | Verify logout and protected-route blocking | User is logged in | Log out; attempt to access a protected route | Token/session is cleared and protected routes are inaccessible | Medium |

#### 11.2 Slot Search and Reservation

| TC ID | Req ID | Objective | Preconditions | Test Steps | Expected Result | Priority |
|---|---|---|---|---|---|---|
| TC-Slot-01 | PVT-F-004 | Verify current slot availability | Slots exist with known free/occupied states | Open slot availability by zone/location | UI shows the current free and occupied status correctly | High |
| TC-Slot-02 | PVT-F-005 | Verify vehicle-type filtering | Two-wheeler and four-wheeler slots exist | Select two-wheeler; repeat for four-wheeler | Results contain only slots matching the selected vehicle type | Medium |
| TC-Slot-03 | PVT-F-006 | Verify duplicate/occupied slot booking prevention | Target slot is occupied or reserved | Attempt to book the target slot | Booking is rejected and a conflict/error is returned | High |
| TC-Slot-04 | PVT-F-007 | Verify reservation of an available slot | User is logged in; slot is free | Select slot and valid time window; confirm reservation | Slot becomes reserved and confirmation is shown | High |

#### 11.3 Vehicle Entry/Exit Tracking

| TC ID | Req ID | Objective | Preconditions | Test Steps | Expected Result | Priority |
|---|---|---|---|---|---|---|
| TC-Track-01 | PVT-F-008 | Verify vehicle entry logging | Valid vehicle and free slot exist | Enter vehicle number and slot ID; submit entry | Entry record with vehicle number, slot ID, and timestamp is created; slot becomes occupied | High |
| TC-Track-02 | PVT-F-009 | Verify vehicle exit and slot release | Active entry record exists | Record vehicle exit | Exit timestamp is recorded and slot becomes available | High |
| TC-Track-03 | PVT-F-010 | Verify live occupancy count | Known set of occupied/free slots exists | Open occupancy count; change slot state through entry/exit | Occupancy count matches the number of occupied slots | High |
| TC-Track-04 | PVT-F-011 | Verify entry/exit audit logs | Entry/exit events exist | Open admin audit-log view | Logs are retrievable and timestamps are correct | Medium |

#### 11.4 Fee Calculation and Payment

| TC ID | Req ID | Objective | Preconditions | Test Steps | Expected Result | Priority |
|---|---|---|---|---|---|---|
| TC-Bill-01 | PVT-F-012 | Verify fee calculation | Exit data, duration, and rate table are configured | Complete an exit scenario with known duration and vehicle type | Calculated fee equals configured rate × billed hours for the vehicle type | High |
| TC-Bill-02 | PVT-F-013 | Verify displayed fee matches backend result | Valid exit scenario exists | Proceed to exit confirmation | Fee displayed to the user matches backend calculation | High |
| TC-Pay-01 | PVT-F-014 | Verify payment recording and receipt | Calculated fee is available | Complete simulated payment | Payment transaction is recorded and receipt contains transaction ID, amount, and timestamp | High |

#### 11.5 Admin Dashboard

| TC ID | Req ID | Objective | Preconditions | Test Steps | Expected Result | Priority |
|---|---|---|---|---|---|---|
| TC-Admin-01 | PVT-F-015 | Verify parking-slot CRUD | Admin is authenticated | Add a slot; edit it; remove it; refresh listing | Add/edit/remove operations are reflected in the slot listing | Medium |
| TC-Admin-02 | PVT-F-016 | Verify hourly-rate configuration | Admin is authenticated; vehicle type exists | Update hourly rate; perform a new billing calculation | New fee calculation uses the updated rate | Medium |
| TC-Admin-03 | PVT-F-017 | Verify occupancy/revenue reports | Transaction and occupancy data exist | Generate daily/monthly report | Report totals match the underlying individual transactions and occupancy records | Low |

### 12. Non-Functional Test Cases

| TC ID | Req ID | Objective | Preconditions | Test Steps | Expected Result | Priority |
|---|---|---|---|---|---|---|
| TC-Perf-01 | PVT-NF-001 | Verify response-time target | Performance environment ready; normal-load workload defined | Execute representative page/API workload; collect response times | 90th-percentile page/API response time is ≤ 2 seconds | High |
| TC-Perf-02 | PVT-NF-002 | Verify support for 50 concurrent users | Load-test setup ready | Run test with at least 50 concurrent sessions | System remains stable without degradation; response behavior remains acceptable | Medium |
| TC-UX-01 | PVT-NF-004 | Verify responsive UI | Supported browser available | Test key pages at desktop and mobile screen sizes | Layout remains usable and controls/content display correctly at all tested sizes | Medium |

**Availability check:** PVT-NF-003 requires at least 99% availability during operational hours. The SRS identifies this as an operational/uptime report rather than a named `TC-*` test case, so it will be verified using uptime monitoring records as specified in the SRS.

### 13. Security Test Cases

| TC ID | Req ID | Objective | Preconditions | Test Steps | Expected Result | Priority |
|---|---|---|---|---|---|---|
| TC-Sec-01 | PVT-NF-005 / PRJ-SR-001 | Verify password hashing and salting | Test account exists; DB inspection is permitted | Register/change a password; inspect stored password value | Password is stored only as a one-way salted hash and never plaintext | High |
| TC-Sec-02 | PRJ-SR-002 | Verify role-based access control | User and admin accounts exist | Attempt admin operations using a normal user account | Unauthorized role access returns 403 / is denied | High |
| TC-Sec-03 | PRJ-SR-003 | Verify HTTPS/TLS | HTTPS-enabled environment available | Inspect client-server connection/network capture | Client-server communication uses TLS/HTTPS | High |
| TC-Sec-04 | PRJ-SR-004 | Verify input validation and injection/XSS protection | Test application available | Submit malformed, injection-like, and XSS payloads through relevant inputs | Inputs are validated/sanitized and no SQL/NoSQL injection or XSS vulnerability is observed in the tested paths | High |
| TC-Sec-05 | PRJ-SR-005 | Verify failed-login account lockout | Test account available | Enter an incorrect password 6 consecutive times | Login is blocked on the 6th failed attempt for 15 minutes | Medium |

### 14. Test Data

| Data Item | Example test data |
|---|---|
| Normal user | `user01@example.com` / valid test password |
| Admin user | `admin01@example.com` / valid test password |
| Vehicle number | `KA01AB1234` |
| Vehicle types | Two-wheeler, Four-wheeler |
| Slot states | Available, Reserved, Occupied |
| Reservation window | Valid future time window |
| Example hourly rates | Test values configured through the admin interface |
| Entry/exit times | Controlled timestamps suitable for known-duration billing |
| Payment | Simulated successful payment |

Test credentials and secrets used during implementation must not be committed to the repository.

### 15. Defect Handling

For each failed test, record:

- Test Case ID.
- Requirement ID.
- Steps used.
- Actual result.
- Expected result.
- Severity and priority.
- Evidence such as screenshots, logs, or API responses.
- Developer resolution and retest result.

A failed test is not marked passed until the defect is fixed and the test is successfully rerun.

### 16. Traceability Matrix

| Requirement | Test Case |
|---|---|
| PVT-F-001 | TC-Auth-01 |
| PVT-F-002 | TC-Auth-02 |
| PVT-F-003 | TC-Auth-03 |
| PVT-F-004 | TC-Slot-01 |
| PVT-F-005 | TC-Slot-02 |
| PVT-F-006 | TC-Slot-03 |
| PVT-F-007 | TC-Slot-04 |
| PVT-F-008 | TC-Track-01 |
| PVT-F-009 | TC-Track-02 |
| PVT-F-010 | TC-Track-03 |
| PVT-F-011 | TC-Track-04 |
| PVT-F-012 | TC-Bill-01 |
| PVT-F-013 | TC-Bill-02 |
| PVT-F-014 | TC-Pay-01 |
| PVT-F-015 | TC-Admin-01 |
| PVT-F-016 | TC-Admin-02 |
| PVT-F-017 | TC-Admin-03 |
| PVT-NF-001 | TC-Perf-01 |
| PVT-NF-002 | TC-Perf-02 |
| PVT-NF-003 | Ops report / uptime monitoring |
| PVT-NF-004 | TC-UX-01 |
| PVT-NF-005 | TC-Sec-01 |
| PRJ-SR-001 | TC-Sec-01 |
| PRJ-SR-002 | TC-Sec-02 |
| PRJ-SR-003 | TC-Sec-03 |
| PRJ-SR-004 | TC-Sec-04 |
| PRJ-SR-005 | TC-Sec-05 |

### 17. Acceptance and Sign-Off

The test effort is considered complete when the SRS exit criteria are satisfied: all high-priority functional requirements have been verified, there are no critical NFR failures, and the RTM indicates that all required test cases have passed. Final acceptance is subject to project/instructor evaluation.

| Role | Name | Signature/Date |
|---|---|---|
| Test Lead | Team 10 | |
| Project Team | Team 10 | |
| Course Coordinator | | |
