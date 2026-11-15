"""Existing prototype history survives upgrade; failed DDL is transactional."""

from datetime import datetime
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text

from app import create_app, db


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.app = create_app(
            {
                "TESTING": True,
                "AUTO_MIGRATE": False,
                "SQLALCHEMY_DATABASE_URI": f"sqlite:///{Path(self.temp.name)/'legacy.db'}",
            }
        )
        self.addCleanup(self.dispose)
        with self.app.app_context():
            self.upgrade("0001")
            with db.engine.begin() as connection:
                connection.execute(
                    text(
                        "INSERT INTO user (id,name,email,password_hash,role) VALUES (1,'Legacy','legacy@example.com','synthetic-hash','user')"
                    )
                )
                connection.execute(
                    text(
                        "INSERT INTO parking_slot (id,slot_number,zone,vehicle_type,is_occupied,hourly_rate) VALUES (1,'A-01','Zone A','four-wheeler',1,40),(2,'A-02','Zone A','four-wheeler',0,60)"
                    )
                )
                connection.execute(
                    text(
                        "INSERT INTO reservation (id,user_id,slot_id,vehicle_number,start_time,scheduled_end_time,status,fee) VALUES (1,1,1,'KA01AB1234','2026-11-15 09:00:00','2026-11-15 11:00:00','parked',80)"
                    )
                )
                connection.execute(
                    text(
                        "INSERT INTO vehicle_log (id,reservation_id,entry_time) VALUES (1,1,'2026-11-15 09:00:00')"
                    )
                )
                connection.execute(
                    text(
                        "INSERT INTO payment (id,reservation_id,amount,status,created_at) VALUES (1,1,80,'pending','2026-11-15 10:00:00')"
                    )
                )

    def upgrade(self, revision="head"):
        config = Config()
        config.set_main_option(
            "script_location", str(Path(__file__).resolve().parents[1] / "migrations")
        )
        with db.engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, revision)

    def dispose(self):
        with self.app.app_context():
            db.session.remove()
            db.engine.dispose()

    def test_upgrade_preserves_money_rates_users_and_converts_declared_timezone(self):
        with self.app.app_context(), patch.dict(
            os.environ, {"VPS_LEGACY_TIMEZONE": "Asia/Kolkata"}
        ):
            self.upgrade()
            with db.engine.connect() as connection:
                self.assertEqual(
                    connection.execute(text("SELECT name FROM user")).scalar(), "Legacy"
                )
                self.assertEqual(
                    connection.execute(
                        text("SELECT amount_cents FROM payment")
                    ).scalar(),
                    8000,
                )
                self.assertEqual(
                    connection.execute(
                        text("SELECT rate_cents FROM reservation")
                    ).scalar(),
                    4000,
                )
                stamp = connection.execute(
                    text("SELECT entry_time FROM vehicle_log")
                ).scalar()
                self.assertEqual(
                    datetime.fromisoformat(stamp), datetime(2026, 11, 15, 3, 30)
                )
                self.assertEqual(
                    connection.execute(
                        text("SELECT COUNT(*) FROM parking_slot WHERE hourly_rate=40")
                    ).scalar(),
                    2,
                )
                self.assertEqual(
                    connection.execute(
                        text("SELECT version_num FROM alembic_version")
                    ).scalar(),
                    "0002",
                )
            self.upgrade()  # Already-applied data conversion is never repeated.
            with db.engine.connect() as connection:
                stamp = connection.execute(
                    text("SELECT entry_time FROM vehicle_log")
                ).scalar()
                self.assertEqual(
                    datetime.fromisoformat(stamp), datetime(2026, 11, 15, 3, 30)
                )

    def test_duplicate_history_refuses_upgrade_without_partial_columns_or_deletion(
        self,
    ):
        with self.app.app_context(), patch.dict(
            os.environ, {"VPS_LEGACY_TIMEZONE": "UTC"}
        ):
            with db.engine.begin() as connection:
                connection.execute(
                    text(
                        "INSERT INTO payment (id,reservation_id,amount,status,created_at) VALUES (2,1,80,'pending','2026-11-15 10:00:00')"
                    )
                )
            with self.assertRaisesRegex(RuntimeError, "duplicate"):
                self.upgrade()
            self.assertNotIn(
                "rate_cents",
                {
                    column["name"]
                    for column in inspect(db.engine).get_columns("reservation")
                },
            )
            with db.engine.connect() as connection:
                self.assertEqual(
                    connection.execute(text("SELECT COUNT(*) FROM payment")).scalar(), 2
                )
                self.assertEqual(
                    connection.execute(
                        text("SELECT version_num FROM alembic_version")
                    ).scalar(),
                    "0001",
                )
