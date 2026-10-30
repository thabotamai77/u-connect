import hmac
import os
import re
import secrets
import smtplib
import sqlite3
from contextlib import closing
from datetime import timedelta
from email.message import EmailMessage
from pathlib import Path
from urllib.parse import quote

from flask import Flask, current_app, jsonify, request, send_from_directory, session
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from werkzeug.security import check_password_hash, generate_password_hash


FRONTEND_DIR = Path(__file__).resolve().parents[1] / "frontend"
SCHEMA = """
CREATE TABLE IF NOT EXISTS schools (
    id INTEGER PRIMARY KEY,
    slug TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    school_id INTEGER NOT NULL REFERENCES schools(id),
    email TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'student' CHECK (role IN ('student', 'administrator')),
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
    verified_at TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
CREATE TABLE IF NOT EXISTS support_requests (
    id TEXT PRIMARY KEY,
    school_id INTEGER NOT NULL REFERENCES schools(id),
    user_id INTEGER NOT NULL REFERENCES users(id),
    category TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'New'
        CHECK (status IN ('New', 'In review', 'Approved', 'Resolved', 'Rejected')),
    assigned TEXT NOT NULL DEFAULT 'Unassigned',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
CREATE INDEX IF NOT EXISTS support_requests_school_created
    ON support_requests (school_id, created_at DESC);
CREATE INDEX IF NOT EXISTS support_requests_user_created
    ON support_requests (user_id, created_at DESC);
CREATE TABLE IF NOT EXISTS login_attempts (
    email TEXT NOT NULL,
    remote_addr TEXT NOT NULL,
    attempted_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS login_attempts_lookup
    ON login_attempts (email, remote_addr, attempted_at);
"""

REQUEST_CATEGORIES = {
    "Academic support",
    "Wellbeing and safety",
    "Practical support",
    "Digital access",
}
REQUEST_STATUSES = {"New", "In review", "Approved", "Resolved", "Rejected"}
ASSIGNMENT_TEAMS = {
    "Unassigned",
    "Support team",
    "Academic team",
    "Wellbeing team",
    "Practical support team",
}
EMAIL_PATTERN = re.compile(r"^[^@\s]{1,64}@[^@\s.]+(?:\.[^@\s.]+)+$")
DUMMY_PASSWORD_HASH = generate_password_hash(secrets.token_urlsafe(32))


def connect_db():
    connection = sqlite3.connect(current_app.config["DATABASE"], timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 10000")
    return connection


def init_db():
    with closing(connect_db()) as connection:
        connection.executescript(SCHEMA)
        connection.commit()


def json_error(message, status, code=None):
    payload = {"error": message}
    if code:
        payload["code"] = code
    return jsonify(payload), status


def current_user():
    user_id = session.get("user_id")
    if not user_id:
        return None
    with closing(connect_db()) as connection:
        row = connection.execute(
            """SELECT id, school_id, email, name, role, active, verified_at
               FROM users WHERE id = ?""",
            (user_id,),
        ).fetchone()
    if row is None or not row["active"] or not row["verified_at"]:
        session.clear()
        return None
    return dict(row)


def csrf_token():
    token = session.get("csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        session["csrf_token"] = token
    return token


def verification_serializer():
    return URLSafeTimedSerializer(
        current_app.config["SECRET_KEY"], salt="uconnect-email-verification"
    )


def send_verification_email(email, token):
    host = current_app.config["SMTP_HOST"]
    public_url = current_app.config["PUBLIC_BASE_URL"].rstrip("/")
    sender = current_app.config["EMAIL_FROM"]
    if not host or not public_url.startswith("https://") or "example.invalid" in sender:
        raise RuntimeError("Email delivery, sender, and a public HTTPS URL are not configured.")

    message = EmailMessage()
    message["Subject"] = "Verify your U-Connect account"
    message["From"] = sender
    message["To"] = email
    message.set_content(
        "Verify your U-Connect account by opening this link:\n\n"
        f"{public_url}/#verify={quote(token)}\n\n"
        "This link expires in 24 hours. If you did not create this account, "
        "you can ignore this message."
    )

    port = current_app.config["SMTP_PORT"]
    username = current_app.config["SMTP_USERNAME"]
    password = current_app.config["SMTP_PASSWORD"]
    if current_app.config["SMTP_USE_SSL"]:
        smtp = smtplib.SMTP_SSL(host, port, timeout=15)
    else:
        smtp = smtplib.SMTP(host, port, timeout=15)
    with smtp:
        if not current_app.config["SMTP_USE_SSL"]:
            smtp.starttls()
        if username:
            smtp.login(username, password)
        smtp.send_message(message)


def deliver_verification(email):
    token = verification_serializer().dumps({"email": email})
    try:
        send_verification_email(email, token)
    except (OSError, RuntimeError, smtplib.SMTPException) as error:
        current_app.logger.error("Could not deliver verification email: %s", error)
        return False
    return True


def require_authentication():
    user = current_user()
    if user is None:
        return None, json_error("Sign in to continue.", 401, "authentication_required")
    return user, None


def create_app(test_config=None):
    instance_dir = Path(__file__).resolve().parent / "instance"
    app = Flask(__name__, static_folder=None)
    app.config.from_mapping(
        SECRET_KEY=os.environ.get("UCONNECT_SECRET_KEY"),
        DATABASE=os.environ.get(
            "UCONNECT_DATABASE", str(instance_dir / "uconnect.sqlite3")
        ),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.environ.get("UCONNECT_COOKIE_SECURE", "1") == "1",
        PERMANENT_SESSION_LIFETIME=timedelta(hours=8),
        MAX_CONTENT_LENGTH=16 * 1024,
        PUBLIC_BASE_URL=os.environ.get("UCONNECT_PUBLIC_BASE_URL", ""),
        SMTP_HOST=os.environ.get("UCONNECT_SMTP_HOST", ""),
        SMTP_PORT=int(os.environ.get("UCONNECT_SMTP_PORT", "587")),
        SMTP_USERNAME=os.environ.get("UCONNECT_SMTP_USERNAME", ""),
        SMTP_PASSWORD=os.environ.get("UCONNECT_SMTP_PASSWORD", ""),
        SMTP_USE_SSL=os.environ.get("UCONNECT_SMTP_USE_SSL", "0") == "1",
        EMAIL_FROM=os.environ.get("UCONNECT_EMAIL_FROM", "U-Connect <no-reply@example.invalid>"),
    )
    if test_config:
        app.config.update(test_config)
    if not app.config["SECRET_KEY"]:
        raise RuntimeError("Set UCONNECT_SECRET_KEY to a long, random secret before starting.")

    Path(app.config["DATABASE"]).parent.mkdir(parents=True, exist_ok=True)
    with app.app_context():
        init_db()

    @app.after_request
    def set_security_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        if request.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "connect-src 'self'; img-src 'self' data:; font-src 'self'; "
            "object-src 'none'; "
            "base-uri 'self'; form-action 'self'; frame-ancestors 'none'"
        )
        if request.is_secure:
            response.headers["Strict-Transport-Security"] = "max-age=31536000"
        return response

    @app.before_request
    def protect_api_mutations():
        if request.path.startswith("/api/") and request.method in {
            "POST",
            "PATCH",
            "PUT",
            "DELETE",
        }:
            expected = session.get("csrf_token", "")
            supplied = request.headers.get("X-CSRF-Token", "")
            if not expected or not supplied or not hmac.compare_digest(expected, supplied):
                return json_error("Refresh the page and try again.", 400, "csrf_failed")
        return None

    @app.get("/")
    def home():
        return send_from_directory(FRONTEND_DIR, "index.html")

    @app.get("/static/<path:filename>")
    def public_asset(filename):
        if filename not in {"app.js", "style.css"}:
            return json_error("Asset not found.", 404)
        return send_from_directory(FRONTEND_DIR, filename)

    @app.get("/api/health")
    def health():
        return jsonify({"status": "online"})

    @app.get("/api/schools")
    def schools():
        with closing(connect_db()) as connection:
            rows = connection.execute(
                "SELECT slug, name FROM schools ORDER BY name"
            ).fetchall()
        return jsonify({"schools": [dict(row) for row in rows]})

    @app.get("/api/session")
    def session_info():
        return jsonify({"csrf_token": csrf_token(), "user": current_user()})

    @app.post("/api/auth/register")
    def register():
        data = request.get_json(silent=True) or {}
        name = data.get("name", "")
        name = name.strip() if isinstance(name, str) else ""
        email = str(data.get("email", "")).strip().lower()
        password = data.get("password")
        school_slug = str(data.get("school", "")).strip().lower()
        if not 1 <= len(name) <= 80:
            return json_error("Enter a name between 1 and 80 characters.", 400)
        if not EMAIL_PATTERN.fullmatch(email):
            return json_error("Enter a valid email address.", 400)
        if not isinstance(password, str) or not 12 <= len(password) <= 128:
            return json_error("Password must be between 12 and 128 characters.", 400)
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,62}", school_slug):
            return json_error("Choose a valid school.", 400)

        with closing(connect_db()) as connection:
            school = connection.execute(
                "SELECT id FROM schools WHERE slug = ?", (school_slug,)
            ).fetchone()
            if school is None:
                return json_error("Choose a listed school.", 400)
            try:
                connection.execute(
                    """INSERT INTO users (school_id, email, name, password_hash)
                       VALUES (?, ?, ?, ?)""",
                    (school["id"], email, name, generate_password_hash(password)),
                )
                connection.commit()
            except sqlite3.IntegrityError:
                return json_error("An account with that email already exists.", 409)

        if not deliver_verification(email):
            return json_error(
                "Your account was created, but verification email could not be sent. "
                "Contact the administrator after email delivery is configured.",
                503,
                "email_delivery_unavailable",
            )
        return jsonify({"message": "Check your email to verify your account."}), 201

    @app.post("/api/auth/verify")
    def verify_email():
        data = request.get_json(silent=True) or {}
        token = data.get("token")
        if not isinstance(token, str) or not token:
            return json_error("A verification token is required.", 400)
        try:
            payload = verification_serializer().loads(token, max_age=86400)
        except SignatureExpired:
            return json_error("This verification link has expired.", 400)
        except BadSignature:
            return json_error("This verification link is invalid.", 400)
        email = payload.get("email")
        with closing(connect_db()) as connection:
            cursor = connection.execute(
                """UPDATE users SET verified_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                   WHERE email = ? AND verified_at IS NULL AND active = 1""",
                (email,),
            )
            connection.commit()
        if cursor.rowcount == 0:
            return json_error("This account is already verified or unavailable.", 400)
        return jsonify({"message": "Email verified. You can now sign in."})

    @app.post("/api/auth/resend-verification")
    def resend_verification():
        data = request.get_json(silent=True) or {}
        email = str(data.get("email", "")).strip().lower()
        if not EMAIL_PATTERN.fullmatch(email):
            return json_error("Enter a valid email address.", 400)
        with closing(connect_db()) as connection:
            row = connection.execute(
                "SELECT verified_at, active FROM users WHERE email = ?", (email,)
            ).fetchone()
        if row and row["active"] and not row["verified_at"] and not deliver_verification(email):
            return json_error(
                "Verification email could not be sent. Contact the administrator.",
                503,
                "email_delivery_unavailable",
            )
        return jsonify({"message": "If the account needs verification, an email will be sent."})

    @app.post("/api/auth/login")
    def login():
        data = request.get_json(silent=True) or {}
        email = str(data.get("email", "")).strip().lower()
        password = data.get("password")
        remote_addr = request.remote_addr or ""
        if not EMAIL_PATTERN.fullmatch(email) or not isinstance(password, str):
            return json_error("Email or password is incorrect.", 401, "invalid_credentials")

        with closing(connect_db()) as connection:
            connection.execute(
                "DELETE FROM login_attempts WHERE attempted_at < strftime('%s', 'now') - 900"
            )
            failures = connection.execute(
                """SELECT COUNT(*) AS count FROM login_attempts
                   WHERE email = ? AND remote_addr = ?
                     AND attempted_at >= strftime('%s', 'now') - 900""",
                (email, remote_addr),
            ).fetchone()["count"]
            if failures >= 5:
                return json_error(
                    "Too many sign-in attempts. Try again in 15 minutes.",
                    429,
                    "login_rate_limited",
                )
            user = connection.execute(
                "SELECT * FROM users WHERE email = ?", (email,)
            ).fetchone()
            password_hash = user["password_hash"] if user else DUMMY_PASSWORD_HASH
            password_matches = check_password_hash(password_hash, password)
            valid = user is not None and password_matches
            if not valid or not user["active"] or not user["verified_at"]:
                connection.execute(
                    "INSERT INTO login_attempts (email, remote_addr, attempted_at) "
                    "VALUES (?, ?, strftime('%s', 'now'))",
                    (email, remote_addr),
                )
                connection.commit()
                if valid and not user["verified_at"] and user["active"]:
                    return json_error(
                        "Verify your email before signing in.",
                        403,
                        "email_not_verified",
                    )
                return json_error("Email or password is incorrect.", 401, "invalid_credentials")
            connection.execute(
                "DELETE FROM login_attempts WHERE email = ? AND remote_addr = ?",
                (email, remote_addr),
            )
            connection.commit()

        session.clear()
        session["user_id"] = user["id"]
        session.permanent = True
        token = csrf_token()
        return jsonify(
            {
                "csrf_token": token,
                "user": {
                    "id": user["id"],
                    "school_id": user["school_id"],
                    "email": user["email"],
                    "name": user["name"],
                    "role": user["role"],
                },
            }
        )

    @app.post("/api/auth/logout")
    def logout():
        session.clear()
        return jsonify({"message": "Signed out."})

    @app.patch("/api/profile")
    def update_profile():
        user, error = require_authentication()
        if error:
            return error
        data = request.get_json(silent=True) or {}
        name = data.get("name", "")
        name = name.strip() if isinstance(name, str) else ""
        if not 1 <= len(name) <= 80:
            return json_error("Enter a name between 1 and 80 characters.", 400)
        with closing(connect_db()) as connection:
            connection.execute(
                "UPDATE users SET name = ? WHERE id = ?", (name, user["id"])
            )
            connection.commit()
        return jsonify({"name": name})

    @app.get("/api/requests")
    def list_own_requests():
        user, error = require_authentication()
        if error:
            return error
        with closing(connect_db()) as connection:
            rows = connection.execute(
                """SELECT id, category, description, status, assigned,
                          created_at AS created
                   FROM support_requests
                   WHERE user_id = ? AND school_id = ?
                   ORDER BY created_at DESC""",
                (user["id"], user["school_id"]),
            ).fetchall()
        return jsonify({"requests": [dict(row) for row in rows]})

    @app.post("/api/requests")
    def create_request():
        user, error = require_authentication()
        if error:
            return error
        data = request.get_json(silent=True) or {}
        category = data.get("category")
        description = data.get("description", "")
        if not isinstance(category, str) or category not in REQUEST_CATEGORIES:
            return json_error("Choose a valid support category.", 400)
        if not isinstance(description, str) or len(description.strip()) > 600:
            return json_error("Description must be at most 600 characters.", 400)
        request_id = f"UC-{secrets.token_hex(4).upper()}"
        with closing(connect_db()) as connection:
            connection.execute(
                """INSERT INTO support_requests
                   (id, school_id, user_id, category, description)
                   VALUES (?, ?, ?, ?, ?)""",
                (
                    request_id,
                    user["school_id"],
                    user["id"],
                    category,
                    description.strip(),
                ),
            )
            connection.commit()
        return jsonify({"id": request_id, "status": "New"}), 201

    @app.get("/api/admin/requests")
    def list_school_requests():
        user, error = require_authentication()
        if error:
            return error
        if user["role"] != "administrator":
            return json_error("Administrator access is required.", 403, "forbidden")
        with closing(connect_db()) as connection:
            rows = connection.execute(
                """SELECT r.id, u.name, r.category, r.description,
                          r.status, r.assigned, r.created_at AS created
                   FROM support_requests r
                   JOIN users u ON u.id = r.user_id AND u.school_id = r.school_id
                   WHERE r.school_id = ?
                   ORDER BY r.created_at DESC""",
                (user["school_id"],),
            ).fetchall()
        return jsonify({"requests": [dict(row) for row in rows]})

    @app.patch("/api/admin/requests/<request_id>")
    def update_school_request(request_id):
        user, error = require_authentication()
        if error:
            return error
        if user["role"] != "administrator":
            return json_error("Administrator access is required.", 403, "forbidden")
        data = request.get_json(silent=True) or {}
        updates = {}
        if "status" in data:
            if not isinstance(data["status"], str) or data["status"] not in REQUEST_STATUSES:
                return json_error("Choose a valid request status.", 400)
            updates["status"] = data["status"]
        if "assigned" in data:
            if not isinstance(data["assigned"], str) or data["assigned"] not in ASSIGNMENT_TEAMS:
                return json_error("Choose a valid support team.", 400)
            updates["assigned"] = data["assigned"]
        if not updates:
            return json_error("Provide a status or assignment update.", 400)

        fields = ", ".join(f"{field} = ?" for field in updates)
        values = list(updates.values())
        values.extend([request_id, user["school_id"]])
        with closing(connect_db()) as connection:
            cursor = connection.execute(
                f"""UPDATE support_requests SET {fields},
                       updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                   WHERE id = ? AND school_id = ?""",
                values,
            )
            connection.commit()
        if cursor.rowcount == 0:
            return json_error("Request not found in your school.", 404)
        return jsonify({"message": "Request updated."})

    @app.cli.command("create-school")
    def create_school_command():
        """Create a school tenant for registration and administration."""
        import click

        name = click.prompt("School name").strip()
        slug = click.prompt("School registration code").strip().lower()
        if not name or not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,62}", slug):
            raise click.ClickException("Enter a school name and a valid code (2-63 characters).")
        try:
            with closing(connect_db()) as connection:
                connection.execute(
                    "INSERT INTO schools (slug, name) VALUES (?, ?)", (slug, name)
                )
                connection.commit()
        except sqlite3.IntegrityError as error:
            raise click.ClickException("That school code already exists.") from error
        click.echo(f"Created school {name} ({slug}).")

    @app.cli.command("create-admin")
    def create_admin_command():
        """Create a verified administrator using a private terminal prompt."""
        import click

        email = click.prompt("Administrator email").strip().lower()
        school_slug = click.prompt("School registration code").strip().lower()
        password = click.prompt(
            "Administrator password", hide_input=True, confirmation_prompt=True
        )
        if not EMAIL_PATTERN.fullmatch(email) or not 12 <= len(password) <= 128:
            raise click.ClickException("Use a valid email and a 12-128 character password.")
        with closing(connect_db()) as connection:
            school = connection.execute(
                "SELECT id FROM schools WHERE slug = ?", (school_slug,)
            ).fetchone()
            if school is None:
                raise click.ClickException("School code not found.")
            try:
                connection.execute(
                    """INSERT INTO users
                       (school_id, email, name, password_hash, role, verified_at)
                       VALUES (?, ?, ?, ?, 'administrator',
                               strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))""",
                    (
                        school["id"],
                        email,
                        email.split("@", 1)[0],
                        generate_password_hash(password),
                    ),
                )
                connection.commit()
            except sqlite3.IntegrityError as error:
                raise click.ClickException("An account with that email already exists.") from error
        click.echo("Administrator account created.")

    return app


if __name__ == "__main__":
    create_app().run(debug=False, host="127.0.0.1", port=5000)
