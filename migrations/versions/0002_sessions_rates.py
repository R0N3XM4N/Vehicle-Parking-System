"""Add revocable sessions, type rates, integer money and operation indexes."""

from alembic import op
import sqlalchemy as sa
from datetime import datetime, timezone
import os
from zoneinfo import ZoneInfo

revision = "0002"
down_revision = "0001"
branch_labels = depends_on = None


def upgrade():
    has_history = (
        op.get_bind().execute(sa.text("SELECT COUNT(*) FROM reservation")).scalar() > 0
    )
    legacy_zone = os.environ.get("VPS_LEGACY_TIMEZONE")
    if has_history and legacy_zone not in {"UTC", "Asia/Kolkata"}:
        raise RuntimeError(
            "Back up the prototype database and set VPS_LEGACY_TIMEZONE=UTC or Asia/Kolkata to identify its existing timestamps before upgrading."
        )
    for query in (
        "SELECT reservation_id FROM payment GROUP BY reservation_id HAVING COUNT(*) > 1",
        "SELECT reservation_id FROM vehicle_log WHERE exit_time IS NULL GROUP BY reservation_id HAVING COUNT(*) > 1",
    ):
        if op.get_bind().execute(sa.text(query)).first():
            raise RuntimeError(
                "Back up and repair duplicate prototype payments/active visits before upgrading; no rows were deleted."
            )
    if has_history and legacy_zone != "UTC":
        # Lockout deadlines were already UTC in PR #51 and must not be shifted.
        for table, columns in {
            "reservation": ("start_time", "scheduled_end_time", "end_time"),
            "vehicle_log": ("entry_time", "exit_time"),
            "payment": ("created_at", "paid_at"),
        }.items():
            for column in columns:
                records = (
                    op.get_bind()
                    .execute(
                        sa.text(
                            f"SELECT id, {column} FROM {table} WHERE {column} IS NOT NULL"
                        )
                    )
                    .all()
                )
                for record_id, stamp in records:
                    converted = (
                        datetime.fromisoformat(str(stamp))
                        .replace(tzinfo=ZoneInfo(legacy_zone))
                        .astimezone(timezone.utc)
                        .replace(tzinfo=None)
                    )
                    op.get_bind().execute(
                        sa.text(f"UPDATE {table} SET {column}=:stamp WHERE id=:id"),
                        {"stamp": converted.isoformat(" "), "id": record_id},
                    )
    op.add_column("reservation", sa.Column("rate_cents", sa.Integer))
    op.add_column(
        "reservation",
        sa.Column("fee_cents", sa.Integer, nullable=False, server_default="0"),
    )
    op.add_column(
        "payment",
        sa.Column("amount_cents", sa.Integer, nullable=False, server_default="0"),
    )
    op.create_table(
        "vehicle_rate",
        sa.Column("vehicle_type", sa.String(20), primary_key=True),
        sa.Column("cents_per_hour", sa.Integer, nullable=False),
    )
    op.create_table(
        "auth_session",
        sa.Column("jti", sa.String(36), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer,
            sa.ForeignKey("user.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime, nullable=False),
        sa.Column("revoked_at", sa.DateTime),
    )
    op.create_table(
        "audit_event",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("actor_id", sa.Integer),
        sa.Column("action", sa.String(50), nullable=False),
        sa.Column("resource_id", sa.Integer),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )
    op.execute(
        "INSERT INTO vehicle_rate SELECT vehicle_type, CAST(ROUND(MIN(hourly_rate)*100) AS INTEGER) FROM parking_slot GROUP BY vehicle_type"
    )
    op.execute(
        "UPDATE reservation SET fee_cents=CAST(ROUND(fee*100) AS INTEGER), rate_cents=(SELECT CAST(ROUND(hourly_rate*100) AS INTEGER) FROM parking_slot WHERE id=slot_id) WHERE status IN ('parked','awaiting_payment','completed')"
    )
    op.execute("UPDATE payment SET amount_cents=CAST(ROUND(amount*100) AS INTEGER)")
    op.execute(
        "UPDATE parking_slot SET hourly_rate=(SELECT cents_per_hour/100.0 FROM vehicle_rate WHERE vehicle_type=parking_slot.vehicle_type)"
    )
    op.create_index(
        "ix_reservation_window",
        "reservation",
        ["slot_id", "status", "start_time", "scheduled_end_time"],
    )
    op.create_index("ix_slot_zone_type", "parking_slot", ["zone", "vehicle_type"])
    op.create_index("ix_auth_user", "auth_session", ["user_id"])
    op.create_index("ix_auth_expiry", "auth_session", ["expires_at"])
    op.create_index("ix_audit_created", "audit_event", ["created_at"])
    # Do not silently delete prototype duplicates. A backup/data repair is required.
    op.create_index(
        "uq_payment_reservation", "payment", ["reservation_id"], unique=True
    )
    op.create_index(
        "uq_active_visit",
        "vehicle_log",
        ["reservation_id"],
        unique=True,
        sqlite_where=sa.text("exit_time IS NULL"),
    )


def downgrade():
    for table, name in [
        ("payment", "uq_payment_reservation"),
        ("vehicle_log", "uq_active_visit"),
        ("reservation", "ix_reservation_window"),
        ("parking_slot", "ix_slot_zone_type"),
    ]:
        op.drop_index(name, table_name=table)
    for table in ("audit_event", "auth_session", "vehicle_rate"):
        op.drop_table(table)
    op.drop_column("payment", "amount_cents")
    op.drop_column("reservation", "fee_cents")
    op.drop_column("reservation", "rate_cents")
