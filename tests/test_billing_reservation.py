import re
from datetime import timedelta

from app import db
from app.models import ParkingSlot, Payment, Reservation, User, VehicleLog, VehicleRate
from app.timeutils import local_time, utcnow
from tests.helpers import BaseCase, PASSWORD

FMT = "%Y-%m-%dT%H:%M"


class ReservationBillingCases(BaseCase):
    def window(self):
        with self.app.app_context():
            start = local_time(utcnow()).replace(second=0, microsecond=0)
        return start.strftime(FMT), (start + timedelta(hours=1)).strftime(FMT)

    def reserve(self, slot_id=None, vehicle="KA01AB1234", client=None):
        s, e = self.window()
        return (client or self.client).post(
            f"/reserve/{slot_id or self.slot_id}",
            data={"vehicle_number": vehicle, "start_time": s, "end_time": e},
        )

    def reservation_id(self):
        with self.app.app_context():
            return Reservation.query.filter_by(user_id=self.user_id).first().id

    def full_visit(self):
        self.login()
        self.reserve()
        rid = self.reservation_id()
        self.client.post(f"/reservation/{rid}/entry")
        self.client.post(f"/reservation/{rid}/exit")
        return rid

    def quote_token(self, rid):
        html = self.client.get(f"/reservation/{rid}/checkout").get_data(as_text=True)
        m = re.search(r'name="quote_token"[^>]*value="([^"]+)"', html) or re.search(
            r'value="([^"]+)"[^>]*name="quote_token"', html
        )
        self.assertIsNotNone(m, "quote_token input not found in checkout page")
        return m.group(1)

    def test_reserve_requires_login(self):
        self.assertEqual(self.client.post(f"/reserve/{self.slot_id}").status_code, 302)

    def test_tc_slot_04_reserve_available_slot(self):
        self.login()
        r = self.reserve()
        self.assertEqual(r.status_code, 302)
        with self.app.app_context():
            res = Reservation.query.filter_by(user_id=self.user_id).one()
            self.assertEqual(res.slot_id, self.slot_id)
            self.assertEqual(res.vehicle_number, "KA01AB1234")
            self.assertEqual(res.status, "reserved")

    def test_tc_slot_03_double_booking_rejected(self):
        self.login()
        self.reserve()
        other = self.app.test_client()
        with self.app.app_context():
            u = User(name="Other", email="other@example.com")
            u.set_password(PASSWORD)
            db.session.add(u)
            db.session.commit()
        self.login(email="other@example.com", client=other)
        r = self.reserve(vehicle="KA02CD5678", client=other)
        self.assertGreaterEqual(r.status_code, 400)
        with self.app.app_context():
            self.assertEqual(Reservation.query.count(), 1)

    def test_reserve_unknown_slot_404(self):
        self.login()
        self.assertEqual(self.reserve(slot_id=999999).status_code, 404)

    def test_tc_track_01_entry_logged_and_slot_occupied(self):
        self.login()
        self.reserve()
        rid = self.reservation_id()
        r = self.client.post(f"/reservation/{rid}/entry")
        self.assertEqual(r.status_code, 302)
        with self.app.app_context():
            self.assertEqual(VehicleLog.query.filter_by(reservation_id=rid).count(), 1)
            self.assertTrue(db.session.get(ParkingSlot, self.slot_id).is_occupied)

    def test_tc_track_02_exit_redirects_to_checkout(self):
        self.login()
        self.reserve()
        rid = self.reservation_id()
        self.client.post(f"/reservation/{rid}/entry")
        r = self.client.post(f"/reservation/{rid}/exit")
        self.assertEqual(r.status_code, 302)
        self.assertIn("checkout", r.headers["Location"])

    def test_tc_bill_02_checkout_shows_quote(self):
        rid = self.full_visit()
        r = self.client.get(f"/reservation/{rid}/checkout")
        self.assertEqual(r.status_code, 200)

    def test_tc_bill_01_checkout_creates_payment_with_fee(self):
        rid = self.full_visit()
        r = self.client.post(
            f"/reservation/{rid}/checkout", data={"quote_token": self.quote_token(rid)}
        )
        self.assertEqual(r.status_code, 302)
        with self.app.app_context():
            p = Payment.query.filter_by(reservation_id=rid).one()
            self.assertGreaterEqual(p.amount_cents, 0)
            res = db.session.get(Reservation, rid)
            self.assertEqual(p.amount_cents, res.fee_cents)

    def test_checkout_rejects_bad_quote_token(self):
        rid = self.full_visit()
        r = self.client.post(f"/reservation/{rid}/checkout", data={"quote_token": "bad"})
        self.assertNotEqual(r.status_code, 200 if False else 302)

    def test_tc_pay_01_payment_and_receipt(self):
        rid = self.full_visit()
        r = self.client.post(
            f"/reservation/{rid}/checkout", data={"quote_token": self.quote_token(rid)}
        )
        pay_url = r.headers["Location"]
        self.assertEqual(self.client.get(pay_url).status_code, 200)
        self.client.post(pay_url)  # simulated payment; add form fields if yours need any
        with self.app.app_context():
            p = Payment.query.filter_by(reservation_id=rid).one()
            self.assertNotEqual(p.status, "pending")
            self.assertIsNotNone(p.paid_at)
            pid = p.id
        self.assertEqual(self.client.get(f"/payments/{pid}/receipt").status_code, 200)

    def test_payment_not_visible_to_other_user(self):
        rid = self.full_visit()
        r = self.client.post(
            f"/reservation/{rid}/checkout", data={"quote_token": self.quote_token(rid)}
        )
        pay_url = r.headers["Location"]
        other = self.app.test_client()
        self.login(email="admin@example.com", client=other)
        self.assertEqual(other.get(pay_url).status_code, 404)

    def test_tc_admin_02_rate_update_applies(self):
        self.login(email="admin@example.com")
        with self.app.app_context():
            vtype = db.session.get(ParkingSlot, self.slot_id).vehicle_type
        r = self.client.post(
            "/admin/rates/update", data={"vehicle_type": vtype, "hourly_rate": "55"}
        )
        self.assertEqual(r.status_code, 302)
        with self.app.app_context():
            rate = db.session.get(VehicleRate, vtype)
            self.assertEqual(rate.cents_per_hour, 5500)

    def test_tc_admin_02_invalid_rate_rejected(self):
        self.login(email="admin@example.com")
        r = self.client.post(
            "/admin/rates/update", data={"vehicle_type": "four-wheeler", "hourly_rate": "-5"}
        )
        self.assertGreaterEqual(r.status_code, 400)

    def test_tc_admin_01_slot_add_edit_delete(self):
        self.login(email="admin@example.com")
        r = self.client.post(
            "/admin/slots/add",
            data={"slot_number": "T-901", "zone": "Zone T", "vehicle_type": "four-wheeler"},
        )
        self.assertEqual(r.status_code, 302)
        with self.app.app_context():
            slot = ParkingSlot.query.filter_by(slot_number="T-901").one()
            sid = slot.id
        r = self.client.post(
            f"/admin/slots/{sid}/edit",
            data={"slot_number": "T-902", "zone": "Zone T", "vehicle_type": "four-wheeler"},
        )
        self.assertEqual(r.status_code, 302)
        with self.app.app_context():
            self.assertEqual(db.session.get(ParkingSlot, sid).slot_number, "T-902")
        r = self.client.post(f"/admin/slots/{sid}/delete")
        self.assertEqual(r.status_code, 302)
        with self.app.app_context():
            self.assertIsNone(db.session.get(ParkingSlot, sid))

    def test_tc_sec_02_user_cannot_change_rate(self):
        self.login()
        r = self.client.post(
            "/admin/rates/update", data={"vehicle_type": "four-wheeler", "hourly_rate": "1"}
        )
        self.assertNotEqual(r.status_code, 302 if False else 200)
        with self.app.app_context():
            rate = db.session.get(VehicleRate, "four-wheeler")
            self.assertTrue(rate is None or rate.cents_per_hour != 100)
