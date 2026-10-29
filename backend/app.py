import hmac
import os
import re
import secrets
import smtplib
import sqlite3
from contextlib import closing
from datetime import date, timedelta
from email.message import EmailMessage
from pathlib import Path
from urllib.parse import quote

from flask import Flask, current_app, jsonify, request, send_from_directory, session
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import check_password_hash, generate_password_hash

BASE_DIR = Path(__file__).resolve().parent.parent
FRONTEND_DIR = BASE_DIR / "frontend"
DEFAULT_DB_PATH = BASE_DIR / "database" / "unconnect.db"
EMAIL_PATTERN = re.compile(r"^[^@\s]{1,64}@[^@\s.]+(?:\.[^@\s.]+)+$")
REQUEST_STATUSES = {"New", "In review", "Approved", "Resolved", "Rejected"}
ASSIGNMENT_TEAMS = {
    "Unassigned",
    "Support team",
    "Academic team",
    "Wellbeing team",
    "Practical support team",
}
DUMMY_PASSWORD_HASH = generate_password_hash(secrets.token_urlsafe(32))

CAPS_SUBJECTS = {
    8: [("English Home Language", True), ("Afrikaans or isiZulu", True), ("Mathematics", True), ("Natural Sciences", True), ("Social Sciences", True), ("Technology", True), ("Life Orientation", True)],
    9: [("English Home Language", True), ("Afrikaans or isiZulu", True), ("Mathematics", True), ("Natural Sciences", True), ("Social Sciences", True), ("Technology", True), ("Life Orientation", True)],
    10: [("English Home Language", True), ("Afrikaans or isiZulu", True), ("Mathematics", True), ("Life Orientation", True), ("Physical Sciences", False), ("Life Sciences", False), ("Accounting", False), ("Information Technology", False)],
    11: [("English Home Language", True), ("Afrikaans or isiZulu", True), ("Mathematics", True), ("Life Orientation", True), ("Physical Sciences", False), ("Life Sciences", False), ("Accounting", False), ("Information Technology", False)],
    12: [("English Home Language", True), ("Afrikaans or isiZulu", True), ("Mathematics", True), ("Life Orientation", True), ("Physical Sciences", False), ("Life Sciences", False), ("Accounting", False), ("Information Technology", False)],
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS schools (
    id INTEGER PRIMARY KEY,
    slug TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL
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
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS login_attempts (
    email TEXT NOT NULL,
    remote_addr TEXT NOT NULL,
    attempted_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS login_attempts_lookup
    ON login_attempts (email, remote_addr, attempted_at);
CREATE TABLE IF NOT EXISTS students (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    full_name TEXT NOT NULL,
    email TEXT UNIQUE,
    phone TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    user_id INTEGER REFERENCES users(id),
    school_id INTEGER REFERENCES schools(id)
);
CREATE TABLE IF NOT EXISTS incidents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    incident_type TEXT NOT NULL,
    description TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    user_id INTEGER REFERENCES users(id),
    school_id INTEGER REFERENCES schools(id),
    status TEXT NOT NULL DEFAULT 'New'
);
CREATE TABLE IF NOT EXISTS announcements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    message TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS progress (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER NOT NULL,
    subject TEXT NOT NULL,
    percentage INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(student_id) REFERENCES students(id)
);
CREATE TABLE IF NOT EXISTS papers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    grade INTEGER NOT NULL,
    subject TEXT NOT NULL,
    title TEXT NOT NULL,
    file_url TEXT NOT NULL,
    memo_url TEXT,
    year INTEGER NOT NULL,
    term TEXT,
    school_id INTEGER REFERENCES schools(id)
);
CREATE TABLE IF NOT EXISTS timetable (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    grade INTEGER NOT NULL,
    day TEXT NOT NULL,
    start_time TEXT NOT NULL,
    end_time TEXT NOT NULL,
    subject TEXT NOT NULL,
    venue TEXT,
    user_id INTEGER REFERENCES users(id),
    school_id INTEGER REFERENCES schools(id)
);
CREATE TABLE IF NOT EXISTS exams (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    grade INTEGER NOT NULL,
    subject TEXT NOT NULL,
    exam_date TEXT NOT NULL,
    start_time TEXT NOT NULL,
    duration_min INTEGER NOT NULL,
    venue TEXT,
    user_id INTEGER REFERENCES users(id),
    school_id INTEGER REFERENCES schools(id)
);
"""


def connect_db():
    connection = sqlite3.connect(current_app.config["DATABASE"], timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 10000")
    return connection


def init_db():
    with closing(connect_db()) as connection:
        connection.executescript(SCHEMA)
        migrations = {
            "students": {"user_id": "INTEGER REFERENCES users(id)", "school_id": "INTEGER REFERENCES schools(id)"},
            "incidents": {
                "user_id": "INTEGER REFERENCES users(id)",
                "school_id": "INTEGER REFERENCES schools(id)",
                "status": "TEXT NOT NULL DEFAULT 'New'",
            },
            "papers": {"school_id": "INTEGER REFERENCES schools(id)"},
            "timetable": {
                "user_id": "INTEGER REFERENCES users(id)",
                "school_id": "INTEGER REFERENCES schools(id)",
            },
            "exams": {
                "user_id": "INTEGER REFERENCES users(id)",
                "school_id": "INTEGER REFERENCES schools(id)",
            },
        }
        for table, columns in migrations.items():
            existing = {
                row["name"] for row in connection.execute(f"PRAGMA table_info({table})")
            }
            for name, definition in columns.items():
                if name not in existing:
                    connection.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")
        connection.execute(
            "CREATE INDEX IF NOT EXISTS students_user ON students(user_id, school_id)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS incidents_school ON incidents(school_id, created_at DESC)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS progress_student ON progress(student_id, updated_at DESC)"
        )
        connection.commit()


def error(message, status, code=None):
    payload = {"error": message}
    if code:
        payload["code"] = code
    return jsonify(payload), status


def get_current_user():
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


def require_user():
    user = get_current_user()
    if user is None:
        return None, error("Sign in to continue.", 401, "authentication_required")
    return user, None


def require_admin():
    user, response = require_user()
    if response:
        return None, response
    if user["role"] != "administrator":
        return None, error("Administrator access is required.", 403, "forbidden")
    return user, None


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
    sender = current_app.config["EMAIL_FROM"]
    public_url = current_app.config["PUBLIC_BASE_URL"].rstrip("/")
    host = current_app.config["SMTP_HOST"]
    if not host or not public_url.startswith("https://") or "example.invalid" in sender:
        raise RuntimeError("Email delivery settings are not configured.")
    message = EmailMessage()
    message["Subject"] = "Verify your U-CONNECT account"
    message["From"] = sender
    message["To"] = email
    message.set_content(
        "Verify your U-CONNECT account using this link (valid for 24 hours):\n\n"
        f"{public_url}/#verify={quote(token)}\n\n"
        "If you did not create this account, ignore this email."
    )
    port = current_app.config["SMTP_PORT"]
    if current_app.config["SMTP_USE_SSL"]:
        smtp = smtplib.SMTP_SSL(host, port, timeout=15)
    else:
        smtp = smtplib.SMTP(host, port, timeout=15)
    with smtp:
        if not current_app.config["SMTP_USE_SSL"]:
            smtp.starttls()
        if current_app.config["SMTP_USERNAME"]:
            smtp.login(
                current_app.config["SMTP_USERNAME"],
                current_app.config["SMTP_PASSWORD"],
            )
        smtp.send_message(message)


def deliver_verification(email):
    try:
        send_verification_email(
            email, verification_serializer().dumps({"email": email})
        )
    except (OSError, RuntimeError, smtplib.SMTPException) as exc:
        current_app.logger.error("Could not deliver verification email: %s", exc)
        return False
    return True


def learn_grade():
    try:
        return max(8, min(12, int(request.args.get("grade", 12))))
    except (TypeError, ValueError):
        return 12


def build_learning_plan(progress_rows):
    progress = {}
    for row in progress_rows:
        progress[row["subject"]] = max(0, min(100, int(row["percentage"])))
    if not progress:
        return {
            "overall_progress": 0,
            "focus_subject": "Mathematics",
            "focus_percentage": 0,
            "recommendation": "Start with a short Mathematics exercise, then record your result.",
            "steps": [
                "Study one concept for 15 minutes.",
                "Complete two practice questions.",
                "Record your progress after studying.",
            ],
            "reason": "No progress has been recorded yet, so the coach starts with a simple practice session.",
        }
    weakest, low = min(progress.items(), key=lambda item: item[1])
    strongest, high = max(progress.items(), key=lambda item: item[1])
    if low < 50:
        recommendation = f"Review the basics of {weakest}, then complete three guided exercises."
    elif low < 75:
        recommendation = f"Practise {weakest} with two exam-style questions and review your mistakes."
    else:
        recommendation = f"Challenge yourself with an advanced {weakest} question and explain your solution."
    return {
        "overall_progress": round(sum(progress.values()) / len(progress)),
        "focus_subject": weakest,
        "focus_percentage": low,
        "strongest_subject": strongest,
        "strongest_percentage": high,
        "recommendation": recommendation,
        "steps": [
            f"Spend 15 minutes reviewing {weakest}.",
            "Complete two practice questions without checking the answers.",
            f"Use {strongest} for a 10-minute confidence-building recap.",
        ],
        "reason": "The coach prioritises the subject with the lowest recorded mastery and uses your strongest subject to maintain momentum.",
    }


def create_app(test_config=None):
    app = Flask(__name__)
    app.config.from_mapping(
        SECRET_KEY=os.environ.get("UCONNECT_SECRET_KEY"),
        DATABASE=os.environ.get("UCONNECT_DATABASE", str(DEFAULT_DB_PATH)),
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
        EMAIL_FROM=os.environ.get(
            "UCONNECT_EMAIL_FROM", "U-CONNECT <no-reply@example.invalid>"
        ),
    )
    if test_config:
        app.config.update(test_config)
    if not app.config["SECRET_KEY"]:
        raise RuntimeError("Set UCONNECT_SECRET_KEY to a strong random secret.")
    Path(app.config["DATABASE"]).parent.mkdir(parents=True, exist_ok=True)
    with app.app_context():
        init_db()

    @app.after_request
    def security_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        if request.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com; img-src 'self' data:; "
            "connect-src 'self'; object-src 'none'; base-uri 'self'; "
            "form-action 'self'; frame-ancestors 'none'"
        )
        if request.is_secure:
            response.headers["Strict-Transport-Security"] = "max-age=31536000"
        return response

    @app.before_request
    def protect_mutations():
        if request.path.startswith("/api/") and request.method in {
            "POST",
            "PUT",
            "PATCH",
            "DELETE",
        }:
            expected = session.get("csrf_token", "")
            supplied = request.headers.get("X-CSRF-Token", "")
            if not expected or not supplied or not hmac.compare_digest(expected, supplied):
                return error("Refresh the page and try again.", 400, "csrf_failed")

    @app.get("/")
    def root():
        return send_from_directory(FRONTEND_DIR, "index.html")

    @app.get("/learn.html")
    def learn_page():
        return send_from_directory(FRONTEND_DIR, "learn.html")

    @app.get("/app/frontend/")
    def frontend_index():
        return send_from_directory(FRONTEND_DIR, "index.html")

    @app.get("/app/frontend/<path:filename>")
    @app.get("/<path:filename>")
    def frontend_asset(filename):
        if filename not in {
            "app.js",
            "admin.html",
            "admin.js",
            "auth.js",
            "dashboard.js",
            "index.html",
            "learn.html",
            "learn.js",
            "learn.css",
            "style.css",
            "manifest.json",
            "service-worker.js",
        }:
            return error("Asset not found.", 404)
        return send_from_directory(FRONTEND_DIR, filename)

    @app.get("/api/session")
    def session_info():
        return jsonify({"csrf_token": csrf_token(), "user": get_current_user()})

    @app.get("/api/schools")
    def schools():
        with closing(connect_db()) as connection:
            rows = connection.execute(
                "SELECT slug, name FROM schools ORDER BY name"
            ).fetchall()
        return jsonify({"schools": [dict(row) for row in rows]})

    @app.post("/api/auth/register")
    def register():
        payload = request.get_json(silent=True) or {}
        name, email = payload.get("name"), payload.get("email")
        password, school_slug = payload.get("password"), payload.get("school")
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 80:
            return error("Enter a name between 1 and 80 characters.", 400)
        if not isinstance(email, str) or not EMAIL_PATTERN.fullmatch(email.strip().lower()):
            return error("Enter a valid email address.", 400)
        email = email.strip().lower()
        if not isinstance(password, str) or not 12 <= len(password) <= 128:
            return error("Password must be between 12 and 128 characters.", 400)
        if not isinstance(school_slug, str) or not re.fullmatch(
            r"[a-z0-9][a-z0-9-]{1,62}", school_slug.lower()
        ):
            return error("Choose a valid school.", 400)
        with closing(connect_db()) as connection:
            school = connection.execute(
                "SELECT id FROM schools WHERE slug = ?", (school_slug.lower(),)
            ).fetchone()
            if school is None:
                return error("Choose a listed school.", 400)
            try:
                cursor = connection.execute(
                    """INSERT INTO users (school_id, email, name, password_hash)
                       VALUES (?, ?, ?, ?)""",
                    (
                        school["id"],
                        email,
                        name.strip(),
                        generate_password_hash(password),
                    ),
                )
                user_id = cursor.lastrowid
                connection.execute(
                    "INSERT INTO students (full_name, email, user_id, school_id) "
                    "VALUES (?, ?, ?, ?)",
                    (name.strip(), email, user_id, school["id"]),
                )
                connection.commit()
            except sqlite3.IntegrityError:
                return error("An account with that email already exists.", 409)
        if not deliver_verification(email):
            return error(
                "Account created, but verification email could not be sent. "
                "Contact the administrator after email delivery is configured.",
                503,
                "email_delivery_unavailable",
            )
        return jsonify({"message": "Check your email to verify your account."}), 201

    @app.post("/api/auth/verify")
    def verify_email():
        token = (request.get_json(silent=True) or {}).get("token")
        if not isinstance(token, str) or not token:
            return error("A verification token is required.", 400)
        try:
            email = verification_serializer().loads(token, max_age=86400)["email"]
        except SignatureExpired:
            return error("This verification link has expired.", 400)
        except (BadSignature, KeyError, TypeError):
            return error("This verification link is invalid.", 400)
        with closing(connect_db()) as connection:
            cursor = connection.execute(
                """UPDATE users SET verified_at = CURRENT_TIMESTAMP
                   WHERE email = ? AND verified_at IS NULL AND active = 1""",
                (email,),
            )
            connection.commit()
        if not cursor.rowcount:
            return error("This account is already verified or unavailable.", 400)
        return jsonify({"message": "Email verified. You can now sign in."})

    @app.post("/api/auth/resend-verification")
    def resend_verification():
        email = (request.get_json(silent=True) or {}).get("email", "")
        if not isinstance(email, str) or not EMAIL_PATTERN.fullmatch(email.strip().lower()):
            return error("Enter a valid email address.", 400)
        email = email.strip().lower()
        with closing(connect_db()) as connection:
            row = connection.execute(
                "SELECT active, verified_at FROM users WHERE email = ?", (email,)
            ).fetchone()
        if row and row["active"] and not row["verified_at"] and not deliver_verification(email):
            return error("Verification email could not be sent.", 503)
        return jsonify({"message": "If the account needs verification, an email will be sent."})

    @app.post("/api/auth/login")
    def login():
        payload = request.get_json(silent=True) or {}
        email = payload.get("email", "")
        password = payload.get("password")
        if not isinstance(email, str) or not isinstance(password, str):
            return error("Email or password is incorrect.", 401, "invalid_credentials")
        email = email.strip().lower()
        if not EMAIL_PATTERN.fullmatch(email):
            return error("Email or password is incorrect.", 401, "invalid_credentials")
        address = request.remote_addr or ""
        with closing(connect_db()) as connection:
            connection.execute(
                "DELETE FROM login_attempts WHERE attempted_at < strftime('%s','now') - 900"
            )
            attempts = connection.execute(
                """SELECT COUNT(*) AS count FROM login_attempts
                   WHERE email = ? AND remote_addr = ?
                     AND attempted_at >= strftime('%s','now') - 900""",
                (email, address),
            ).fetchone()["count"]
            if attempts >= 5:
                return error("Too many sign-in attempts. Try again in 15 minutes.", 429)
            user = connection.execute(
                "SELECT * FROM users WHERE email = ?", (email,)
            ).fetchone()
            password_ok = check_password_hash(
                user["password_hash"] if user else DUMMY_PASSWORD_HASH, password
            )
            if (
                user is None
                or not password_ok
                or not user["active"]
                or not user["verified_at"]
            ):
                connection.execute(
                    "INSERT INTO login_attempts VALUES (?, ?, strftime('%s','now'))",
                    (email, address),
                )
                connection.commit()
                if user and password_ok and user["active"] and not user["verified_at"]:
                    return error("Verify your email before signing in.", 403, "email_not_verified")
                return error("Email or password is incorrect.", 401, "invalid_credentials")
            connection.execute(
                "DELETE FROM login_attempts WHERE email = ? AND remote_addr = ?",
                (email, address),
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

    @app.get("/api/student")
    def get_student():
        user, response = require_user()
        if response:
            return response
        with closing(connect_db()) as connection:
            student = connection.execute(
                """SELECT id, full_name, email, phone FROM students
                   WHERE user_id = ? AND school_id = ?""",
                (user["id"], user["school_id"]),
            ).fetchone()
        return jsonify({"student": dict(student) if student else None})

    @app.route("/api/student", methods=["POST", "PUT", "PATCH"])
    @app.route("/api/student/<int:student_id>", methods=["PUT"])
    def update_student(student_id=None):
        user, response = require_user()
        if response:
            return response
        payload = request.get_json(silent=True) or {}
        full_name = payload.get("full_name") or payload.get("name") or ""
        phone = payload.get("phone")
        if not isinstance(full_name, str) or not 1 <= len(full_name.strip()) <= 80:
            return error("Enter a name between 1 and 80 characters.", 400)
        if phone is not None and (not isinstance(phone, str) or len(phone) > 40):
            return error("Enter a valid phone number.", 400)
        with closing(connect_db()) as connection:
            if student_id is not None:
                owned = connection.execute(
                    "SELECT 1 FROM students WHERE id = ? AND user_id = ? AND school_id = ?",
                    (student_id, user["id"], user["school_id"]),
                ).fetchone()
                if not owned:
                    return error("Student profile not found.", 404)
            connection.execute(
                "UPDATE users SET name = ? WHERE id = ?", (full_name.strip(), user["id"])
            )
            connection.execute(
                """UPDATE students SET full_name = ?, phone = ?
                   WHERE user_id = ? AND school_id = ?""",
                (full_name.strip(), phone, user["id"], user["school_id"]),
            )
            connection.commit()
            student = connection.execute(
                "SELECT id FROM students WHERE user_id = ? AND school_id = ?",
                (user["id"], user["school_id"]),
            ).fetchone()
        return jsonify({"message": "Profile updated.", "student_id": student["id"]})

    @app.get("/api/subjects")
    def subjects():
        return jsonify(
            [
                {"name": name, "is_compulsory": compulsory}
                for name, compulsory in CAPS_SUBJECTS[learn_grade()]
            ]
        )

    @app.get("/api/learning-plan")
    def learning_plan():
        user, response = require_user()
        if response:
            return response
        with closing(connect_db()) as connection:
            rows = connection.execute(
                """SELECT p.subject, p.percentage FROM progress p
                   JOIN students s ON s.id = p.student_id
                   WHERE s.user_id = ? AND s.school_id = ?
                   ORDER BY p.updated_at DESC""",
                (user["id"], user["school_id"]),
            ).fetchall()
        return jsonify(build_learning_plan(rows))

    @app.route("/api/papers", methods=["GET", "POST"])
    def papers():
        if request.method == "POST":
            user, response = require_admin()
            if response:
                return response
            payload = request.get_json(silent=True) or {}
            fields = [
                payload.get(key)
                for key in ("grade", "subject", "title", "file_url", "year")
            ]
            if any(value in (None, "") for value in fields):
                return error("Grade, subject, title, file URL and year are required.", 400)
            if not isinstance(fields[1], str) or len(fields[1]) > 120:
                return error("Invalid subject.", 400)
            if not isinstance(fields[2], str) or len(fields[2]) > 160:
                return error("Title must be at most 160 characters.", 400)
            file_url = fields[3]
            if not isinstance(file_url, str) or not file_url.startswith("https://"):
                return error("Paper URL must use HTTPS.", 400)
            memo_url = payload.get("memo_url")
            if memo_url and (
                not isinstance(memo_url, str) or not memo_url.startswith("https://")
            ):
                return error("Memo URL must use HTTPS.", 400)
            with closing(connect_db()) as connection:
                connection.execute(
                    """INSERT INTO papers
                       (grade, subject, title, file_url, memo_url, year, term, school_id)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        *fields[:4],
                        memo_url,
                        fields[4],
                        payload.get("term"),
                        user["school_id"],
                    ),
                )
                connection.commit()
            return jsonify({"message": "Paper saved."}), 201
        user, response = require_user()
        if response:
            return response
        subject = request.args.get("subject")
        query = "SELECT * FROM papers WHERE grade = ? AND (school_id IS NULL OR school_id = ?)"
        params = [learn_grade(), user["school_id"]]
        if subject:
            query += " AND subject = ?"
            params.append(subject)
        with closing(connect_db()) as connection:
            rows = connection.execute(
                query + " ORDER BY year DESC, id DESC", params
            ).fetchall()
        return jsonify([dict(row) for row in rows])

    @app.route("/api/timetable", methods=["GET", "POST"])
    def timetable():
        user, response = require_user()
        if response:
            return response
        if request.method == "POST":
            payload = request.get_json(silent=True) or {}
            keys = ("grade", "day", "start_time", "end_time", "subject")
            if any(not payload.get(key) for key in keys):
                return error("All timetable fields are required.", 400)
            with closing(connect_db()) as connection:
                connection.execute(
                    """INSERT INTO timetable
                       (grade, day, start_time, end_time, subject, venue, user_id, school_id)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        *(payload.get(key) for key in keys),
                        payload.get("venue"),
                        user["id"],
                        user["school_id"],
                    ),
                )
                connection.commit()
            return jsonify({"message": "Period saved."}), 201
        with closing(connect_db()) as connection:
            rows = connection.execute(
                """SELECT * FROM timetable WHERE grade = ? AND user_id = ?
                   AND school_id = ? ORDER BY day, start_time""",
                (learn_grade(), user["id"], user["school_id"]),
            ).fetchall()
        return jsonify([dict(row) for row in rows])

    @app.delete("/api/timetable/<int:period_id>")
    def delete_period(period_id):
        user, response = require_user()
        if response:
            return response
        with closing(connect_db()) as connection:
            cursor = connection.execute(
                "DELETE FROM timetable WHERE id = ? AND user_id = ? AND school_id = ?",
                (period_id, user["id"], user["school_id"]),
            )
            connection.commit()
        if not cursor.rowcount:
            return error("Period not found.", 404)
        return jsonify({"message": "Period deleted."})

    @app.route("/api/exams", methods=["GET", "POST"])
    def exams():
        user, response = require_user()
        if response:
            return response
        if request.method == "POST":
            payload = request.get_json(silent=True) or {}
            keys = ("grade", "subject", "exam_date", "start_time", "duration_min")
            if any(not payload.get(key) for key in keys):
                return error("All exam fields are required.", 400)
            try:
                date.fromisoformat(payload["exam_date"])
                duration = int(payload["duration_min"])
            except (TypeError, ValueError):
                return error("Enter a valid date and duration.", 400)
            if duration < 1 or duration > 1440:
                return error("Exam duration must be from 1 to 1440 minutes.", 400)
            with closing(connect_db()) as connection:
                connection.execute(
                    """INSERT INTO exams
                       (grade, subject, exam_date, start_time, duration_min, venue, user_id, school_id)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        payload["grade"],
                        payload["subject"],
                        payload["exam_date"],
                        payload["start_time"],
                        duration,
                        payload.get("venue"),
                        user["id"],
                        user["school_id"],
                    ),
                )
                connection.commit()
            return jsonify({"message": "Exam saved."}), 201
        with closing(connect_db()) as connection:
            rows = connection.execute(
                """SELECT * FROM exams WHERE grade = ? AND user_id = ?
                   AND school_id = ? ORDER BY exam_date, start_time""",
                (learn_grade(), user["id"], user["school_id"]),
            ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["days_left"] = (
                date.fromisoformat(item["exam_date"]) - date.today()
            ).days
            result.append(item)
        return jsonify(result)

    @app.get("/health")
    def health():
        with closing(connect_db()) as connection:
            connection.execute("SELECT 1")
        return jsonify({"status": "ok"})

    @app.get("/api/announcements")
    def announcements():
        with closing(connect_db()) as connection:
            rows = connection.execute(
                """SELECT id, title, message, created_at FROM announcements
                   ORDER BY created_at DESC"""
            ).fetchall()
        return jsonify({"announcements": [dict(row) for row in rows]})

    @app.get("/api/students")
    def list_students():
        user, response = require_user()
        if response:
            return response
        with closing(connect_db()) as connection:
            rows = connection.execute(
                """SELECT id, full_name, email, phone, created_at FROM students
                   WHERE user_id = ? AND school_id = ? ORDER BY created_at DESC""",
                (user["id"], user["school_id"]),
            ).fetchall()
        return jsonify({"students": [dict(row) for row in rows]})

    @app.route("/api/progress", methods=["GET", "POST"])
    def progress():
        user, response = require_user()
        if response:
            return response
        if request.method == "POST":
            payload = request.get_json(silent=True) or {}
            subject, percentage = payload.get("subject"), payload.get("percentage")
            if not isinstance(subject, str) or not 1 <= len(subject.strip()) <= 120:
                return error("Choose a valid subject.", 400)
            try:
                percentage = int(percentage)
            except (TypeError, ValueError):
                return error("Progress must be a whole number from 0 to 100.", 400)
            if not 0 <= percentage <= 100:
                return error("Progress must be a whole number from 0 to 100.", 400)
            with closing(connect_db()) as connection:
                student = connection.execute(
                    "SELECT id FROM students WHERE user_id = ? AND school_id = ?",
                    (user["id"], user["school_id"]),
                ).fetchone()
                if student is None:
                    return error("Student profile not found.", 404)
                connection.execute(
                    "INSERT INTO progress (student_id, subject, percentage) VALUES (?, ?, ?)",
                    (student["id"], subject.strip(), percentage),
                )
                connection.commit()
            return jsonify({"message": "Progress saved."}), 201
        with closing(connect_db()) as connection:
            rows = connection.execute(
                """SELECT p.id, p.student_id, s.full_name, p.subject, p.percentage, p.updated_at
                   FROM progress p JOIN students s ON s.id = p.student_id
                   WHERE s.user_id = ? AND s.school_id = ?
                   ORDER BY p.updated_at DESC, p.id DESC""",
                (user["id"], user["school_id"]),
            ).fetchall()
        entries = [dict(row) for row in rows]
        latest_by_subject = {}
        for item in entries:
            latest_by_subject.setdefault(item["subject"], item)
        return jsonify(
            {
                "progress": entries,
                "summary": list(latest_by_subject.values()),
                "activity_count": len(entries),
            }
        )

    @app.post("/api/incident")
    def create_incident():
        user, response = require_user()
        if response:
            return response
        payload = request.get_json(silent=True) or {}
        incident_type, description = payload.get("incident_type"), payload.get("description")
        if not isinstance(incident_type, str) or not 1 <= len(incident_type.strip()) <= 80:
            return error("Choose a valid report category.", 400)
        if not isinstance(description, str) or not 1 <= len(description.strip()) <= 2000:
            return error("Description must be between 1 and 2000 characters.", 400)
        with closing(connect_db()) as connection:
            connection.execute(
                """INSERT INTO incidents (incident_type, description, user_id, school_id)
                   VALUES (?, ?, ?, ?)""",
                (
                    incident_type.strip(),
                    description.strip(),
                    user["id"],
                    user["school_id"],
                ),
            )
            connection.commit()
        return jsonify({"message": "Report received."}), 201

    @app.get("/api/admin/incidents")
    def list_incidents():
        user, response = require_admin()
        if response:
            return response
        with closing(connect_db()) as connection:
            rows = connection.execute(
                """SELECT i.id, i.incident_type, i.description, i.status,
                          i.created_at, s.full_name
                   FROM incidents i JOIN students s ON s.user_id = i.user_id
                   WHERE i.school_id = ? ORDER BY i.created_at DESC""",
                (user["school_id"],),
            ).fetchall()
        return jsonify({"incidents": [dict(row) for row in rows]})

    @app.patch("/api/admin/incidents/<int:incident_id>")
    def update_incident(incident_id):
        user, response = require_admin()
        if response:
            return response
        status = (request.get_json(silent=True) or {}).get("status")
        if not isinstance(status, str) or status not in REQUEST_STATUSES:
            return error("Choose a valid report status.", 400)
        with closing(connect_db()) as connection:
            cursor = connection.execute(
                "UPDATE incidents SET status = ? WHERE id = ? AND school_id = ?",
                (status, incident_id, user["school_id"]),
            )
            connection.commit()
        if not cursor.rowcount:
            return error("Report not found.", 404)
        return jsonify({"message": "Report updated."})

    @app.cli.command("create-school")
    def create_school_command():
        import click

        name = click.prompt("School name").strip()
        slug = click.prompt("School registration code").strip().lower()
        if not name or not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,62}", slug):
            raise click.ClickException("Enter a school name and a valid code.")
        try:
            with closing(connect_db()) as connection:
                connection.execute(
                    "INSERT INTO schools (slug, name) VALUES (?, ?)", (slug, name)
                )
                connection.commit()
        except sqlite3.IntegrityError as exc:
            raise click.ClickException("That school code already exists.") from exc
        click.echo(f"Created school {name} ({slug}).")

    @app.cli.command("create-admin")
    def create_admin_command():
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
            if not school:
                raise click.ClickException("School code not found.")
            try:
                connection.execute(
                    """INSERT INTO users
                       (school_id, email, name, password_hash, role, verified_at)
                       VALUES (?, ?, ?, ?, 'administrator', CURRENT_TIMESTAMP)""",
                    (
                        school["id"],
                        email,
                        email.split("@", 1)[0],
                        generate_password_hash(password),
                    ),
                )
                connection.commit()
            except sqlite3.IntegrityError as exc:
                raise click.ClickException("That account already exists.") from exc
        click.echo("Administrator account created.")

    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
    return app


app = create_app()


if __name__ == "__main__":
    app.run(debug=False, host="0.0.0.0", port=int(os.environ.get("PORT", "5000")))
