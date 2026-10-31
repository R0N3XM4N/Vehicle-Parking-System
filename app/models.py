
from datetime import datetime

from werkzeug.security import generate_password_hash, check_password_hash
from app import db


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(256), nullable=False)
    role = db.Column(db.String(20), nullable=False, default="user")

    reservations = db.relationship("Reservation", backref="user", lazy=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class ParkingSlot(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    slot_number = db.Column(db.String(20), unique=True, nullable=False)
    zone = db.Column(db.String(50), nullable=False, default="Zone A")
    vehicle_type = db.Column(
        db.String(20), nullable=False, default="four-wheeler"
    )
    is_occupied = db.Column(db.Boolean, nullable=False, default=False)
    hourly_rate = db.Column(db.Float, nullable=False, default=30.0)

    reservations = db.relationship(
        "Reservation", backref="parking_slot", lazy=True
    )


class Reservation(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer, db.ForeignKey("user.id"), nullable=False
    )
    slot_id = db.Column(
        db.Integer, db.ForeignKey("parking_slot.id"), nullable=False
    )
    vehicle_number = db.Column(db.String(20), nullable=False)
    start_time = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    scheduled_end_time = db.Column(db.DateTime, nullable=True)
    end_time = db.Column(db.DateTime, nullable=True)
    status = db.Column(db.String(20), nullable=False, default="reserved")
    fee = db.Column(db.Float, nullable=False, default=0.0)


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

    reservation = db.relationship("Reservation", backref="payments")
