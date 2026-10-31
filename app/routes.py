from collections import defaultdict
from datetime import datetime, timedelta
from functools import wraps
from math import ceil

from flask import (
    Blueprint,
    abort,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from sqlalchemy import or_

from app import db
from app.models import ParkingSlot, Payment, Reservation, User, VehicleLog


main = Blueprint("main", __name__)


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if "user_id" not in session:
            flash("Please log in first.", "error")
            return redirect(url_for("main.login"))
        return view(*args, **kwargs)

    return wrapped


def admin_required(view):
    @wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        user = db.session.get(User, session["user_id"])
        if user is None or user.role != "admin":
            abort(403)
        return view(*args, **kwargs)

    return wrapped


def parse_local_datetime(value):
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M")
    except (TypeError, ValueError):
        return None


def active_log_for(reservation):
    return (
        VehicleLog.query.filter_by(
            reservation_id=reservation.id, exit_time=None
        )
        .order_by(VehicleLog.entry_time.desc())
        .first()
    )


def fee_quote(reservation, exit_time=None):
    log = active_log_for(reservation)
    if log is None:
        return None
    exit_time = exit_time or datetime.now()
    elapsed_seconds = max(0, (exit_time - log.entry_time).total_seconds())
    hours = max(1, ceil(elapsed_seconds / 3600))
    fee = round(hours * reservation.parking_slot.hourly_rate, 2)
    return {"log": log, "exit_time": exit_time, "hours": hours, "fee": fee}


def reservation_owned_by_current_user(reservation_id):
    reservation = db.session.get(Reservation, reservation_id)
    if reservation is None or reservation.user_id != session.get("user_id"):
        return None
    return reservation


@main.route("/")
def home():
    if "user_id" in session:
        return redirect(url_for("main.dashboard"))
    total_slots = ParkingSlot.query.count()
    available_slots = ParkingSlot.query.filter_by(is_occupied=False).count()
    lowest_rate = db.session.query(db.func.min(ParkingSlot.hourly_rate)).scalar()
    return render_template(
        "index.html",
        total_slots=total_slots,
        available_slots=available_slots,
        lowest_rate=lowest_rate or 0,
    )


@main.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        if not name or not email or not password:
            flash("All fields are required.", "error")
            return render_template("register.html")
        if "@" not in email or "." not in email.rsplit("@", 1)[-1]:
            flash("Enter a valid email address.", "error")
            return render_template("register.html")
        if len(password) < 8:
            flash("Password must be at least 8 characters.", "error")
            return render_template("register.html")
        if User.query.filter_by(email=email).first():
            flash("An account with that email already exists.", "error")
            return render_template("register.html")

        user = User(name=name, email=email)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        flash("Registration successful. Please log in.", "success")
        return redirect(url_for("main.login"))

    return render_template("register.html")


@main.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        user = User.query.filter_by(email=email).first()

        if user and user.check_password(password):
            session.clear()
            session["user_id"] = user.id
            session["user_name"] = user.name
            session["user_role"] = user.role
            return redirect(url_for("main.dashboard"))

        flash("Invalid email or password.", "error")
    return render_template("login.html")


@main.route("/dashboard")
@login_required
def dashboard():
    return render_template(
        "dashboard.html",
        name=session["user_name"],
        is_admin=session.get("user_role") == "admin",
    )


@main.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out.", "success")
    return redirect(url_for("main.login"))


@main.route("/parking")
@login_required
def parking():
    search = request.args.get("search", "").strip()
    zone = request.args.get("zone", "").strip()
    vehicle_type = request.args.get("vehicle_type", "").strip()
    availability = request.args.get("availability", "").strip()

    query = ParkingSlot.query
    if search:
        query = query.filter(ParkingSlot.slot_number.ilike(f"%{search}%"))
    if zone:
        query = query.filter_by(zone=zone)
    if vehicle_type in {"two-wheeler", "four-wheeler"}:
        query = query.filter_by(vehicle_type=vehicle_type)
    if availability == "available":
        query = query.filter_by(is_occupied=False)
    elif availability == "occupied":
        query = query.filter_by(is_occupied=True)

    slots = query.order_by(ParkingSlot.zone, ParkingSlot.slot_number).all()
    zones = [row[0] for row in db.session.query(ParkingSlot.zone).distinct()]

    active_reservations = (
        db.session.query(Reservation.slot_id, db.func.count(Reservation.id))
        .filter(Reservation.status.in_(["reserved", "parked"]))
        .group_by(Reservation.slot_id)
        .all()
    )
    reservation_counts = dict(active_reservations)

    return render_template(
        "parking.html",
        slots=slots,
        zones=sorted(zones),
        filters={
            "search": search,
            "zone": zone,
            "vehicle_type": vehicle_type,
            "availability": availability,
        },
        reservation_counts=reservation_counts,
    )


@main.route("/reserve/<int:slot_id>", methods=["GET", "POST"])
@login_required
def reserve(slot_id):
    slot = db.session.get(ParkingSlot, slot_id)
    if slot is None:
        flash("Parking slot not found.", "error")
        return redirect(url_for("main.parking"))

    default_start = datetime.now().replace(second=0, microsecond=0) + timedelta(
        minutes=5
    )
    default_end = default_start + timedelta(hours=1)

    if request.method == "POST":
        vehicle_number = request.form.get("vehicle_number", "").strip().upper()
        start_time = parse_local_datetime(request.form.get("start_time"))
        scheduled_end_time = parse_local_datetime(request.form.get("end_time"))

        if not vehicle_number or len(vehicle_number) > 20:
            flash("Enter a valid vehicle number.", "error")
        elif start_time is None or scheduled_end_time is None:
            flash("Choose a valid reservation start and end time.", "error")
        elif start_time < datetime.now() - timedelta(minutes=1):
            flash("Reservation start time cannot be in the past.", "error")
        elif scheduled_end_time <= start_time:
            flash("Reservation end time must be after the start time.", "error")
        elif scheduled_end_time - start_time > timedelta(hours=24):
            flash("A reservation window cannot exceed 24 hours.", "error")
        else:
            conflict = Reservation.query.filter(
                Reservation.slot_id == slot.id,
                Reservation.status.in_(["reserved", "parked", "awaiting_payment"]),
                Reservation.start_time < scheduled_end_time,
                or_(
                    Reservation.scheduled_end_time.is_(None),
                    Reservation.scheduled_end_time > start_time,
                ),
            ).first()

            if conflict:
                flash(
                    "This slot is already reserved during that time window.",
                    "error",
                )
            else:
                reservation = Reservation(
                    user_id=session["user_id"],
                    slot_id=slot.id,
                    vehicle_number=vehicle_number,
                    start_time=start_time,
                    scheduled_end_time=scheduled_end_time,
                    status="reserved",
                )
                db.session.add(reservation)
                db.session.commit()
                flash(
                    f"Slot {slot.slot_number} reserved successfully.",
                    "success",
                )
                return redirect(url_for("main.my_reservations"))

        return render_template(
            "reserve.html",
            slot=slot,
            default_start=request.form.get("start_time", ""),
            default_end=request.form.get("end_time", ""),
            vehicle_number=vehicle_number,
        )

    return render_template(
        "reserve.html",
        slot=slot,
        default_start=default_start.strftime("%Y-%m-%dT%H:%M"),
        default_end=default_end.strftime("%Y-%m-%dT%H:%M"),
        vehicle_number="",
    )


@main.route("/my-reservations")
@login_required
def my_reservations():
    reservations = (
        Reservation.query.filter_by(user_id=session["user_id"])
        .order_by(Reservation.start_time.desc())
        .all()
    )
    payment_by_reservation = {
        payment.reservation_id: payment
        for payment in Payment.query.join(Reservation).filter(
            Reservation.user_id == session["user_id"]
        )
    }
    return render_template(
        "my_reservations.html",
        reservations=reservations,
        payment_by_reservation=payment_by_reservation,
    )


@main.route("/reservation/<int:reservation_id>/entry", methods=["POST"])
@login_required
def vehicle_entry(reservation_id):
    reservation = reservation_owned_by_current_user(reservation_id)
    if reservation is None:
        flash("Reservation not found.", "error")
        return redirect(url_for("main.my_reservations"))
    if reservation.status != "reserved":
        flash("This reservation cannot be used for vehicle entry.", "error")
        return redirect(url_for("main.my_reservations"))
    if reservation.parking_slot.is_occupied:
        flash("The selected slot is currently occupied.", "error")
        return redirect(url_for("main.my_reservations"))

    reservation.parking_slot.is_occupied = True
    reservation.status = "parked"
    db.session.add(
        VehicleLog(reservation_id=reservation.id, entry_time=datetime.now())
    )
    db.session.commit()
    flash("Vehicle entry recorded successfully.", "success")
    return redirect(url_for("main.my_reservations"))


@main.route("/reservation/<int:reservation_id>/exit", methods=["POST"])
@login_required
def vehicle_exit(reservation_id):
    reservation = reservation_owned_by_current_user(reservation_id)
    if reservation is None or reservation.status != "parked":
        flash("No active parking visit was found.", "error")
        return redirect(url_for("main.my_reservations"))
    return redirect(url_for("main.checkout", reservation_id=reservation.id))


@main.route(
    "/reservation/<int:reservation_id>/checkout", methods=["GET", "POST"]
)
@login_required
def checkout(reservation_id):
    reservation = reservation_owned_by_current_user(reservation_id)
    if reservation is None:
        abort(404)
    if reservation.status != "parked":
        flash("Only a parked vehicle can be checked out.", "error")
        return redirect(url_for("main.my_reservations"))

    quote = fee_quote(reservation)
    if quote is None:
        flash("No active vehicle entry record was found.", "error")
        return redirect(url_for("main.my_reservations"))

    if request.method == "POST":
        quote["log"].exit_time = quote["exit_time"]
        reservation.end_time = quote["exit_time"]
        reservation.fee = quote["fee"]
        reservation.status = "awaiting_payment"
        reservation.parking_slot.is_occupied = False
        payment_record = Payment(
            reservation_id=reservation.id,
            amount=quote["fee"],
            status="pending",
            created_at=datetime.now(),
        )
        db.session.add(payment_record)
        db.session.commit()
        flash("Exit confirmed. Complete the simulated payment.", "success")
        return redirect(url_for("main.payment", payment_id=payment_record.id))

    return render_template("checkout.html", reservation=reservation, quote=quote)


@main.route("/payments/<int:payment_id>", methods=["GET", "POST"])
@login_required
def payment(payment_id):
    payment_record = db.session.get(Payment, payment_id)
    if (
        payment_record is None
        or payment_record.reservation.user_id != session["user_id"]
    ):
        abort(404)

    if request.method == "POST" and payment_record.status != "paid":
        payment_record.status = "paid"
        payment_record.paid_at = datetime.now()
        payment_record.reservation.status = "completed"
        db.session.commit()
        flash("Payment recorded successfully.", "success")
        return redirect(url_for("main.receipt", payment_id=payment_record.id))

    if payment_record.status == "paid":
        return redirect(url_for("main.receipt", payment_id=payment_record.id))
    return render_template("payment.html", payment=payment_record)


@main.route("/payments/<int:payment_id>/receipt")
@login_required
def receipt(payment_id):
    payment_record = db.session.get(Payment, payment_id)
    is_admin = session.get("user_role") == "admin"
    if payment_record is None or (
        payment_record.reservation.user_id != session["user_id"] and not is_admin
    ):
        abort(404)
    if payment_record.status != "paid":
        return redirect(url_for("main.payment", payment_id=payment_record.id))
    return render_template("receipt.html", payment=payment_record)


@main.route("/admin")
@admin_required
def admin_dashboard():
    slots = ParkingSlot.query.order_by(
        ParkingSlot.zone, ParkingSlot.slot_number
    ).all()
    stats = {
        "total": len(slots),
        "occupied": sum(slot.is_occupied for slot in slots),
        "available": sum(not slot.is_occupied for slot in slots),
        "rate_average": (
            round(sum(slot.hourly_rate for slot in slots) / len(slots), 2)
            if slots
            else 0
        ),
    }
    return render_template("admin.html", slots=slots, stats=stats)


@main.route("/admin/slots/add", methods=["POST"])
@admin_required
def admin_add_slot():
    slot_number = request.form.get("slot_number", "").strip().upper()
    zone = request.form.get("zone", "").strip()
    vehicle_type = request.form.get("vehicle_type", "").strip()
    try:
        hourly_rate = float(request.form.get("hourly_rate", ""))
    except ValueError:
        hourly_rate = 0

    if (
        not slot_number
        or not zone
        or vehicle_type not in {"two-wheeler", "four-wheeler"}
        or hourly_rate <= 0
    ):
        flash("Enter valid details for the new parking slot.", "error")
    elif ParkingSlot.query.filter_by(slot_number=slot_number).first():
        flash("A slot with that number already exists.", "error")
    else:
        db.session.add(
            ParkingSlot(
                slot_number=slot_number,
                zone=zone,
                vehicle_type=vehicle_type,
                hourly_rate=hourly_rate,
            )
        )
        db.session.commit()
        flash(f"Slot {slot_number} added.", "success")
    return redirect(url_for("main.admin_dashboard"))


@main.route("/admin/slots/<int:slot_id>/edit", methods=["POST"])
@admin_required
def admin_edit_slot(slot_id):
    slot = db.session.get(ParkingSlot, slot_id)
    if slot is None:
        abort(404)
    slot_number = request.form.get("slot_number", "").strip().upper()
    zone = request.form.get("zone", "").strip()
    vehicle_type = request.form.get("vehicle_type", "").strip()
    try:
        hourly_rate = float(request.form.get("hourly_rate", ""))
    except ValueError:
        hourly_rate = 0

    duplicate = ParkingSlot.query.filter(
        ParkingSlot.slot_number == slot_number, ParkingSlot.id != slot.id
    ).first()
    if (
        not slot_number
        or not zone
        or vehicle_type not in {"two-wheeler", "four-wheeler"}
        or hourly_rate <= 0
    ):
        flash("Enter valid slot details and a positive hourly rate.", "error")
    elif duplicate:
        flash("A slot with that number already exists.", "error")
    else:
        slot.slot_number = slot_number
        slot.zone = zone
        slot.vehicle_type = vehicle_type
        slot.hourly_rate = hourly_rate
        db.session.commit()
        flash(f"Slot {slot_number} updated.", "success")
    return redirect(url_for("main.admin_dashboard"))


@main.route("/admin/slots/<int:slot_id>/delete", methods=["POST"])
@admin_required
def admin_delete_slot(slot_id):
    slot = db.session.get(ParkingSlot, slot_id)
    if slot is None:
        abort(404)
    if slot.is_occupied or slot.reservations:
        flash(
            "Slots with occupancy or reservation history cannot be removed.",
            "error",
        )
    else:
        slot_number = slot.slot_number
        db.session.delete(slot)
        db.session.commit()
        flash(f"Slot {slot_number} removed.", "success")
    return redirect(url_for("main.admin_dashboard"))


@main.route("/admin/reports")
@admin_required
def reports():
    period = request.args.get("period", "daily")
    if period not in {"daily", "monthly"}:
        period = "daily"
    date_format = "%Y-%m" if period == "monthly" else "%Y-%m-%d"

    occupancy = defaultdict(int)
    for log in VehicleLog.query.all():
        occupancy[log.entry_time.strftime(date_format)] += 1

    revenue = defaultdict(float)
    transactions = defaultdict(int)
    paid_payments = Payment.query.filter_by(status="paid").all()
    for payment_record in paid_payments:
        timestamp = payment_record.paid_at or payment_record.created_at
        key = timestamp.strftime(date_format)
        revenue[key] += payment_record.amount
        transactions[key] += 1

    rows = [
        {
            "period": key,
            "occupancy": occupancy[key],
            "transactions": transactions[key],
            "revenue": round(revenue[key], 2),
        }
        for key in sorted(set(occupancy) | set(revenue), reverse=True)
    ]
    totals = {
        "occupancy": sum(occupancy.values()),
        "transactions": len(paid_payments),
        "revenue": round(sum(item.amount for item in paid_payments), 2),
        "current_occupancy": ParkingSlot.query.filter_by(is_occupied=True).count(),
    }
    return render_template(
        "reports.html", period=period, rows=rows, totals=totals
    )


@main.app_errorhandler(403)
def forbidden(_error):
    return render_template("error.html", code=403, message="Access denied"), 403


@main.app_errorhandler(404)
def not_found(_error):
    return render_template("error.html", code=404, message="Page not found"), 404
