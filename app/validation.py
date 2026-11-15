"""Server-side validation shared by the browser form handlers.

Validate structured values; keep Jinja autoescaping enabled for displayed text.
Never interpolate user input into SQL.
"""

from decimal import Decimal, InvalidOperation
import re


def plain_text(value, max_length):
    return (
        bool(value)
        and len(value) <= max_length
        and all(
            character.isprintable() and character not in "<>" for character in value
        )
    )


def valid_email(value):
    local = value.partition("@")[0]
    return (
        len(value) <= 120
        and re.fullmatch(
            r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@"
            r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
            r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+",
            value,
        )
        is not None
        and ".." not in value
        and (len(local) <= 64 and not local.startswith(".") and not local.endswith("."))
    )


def valid_vehicle_number(value):
    return re.fullmatch(r"[A-Z0-9][A-Z0-9 -]{1,18}[A-Z0-9]", value) is not None


def parse_rate(value):
    try:
        rate = Decimal(value)
        if not rate.is_finite() or not Decimal("0") < rate <= Decimal("1000000"):
            return None
        if rate != rate.quantize(Decimal("0.01")):
            return None
        return float(rate)
    except (InvalidOperation, ValueError):
        return None


def valid_slot(slot_number, zone, vehicle_type, rate):
    return (
        re.fullmatch(r"[A-Z0-9][A-Z0-9 -]{0,19}", slot_number) is not None
        and plain_text(zone, 50)
        and vehicle_type in {"two-wheeler", "four-wheeler"}
        and rate is not None
    )
