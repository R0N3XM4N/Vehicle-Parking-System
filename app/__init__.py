
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from pathlib import Path

db = SQLAlchemy()


def create_app():
    app = Flask(__name__)

    app.config["SECRET_KEY"] = "dev-only-change-before-deployment"
    app.config["SQLALCHEMY_DATABASE_URI"] = (
        "sqlite:///" + str(Path(app.instance_path) / "parking.db")
    )
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    Path(app.instance_path).mkdir(parents=True, exist_ok=True)
    db.init_app(app)

    from app.routes import main
    app.register_blueprint(main)

    with app.app_context():
        from app import models
        db.create_all()

        from app.models import ParkingSlot

        if ParkingSlot.query.count() == 0:
            for number in range(1, 11):
                db.session.add(
                    ParkingSlot(
                        slot_number=f"A-{number:02d}",
                        hourly_rate=30.0
                    )
                )
            db.session.commit()

    return app
