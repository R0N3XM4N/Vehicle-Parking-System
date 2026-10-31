import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from app import create_app, db
from app.models import ParkingSlot, Payment, Reservation, User, VehicleLog


class FrontendIssueTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        database_path = Path(self.temp_dir.name) / "test.db"
        self.app = create_app(
            {
                "TESTING": True,
                "SECRET_KEY": "test-secret",
                "SQLALCHEMY_DATABASE_URI": f"sqlite:///{database_path}",
            }
        )
        self.client = self.app.test_client()

        with self.app.app_context():
            Payment.query.delete()
            VehicleLog.query.delete()
            Reservation.query.delete()
            ParkingSlot.query.delete()
            User.query.delete()

            self.user = User(name="Test User", email="user@example.com")
            self.user.set_password("password123")
            self.admin = User(
                name="Test Admin", email="admin@example.com", role="admin"
            )
            self.admin.set_password("password123")
            self.slot = ParkingSlot(
                slot_number="A-01",
                zone="Zone A",
                vehicle_type="four-wheeler",
                hourly_rate=30,
            )
            db.session.add_all([self.user, self.admin, self.slot])
            db.session.commit()
            self.user_id = self.user.id
            self.admin_id = self.admin.id
            self.slot_id = self.slot.id

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.engine.dispose()
        self.temp_dir.cleanup()

    def login(self, email="user@example.com"):
        return self.client.post(
            "/login",
            data={"email": email, "password": "password123"},
            follow_redirects=True,
        )

    def test_auth_pages_and_responsive_stylesheet_render(self):
        self.assertEqual(self.client.get("/").status_code, 200)
        self.assertEqual(self.client.get("/login").status_code, 200)
        self.assertEqual(self.client.get("/register").status_code, 200)
        stylesheet = self.client.get("/static/style.css")
        self.assertEqual(stylesheet.status_code, 200)
        self.assertIn(b"@media (max-width: 720px)", stylesheet.data)
        self.assertIn(b"@media (max-width: 460px)", stylesheet.data)
        stylesheet.close()

    def test_slot_filters_and_time_window_reservation(self):
        self.login()
        response = self.client.get(
            "/parking?zone=Zone+A&vehicle_type=four-wheeler&availability=available"
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"A-01", response.data)

        start = datetime.now().replace(second=0, microsecond=0) + timedelta(hours=1)
        end = start + timedelta(hours=2)
        reservation_data = {
            "vehicle_number": "KA01AB1234",
            "start_time": start.strftime("%Y-%m-%dT%H:%M"),
            "end_time": end.strftime("%Y-%m-%dT%H:%M"),
        }
        response = self.client.post(
            f"/reserve/{self.slot_id}",
            data=reservation_data,
            follow_redirects=True,
        )
        self.assertIn(b"reserved successfully", response.data)

        conflict = self.client.post(
            f"/reserve/{self.slot_id}",
            data=reservation_data,
            follow_redirects=True,
        )
        self.assertIn(b"already reserved during that time window", conflict.data)

    def test_checkout_payment_receipt_and_report_totals(self):
        self.login()
        with self.app.app_context():
            reservation = Reservation(
                user_id=self.user_id,
                slot_id=self.slot_id,
                vehicle_number="KA01AB1234",
                start_time=datetime.now() - timedelta(hours=2),
                scheduled_end_time=datetime.now() + timedelta(hours=1),
                status="parked",
            )
            slot = db.session.get(ParkingSlot, self.slot_id)
            slot.is_occupied = True
            db.session.add(reservation)
            db.session.flush()
            db.session.add(
                VehicleLog(
                    reservation_id=reservation.id,
                    entry_time=datetime.now() - timedelta(hours=1, minutes=5),
                )
            )
            db.session.commit()
            reservation_id = reservation.id

        preview = self.client.get(f"/reservation/{reservation_id}/checkout")
        self.assertEqual(preview.status_code, 200)
        self.assertIn(b"Review your parking fee", preview.data)
        self.assertIn("₹60.00".encode(), preview.data)

        payment_page = self.client.post(
            f"/reservation/{reservation_id}/checkout", follow_redirects=True
        )
        self.assertIn(b"Complete payment", payment_page.data)
        with self.app.app_context():
            payment_id = Payment.query.one().id

        receipt = self.client.post(
            f"/payments/{payment_id}", follow_redirects=True
        )
        self.assertIn(b"Payment successful", receipt.data)
        self.assertIn(f"VPS-{payment_id:06d}".encode(), receipt.data)

        self.client.get("/logout")
        self.login("admin@example.com")
        report = self.client.get("/admin/reports?period=daily")
        self.assertEqual(report.status_code, 200)
        self.assertIn("₹60.00".encode(), report.data)

    def test_admin_slot_crud_and_role_protection(self):
        self.login()
        self.assertEqual(self.client.get("/admin").status_code, 403)
        self.client.get("/logout")
        self.login("admin@example.com")

        added = self.client.post(
            "/admin/slots/add",
            data={
                "slot_number": "B-01",
                "zone": "Zone B",
                "vehicle_type": "two-wheeler",
                "hourly_rate": "20",
            },
            follow_redirects=True,
        )
        self.assertIn(b"Slot B-01 added", added.data)

        with self.app.app_context():
            slot_id = ParkingSlot.query.filter_by(slot_number="B-01").one().id
        edited = self.client.post(
            f"/admin/slots/{slot_id}/edit",
            data={
                "slot_number": "B-02",
                "zone": "Zone B",
                "vehicle_type": "two-wheeler",
                "hourly_rate": "25",
            },
            follow_redirects=True,
        )
        self.assertIn(b"Slot B-02 updated", edited.data)

        deleted = self.client.post(
            f"/admin/slots/{slot_id}/delete", follow_redirects=True
        )
        self.assertIn(b"Slot B-02 removed", deleted.data)


if __name__ == "__main__":
    unittest.main()
