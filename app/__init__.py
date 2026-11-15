"""Application factory and deployment configuration."""

import json
import logging
import os
from pathlib import Path
import secrets
import time

import click
from flask import Flask, g, jsonify, request
from flask_sqlalchemy import SQLAlchemy
from flask_wtf.csrf import CSRFProtect
from sqlalchemy import event
from werkzeug.exceptions import HTTPException


db = SQLAlchemy()
csrf = CSRFProtect()


def migrate_database():
    from alembic import command
    from alembic.config import Config

    config = Config()
    config.set_main_option(
        "script_location", str(Path(__file__).parent.parent / "migrations")
    )
    with db.engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "head")


def create_app(test_config=None):
    app = Flask(__name__, static_folder="../static")
    key = os.environ.get("VPS_SECRET_KEY") or secrets.token_hex(32)
    app.config.update(
        SECRET_KEY=key,
        JWT_SECRET_KEY=key,
        JWT_ISSUER="vehicle-parking-system",
        JWT_AUDIENCE="vps-clients",
        JWT_TTL_SECONDS=3600,
        SQLALCHEMY_DATABASE_URI=os.environ.get("VPS_DATABASE_URL")
        or "sqlite:///" + str(Path(app.instance_path) / "parking.db"),
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        SQLALCHEMY_ENGINE_OPTIONS={"connect_args": {"timeout": 30}},
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.environ.get("VPS_COOKIE_SECURE") == "1",
        REPORT_TIMEZONE="Asia/Kolkata",
        BCRYPT_ROUNDS=12,
        MAX_CONTENT_LENGTH=64 * 1024,
        AUTO_MIGRATE=True,
    )
    if test_config:
        app.config.update(test_config)
        if "JWT_SECRET_KEY" not in test_config:
            app.config["JWT_SECRET_KEY"] = app.config["SECRET_KEY"]
    Path(app.instance_path).mkdir(parents=True, exist_ok=True)
    db.init_app(app)
    csrf.init_app(app)
    with app.app_context():
        from app import models

        @event.listens_for(db.engine, "connect")
        def sqlite_settings(connection, _record):
            cursor = connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA busy_timeout=30000")
            cursor.close()

        if app.config["AUTO_MIGRATE"]:
            migrate_database()
            from app.services import seed_defaults

            seed_defaults()

    from app.routes import main
    from app.api import api
    from app.errors import DomainError, wants_json

    app.register_blueprint(main)
    app.register_blueprint(api)
    csrf.exempt(api)  # API accepts Authorization: Bearer only, never cookies.

    @app.before_request
    def request_start():
        g.started_at = time.perf_counter()

    @app.after_request
    def response_headers(response):
        duration = round(
            (time.perf_counter() - getattr(g, "started_at", time.perf_counter()))
            * 1000,
            3,
        )
        response.headers.update(
            {
                "X-Content-Type-Options": "nosniff",
                "X-Frame-Options": "DENY",
                "Referrer-Policy": "same-origin",
                "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'",
            }
        )
        if request.is_secure:
            response.headers["Strict-Transport-Security"] = (
                "max-age=31536000; includeSubDomains"
            )
        if request.path != "/static/style.css":
            app.logger.info(
                json.dumps(
                    {
                        "event": "request",
                        "method": request.method,
                        "route": (
                            request.url_rule.rule if request.url_rule else "unmatched"
                        ),
                        "status": response.status_code,
                        "duration_ms": duration,
                    }
                )
            )
        if request.path.startswith("/auth") or getattr(g, "current_user", None):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.errorhandler(DomainError)
    def domain_error(error):
        db.session.rollback()
        app.logger.warning(
            json.dumps(
                {"event": "request_denied", "code": error.code, "status": error.status}
            )
        )
        if wants_json():
            return (
                jsonify(error={"code": error.code, "message": error.message}),
                error.status,
            )
        from flask import render_template

        return (
            render_template("error.html", code=error.status, message=error.message),
            error.status,
        )

    @app.errorhandler(HTTPException)
    def http_error(error):
        return domain_error(
            DomainError(
                error.code,
                error.name.lower().replace(" ", "_"),
                "Invalid request" if error.code == 400 else error.name,
            )
        )

    @app.errorhandler(Exception)
    def internal_error(error):
        db.session.rollback()
        app.logger.exception("Unhandled application failure")
        if app.testing:
            raise error
        return domain_error(
            DomainError(500, "internal_error", "An unexpected error occurred.")
        )

    @app.cli.command("db-upgrade")
    def db_upgrade():
        """Apply reviewed versioned migrations before serving production traffic."""
        migrate_database()
        from app.services import seed_defaults

        seed_defaults()
        click.echo("Database is at the latest revision.")

    @app.cli.command("expire-reservations")
    def expire_command():
        from app.services import write_transaction, expire_reservations

        with write_transaction():
            count = expire_reservations()
        click.echo(f"Expired {count} reservations.")

    @app.cli.command("create-admin")
    @click.option("--email", required=True)
    @click.password_option()
    def create_admin(email, password):
        from app.auth import register_user
        from app.services import write_transaction

        user = register_user("System Administrator", email, password)
        user_id = user.id
        with write_transaction():
            db.session.get(models.User, user_id).role = "admin"
        click.echo(
            "Administrator created. Existing accounts are never silently promoted."
        )

    from app.timeutils import local_time

    app.jinja_env.filters["localtime"] = local_time
    app.logger.setLevel(logging.INFO)
    return app
