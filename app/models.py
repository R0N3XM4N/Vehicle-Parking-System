from datetime import datetime

from werkzeug.security import check_password_hash
from flask import current_app, has_app_context
from app import db
import bcrypt


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(256), nullable=False)
    role = db.Column(db.String(20), nullable=False, default="user")

    failed_login_attempts = db.Column(db.Integer, nullable=False, default=0)
    locked_until = db.Column(db.DateTime, nullable=True)

    reservations = db.relationship("Reservation", backref="user", lazy=True)

    def set_password(self, password):
        rounds = (
            current_app.config.get("BCRYPT_ROUNDS", 12) if has_app_context() else 12
        )
        self.password_hash = bcrypt.hashpw(
            password.encode(), bcrypt.gensalt(rounds)
        ).decode()

    def check_password(self, password):
        if self.password_hash.startswith(("$2a$", "$2b$", "$2y$")):
            return len(password.encode()) <= 72 and bcrypt.checkpw(
                password.encode(), self.password_hash.encode()
            )
        return check_password_hash(self.password_hash, password)


class ParkingSlot(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    slot_number = db.Column(db.String(20), unique=True, nullable=False)
    zone = db.Column(db.String(50), nullable=False, default="Zone A")
    vehicle_type = db.Column(db.String(20), nullable=False, default="four-wheeler")
    is_occupied = db.Column(db.Boolean, nullable=False, default=False)
    hourly_rate = db.Column(db.Float, nullable=False, default=30.0)

    reservations = db.relationship("Reservation", backref="parking_slot", lazy=True)


class Reservation(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    slot_id = db.Column(db.Integer, db.ForeignKey("parking_slot.id"), nullable=False)
    vehicle_number = db.Column(db.String(20), nullable=False)
    start_time = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    scheduled_end_time = db.Column(db.DateTime, nullable=True)
    end_time = db.Column(db.DateTime, nullable=True)
    status = db.Column(db.String(20), nullable=False, default="reserved")
    fee = db.Column(db.Float, nullable=False, default=0.0)
    rate_cents = db.Column(db.Integer, nullable=True)
    fee_cents = db.Column(db.Integer, nullable=False, default=0)


class VehicleLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    reservation_id = db.Column(
        db.Integer, db.ForeignKey("reservation.id"), nullable=False
    )
    entry_time = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    exit_time = db.Column(db.DateTime, nullable=True)

    reservation = db.relationship("Reservation", backref="vehicle_logs")


class Payment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    reservation_id = db.Column(
        db.Integer, db.ForeignKey("reservation.id"), nullable=False
    )
    amount = db.Column(db.Float, nullable=False)
    status = db.Column(db.String(20), nullable=False, default="pending")
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    paid_at = db.Column(db.DateTime, nullable=True)
    amount_cents = db.Column(db.Integer, nullable=False, default=0)

    reservation = db.relationship("Reservation", backref="payments")


class VehicleRate(db.Model):
    vehicle_type = db.Column(db.String(20), primary_key=True)
    cents_per_hour = db.Column(db.Integer, nullable=False)


class AuthSession(db.Model):
    jti = db.Column(db.String(36), primary_key=True)
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    expires_at = db.Column(db.DateTime, nullable=False, index=True)
    revoked_at = db.Column(db.DateTime, nullable=True)


class AuditEvent(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    actor_id = db.Column(db.Integer, nullable=True)
    action = db.Column(db.String(50), nullable=False, index=True)
    resource_id = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
