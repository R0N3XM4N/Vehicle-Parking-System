"""SAD REST contract. Bearer tokens only; browser cookies never authorize API calls."""

from flask import Blueprint, current_app, g, jsonify, request
from sqlalchemy import text

from app import db
from app.auth import login_user, protected, register_user, revoke_current
from app.errors import DomainError
from app.models import (
    AuditEvent,
    ParkingSlot,
    Payment,
    Reservation,
    User,
    VehicleLog,
    VehicleRate,
)
from app import services
from app.timeutils import iso, parse_time

api = Blueprint("api", __name__)
user_required = protected(api=True)
admin_required = protected(admin=True, api=True)


def payload():
    if not request.is_json:
        raise DomainError(400, "json_required", "Send an application/json object.")
    data = request.get_json()
    if not isinstance(data, dict):
        raise DomainError(
            400, "invalid_json", "The request body must be a JSON object."
        )
    return data


def integer(value, name="id"):
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not 0 < value <= 2147483647
    ):
        raise DomainError(400, "invalid_id", f"{name} must be a positive integer.")
    return value


def paging():
    try:
        page, size = int(request.args.get("page", 1)), int(
            request.args.get("per_page", 50)
        )
        if not 1 <= page <= 100000 or not 1 <= size <= 100:
            raise ValueError
        return page, size
    except (ValueError, TypeError):
        raise DomainError(
            400, "invalid_page", "Use a positive page and per_page between 1 and 100."
        ) from None


def ok(data, status=200):
    return jsonify(data=data), status


def user_json(user):
    return dict(id=user.id, name=user.name, email=user.email, role=user.role)


def reservation_json(row):
    return dict(
        id=row.id,
        user_id=row.user_id,
        slot_id=row.slot_id,
        vehicle_number=row.vehicle_number,
        start_time=iso(row.start_time),
        end_time=iso(row.scheduled_end_time),
        actual_exit=iso(row.end_time),
        status=row.status,
        fee_cents=row.fee_cents,
        rate_cents=row.rate_cents,
    )


def payment_json(row):
    return dict(
        id=row.id,
        transaction_id=f"VPS-{row.id:06d}",
        reservation_id=row.reservation_id,
        amount_cents=row.amount_cents,
        amount=f"{row.amount_cents/100:.2f}",
        currency="INR",
        status=row.status,
        timestamp=iso(row.paid_at),
        created_at=iso(row.created_at),
    )


def log_json(log):
    return dict(
        id=log.id,
        reservation_id=log.reservation_id,
        vehicle_number=log.reservation.vehicle_number,
        slot_id=log.reservation.slot_id,
        zone=log.reservation.parking_slot.zone,
        entry_time=iso(log.entry_time),
        exit_time=iso(log.exit_time),
    )


@api.route("/auth/register", methods=["POST"])
def register():
    data = payload()
    return ok(
        user_json(
            register_user(data.get("name"), data.get("email"), data.get("password"))
        ),
        201,
    )


@api.route("/auth/login", methods=["POST"])
def login():
    data = payload()
    user, token = login_user(data.get("email"), data.get("password"))
    return ok(
        dict(
            access_token=token,
            token_type="Bearer",
            expires_in=current_app.config["JWT_TTL_SECONDS"],
            user=user_json(user),
        )
    )


@api.route("/auth/logout", methods=["POST"])
@user_required
def logout():
    revoke_current()
    return ok(dict(revoked=True))


@api.route("/slots")
@user_required
def slots():
    kind, zone, state = (
        request.args.get(key, "") for key in ("vehicle_type", "zone", "state")
    )
    if (
        kind not in {"", "two-wheeler", "four-wheeler"}
        or len(zone) > 50
        or state not in {"", "available", "reserved", "occupied"}
    ):
        raise DomainError(400, "invalid_filter", "Choose valid slot filters.")
    start, end = request.args.get("start_time"), request.args.get("end_time")
    if bool(start) != bool(end):
        raise DomainError(
            400, "invalid_window", "Provide both start_time and end_time."
        )
    if start:
        start, end = parse_time(start), parse_time(end)
        if end <= start:
            raise DomainError(400, "invalid_window", "End must be after start.")
    states = services.slot_states(start, end)
    query = ParkingSlot.query
    if kind:
        query = query.filter_by(vehicle_type=kind)
    if zone:
        query = query.filter_by(zone=zone)
    rows = query.order_by(ParkingSlot.id).all()
    if state:
        rows = [row for row in rows if states[row.id] == state]
    page, size = paging()
    return ok(
        dict(
            total=len(rows),
            page=page,
            items=[
                dict(
                    id=row.id,
                    slot_number=row.slot_number,
                    zone=row.zone,
                    vehicle_type=row.vehicle_type,
                    state=states[row.id],
                    rate_cents=db.session.get(
                        VehicleRate, row.vehicle_type
                    ).cents_per_hour,
                )
                for row in rows[(page - 1) * size : page * size]
            ],
        )
    )


@api.route("/occupancy")
@user_required
def occupancy():
    return ok(services.occupancy())


@api.route("/reservations", methods=["GET", "POST"])
@user_required
def reservations():
    if request.method == "POST":
        data = payload()
        vehicle = data.get("vehicle_number")
        if not isinstance(vehicle, str):
            raise DomainError(400, "invalid_vehicle", "Provide a vehicle number.")
        row = services.reserve_slot(
            g.current_user.id,
            integer(data.get("slot_id"), "slot_id"),
            vehicle.strip().upper(),
            parse_time(data.get("start_time")),
            parse_time(data.get("end_time")),
        )
        return ok(reservation_json(row), 201)
    page, size = paging()
    query = Reservation.query.filter_by(user_id=g.current_user.id)
    return ok(
        dict(
            total=query.count(),
            items=[
                reservation_json(row)
                for row in query.order_by(Reservation.id.desc())
                .offset((page - 1) * size)
                .limit(size)
            ],
        )
    )


@api.route("/entries", methods=["POST", "GET"])
@user_required
def entries():
    if request.method == "POST":
        data = payload()
        return ok(
            log_json(
                services.enter_vehicle(
                    g.current_user.id,
                    integer(data.get("reservation_id"), "reservation_id"),
                )
            ),
            201,
        )
    page, size = paging()
    query = VehicleLog.query.join(Reservation).filter(
        Reservation.user_id == g.current_user.id
    )
    return ok(
        dict(
            total=query.count(),
            items=[
                log_json(log)
                for log in query.order_by(VehicleLog.id.desc())
                .offset((page - 1) * size)
                .limit(size)
            ],
        )
    )


def entry_for_user(entry_id):
    integer(entry_id)
    log = db.session.get(VehicleLog, entry_id)
    if log is None or log.reservation.user_id != g.current_user.id:
        raise DomainError(404, "not_found", "Entry not found.")
    return log


@api.route("/entries/<int:entry_id>/quote")
@user_required
def quote(entry_id):
    log = entry_for_user(entry_id)
    result = services.preview_exit(g.current_user.id, log.reservation_id)
    return ok(
        dict(
            quote_token=result["quote_token"],
            billed_hours=result["hours"],
            amount_cents=result["fee_cents"],
            rate_cents=result["rate_cents"],
            expires_in=300,
        )
    )


@api.route("/entries/<int:entry_id>/exit", methods=["POST"])
@user_required
def exit_entry(entry_id):
    log = entry_for_user(entry_id)
    token = payload().get("quote_token")
    if not isinstance(token, str):
        raise DomainError(
            400, "quote_required", "Provide the quote_token from the fee preview."
        )
    payment = services.confirm_exit(g.current_user.id, log.reservation_id, token)
    return ok(
        dict(
            entry=log_json(db.session.get(VehicleLog, entry_id)),
            payment=payment_json(payment),
        )
    )


@api.route("/payments", methods=["POST"])
@user_required
def payments():
    data = payload()
    return ok(
        payment_json(
            services.confirm_payment(
                g.current_user.id, integer(data.get("payment_id"), "payment_id")
            )
        )
    )


@api.route("/receipts/<int:payment_id>")
@user_required
def receipt(payment_id):
    payment = db.session.get(Payment, payment_id)
    if payment is None or (
        payment.reservation.user_id != g.current_user.id
        and g.current_user.role != "admin"
    ):
        raise DomainError(404, "not_found", "Receipt not found.")
    if payment.status != "paid":
        raise DomainError(409, "unpaid", "A receipt is available only after payment.")
    return ok(payment_json(payment))


@api.route("/admin/slots", methods=["GET", "POST"])
@api.route("/admin/slots/<int:slot_id>", methods=["PUT", "DELETE"])
@admin_required
def admin_slots(slot_id=None):
    if slot_id is not None:
        integer(slot_id)
    if request.method == "GET":
        page, size = paging()
        return ok(
            dict(
                total=ParkingSlot.query.count(),
                items=[
                    dict(
                        id=s.id,
                        slot_number=s.slot_number,
                        zone=s.zone,
                        vehicle_type=s.vehicle_type,
                    )
                    for s in ParkingSlot.query.order_by(ParkingSlot.id)
                    .offset((page - 1) * size)
                    .limit(size)
                ],
            )
        )
    if request.method == "DELETE":
        services.delete_slot(g.current_user.id, slot_id)
        return ok(dict(deleted=True))
    row = services.save_slot(g.current_user.id, payload(), slot_id)
    return ok(
        dict(
            id=row.id,
            slot_number=row.slot_number,
            zone=row.zone,
            vehicle_type=row.vehicle_type,
        ),
        201 if request.method == "POST" else 200,
    )


@api.route("/admin/rates", methods=["GET", "POST", "PUT"])
@api.route("/admin/rates/<vehicle_type>", methods=["PUT"])
@admin_required
def rates(vehicle_type=None):
    if request.method != "GET":
        data = payload()
        services.set_rate(
            g.current_user.id,
            vehicle_type or data.get("vehicle_type"),
            data.get("hourly_rate"),
        )
    return ok(
        [
            dict(vehicle_type=r.vehicle_type, cents_per_hour=r.cents_per_hour)
            for r in VehicleRate.query.order_by(VehicleRate.vehicle_type)
        ]
    )


@api.route("/admin/logs")
@admin_required
def logs():
    page, size = paging()
    query = VehicleLog.query
    zone = request.args.get("zone")
    if zone:
        if len(zone) > 50:
            raise DomainError(400, "invalid_filter", "Zone is too long.")
        query = (
            query.join(Reservation).join(ParkingSlot).filter(ParkingSlot.zone == zone)
        )
    return ok(
        dict(
            total=query.count(),
            items=[
                log_json(log)
                for log in query.order_by(VehicleLog.id.desc())
                .offset((page - 1) * size)
                .limit(size)
            ],
        )
    )
