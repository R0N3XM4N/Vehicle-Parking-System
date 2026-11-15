"""Browser views; all state changes delegate to shared application services."""

from datetime import timedelta

from flask import (
    Blueprint,
    flash,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from app import db
from app.auth import login_user, protected, register_user, revoke_current
from app.errors import DomainError, wants_json
from app.models import (
    AuditEvent,
    ParkingSlot,
    Payment,
    Reservation,
    VehicleLog,
    VehicleRate,
)
from app import services
from app.timeutils import local_time, parse_time, utcnow
from app.validation import parse_rate

main = Blueprint("main", __name__)
login_required = protected()
admin_required = protected(admin=True)


def parse_local_datetime(value):
    return parse_time(value, browser=True)


def fee_quote(reservation, exit_time=None):
    return services.calculate_quote(reservation, exit_time)


@main.route("/")
def home():
    if session.get("access_token"):
        return redirect(url_for("main.dashboard"))
    services.refresh_expiry()
    states = services.slot_states()
    return render_template(
        "index.html",
        total_slots=len(states),
        available_slots=sum(state == "available" for state in states.values()),
        lowest_rate=(
            db.session.query(db.func.min(VehicleRate.cents_per_hour)).scalar() or 0
        )
        / 100,
    )


@main.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        try:
            register_user(
                request.form.get("name", ""),
                request.form.get("email", ""),
                request.form.get("password", ""),
            )
        except DomainError as error:
            flash(error.message, "error")
            return render_template("register.html"), error.status
        flash("Registration successful. Please log in.", "success")
        return redirect(url_for("main.login"))
    return render_template("register.html")


@main.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        try:
            user, token = login_user(
                request.form.get("email", ""), request.form.get("password", "")
            )
        except DomainError as error:
            flash(error.message, "error")
            return render_template("login.html"), error.status
        # Revoke the replaced session instead of leaving an orphan token.
        old = session.get("access_token")
        if old:
            from app.auth import authenticate

            try:
                authenticate(old)
                revoke_current()
            except DomainError:
                pass
        session.clear()
        session.update(
            access_token=token,
            user_id=user.id,
            user_name=user.name,
            user_role=user.role,
        )
        return redirect(url_for("main.dashboard"))
    return render_template("login.html")


@main.route("/logout", methods=["POST"])
@login_required
def logout():
    revoke_current()
    session.clear()
    flash("You have been logged out.", "success")
    return redirect(url_for("main.login"))


@main.route("/dashboard")
@login_required
def dashboard():
    return render_template(
        "dashboard.html",
        name=g.current_user.name,
        is_admin=g.current_user.role == "admin",
    )


@main.route("/parking")
@login_required
def parking():
    filters = {
        key: request.args.get(key, "").strip()
        for key in ("search", "zone", "vehicle_type", "availability")
    }
    if (
        len(filters["search"]) > 100
        or len(filters["zone"]) > 50
        or filters["vehicle_type"] not in {"", "two-wheeler", "four-wheeler"}
        or filters["availability"] not in {"", "available", "occupied", "reserved"}
    ):
        raise DomainError(400, "invalid_filter", "Choose valid parking filters.")
    states = services.slot_states()
    query = ParkingSlot.query
    if filters["search"]:
        query = query.filter(
            ParkingSlot.slot_number.contains(filters["search"], autoescape=True)
        )
    for field in ("zone", "vehicle_type"):
        if filters[field]:
            query = query.filter(getattr(ParkingSlot, field) == filters[field])
    slots = query.order_by(ParkingSlot.zone, ParkingSlot.slot_number).all()
    if filters["availability"]:
        slots = [slot for slot in slots if states[slot.id] == filters["availability"]]
    return render_template(
        "parking.html",
        slots=slots,
        states=states,
        filters=filters,
        zones=sorted({slot.zone for slot in ParkingSlot.query.all()}),
        zones_stats=services.occupancy(),
        reservation_counts={},
    )


@main.route("/reserve/<int:slot_id>", methods=["GET", "POST"])
@login_required
def reserve(slot_id):
    slot = db.session.get(ParkingSlot, slot_id)
    if slot is None:
        raise DomainError(404, "not_found", "Parking slot not found.")
    start = local_time(utcnow()).replace(second=0, microsecond=0)
    end = start + timedelta(hours=1)
    vehicle = request.form.get("vehicle_number", "").strip().upper()
    status = 200
    if request.method == "POST":
        try:
            services.reserve_slot(
                g.current_user.id,
                slot_id,
                vehicle,
                parse_local_datetime(request.form.get("start_time")),
                parse_local_datetime(request.form.get("end_time")),
            )
            flash(f"Slot {slot.slot_number} reserved successfully.", "success")
            return redirect(url_for("main.my_reservations"))
        except DomainError as error:
            flash(error.message, "error")
            status = error.status
    return (
        render_template(
            "reserve.html",
            slot=slot,
            vehicle_number=vehicle,
            default_start=request.form.get(
                "start_time", start.strftime("%Y-%m-%dT%H:%M")
            ),
            default_end=request.form.get("end_time", end.strftime("%Y-%m-%dT%H:%M")),
        ),
        status,
    )


@main.route("/my-reservations")
@login_required
def my_reservations():
    reservations = (
        Reservation.query.filter_by(user_id=g.current_user.id)
        .order_by(Reservation.start_time.desc())
        .all()
    )
    payments = {
        p.reservation_id: p
        for p in Payment.query.join(Reservation).filter(
            Reservation.user_id == g.current_user.id
        )
    }
    return render_template(
        "my_reservations.html",
        reservations=reservations,
        payment_by_reservation=payments,
    )


@main.route("/reservation/<int:reservation_id>/entry", methods=["POST"])
@login_required
def vehicle_entry(reservation_id):
    services.enter_vehicle(g.current_user.id, reservation_id)
    flash("Vehicle entry recorded successfully.", "success")
    return redirect(url_for("main.my_reservations"))


@main.route("/reservation/<int:reservation_id>/exit", methods=["POST"])
@login_required
def vehicle_exit(reservation_id):
    services.owned_reservation(reservation_id, g.current_user.id)
    return redirect(url_for("main.checkout", reservation_id=reservation_id))


@main.route("/reservation/<int:reservation_id>/checkout", methods=["GET", "POST"])
@login_required
def checkout(reservation_id):
    user_id = g.current_user.id
    if request.method == "POST":
        payment = services.confirm_exit(
            user_id, reservation_id, request.form.get("quote_token")
        )
        return redirect(url_for("main.payment", payment_id=payment.id))
    reservation = services.owned_reservation(reservation_id, user_id)
    quote = services.preview_exit(user_id, reservation_id)
    return render_template("checkout.html", reservation=reservation, quote=quote)


@main.route("/payments/<int:payment_id>", methods=["GET", "POST"])
@login_required
def payment(payment_id):
    record = db.session.get(Payment, payment_id)
    if record is None or record.reservation.user_id != g.current_user.id:
        raise DomainError(404, "not_found", "Payment not found.")
    if request.method == "POST":
        record = services.confirm_payment(g.current_user.id, payment_id)
    if record.status == "paid":
        return redirect(url_for("main.receipt", payment_id=payment_id))
    return render_template("payment.html", payment=record)


@main.route("/payments/<int:payment_id>/receipt")
@login_required
def receipt(payment_id):
    record = db.session.get(Payment, payment_id)
    if record is None or (
        record.reservation.user_id != g.current_user.id
        and g.current_user.role != "admin"
    ):
        raise DomainError(404, "not_found", "Payment not found.")
    if record.status != "paid":
        return redirect(url_for("main.payment", payment_id=payment_id))
    return render_template("receipt.html", payment=record)


@main.route("/admin")
@admin_required
def admin_dashboard():
    slots = ParkingSlot.query.order_by(ParkingSlot.zone, ParkingSlot.slot_number).all()
    states = services.slot_states()
    stats = dict(
        total=len(slots),
        occupied=sum(s == "occupied" for s in states.values()),
        available=sum(s == "available" for s in states.values()),
        rate_average=sum(s.hourly_rate for s in slots) / len(slots) if slots else 0,
    )
    return render_template(
        "admin.html",
        slots=slots,
        stats=stats,
        rates=VehicleRate.query.all(),
        zones_stats=services.occupancy(),
    )


@main.route("/admin/slots/add", methods=["POST"])
@admin_required
def admin_add_slot():
    # Legacy form field remains accepted as a type-wide rate update.
    rate = request.form.get("hourly_rate")
    if rate is not None and parse_rate(rate) is None:
        raise DomainError(400, "invalid_rate", "Enter a positive hourly rate.")
    slot = services.save_slot(g.current_user.id, request.form)
    if rate is not None:
        services.set_rate(g.current_user.id, slot.vehicle_type, rate)
    flash(f"Slot {slot.slot_number} added.", "success")
    return redirect(url_for("main.admin_dashboard"))


@main.route("/admin/slots/<int:slot_id>/edit", methods=["POST"])
@admin_required
def admin_edit_slot(slot_id):
    rate = request.form.get("hourly_rate")
    if rate is not None and parse_rate(rate) is None:
        raise DomainError(400, "invalid_rate", "Enter a positive hourly rate.")
    slot = services.save_slot(g.current_user.id, request.form, slot_id)
    if rate is not None:
        services.set_rate(g.current_user.id, slot.vehicle_type, rate)
    flash(f"Slot {slot.slot_number} updated.", "success")
    return redirect(url_for("main.admin_dashboard"))


@main.route("/admin/slots/<int:slot_id>/delete", methods=["POST"])
@admin_required
def admin_delete_slot(slot_id):
    slot = db.session.get(ParkingSlot, slot_id)
    if slot is None:
        raise DomainError(404, "not_found", "Parking slot not found.")
    number = slot.slot_number
    services.delete_slot(g.current_user.id, slot_id)
    flash(f"Slot {number} removed.", "success")
    return redirect(url_for("main.admin_dashboard"))


@main.route("/admin/rates/update", methods=["POST"])
@admin_required
def admin_update_rate():
    services.set_rate(
        g.current_user.id,
        request.form.get("vehicle_type"),
        request.form.get("hourly_rate"),
    )
    flash("Vehicle-type rate updated. Active visits keep their entry rate.", "success")
    return redirect(url_for("main.admin_dashboard"))


@main.route("/admin/reports")
@admin_required
def reports():
    data = services.report_data(request.args.get("period", "daily"))
    return render_template("reports.html", **data)


@main.route("/admin/audit")
@admin_required
def audit_logs():
    page = request.args.get("page", "1")
    if not page.isdigit() or not 1 <= int(page) <= 100000:
        raise DomainError(400, "invalid_page", "Choose a valid audit page.")
    offset = (int(page) - 1) * 50
    logs = (
        VehicleLog.query.order_by(VehicleLog.entry_time.desc())
        .offset(offset)
        .limit(50)
        .all()
    )
    events = (
        AuditEvent.query.order_by(AuditEvent.id.desc()).offset(offset).limit(50).all()
    )
    return render_template("audit.html", logs=logs, events=events, page=int(page))
