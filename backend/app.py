import sqlite3
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "database" / "unconnect.db"
FRONTEND_DIR = BASE_DIR / "frontend"


def ensure_db_file():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not DB_PATH.exists():
        return False

    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("SELECT 1")
        return True
    except sqlite3.DatabaseError:
        return False


def get_connection():
    if not ensure_db_file():
        init_db()

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS students (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            full_name TEXT NOT NULL,
            email TEXT UNIQUE,
            phone TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS incidents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            incident_type TEXT NOT NULL,
            description TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
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
        """
    )

    conn.executemany(
        """
        INSERT OR IGNORE INTO announcements (title, message)
        VALUES (?, ?)
        """,
        [
            ("📢 Campus Update", "Check your student portal for the latest announcements."),
            ("🏆 Sports Day", "Don't forget to support your campus teams!"),
            ("💻 IT Students", "Remember to submit your projects before the deadline."),
        ],
    )

    conn.commit()
    conn.close()


def save_student(full_name, email=None, phone=None):
    conn = get_connection()
    cursor = conn.execute(
        """
        INSERT INTO students (full_name, email, phone)
        VALUES (?, ?, ?)
        """,
        (full_name, email, phone),
    )
    conn.commit()
    student_id = cursor.lastrowid
    conn.close()
    return student_id


def save_incident(incident_type, description):
    conn = get_connection()
    conn.execute(
        """
        INSERT INTO incidents (incident_type, description)
        VALUES (?, ?)
        """,
        (incident_type, description),
    )
    conn.commit()
    conn.close()


def save_progress(student_id, subject, percentage):
    conn = get_connection()
    conn.execute(
        """
        INSERT INTO progress (student_id, subject, percentage)
        VALUES (?, ?, ?)
        """,
        (student_id, subject, percentage),
    )
    conn.commit()
    conn.close()


def get_announcements():
    conn = get_connection()
    rows = conn.execute(
        "SELECT id, title, message, created_at FROM announcements ORDER BY created_at DESC"
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_students():
    conn = get_connection()
    rows = conn.execute(
        "SELECT id, full_name, email, phone, created_at FROM students ORDER BY created_at DESC"
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_progress():
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT p.id, p.student_id, s.full_name, p.subject, p.percentage, p.updated_at
        FROM progress p
        LEFT JOIN students s ON s.id = p.student_id
        ORDER BY p.updated_at DESC
        """
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


app = Flask(__name__)


@app.route("/health")
def health():
    return jsonify({"status": "ok", "database": str(DB_PATH)})


@app.route("/api/announcements")
def announcements():
    return jsonify({"announcements": get_announcements()})


@app.route("/api/students")
def list_students():
    return jsonify({"students": get_students()})


@app.route("/api/progress")
def list_progress():
    return jsonify({"progress": get_progress()})


@app.route("/api/student", methods=["POST"])
def create_student():
    payload = request.get_json(silent=True) or request.form or {}
    full_name = (payload.get("full_name") or payload.get("name") or "").strip()
    if not full_name:
        return jsonify({"error": "Name is required"}), 400

    email = payload.get("email")
    phone = payload.get("phone")
    student_id = save_student(full_name, email, phone)
    return jsonify({"message": "Student saved", "student_id": student_id}), 201


@app.route("/api/incident", methods=["POST"])
def create_incident():
    payload = request.get_json(silent=True) or request.form or {}
    incident_type = (payload.get("incident_type") or payload.get("type") or "").strip()
    description = (payload.get("description") or "").strip()

    if not incident_type or not description:
        return jsonify({"error": "Incident type and description are required"}), 400

    save_incident(incident_type, description)
    return jsonify({"message": "Incident saved"}), 201


@app.route("/api/progress", methods=["POST"])
def create_progress():
    payload = request.get_json(silent=True) or request.form or {}
    student_id = payload.get("student_id")
    subject = (payload.get("subject") or "").strip()
    percentage = payload.get("percentage")

    if not student_id or not subject or percentage is None:
        return jsonify({"error": "Student ID, subject and percentage are required"}), 400

    save_progress(student_id, subject, int(percentage))
    return jsonify({"message": "Progress saved"}), 201


@app.route("/app/frontend/<path:filename>")
def serve_frontend(filename):
    return send_from_directory(str(FRONTEND_DIR), filename)


@app.route("/app/frontend/")
def serve_frontend_index():
    return send_from_directory(str(FRONTEND_DIR), "index.html")


@app.route("/")
def root():
    return send_from_directory(str(FRONTEND_DIR), "index.html")


if __name__ == "__main__":
    init_db()
    import os
    debug = os.getenv("FLASK_ENV") != "production"
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=debug)
