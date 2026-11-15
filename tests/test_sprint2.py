"""Sprint 2 acceptance and negative-path integration tests on isolated SQLite."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
import re
import sqlite3
import tempfile
from threading import Barrier
import unittest
from unittest.mock import patch

from app import create_app, db
from app.models import ParkingSlot, Payment, Reservation, User, VehicleLog


class SprintTwoTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.database = Path(self.temp.name) / "parking.db"
        self.app = create_app({
            "TESTING": True,
            "SECRET_KEY": "isolated-test-secret",
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{self.database}",
            "WTF_CSRF_ENABLED": False,
        })
        self.addCleanup(self.dispose)
        self.client = self.app.test_client()
        with self.app.app_context():
            user = User(name="Driver", email="driver@example.com")
            admin = User(name="Administrator", email="admin@example.com", role="admin")
            other = User(name="Other driver", email="other@example.com")
            for account in (user, admin, other):
                account.set_password("Test-password-123")
            db.session.add_all([user, admin, other])
            db.session.commit()
            self.user_id, self.admin_id = user.id, admin.id
            self.slot_id = ParkingSlot.query.first().id

    def dispose(self):
        with self.app.app_context():
            db.session.remove()
            db.engine.dispose()

    def login(self, email="driver@example.com", password="Test-password-123", client=None):
        return (client or self.client).post("/login", data={
            "email": email, "password": password,
        })

    def parked_visit(self):
        with self.app.app_context():
            reservation = Reservation(
                user_id=self.user_id, slot_id=self.slot_id,
                vehicle_number="KA01AB1234", status="parked",
                start_time=datetime.now() - timedelta(hours=2),
                scheduled_end_time=datetime.now() + timedelta(hours=1),
            )
            db.session.add(reservation)
            db.session.flush()
            db.session.add(VehicleLog(
                reservation_id=reservation.id,
                entry_time=datetime.now() - timedelta(minutes=65),
            ))
            db.session.get(ParkingSlot, self.slot_id).is_occupied = True
            db.session.commit()
            return reservation.id

    def checkout(self):
        reservation_id = self.parked_visit()
        self.login()
        response = self.client.post(f"/reservation/{reservation_id}/checkout")
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            return reservation_id, Payment.query.one().id

    def test_tc_sec_02_every_admin_route_rejects_normal_user(self):
        self.login()
        routes = [
            ("GET", "/admin"), ("GET", "/admin/reports"),
            ("POST", "/admin/slots/add"),
            ("POST", f"/admin/slots/{self.slot_id}/edit"),
            ("POST", f"/admin/slots/{self.slot_id}/delete"),
        ]
        for method, route in routes:
            with self.subTest(route=route):
                self.assertEqual(self.client.open(route, method=method).status_code, 403)
        with self.app.app_context():
            self.assertEqual(ParkingSlot.query.count(), 10)

    def test_tc_sec_02_anonymous_and_deleted_sessions_are_rejected(self):
        self.assertEqual(self.client.get("/admin").status_code, 302)
        self.login()
        with self.app.app_context():
            db.session.delete(db.session.get(User, self.user_id))
            db.session.commit()
        self.assertEqual(self.client.get("/parking").status_code, 302)
        with self.client.session_transaction() as session:
            self.assertNotIn("user_id", session)

    def test_tc_sec_02_role_is_checked_against_database(self):
        self.login("admin@example.com")
        self.assertEqual(self.client.get("/admin").status_code, 200)
        with self.app.app_context():
            db.session.get(User, self.admin_id).role = "user"
            db.session.commit()
        self.assertEqual(self.client.get("/admin").status_code, 403)
        with self.client.session_transaction() as session:
            session["user_role"] = "admin"
        self.assertEqual(self.client.get("/admin/reports").status_code, 403)

    def test_tc_sec_05_fifth_failure_locks_correct_password_for_fifteen_minutes(self):
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        with patch("app.routes.datetime") as clock:
            clock.now.return_value = now.replace(tzinfo=timezone.utc)
            for attempt in range(1, 6):
                response = self.login(password="wrong-password")
                self.assertEqual(response.status_code, 429 if attempt == 5 else 401)
            self.assertEqual(self.login().status_code, 429)
            with self.app.app_context():
                user = db.session.get(User, self.user_id)
                self.assertEqual(user.failed_login_attempts, 5)
                self.assertEqual(user.locked_until, now + timedelta(minutes=15))
            clock.now.return_value = (now + timedelta(minutes=14, seconds=59)).replace(tzinfo=timezone.utc)
            self.assertEqual(self.login().status_code, 429)
            clock.now.return_value = (now + timedelta(minutes=15)).replace(tzinfo=timezone.utc)
            self.assertEqual(self.login().status_code, 302)
        with self.app.app_context():
            user = db.session.get(User, self.user_id)
            self.assertEqual(user.failed_login_attempts, 0)
            self.assertIsNone(user.locked_until)

    def test_tc_sec_05_success_resets_consecutive_failures(self):
        for _ in range(4):
            self.login(password="wrong-password")
        self.assertEqual(self.login().status_code, 302)
        self.client.post("/logout")
        self.assertEqual(self.login(password="wrong-password").status_code, 401)
        with self.app.app_context():
            self.assertEqual(db.session.get(User, self.user_id).failed_login_attempts, 1)

    def test_tc_sec_05_expired_lock_starts_a_new_failure_sequence(self):
        with self.app.app_context():
            user = db.session.get(User, self.user_id)
            user.failed_login_attempts = 5
            user.locked_until = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(seconds=1)
            db.session.commit()
        self.assertEqual(self.login(password="wrong-password").status_code, 401)
        with self.app.app_context():
            user = db.session.get(User, self.user_id)
            self.assertEqual(user.failed_login_attempts, 1)
            self.assertIsNone(user.locked_until)

    def test_tc_sec_05_parallel_failures_are_not_lost(self):
        def fail_login(_):
            with self.app.test_client() as client:
                return self.login(password="wrong-password", client=client).status_code
        with ThreadPoolExecutor(max_workers=5) as executor:
            statuses = list(executor.map(fail_login, range(5)))
        self.assertTrue(all(status in (401, 429) for status in statuses))
        self.assertEqual(self.login().status_code, 429)
        with self.app.app_context():
            self.assertEqual(db.session.get(User, self.user_id).failed_login_attempts, 5)

    def test_tc_sec_04_invalid_registration_does_not_create_accounts(self):
        payloads = [
            {"email": "a@@example.com"}, {"email": "a b@example.com"},
            {"email": ".a@example.com"}, {"email": "a.@example.com"},
            {"email": "' OR 1=1 --"}, {"email": "a@example.com\nBcc:x@y.com"},
            {"name": "<script>alert(1)</script>"}, {"name": "x" * 101},
            {"password": "short"}, {"password": "x" * 129},
        ]
        for changes in payloads:
            with self.subTest(changes=changes):
                data = dict(name="New Driver", email="new@example.com", password="Test-password-123")
                data.update(changes)
                response = self.client.post("/register", data=data)
                self.assertNotEqual(response.status_code, 500)
                with self.app.app_context():
                    self.assertEqual(User.query.count(), 3)

    def test_registration_normalizes_email_and_ignores_role(self):
        self.client.post("/register", data={
            "name": "New Driver", "email": " NEW@Example.COM ",
            "password": "Test-password-123", "role": "admin",
        })
        with self.app.app_context():
            self.assertEqual(User.query.filter_by(email="new@example.com").one().role, "user")

    def test_tc_sec_04_sql_payload_cannot_authenticate_or_change_data(self):
        self.assertEqual(self.login(email="' OR 1=1 --").status_code, 401)
        with self.client.session_transaction() as session:
            self.assertNotIn("user_id", session)
        self.login()
        response = self.client.get("/parking", query_string={"search": "' OR 1=1 --"})
        self.assertEqual(response.status_code, 200)
        with self.app.app_context():
            self.assertEqual(ParkingSlot.query.count(), 10)

    def test_tc_sec_04_vehicle_and_time_validation(self):
        self.login()
        start = datetime.now() + timedelta(hours=1)
        data = dict(vehicle_number="KA01AB1234", start_time=start.strftime("%Y-%m-%dT%H:%M"),
                    end_time=(start + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M"))
        for changes in [
            {"vehicle_number": "<script>alert(1)</script>"},
            {"vehicle_number": "' OR 1=1 --"}, {"vehicle_number": "x" * 21},
            {"start_time": "invalid"}, {"end_time": data["start_time"]},
            {"end_time": (start + timedelta(hours=25)).strftime("%Y-%m-%dT%H:%M")},
        ]:
            with self.subTest(changes=changes):
                self.client.post(f"/reserve/{self.slot_id}", data=data | changes)
                with self.app.app_context():
                    self.assertEqual(Reservation.query.count(), 0)

    def test_tc_sec_04_admin_rejects_invalid_slot_fields_and_nonfinite_rates(self):
        self.login("admin@example.com")
        data = dict(slot_number="C-01", zone="Zone C", vehicle_type="four-wheeler", hourly_rate="25")
        for changes in [
            {"hourly_rate": rate} for rate in ("NaN", "Infinity", "-1", "0", "0.001", "1000001", "bad")
        ] + [{"zone": "<script>bad</script>"}, {"zone": "x" * 51},
             {"slot_number": "x" * 21}, {"vehicle_type": "truck"}]:
            for route in ("/admin/slots/add", f"/admin/slots/{self.slot_id}/edit"):
                with self.subTest(changes=changes, route=route):
                    self.client.post(route, data=data | changes)
                    with self.app.app_context():
                        self.assertEqual(ParkingSlot.query.count(), 10)
                        self.assertEqual(db.session.get(ParkingSlot, self.slot_id).hourly_rate, 30)

    def test_tc_sec_04_output_escapes_legacy_stored_markup(self):
        with self.app.app_context():
            db.session.get(User, self.user_id).name = '<script>alert("xss")</script>'
            db.session.commit()
        self.login()
        response = self.client.get("/dashboard")
        self.assertNotIn(b'<script>alert("xss")</script>', response.data)
        self.assertIn(b"&lt;script&gt;", response.data)

    def test_tc_sec_04_csrf_rejects_missing_and_invalid_tokens(self):
        self.app.config["WTF_CSRF_ENABLED"] = True
        for route in ("/login", "/register", "/logout", "/admin/slots/add", "/payments/1"):
            with self.subTest(route=route):
                self.assertEqual(self.client.post(route).status_code, 400)
                self.assertEqual(self.client.post(route, data={"csrf_token": "forged"}).status_code, 400)
        page = self.client.get("/login")
        token = re.search(rb'name="csrf_token" value="([^"]+)"', page.data).group(1).decode()
        self.assertEqual(self.client.post("/login", data={
            "email": "driver@example.com", "password": "Test-password-123", "csrf_token": token,
        }).status_code, 302)
        self.assertEqual(self.client.get("/logout").status_code, 405)

    def test_tc_pay_01_receipt_persists_amount_id_and_timestamp(self):
        reservation_id, payment_id = self.checkout()
        with self.app.app_context():
            self.assertEqual(Payment.query.one().status, "pending")
            self.assertIsNone(Payment.query.one().paid_at)
        self.client.post(f"/payments/{payment_id}", data={"amount": "0.01", "status": "paid"})
        with self.app.app_context():
            payment = db.session.get(Payment, payment_id)
            self.assertEqual(payment.amount, 60)
            self.assertEqual(payment.status, "paid")
            self.assertIsNotNone(payment.paid_at)
            timestamp = payment.paid_at
            self.assertEqual(db.session.get(Reservation, reservation_id).status, "completed")
        receipt = self.client.get(f"/payments/{payment_id}/receipt")
        self.assertEqual(receipt.status_code, 200)
        self.assertIn(f"VPS-{payment_id:06d}".encode(), receipt.data)
        self.assertIn(b"60.00", receipt.data)
        self.assertIn(timestamp.strftime("%d %b %Y, %I:%M %p").encode(), receipt.data)
        self.client.post(f"/payments/{payment_id}")
        self.client.post(f"/reservation/{reservation_id}/checkout")
        with self.app.app_context():
            self.assertEqual(Payment.query.count(), 1)
            self.assertEqual(Payment.query.one().paid_at, timestamp)
        self.client.post("/logout")
        self.login()
        self.assertEqual(self.client.get(f"/payments/{payment_id}/receipt").status_code, 200)

    def test_tc_pay_01_payment_and_receipt_are_private(self):
        _, payment_id = self.checkout()
        self.assertEqual(self.client.get(f"/payments/{payment_id}/receipt").status_code, 302)
        self.client.post("/logout")
        self.login("other@example.com")
        for method, suffix in (("GET", ""), ("POST", ""), ("GET", "/receipt")):
            self.assertEqual(self.client.open(f"/payments/{payment_id}{suffix}", method=method).status_code, 404)
        self.client.post("/logout")
        self.login()
        self.client.post(f"/payments/{payment_id}")
        self.client.post("/logout")
        self.login("admin@example.com")
        self.assertEqual(self.client.get(f"/payments/{payment_id}/receipt").status_code, 200)
        with self.app.app_context():
            db.session.get(User, self.admin_id).role = "user"
            db.session.commit()
        self.assertEqual(self.client.get(f"/payments/{payment_id}/receipt").status_code, 404)

    def test_tc_pay_01_invalid_payment_state_is_not_confirmed(self):
        _, payment_id = self.checkout()
        with self.app.app_context():
            db.session.get(Payment, payment_id).status = "cancelled"
            db.session.commit()
        self.assertEqual(self.client.post(f"/payments/{payment_id}").status_code, 409)

    def test_tc_pay_01_parallel_checkout_and_payment_create_one_transaction(self):
        from app.routes import fee_quote

        reservation_id = self.parked_visit()
        barrier = Barrier(2)

        def quote_together(*args, **kwargs):
            quote = fee_quote(*args, **kwargs)
            barrier.wait(timeout=10)
            return quote

        def post_as_owner(route):
            with self.app.test_client() as client:
                with client.session_transaction() as session:
                    session["user_id"] = self.user_id
                    session["user_name"] = "Driver"
                return client.post(route).status_code

        route = f"/reservation/{reservation_id}/checkout"
        with patch("app.routes.fee_quote", side_effect=quote_together):
            with ThreadPoolExecutor(max_workers=2) as executor:
                statuses = list(executor.map(post_as_owner, [route, route]))
        self.assertEqual(sorted(statuses), [302, 409])
        with self.app.app_context():
            payment_id = Payment.query.one().id
        route = f"/payments/{payment_id}"
        with ThreadPoolExecutor(max_workers=2) as executor:
            statuses = list(executor.map(post_as_owner, [route, route]))
        self.assertTrue(all(status in (302, 409) for status in statuses))
        with self.app.app_context():
            payment = Payment.query.one()
            self.assertEqual(payment.status, "paid")
            self.assertEqual(payment.amount, 60)
            self.assertIsNotNone(payment.paid_at)

    def test_tc_sec_04_invalid_search_filters_return_bad_request(self):
        self.login()
        for query in ({"search": "x" * 101}, {"zone": "x" * 51},
                      {"vehicle_type": "truck"}, {"availability": "invalid"}):
            with self.subTest(query=query):
                self.assertEqual(self.client.get("/parking", query_string=query).status_code, 400)

    def test_existing_database_gets_lockout_columns_without_data_loss(self):
        with sqlite3.connect(self.database) as connection:
            connection.execute("ALTER TABLE user DROP COLUMN locked_until")
            connection.execute("ALTER TABLE user DROP COLUMN failed_login_attempts")
        connection.close()
        upgraded = create_app(self.app.config)
        with upgraded.app_context():
            self.assertEqual(User.query.count(), 3)
            self.assertEqual(db.session.get(User, self.user_id).failed_login_attempts, 0)
            self.assertIsNone(db.session.get(User, self.user_id).locked_until)
            db.session.remove()
            db.engine.dispose()
