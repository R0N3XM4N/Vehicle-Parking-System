
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from pathlib import Path
from sqlalchemy import inspect, text
import os

db = SQLAlchemy()


def _add_missing_columns():
    """Apply the small SQLite schema upgrades needed by existing installs."""
    upgrades = {
        "parking_slot": {
            "zone": "VARCHAR(50) DEFAULT 'Zone A'",
            "vehicle_type": "VARCHAR(20) DEFAULT 'four-wheeler'",
        },
        "reservation": {
            "scheduled_end_time": "DATETIME",
        },
        "payment": {
            "paid_at": "DATETIME",
        },
    }

    schema = inspect(db.engine)
    with db.engine.begin() as connection:
        for table_name, columns in upgrades.items():
            if table_name not in schema.get_table_names():
                continue
            existing = {
                column["name"] for column in schema.get_columns(table_name)
            }
            for column_name, definition in columns.items():
                if column_name not in existing:
                    connection.execute(
                        text(
                            f"ALTER TABLE {table_name} "
                            f"ADD COLUMN {column_name} {definition}"
                        )
                    )

        connection.execute(
            text(
                "UPDATE parking_slot SET zone = 'Zone A' "
                "WHERE zone IS NULL OR zone = ''"
            )
        )
        connection.execute(
            text(
                "UPDATE parking_slot SET vehicle_type = 'four-wheeler' "
                "WHERE vehicle_type IS NULL OR vehicle_type = ''"
            )
        )
        connection.execute(
            text(
                "UPDATE reservation "
                "SET scheduled_end_time = datetime(start_time, '+1 hour') "
                "WHERE scheduled_end_time IS NULL"
            )
        )


def create_app(test_config=None):
    app = Flask(__name__, static_folder="../static")

    app.config["SECRET_KEY"] = "dev-only-change-before-deployment"
    app.config["SQLALCHEMY_DATABASE_URI"] = (
        "sqlite:///" + str(Path(app.instance_path) / "parking.db")
    )
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    if test_config:
        app.config.update(test_config)

    Path(app.instance_path).mkdir(parents=True, exist_ok=True)
    db.init_app(app)

    from app.routes import main
    app.register_blueprint(main)

    with app.app_context():
        from app import models
        db.create_all()
        _add_missing_columns()

        from app.models import ParkingSlot

        if ParkingSlot.query.count() == 0:
            for number in range(1, 11):
                db.session.add(
                    ParkingSlot(
                        slot_number=f"A-{number:02d}",
                        zone="Zone A" if number <= 5 else "Zone B",
                        vehicle_type=(
                            "two-wheeler" if number % 3 == 0
                            else "four-wheeler"
                        ),
                        hourly_rate=30.0
                    )
                )
            db.session.commit()

        admin_email = os.environ.get("VPS_ADMIN_EMAIL", "").strip().lower()
        admin_password = os.environ.get("VPS_ADMIN_PASSWORD", "")
        if admin_email and admin_password:
            from app.models import User

            admin = User.query.filter_by(email=admin_email).first()
            if admin is None:
                admin = User(
                    name="System Administrator",
                    email=admin_email,
                    role="admin",
                )
                admin.set_password(admin_password)
                db.session.add(admin)
            else:
                admin.role = "admin"
            db.session.commit()

    return app
