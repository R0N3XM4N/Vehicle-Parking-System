import tempfile
import unittest
from pathlib import Path

from app import create_app, db
from app.models import ParkingSlot, User

PASSWORD = "Test-password-123"


class BaseCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.database = Path(self.temp.name) / "parking.db"
        self.app = create_app(
            {
                "TESTING": True,
                "BCRYPT_ROUNDS": 4,
                "SECRET_KEY": "isolated-test-secret",
                "SQLALCHEMY_DATABASE_URI": f"sqlite:///{self.database}",
                "WTF_CSRF_ENABLED": False,
            }
        )
        self.addCleanup(self.dispose)
        self.client = self.app.test_client()
        with self.app.app_context():
            user = User(name="Driver", email="driver@example.com")
            admin = User(name="Administrator", email="admin@example.com", role="admin")
            for account in (user, admin):
                account.set_password(PASSWORD)
            db.session.add_all([user, admin])
            db.session.commit()
            self.user_id, self.admin_id = user.id, admin.id
            self.slot_id = ParkingSlot.query.first().id

    def dispose(self):
        with self.app.app_context():
            db.session.remove()
            db.engine.dispose()

    def login(self, email="driver@example.com", password=PASSWORD, client=None):
        return (client or self.client).post(
            "/login", data={"email": email, "password": password}
        )
