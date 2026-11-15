from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from flask import current_app
from app.errors import DomainError


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def local_time(value):
    return value.replace(tzinfo=timezone.utc).astimezone(
        ZoneInfo(current_app.config["REPORT_TIMEZONE"])
    )


def parse_time(value, browser=False):
    if not isinstance(value, str):
        raise DomainError(400, "invalid_time", "Provide an ISO 8601 timestamp.")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            if not browser:
                raise ValueError("Timezone required")
            parsed = parsed.replace(
                tzinfo=ZoneInfo(current_app.config["REPORT_TIMEZONE"])
            )
        return parsed.astimezone(timezone.utc).replace(tzinfo=None)
    except (ValueError, OverflowError):
        raise DomainError(
            400, "invalid_time", "Provide a valid timestamp with a timezone."
        ) from None


def iso(value):
    return value.replace(tzinfo=timezone.utc).isoformat() if value else None
