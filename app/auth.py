"""JWT issuance, persistent revocation, role checks and shared login policy."""

from datetime import timedelta, timezone
from functools import wraps
from uuid import uuid4

import jwt
from flask import current_app, g, redirect, request, session, url_for

from app import db
from app.errors import DomainError
from app.models import AuthSession, User
from app.services import audit, refresh_expiry, write_transaction
from app.timeutils import utcnow
from app.validation import plain_text, valid_email


def account_fields(name, email, password=None):
    if not isinstance(name, str) or not plain_text(name.strip(), 100):
        raise DomainError(400, "invalid_name", "Enter a name of up to 100 characters.")
    if not isinstance(email, str) or not valid_email(email.strip().lower()):
        raise DomainError(400, "invalid_email", "Enter a valid email address.")
    if password is not None and (
        not isinstance(password, str)
        or not 8 <= len(password) <= 128
        or len(password.encode()) > 72
    ):
        raise DomainError(
            400,
            "invalid_password",
            "Use at least 8 characters and at most 72 UTF-8 bytes for the password.",
        )


def register_user(name, email, password):
    account_fields(name, email, password)
    user = User(name=name.strip(), email=email.strip().lower())
    user.set_password(password)
    with write_transaction():
        db.session.add(user)
        db.session.flush()
        audit(user.id, "account_created", user.id)
        user_id = user.id
    return db.session.get(User, user_id)


def login_user(email, password):
    if (
        not isinstance(email, str)
        or not isinstance(password, str)
        or len(password) > 128
    ):
        raise DomainError(401, "invalid_credentials", "Invalid email or password.")
    email = email.strip().lower()
    user = User.query.filter_by(email=email).first()
    now = utcnow()
    if user and user.locked_until and user.locked_until > now:
        raise DomainError(
            429, "account_locked", "Account locked. Try again in 15 minutes."
        )
    valid = user is not None and user.check_password(password)
    user_id = user.id if user else None
    locked = False
    if user_id is None:
        raise DomainError(401, "invalid_credentials", "Invalid email or password.")
    with write_transaction():
        user = db.session.get(User, user_id)
        now = utcnow()
        if user.locked_until and user.locked_until > now:
            locked = True
        elif valid:
            user.failed_login_attempts = 0
            user.locked_until = None
            if not user.password_hash.startswith("$2"):
                # Upgrade existing Werkzeug hashes only after proof of password.
                if len(password.encode()) > 72:
                    raise DomainError(
                        400,
                        "password_reset_required",
                        "Reset the legacy password to 72 UTF-8 bytes or fewer.",
                    )
                user.set_password(password)
            token = issue_token(user_id)
            audit(user_id, "login_succeeded")
        else:
            if user.locked_until:
                user.failed_login_attempts = 0
                user.locked_until = None
            user.failed_login_attempts += 1
            if user.failed_login_attempts >= 5:
                user.locked_until = now + timedelta(minutes=15)
                locked = True
                audit(user_id, "account_locked")
            else:
                audit(user_id, "login_failed")
    if locked:
        raise DomainError(
            429, "account_locked", "Account locked. Try again in 15 minutes."
        )
    if not valid:
        raise DomainError(401, "invalid_credentials", "Invalid email or password.")
    return db.session.get(User, user_id), token


def issue_token(user_id):
    """Call inside a write transaction; the returned JWT contains no password/PII."""
    now = utcnow()
    expires = now + timedelta(seconds=current_app.config["JWT_TTL_SECONDS"])
    jti = str(uuid4())
    db.session.add(AuthSession(jti=jti, user_id=user_id, expires_at=expires))
    return jwt.encode(
        dict(
            sub=str(user_id),
            jti=jti,
            iat=int(now.replace(tzinfo=timezone.utc).timestamp()),
            nbf=int(now.replace(tzinfo=timezone.utc).timestamp()),
            exp=int(expires.replace(tzinfo=timezone.utc).timestamp()),
            iss=current_app.config["JWT_ISSUER"],
            aud=current_app.config["JWT_AUDIENCE"],
        ),
        current_app.config["JWT_SECRET_KEY"],
        algorithm="HS256",
    )


def authenticate(token):
    try:
        claims = jwt.decode(
            token,
            current_app.config["JWT_SECRET_KEY"],
            algorithms=["HS256"],
            issuer=current_app.config["JWT_ISSUER"],
            audience=current_app.config["JWT_AUDIENCE"],
            options={"require": ["sub", "jti", "iat", "nbf", "exp", "iss", "aud"]},
        )
        user_id = int(claims["sub"])
    except (jwt.InvalidTokenError, ValueError, TypeError):
        raise DomainError(
            401, "invalid_token", "A valid, unexpired access token is required."
        ) from None
    record = db.session.get(AuthSession, claims["jti"])
    user = db.session.get(User, user_id)
    if (
        record is None
        or record.user_id != user_id
        or record.revoked_at
        or record.expires_at <= utcnow()
        or user is None
    ):
        raise DomainError(401, "revoked_token", "This session is no longer active.")
    g.current_user, g.token_jti = user, claims["jti"]
    return user


def protected(admin=False, api=False):
    def decorate(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            from app.errors import wants_json

            use_api = wants_json() if api is None else api
            if use_api:
                header = request.headers.get("Authorization", "")
                token = header[7:] if header.startswith("Bearer ") else None
            else:
                token = session.get("access_token")
            try:
                user = authenticate(token)
            except DomainError:
                if use_api:
                    raise
                session.clear()
                return redirect(url_for("main.login"))
            if admin and user.role != "admin":
                raise DomainError(403, "forbidden", "Access denied")
            if not use_api:
                session.update(
                    user_id=user.id, user_name=user.name, user_role=user.role
                )
            refresh_expiry()
            return view(*args, **kwargs)

        return wrapped

    return decorate


def revoke_current():
    jti = g.token_jti
    user_id = g.current_user.id
    with write_transaction():
        record = db.session.get(AuthSession, jti)
        if record and record.revoked_at is None:
            record.revoked_at = utcnow()
            audit(user_id, "logout")
