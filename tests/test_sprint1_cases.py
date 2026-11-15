from app import db
from app.models import User
from tests.helpers import BaseCase, PASSWORD


class Sprint1Cases(BaseCase):
    def test_tc_auth_02_valid_login_reaches_dashboard(self):
        self.login()
        self.assertEqual(self.client.get("/dashboard").status_code, 200)

    def test_tc_auth_02_invalid_password_rejected(self):
        self.login(password="wrong-password")
        r = self.client.get("/dashboard")
        self.assertEqual(r.status_code, 302)

    def test_tc_auth_02_unknown_email_rejected(self):
        self.login(email="nobody@example.com")
        self.assertEqual(self.client.get("/dashboard").status_code, 302)

    def test_tc_auth_03_logout_blocks_protected_route(self):
        self.login()
        self.client.post("/logout")
        self.assertEqual(self.client.get("/dashboard").status_code, 302)

    def test_tc_auth_03_protected_route_without_login(self):
        for path in ("/dashboard", "/parking", "/my-reservations"):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 302)

    def test_tc_slot_01_slot_page_loads_when_logged_in(self):
        self.login()
        self.assertEqual(self.client.get("/parking").status_code, 200)

    def test_tc_sec_01_password_is_hashed(self):
        with self.app.app_context():
            u = db.session.get(User, self.user_id)
            self.assertNotEqual(u.password_hash, PASSWORD)
            self.assertNotIn(PASSWORD, u.password_hash)
            self.assertGreater(len(u.password_hash), 30)

    def test_tc_sec_01_same_password_gets_different_hash(self):
        with self.app.app_context():
            a = db.session.get(User, self.user_id)
            b = db.session.get(User, self.admin_id)
            self.assertNotEqual(a.password_hash, b.password_hash)
