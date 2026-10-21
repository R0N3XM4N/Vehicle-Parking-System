
from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from app import db
from app.models import User
from app.models import ParkingSlot, Reservation, VehicleLog, Payment
from datetime import datetime
from math import ceil

main = Blueprint("main", __name__)


@main.route("/")
def home():
    if "user_id" in session:
        return redirect(url_for("main.dashboard"))
    return render_template("index.html")


@main.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        if not name or not email or not password:
            flash("All fields are required.", "error")
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
            return redirect(url_for("main.dashboard"))

        flash("Invalid email or password.", "error")

    return render_template("login.html")


@main.route("/dashboard")
def dashboard():
    if "user_id" not in session:
        flash("Please log in first.", "error")
        return redirect(url_for("main.login"))

    return render_template("dashboard.html", name=session["user_name"])


@main.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out.", "success")
    return redirect(url_for("main.login"))


@main.route("/parking")
def parking():
    if "user_id" not in session:
        flash("Please log in first.", "error")
        return redirect(url_for("main.login"))

    slots = ParkingSlot.query.order_by(ParkingSlot.slot_number).all()

    return render_template("parking.html", slots=slots)



@main.route("/reserve/<int:slot_id>", methods=["GET", "POST"])
def reserve(slot_id):
    if "user_id" not in session:
        flash("Please log in first.", "error")
        return redirect(url_for("main.login"))

    slot = db.session.get(ParkingSlot, slot_id)

    if slot is None:
        flash("Parking slot not found.", "error")
        return redirect(url_for("main.parking"))

    if request.method == "POST":
        vehicle_number = request.form.get("vehicle_number", "").strip().upper()

        if not vehicle_number or len(vehicle_number) > 20:
            flash("Enter a valid vehicle number.", "error")
            return render_template("reserve.html", slot=slot)

        if slot.is_occupied:
            flash("This parking slot is no longer available.", "error")
            return redirect(url_for("main.parking"))

        # Check whether an active reservation already exists.
        active_reservation = Reservation.query.filter_by(
            slot_id=slot.id,
            status="reserved"
        ).first()

        if active_reservation:
            flash("This slot has already been reserved.", "error")
            return redirect(url_for("main.parking"))

        reservation = Reservation(
            user_id=session["user_id"],
            slot_id=slot.id,
            vehicle_number=vehicle_number,
            status="reserved"
        )

        try:
            slot.is_occupied = True
            db.session.add(reservation)
            db.session.commit()
        except Exception:
            db.session.rollback()
            flash("Reservation failed. Please try again.", "error")
            return redirect(url_for("main.parking"))

        flash(f"Slot {slot.slot_number} reserved successfully.", "success")
        return redirect(url_for("main.my_reservations"))

    return render_template("reserve.html", slot=slot)


@main.route("/my-reservations")
def my_reservations():
    if "user_id" not in session:
        flash("Please log in first.", "error")
        return redirect(url_for("main.login"))

    reservations = (
        Reservation.query
        .filter_by(user_id=session["user_id"])
        .order_by(Reservation.start_time.desc())
        .all()
    )

    return render_template(
        "my_reservations.html",
        reservations=reservations
    )



@main.route("/reservation/<int:reservation_id>/entry", methods=["POST"])
def vehicle_entry(reservation_id):
    if "user_id" not in session:
        return redirect(url_for("main.login"))

    reservation = db.session.get(Reservation, reservation_id)

    if reservation is None or reservation.user_id != session["user_id"]:
        flash("Reservation not found.", "error")
        return redirect(url_for("main.my_reservations"))

    if reservation.status != "reserved":
        flash("This reservation cannot be used for vehicle entry.", "error")
        return redirect(url_for("main.my_reservations"))

    log = VehicleLog(
        reservation_id=reservation.id,
        entry_time=datetime.utcnow()
    )

    reservation.status = "parked"
    db.session.add(log)
    db.session.commit()

    flash("Vehicle entry recorded successfully.", "success")
    return redirect(url_for("main.my_reservations"))


@main.route("/reservation/<int:reservation_id>/exit", methods=["POST"])
def vehicle_exit(reservation_id):
    if "user_id" not in session:
        return redirect(url_for("main.login"))

    reservation = db.session.get(Reservation, reservation_id)

    if reservation is None or reservation.user_id != session["user_id"]:
        flash("Reservation not found.", "error")
        return redirect(url_for("main.my_reservations"))

    if reservation.status != "parked":
        flash("Record vehicle entry before recording exit.", "error")
        return redirect(url_for("main.my_reservations"))

    log = (
        VehicleLog.query
        .filter_by(reservation_id=reservation.id, exit_time=None)
        .order_by(VehicleLog.entry_time.desc())
        .first()
    )

    if log is None:
        flash("No active vehicle entry record was found.", "error")
        return redirect(url_for("main.my_reservations"))

    exit_time = datetime.utcnow()
    elapsed_seconds = (exit_time - log.entry_time).total_seconds()
    hours = max(1, ceil(elapsed_seconds / 3600))
    fee = round(hours * reservation.parking_slot.hourly_rate, 2)

    log.exit_time = exit_time
    reservation.end_time = exit_time
    reservation.fee = fee
    reservation.status = "completed"
    reservation.parking_slot.is_occupied = False

    payment = Payment(
        reservation_id=reservation.id,
        amount=fee,
        status="paid"
    )
    db.session.add(payment)
    db.session.commit()

    flash(
        f"Vehicle exit recorded. Parking duration: {hours} hour(s). "
        f"Calculated fee: ₹{fee:.2f}. Simulated payment recorded.",
        "success"
    )
    return redirect(url_for("main.my_reservations"))
