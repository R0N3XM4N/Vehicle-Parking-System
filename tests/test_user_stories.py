"""Acceptance tests for screenshot stories #14–17 and #27–33."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta, timezone
from pathlib import Path
from threading import Barrier
from unittest.mock import patch
import tempfile
import unittest

import jwt
from werkzeug.security import generate_password_hash

from app import create_app, db
from app.models import (
    AuthSession,
    ParkingSlot,
    Payment,
    Reservation,
    User,
    VehicleLog,
    VehicleRate,
)
from app.services import write_transaction
from app.timeutils import utcnow


class UserStoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.app = create_app(
            {
                "TESTING": True,
                "BCRYPT_ROUNDS": 4,
                "SECRET_KEY": "a-long-test-only-key-not-a-production-secret",
                "SQLALCHEMY_DATABASE_URI": f"sqlite:///{Path(self.temp.name)/'test.db'}",
            }
        )
        self.app.logger.disabled = True
        self.addCleanup(self.dispose)
        self.client = self.app.test_client()
        with self.app.app_context():
            for name, role in (
                ("driver", "user"),
                ("other", "user"),
                ("admin", "admin"),
            ):
                user = User(name=name, email=f"{name}@example.com", role=role)
                user.set_password("Test-password-123")
                db.session.add(user)
            db.session.commit()
            self.user_id = User.query.filter_by(name="driver").one().id
            self.slot_id = (
                ParkingSlot.query.filter_by(vehicle_type="four-wheeler").first().id
            )
        self.token = self.login_token()
        self.admin_token = self.login_token("admin")

    def dispose(self):
        with self.app.app_context():
            db.session.remove()
            db.engine.dispose()

    def login_token(self, name="driver"):
        response = self.client.post(
            "/auth/login",
            json={"email": f"{name}@example.com", "password": "Test-password-123"},
        )
        self.assertEqual(response.status_code, 200, response.data)
        return response.json["data"]["access_token"]

    def call(self, method, path, data=None, token=None):
        return self.client.open(
            path,
            method=method,
            json=data,
            headers={
                "Authorization": f"Bearer {token or self.token}",
                "Accept": "application/json",
            },
        )

    def reserve(self, start=None, end=None):
        start = start or utcnow() - timedelta(seconds=5)
        end = end or start + timedelta(hours=1)
        return self.call(
            "POST",
            "/reservations",
            dict(
                slot_id=self.slot_id,
                vehicle_number="KA01AB1234",
                start_time=start.replace(tzinfo=timezone.utc).isoformat(),
                end_time=end.replace(tzinfo=timezone.utc).isoformat(),
            ),
        )

    def visit(self):
        response = self.reserve()
        self.assertEqual(response.status_code, 201, response.data)
        reservation = response.json["data"]["id"]
        response = self.call("POST", "/entries", dict(reservation_id=reservation))
        self.assertEqual(response.status_code, 201, response.data)
        return reservation, response.json["data"]["id"]

    def test_us14_registration_validation_duplicate_and_no_admin_escalation(self):
        response = self.client.post(
            "/auth/register",
            json=dict(
                name="New Driver",
                email=" New@Example.com ",
                password="Test-password-123",
                role="admin",
            ),
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json["data"]["role"], "user")
        self.assertEqual(response.json["data"]["email"], "new@example.com")
        self.assertEqual(
            self.client.post(
                "/auth/register",
                json=dict(
                    name="Duplicate",
                    email="new@example.com",
                    password="Test-password-123",
                ),
            ).status_code,
            409,
        )
        for data in ([], None, dict(name=[], email="invalid", password="short")):
            self.assertEqual(
                self.client.post("/auth/register", json=data).status_code, 400
            )
        self.assertEqual(
            self.client.post(
                "/auth/register", data="bad", content_type="application/json"
            ).status_code,
            400,
        )

    def test_us15_signed_jwt_claims_and_invalid_tokens(self):
        with self.app.app_context():
            claims = jwt.decode(
                self.token,
                self.app.config["JWT_SECRET_KEY"],
                algorithms=["HS256"],
                audience="vps-clients",
                issuer="vehicle-parking-system",
            )
            self.assertEqual(claims["sub"], str(self.user_id))
            self.assertIn("jti", claims)
            for changes in ({"exp": 1}, {"aud": "wrong"}, {"iss": "wrong"}):
                forged = jwt.encode(
                    claims | changes,
                    self.app.config["JWT_SECRET_KEY"],
                    algorithm="HS256",
                )
                self.assertEqual(
                    self.call("GET", "/slots", token=forged).status_code, 401
                )
            none = jwt.encode(claims, key="", algorithm="none")
            self.assertEqual(self.call("GET", "/slots", token=none).status_code, 401)
        self.assertEqual(
            self.call("GET", "/slots", token=self.token[:-5] + "wrong").status_code, 401
        )
        self.assertEqual(self.client.get("/slots").status_code, 401)
        # A browser cookie alone cannot authorize the CSRF-exempt JSON API.
        self.app.config["WTF_CSRF_ENABLED"] = False
        self.assertEqual(
            self.client.post(
                "/login",
                data={"email": "driver@example.com", "password": "Test-password-123"},
            ).status_code,
            302,
        )
        self.assertEqual(self.client.get("/slots").status_code, 401)

    def test_us16_api_logout_revokes_only_the_current_token(self):
        independent = self.login_token()
        self.assertEqual(self.call("POST", "/auth/logout", {}).status_code, 200)
        self.assertEqual(self.call("GET", "/slots").status_code, 401)
        self.assertEqual(self.call("GET", "/slots", token=independent).status_code, 200)

    def test_us16_browser_logout_rejects_copied_cookie(self):
        self.app.config["WTF_CSRF_ENABLED"] = False
        self.client.post(
            "/login",
            data={"email": "driver@example.com", "password": "Test-password-123"},
        )
        cookie = self.client.get_cookie("session").value
        self.assertEqual(self.client.get("/parking").status_code, 200)
        self.client.post("/logout")
        replay = self.app.test_client()
        replay.set_cookie("session", cookie)
        self.assertEqual(replay.get("/parking").status_code, 302)

    def test_us17_bcrypt_unique_salts_and_legacy_hash_upgrade(self):
        with self.app.app_context():
            first, second = User(), User()
            first.set_password("Same-password-123")
            second.set_password("Same-password-123")
            self.assertTrue(first.password_hash.startswith("$2b$"))
            self.assertNotEqual(first.password_hash, second.password_hash)
            self.assertTrue(first.check_password("Same-password-123"))
            self.assertFalse(first.check_password("wrong"))
            user = db.session.get(User, self.user_id)
            user.password_hash = generate_password_hash("Test-password-123")
            db.session.commit()
        self.login_token()
        with self.app.app_context():
            self.assertTrue(
                db.session.get(User, self.user_id).password_hash.startswith("$2b$")
            )

    def test_us32_occupied_overlap_and_adjacent_windows(self):
        start = utcnow() + timedelta(hours=1)
        self.assertEqual(
            self.reserve(start, start + timedelta(hours=1)).status_code, 201
        )
        self.assertEqual(
            self.reserve(start, start + timedelta(minutes=30)).status_code, 409
        )
        self.assertEqual(
            self.reserve(
                start + timedelta(hours=1), start + timedelta(hours=2)
            ).status_code,
            201,
        )
        with self.app.app_context():
            db.session.get(ParkingSlot, self.slot_id).is_occupied = True
            db.session.commit()
        self.assertEqual(
            self.reserve(
                start + timedelta(hours=3), start + timedelta(hours=4)
            ).status_code,
            409,
        )

    def test_us32_parallel_booking_saves_one_reservation(self):
        barrier = Barrier(2)
        start = utcnow() + timedelta(hours=1)
        data = dict(
            slot_id=self.slot_id,
            vehicle_number="KA01AB1234",
            start_time=start.replace(tzinfo=timezone.utc).isoformat(),
            end_time=(start + timedelta(hours=1))
            .replace(tzinfo=timezone.utc)
            .isoformat(),
        )

        def book(_):
            with self.app.test_client() as client:
                barrier.wait(timeout=10)
                return client.post(
                    "/reservations",
                    json=data,
                    headers={"Authorization": f"Bearer {self.token}"},
                ).status_code

        with ThreadPoolExecutor(max_workers=2) as executor:
            self.assertEqual(sorted(executor.map(book, range(2))), [201, 409])
        with self.app.app_context():
            self.assertEqual(Reservation.query.count(), 1)

    def test_us33_time_validation_entry_window_expiry_and_reserved_state(self):
        future = utcnow() + timedelta(hours=1)
        response = self.reserve(future, future + timedelta(hours=1))
        reservation_id = response.json["data"]["id"]
        self.assertEqual(
            self.call(
                "POST", "/entries", dict(reservation_id=reservation_id)
            ).status_code,
            409,
        )
        with self.app.app_context():
            row = db.session.get(Reservation, reservation_id)
            row.start_time = utcnow() - timedelta(minutes=5)
            row.scheduled_end_time = utcnow() + timedelta(minutes=5)
            db.session.commit()
        rows = self.call("GET", "/slots?state=reserved").json["data"]["items"]
        self.assertIn(self.slot_id, [row["id"] for row in rows])
        with self.app.app_context():
            row = db.session.get(Reservation, reservation_id)
            row.scheduled_end_time = utcnow() - timedelta(seconds=1)
            db.session.commit()
        self.assertEqual(
            self.call(
                "POST", "/entries", dict(reservation_id=reservation_id)
            ).status_code,
            409,
        )
        with self.app.app_context():
            self.assertEqual(
                db.session.get(Reservation, reservation_id).status, "expired"
            )
            self.assertEqual(VehicleLog.query.count(), 0)
        self.assertEqual(
            self.reserve(future, future - timedelta(hours=1)).status_code, 400
        )
        self.assertEqual(
            self.reserve(future, future + timedelta(hours=25)).status_code, 400
        )

    def test_us33_parallel_entry_records_one_visit(self):
        row = self.reserve().json["data"]["id"]
        barrier = Barrier(2)

        def enter(_):
            with self.app.test_client() as client:
                barrier.wait(timeout=10)
                return client.post(
                    "/entries",
                    json={"reservation_id": row},
                    headers={"Authorization": f"Bearer {self.token}"},
                ).status_code

        with ThreadPoolExecutor(max_workers=2) as executor:
            self.assertEqual(sorted(executor.map(enter, range(2))), [201, 409])
        with self.app.app_context():
            self.assertEqual(VehicleLog.query.count(), 1)

    def test_us27_zone_counts_follow_reservation_entry_and_exit(self):
        row = self.reserve().json["data"]["id"]
        before = self.call("GET", "/occupancy").json["data"]
        self.assertEqual(sum(zone["reserved"] for zone in before), 1)
        entry = self.call("POST", "/entries", dict(reservation_id=row)).json["data"][
            "id"
        ]
        during = self.call("GET", "/occupancy").json["data"]
        self.assertEqual(sum(zone["occupied"] for zone in during), 1)
        for zone in during:
            self.assertEqual(
                zone["total"], zone["occupied"] + zone["reserved"] + zone["available"]
            )
        quote = self.call("GET", f"/entries/{entry}/quote").json["data"]["quote_token"]
        self.call("POST", f"/entries/{entry}/exit", dict(quote_token=quote))
        after = self.call("GET", "/occupancy").json["data"]
        self.assertEqual(sum(zone["occupied"] for zone in after), 0)

    def test_us28_admin_audit_timestamps_zone_filter_and_rbac(self):
        _, entry = self.visit()
        self.assertEqual(self.call("GET", "/admin/logs").status_code, 403)
        rows = self.call("GET", "/admin/logs?zone=Zone+A", token=self.admin_token).json[
            "data"
        ]["items"]
        self.assertEqual(rows[0]["id"], entry)
        self.assertTrue(rows[0]["entry_time"].endswith("+00:00"))
        self.assertIsNone(rows[0]["exit_time"])
        quote = self.call("GET", f"/entries/{entry}/quote").json["data"]["quote_token"]
        self.call("POST", f"/entries/{entry}/exit", dict(quote_token=quote))
        rows = self.call("GET", "/admin/logs", token=self.admin_token).json["data"][
            "items"
        ]
        self.assertIsNotNone(rows[0]["exit_time"])
        self.assertEqual(
            self.call("GET", "/admin/logs?page=0", token=self.admin_token).status_code,
            400,
        )

    def test_us29_us31_type_rates_frozen_at_entry_and_billing_boundaries(self):
        self.assertEqual(
            self.call(
                "PUT",
                "/admin/rates",
                dict(vehicle_type="four-wheeler", hourly_rate="45"),
            ).status_code,
            403,
        )
        self.assertEqual(
            self.call(
                "PUT",
                "/admin/rates",
                dict(vehicle_type="four-wheeler", hourly_rate="45"),
                token=self.admin_token,
            ).status_code,
            200,
        )
        reservation_id, entry = self.visit()
        self.call(
            "PUT",
            "/admin/rates",
            dict(vehicle_type="four-wheeler", hourly_rate="90"),
            token=self.admin_token,
        )
        base = utcnow()
        for minutes, expected in ((0, 4500), (60, 4500), (61, 9000)):
            with self.app.app_context():
                db.session.get(VehicleLog, entry).entry_time = base - timedelta(
                    minutes=minutes
                )
                db.session.commit()
            with patch("app.services.utcnow", return_value=base):
                quote = self.call("GET", f"/entries/{entry}/quote").json["data"]
                self.assertEqual(quote["amount_cents"], expected)
                self.assertEqual(quote["rate_cents"], 4500)
        with self.app.app_context():
            self.assertEqual(
                db.session.get(Reservation, reservation_id).rate_cents, 4500
            )
            self.assertTrue(
                all(
                    s.hourly_rate == 90
                    for s in ParkingSlot.query.filter_by(vehicle_type="four-wheeler")
                )
            )
        for value in ("NaN", "Infinity", "0", "-1", "0.001", {}, None):
            self.assertEqual(
                self.call(
                    "PUT",
                    "/admin/rates",
                    dict(vehicle_type="four-wheeler", hourly_rate=value),
                    token=self.admin_token,
                ).status_code,
                400,
            )

    def test_us30_signed_quote_exact_amount_tamper_expiry_and_ownership(self):
        _, entry = self.visit()
        quote = self.call("GET", f"/entries/{entry}/quote").json["data"]
        self.assertEqual(
            self.call("POST", f"/entries/{entry}/exit", {}).status_code, 400
        )
        self.assertEqual(
            self.call(
                "POST", f"/entries/{entry}/exit", dict(quote_token="forged")
            ).status_code,
            409,
        )
        other = self.login_token("other")
        self.assertEqual(
            self.call(
                "POST",
                f"/entries/{entry}/exit",
                dict(quote_token=quote["quote_token"]),
                token=other,
            ).status_code,
            404,
        )
        with patch(
            "itsdangerous.timed.time.time", return_value=__import__("time").time() + 301
        ):
            self.assertEqual(
                self.call(
                    "POST",
                    f"/entries/{entry}/exit",
                    dict(quote_token=quote["quote_token"]),
                ).status_code,
                409,
            )
        self.call(
            "PUT",
            "/admin/rates",
            dict(vehicle_type="four-wheeler", hourly_rate="80"),
            token=self.admin_token,
        )
        response = self.call(
            "POST",
            f"/entries/{entry}/exit",
            dict(quote_token=quote["quote_token"], amount_cents=1),
        )
        self.assertEqual(response.status_code, 200, response.data)
        payment = response.json["data"]["payment"]
        self.assertEqual(payment["amount_cents"], quote["amount_cents"])
        paid = self.call("POST", "/payments", dict(payment_id=payment["id"]))
        self.assertEqual(paid.json["data"]["amount_cents"], quote["amount_cents"])
        self.assertEqual(
            self.call("GET", f"/receipts/{payment['id']}").status_code, 200
        )

    def test_json_validation_errors_are_consistent(self):
        response = self.call("POST", "/entries", dict(reservation_id=True))
        self.assertEqual(response.status_code, 400)
        self.assertEqual(set(response.json["error"]), {"code", "message"})
        self.assertEqual(self.call("GET", "/slots?vehicle_type=truck").status_code, 400)
        self.assertEqual(self.call("GET", "/slots?per_page=1000").status_code, 400)
        self.assertEqual(self.call("GET", "/entries/999/quote").status_code, 404)
        self.assertEqual(
            self.call("GET", "/admin/logs", token=self.admin_token).status_code, 200
        )

    def test_us16_revocation_survives_application_restart(self):
        independent = self.login_token()
        self.call("POST", "/auth/logout", {})
        restarted = create_app(dict(self.app.config))
        try:
            with restarted.test_client() as client:
                for token, expected in ((self.token, 401), (independent, 200)):
                    self.assertEqual(
                        client.get(
                            "/slots", headers={"Authorization": f"Bearer {token}"}
                        ).status_code,
                        expected,
                    )
        finally:
            with restarted.app_context():
                db.session.remove()
                db.engine.dispose()

    def test_admin_slot_adapters_and_malformed_ids_preserve_role_guards(self):
        data = dict(slot_number="DEMO-01", zone="Demo", vehicle_type="two-wheeler")
        self.assertEqual(self.call("POST", "/admin/slots", data).status_code, 403)
        response = self.call("POST", "/admin/slots", data, token=self.admin_token)
        self.assertEqual(response.status_code, 201)
        slot_id = response.json["data"]["id"]
        self.assertEqual(
            self.call(
                "PUT",
                f"/admin/slots/{slot_id}",
                data | {"slot_number": "DEMO-02"},
                token=self.admin_token,
            ).status_code,
            200,
        )
        self.assertEqual(
            self.call("GET", "/admin/slots", token=self.admin_token).status_code, 200
        )
        self.assertEqual(
            self.call(
                "DELETE", f"/admin/slots/{slot_id}", token=self.admin_token
            ).status_code,
            200,
        )
        self.assertEqual(self.call("GET", "/entries").status_code, 200)
        for identifier in (True, 2**100):
            self.assertEqual(
                self.call(
                    "POST", "/entries", dict(reservation_id=identifier)
                ).status_code,
                400,
            )
        self.assertEqual(
            self.call(
                "PUT",
                "/admin/rates",
                dict(vehicle_type={}, hourly_rate="30"),
                token=self.admin_token,
            ).status_code,
            400,
        )

    def test_admin_creation_and_expiry_sweep_commands(self):
        runner = self.app.test_cli_runner()
        result = runner.invoke(
            args=[
                "create-admin",
                "--email",
                "new-admin@example.com",
                "--password",
                "Synthetic-admin-123",
            ]
        )
        self.assertEqual(result.exit_code, 0, result.output)
        with self.app.app_context():
            self.assertEqual(
                User.query.filter_by(email="new-admin@example.com").one().role, "admin"
            )
            db.session.add(
                Reservation(
                    user_id=self.user_id,
                    slot_id=self.slot_id,
                    vehicle_number="KA01AB1234",
                    start_time=utcnow() - timedelta(hours=2),
                    scheduled_end_time=utcnow() - timedelta(hours=1),
                    status="reserved",
                )
            )
            db.session.commit()
        result = runner.invoke(args=["expire-reservations"])
        self.assertEqual(result.exit_code, 0, result.output)
        with self.app.app_context():
            self.assertEqual(Reservation.query.one().status, "expired")
