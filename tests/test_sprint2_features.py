from app import db
from app.models import User
from tests.helpers import BaseCase


class FeatureCases(BaseCase):
    def test_tc_sec_02_user_blocked_from_admin_pages(self):
        self.login()
        for path in ("/admin", "/admin/reports", "/admin/audit"):
            with self.subTest(path=path):
                self.assertNotEqual(self.client.get(path).status_code, 200)

    def test_tc_sec_02_user_cannot_add_slot(self):
        self.login()
        r = self.client.post("/admin/slots/add", data={"slot_number": "X1"})
        self.assertNotEqual(r.status_code, 200)

    def test_tc_admin_pages_load_for_admin(self):
        self.login(email="admin@example.com")
        for path in ("/admin", "/admin/reports", "/admin/audit"):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 200)

    def test_tc_sec_05_lockout_after_five_failures(self):
        for _ in range(5):
            self.login(password="bad-password")
        with self.app.app_context():
            u = db.session.get(User, self.user_id)
            self.assertIsNotNone(u.locked_until)
        self.login()
        self.assertEqual(self.client.get("/dashboard").status_code, 302)

    def test_tc_sec_05_four_failures_do_not_lock(self):
        for _ in range(4):
            self.login(password="bad-password")
        with self.app.app_context():
            self.assertIsNone(db.session.get(User, self.user_id).locked_until)
        self.login()
        self.assertEqual(self.client.get("/dashboard").status_code, 200)
