"""Transactional business operations shared by HTML and JSON interfaces.

SQLite has one writer. BEGIN IMMEDIATE serializes validation and mutation before
any state is read, so competing bookings/entries cannot pass the same check.
"""

from collections import defaultdict
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from math import ceil
from zoneinfo import ZoneInfo

from flask import current_app
from itsdangerous import BadSignature, URLSafeTimedSerializer
from sqlalchemy import or_, text
from sqlalchemy.exc import IntegrityError, OperationalError

from app import db
from app.errors import DomainError
from app.models import (
    AuditEvent,
    ParkingSlot,
    Payment,
    Reservation,
    VehicleLog,
    VehicleRate,
)
from app.timeutils import utcnow
from app.validation import plain_text, parse_rate, valid_slot, valid_vehicle_number


@contextmanager
def write_transaction():
    # Discard the request's read transaction; business mutations only occur here.
    db.session.rollback()
    try:
        db.session.execute(text("BEGIN IMMEDIATE"))
        yield
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        raise DomainError(
            409, "conflict", "The requested change conflicts with existing records."
        ) from None
    except OperationalError as error:
        db.session.rollback()
        if "locked" in str(error).lower():
            raise DomainError(
                409, "busy", "Another update is in progress. Retry the request."
            ) from None
        raise
    except Exception:
        db.session.rollback()
        raise


def audit(actor_id, action, resource_id=None):
    db.session.add(
        AuditEvent(
            actor_id=actor_id,
            action=action,
            resource_id=resource_id,
            created_at=utcnow(),
        )
    )


def seed_defaults():
    with write_transaction():
        for vehicle_type in ("two-wheeler", "four-wheeler"):
            if db.session.get(VehicleRate, vehicle_type) is None:
                db.session.add(
                    VehicleRate(vehicle_type=vehicle_type, cents_per_hour=3000)
                )
        if ParkingSlot.query.count() == 0:
            for number in range(1, 11):
                db.session.add(
                    ParkingSlot(
                        slot_number=f"A-{number:02d}",
                        zone="Zone A" if number <= 5 else "Zone B",
                        vehicle_type=(
                            "two-wheeler" if number % 3 == 0 else "four-wheeler"
                        ),
                        hourly_rate=30,
                    )
                )


def expire_reservations(now=None):
    now = now or utcnow()
    expired = Reservation.query.filter(
        Reservation.status == "reserved", Reservation.scheduled_end_time <= now
    ).all()
    for reservation in expired:
        reservation.status = "expired"
        audit(None, "reservation_expired", reservation.id)
    return len(expired)


def refresh_expiry():
    # Only acquire a write lock when an expired row exists.
    if Reservation.query.filter(
        Reservation.status == "reserved", Reservation.scheduled_end_time <= utcnow()
    ).first():
        with write_transaction():
            expire_reservations()


def owned_reservation(reservation_id, user_id, admin=False):
    reservation = db.session.get(Reservation, reservation_id)
    if reservation is None or (reservation.user_id != user_id and not admin):
        raise DomainError(404, "not_found", "Reservation not found.")
    return reservation


def reserve_slot(user_id, slot_id, vehicle_number, start, end):
    if not valid_vehicle_number(vehicle_number):
        raise DomainError(400, "invalid_vehicle", "Enter a valid vehicle number.")
    now = utcnow()
    if (
        start < now - timedelta(minutes=1)
        or end <= start
        or end - start > timedelta(hours=24)
    ):
        raise DomainError(
            400,
            "invalid_window",
            "Choose a current or future window of up to 24 hours.",
        )
    with write_transaction():
        expire_reservations(now)
        slot = db.session.get(ParkingSlot, slot_id)
        if slot is None:
            raise DomainError(404, "not_found", "Parking slot not found.")
        if (
            slot.is_occupied
            or Reservation.query.filter(
                Reservation.slot_id == slot_id, Reservation.status == "parked"
            ).first()
        ):
            raise DomainError(409, "occupied", "The slot is currently occupied.")
        conflict = Reservation.query.filter(
            Reservation.slot_id == slot_id,
            Reservation.status == "reserved",
            Reservation.start_time < end,
            Reservation.scheduled_end_time > start,
        ).first()
        if conflict:
            raise DomainError(
                409,
                "reserved",
                "This slot is already reserved during that time window.",
            )
        reservation = Reservation(
            user_id=user_id,
            slot_id=slot_id,
            vehicle_number=vehicle_number,
            start_time=start,
            scheduled_end_time=end,
        )
        db.session.add(reservation)
        db.session.flush()
        audit(user_id, "reservation_created", reservation.id)
        reservation_id = reservation.id
    return db.session.get(Reservation, reservation_id)


def enter_vehicle(user_id, reservation_id):
    with write_transaction():
        now = utcnow()
        expire_reservations(now)
        reservation = owned_reservation(reservation_id, user_id)
        if (
            reservation.status != "reserved"
            or not reservation.start_time <= now < reservation.scheduled_end_time
        ):
            raise DomainError(
                409,
                "outside_window",
                "Entry is allowed only during an active reservation window.",
            )
        slot = reservation.parking_slot
        if slot.is_occupied:
            raise DomainError(
                409, "occupied", "The selected slot is currently occupied."
            )
        rate = db.session.get(VehicleRate, slot.vehicle_type)
        reservation.rate_cents = rate.cents_per_hour
        slot.is_occupied = True
        reservation.status = "parked"
        log = VehicleLog(reservation_id=reservation_id, entry_time=now)
        db.session.add(log)
        db.session.flush()
        audit(user_id, "vehicle_entered", reservation_id)
        log_id = log.id
    return db.session.get(VehicleLog, log_id)


def active_log(reservation):
    return VehicleLog.query.filter_by(
        reservation_id=reservation.id, exit_time=None
    ).first()


def calculate_quote(reservation, now=None):
    log = active_log(reservation)
    if reservation.status != "parked" or log is None:
        raise DomainError(
            409, "not_parked", "Only a parked vehicle can be checked out."
        )
    now = now or utcnow()
    hours = max(1, ceil(max(0, (now - log.entry_time).total_seconds()) / 3600))
    # Fallback covers legacy records manually created before rate snapshots.
    cents = reservation.rate_cents
    if cents is None:
        cents = int(Decimal(str(reservation.parking_slot.hourly_rate)) * 100)
    return {
        "log": log,
        "hours": hours,
        "rate_cents": cents,
        "fee_cents": cents * hours,
        "fee": cents * hours / 100,
        "exit_time": now,
    }


def quote_signer():
    return URLSafeTimedSerializer(
        current_app.config["SECRET_KEY"], salt="exit-quote-v1"
    )


def preview_exit(user_id, reservation_id):
    reservation = owned_reservation(reservation_id, user_id)
    quote = calculate_quote(reservation)
    quote["quote_token"] = quote_signer().dumps(
        {
            "user": user_id,
            "reservation": reservation_id,
            "log": quote["log"].id,
            "at": quote["exit_time"].isoformat(),
            "hours": quote["hours"],
            "rate": quote["rate_cents"],
            "amount": quote["fee_cents"],
        }
    )
    return quote


def confirm_exit(user_id, reservation_id, token):
    try:
        data = quote_signer().loads(token or "", max_age=300)
    except (BadSignature, TypeError):
        raise DomainError(
            409,
            "quote_required",
            "Preview the fee again; exit quotes expire after five minutes.",
        ) from None
    if data.get("user") != user_id or data.get("reservation") != reservation_id:
        raise DomainError(
            403, "invalid_quote", "This fee quote belongs to another visit."
        )
    with write_transaction():
        reservation = owned_reservation(reservation_id, user_id)
        existing = Payment.query.filter_by(reservation_id=reservation_id).first()
        if existing:
            payment_id = existing.id
        else:
            log = active_log(reservation)
            if reservation.status != "parked" or log is None or log.id != data["log"]:
                raise DomainError(
                    409, "not_parked", "This visit cannot be checked out."
                )
            # Charge exactly the signed preview. Actual exit timestamp is confirmation time.
            now = utcnow()
            log.exit_time = now
            reservation.end_time = now
            reservation.fee_cents = data["amount"]
            reservation.fee = data["amount"] / 100
            reservation.status = "awaiting_payment"
            reservation.parking_slot.is_occupied = False
            payment = Payment(
                reservation_id=reservation_id,
                amount_cents=data["amount"],
                amount=data["amount"] / 100,
                status="pending",
                created_at=now,
            )
            db.session.add(payment)
            db.session.flush()
            audit(user_id, "vehicle_exited", reservation_id)
            payment_id = payment.id
    return db.session.get(Payment, payment_id)


def confirm_payment(user_id, payment_id):
    with write_transaction():
        payment = db.session.get(Payment, payment_id)
        if payment is None or payment.reservation.user_id != user_id:
            raise DomainError(404, "not_found", "Payment not found.")
        if payment.status != "paid":
            if (
                payment.status != "pending"
                or payment.reservation.status != "awaiting_payment"
            ):
                raise DomainError(
                    409, "invalid_state", "This payment cannot be confirmed."
                )
            payment.status = "paid"
            payment.paid_at = utcnow()
            payment.reservation.status = "completed"
            audit(user_id, "payment_confirmed", payment_id)
    return db.session.get(Payment, payment_id)


def slot_states(start=None, end=None):
    now = utcnow()
    start, end = start or now, end or now + timedelta(microseconds=1)
    reserved = {
        row.slot_id
        for row in Reservation.query.filter(
            Reservation.status == "reserved",
            Reservation.start_time < end,
            Reservation.scheduled_end_time > start,
        )
    }
    return {
        slot.id: (
            "occupied"
            if slot.is_occupied
            else "reserved" if slot.id in reserved else "available"
        )
        for slot in ParkingSlot.query.all()
    }


def occupancy():
    states = slot_states()
    zones = {}
    for slot in ParkingSlot.query.all():
        counts = zones.setdefault(
            slot.zone, dict(total=0, occupied=0, reserved=0, available=0)
        )
        counts["total"] += 1
        counts[states[slot.id]] += 1
    return [{"zone": zone, **counts} for zone, counts in sorted(zones.items())]


def set_rate(actor_id, vehicle_type, value):
    parsed = parse_rate(str(value))
    if (
        not isinstance(vehicle_type, str)
        or vehicle_type not in {"two-wheeler", "four-wheeler"}
        or parsed is None
    ):
        raise DomainError(
            400,
            "invalid_rate",
            "Choose a vehicle type and a positive rate with at most two decimals.",
        )
    cents = int(Decimal(str(parsed)) * 100)
    with write_transaction():
        db.session.get(VehicleRate, vehicle_type).cents_per_hour = cents
        ParkingSlot.query.filter_by(vehicle_type=vehicle_type).update(
            {"hourly_rate": cents / 100}
        )
        audit(actor_id, "rate_changed")
    return db.session.get(VehicleRate, vehicle_type)


def save_slot(actor_id, data, slot_id=None):
    number, zone = data.get("slot_number", ""), data.get("zone", "")
    kind = data.get("vehicle_type", "")
    if not all(isinstance(v, str) for v in (number, zone, kind)):
        raise DomainError(400, "invalid_slot", "Slot fields must be strings.")
    number, zone = number.strip().upper(), zone.strip()
    if not valid_slot(number, zone, kind, 1):
        raise DomainError(400, "invalid_slot", "Enter valid slot details.")
    with write_transaction():
        slot = db.session.get(ParkingSlot, slot_id) if slot_id else ParkingSlot()
        if slot is None:
            raise DomainError(404, "not_found", "Parking slot not found.")
        if (
            slot_id
            and slot.vehicle_type != kind
            and (
                slot.is_occupied
                or Reservation.query.filter_by(
                    slot_id=slot_id, status="reserved"
                ).first()
            )
        ):
            raise DomainError(
                409, "active_slot", "Cannot change the vehicle type of an active slot."
            )
        slot.slot_number, slot.zone, slot.vehicle_type = number, zone, kind
        slot.hourly_rate = db.session.get(VehicleRate, kind).cents_per_hour / 100
        db.session.add(slot)
        db.session.flush()
        audit(actor_id, "slot_updated" if slot_id else "slot_created", slot.id)
        result_id = slot.id
    return db.session.get(ParkingSlot, result_id)


def delete_slot(actor_id, slot_id):
    with write_transaction():
        slot = db.session.get(ParkingSlot, slot_id)
        if slot is None:
            raise DomainError(404, "not_found", "Parking slot not found.")
        if slot.is_occupied or slot.reservations:
            raise DomainError(
                409,
                "slot_history",
                "Slots with occupancy or reservation history cannot be removed.",
            )
        db.session.delete(slot)
        audit(actor_id, "slot_deleted", slot_id)


def report_data(period="daily"):
    if period not in {"daily", "monthly"}:
        raise DomainError(400, "invalid_period", "Choose daily or monthly reports.")
    zoneinfo = ZoneInfo(current_app.config["REPORT_TIMEZONE"])
    fmt = "%Y-%m" if period == "monthly" else "%Y-%m-%d"
    counts, revenue, transactions = defaultdict(int), defaultdict(int), defaultdict(int)
    for log in VehicleLog.query.all():
        key = (
            log.entry_time.replace(tzinfo=timezone.utc)
            .astimezone(zoneinfo)
            .strftime(fmt)
        )
        counts[key] += 1
    for payment in Payment.query.filter_by(status="paid"):
        key = (
            (payment.paid_at or payment.created_at)
            .replace(tzinfo=timezone.utc)
            .astimezone(zoneinfo)
            .strftime(fmt)
        )
        transactions[key] += 1
        revenue[key] += payment.amount_cents or round(payment.amount * 100)
    rows = [
        dict(
            period=key,
            occupancy=counts[key],
            transactions=transactions[key],
            revenue=revenue[key] / 100,
        )
        for key in sorted(set(counts) | set(revenue), reverse=True)
    ]
    totals = dict(
        occupancy=sum(counts.values()),
        transactions=sum(transactions.values()),
        revenue=sum(revenue.values()) / 100,
        current_occupancy=ParkingSlot.query.filter_by(is_occupied=True).count(),
    )
    return dict(period=period, rows=rows, totals=totals)
