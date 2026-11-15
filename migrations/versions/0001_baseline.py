"""Adopt the prototype schema without deleting existing records."""

from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = depends_on = None


def upgrade():
    metadata = sa.MetaData()
    definitions = {
        "user": [
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("name", sa.String(100), nullable=False),
            sa.Column("email", sa.String(120), nullable=False, unique=True),
            sa.Column("password_hash", sa.String(256), nullable=False),
            sa.Column("role", sa.String(20), nullable=False, server_default="user"),
            sa.Column(
                "failed_login_attempts", sa.Integer, nullable=False, server_default="0"
            ),
            sa.Column("locked_until", sa.DateTime),
        ],
        "parking_slot": [
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("slot_number", sa.String(20), nullable=False, unique=True),
            sa.Column("zone", sa.String(50), nullable=False, server_default="Zone A"),
            sa.Column(
                "vehicle_type",
                sa.String(20),
                nullable=False,
                server_default="four-wheeler",
            ),
            sa.Column("is_occupied", sa.Boolean, nullable=False, server_default="0"),
            sa.Column("hourly_rate", sa.Float, nullable=False, server_default="30"),
        ],
        "reservation": [
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("user_id", sa.Integer, sa.ForeignKey("user.id"), nullable=False),
            sa.Column(
                "slot_id", sa.Integer, sa.ForeignKey("parking_slot.id"), nullable=False
            ),
            sa.Column("vehicle_number", sa.String(20), nullable=False),
            sa.Column("start_time", sa.DateTime, nullable=False),
            sa.Column("scheduled_end_time", sa.DateTime),
            sa.Column("end_time", sa.DateTime),
            sa.Column(
                "status", sa.String(20), nullable=False, server_default="reserved"
            ),
            sa.Column("fee", sa.Float, nullable=False, server_default="0"),
        ],
        "vehicle_log": [
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column(
                "reservation_id",
                sa.Integer,
                sa.ForeignKey("reservation.id"),
                nullable=False,
            ),
            sa.Column("entry_time", sa.DateTime, nullable=False),
            sa.Column("exit_time", sa.DateTime),
        ],
        "payment": [
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column(
                "reservation_id",
                sa.Integer,
                sa.ForeignKey("reservation.id"),
                nullable=False,
            ),
            sa.Column("amount", sa.Float, nullable=False),
            sa.Column(
                "status", sa.String(20), nullable=False, server_default="pending"
            ),
            sa.Column("created_at", sa.DateTime, nullable=False),
            sa.Column("paid_at", sa.DateTime),
        ],
    }
    for name, columns in definitions.items():
        sa.Table(name, metadata, *columns)
    metadata.create_all(op.get_bind())
    # Older prototypes may predate these columns.
    for name, columns in definitions.items():
        existing = {c["name"] for c in sa.inspect(op.get_bind()).get_columns(name)}
        for column in columns:
            if column.name not in existing:
                op.add_column(name, column._copy())
    op.execute(
        "UPDATE reservation SET scheduled_end_time=datetime(start_time,'+1 hour') WHERE scheduled_end_time IS NULL"
    )


def downgrade():
    raise RuntimeError(
        "Baseline is data-preserving; restore a tested backup to remove it."
    )
