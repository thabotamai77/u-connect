import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

TEST_DIRECTORY = tempfile.TemporaryDirectory()
os.environ.setdefault("UCONNECT_SECRET_KEY", "test-only-secret")
os.environ["UCONNECT_DATABASE"] = str(Path(TEST_DIRECTORY.name) / "default.sqlite3")

from app import connect_db, create_app, generate_password_hash

PASSWORD = "correct-horse-battery"
PASSWORD_HASH = generate_password_hash(PASSWORD, method="pbkdf2:sha256:1000")


class UConnectTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.database = str(Path(self.temporary_directory.name) / "test.sqlite3")
        self.app = create_app(
            {
                "TESTING": True,
                "SECRET_KEY": "test-key-not-for-production",
                "DATABASE": self.database,
                "SESSION_COOKIE_SECURE": False,
                "PUBLIC_BASE_URL": "https://u-connect.test",
                "SMTP_HOST": "",
            }
        )
        self.client = self.app.test_client()
        self.school_a = self.create_school("north-campus", "North Campus")

    def tearDown(self):
        self.temporary_directory.cleanup()

    def create_school(self, slug, name):
        with self.app.app_context(), closing(connect_db()) as connection:
            cursor = connection.execute(
                "INSERT INTO schools (slug, name) VALUES (?, ?)", (slug, name)
            )
            connection.commit()
            return cursor.lastrowid

    def create_user(self, email, school_id, role="student", verified=True):
        with self.app.app_context(), closing(connect_db()) as connection:
            cursor = connection.execute(
                """INSERT INTO users
                   (school_id, email, name, password_hash, role, verified_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    school_id,
                    email,
                    email.split("@", 1)[0],
                    PASSWORD_HASH,
                    role,
                    "2026-01-01T00:00:00Z" if verified else None,
                ),
            )
            user_id = cursor.lastrowid
            if role == "student":
                connection.execute(
                    "INSERT INTO students (full_name, email, user_id, school_id) "
                    "VALUES (?, ?, ?, ?)",
                    (email.split("@", 1)[0], email, user_id, school_id),
                )
            connection.commit()
            return user_id

    def csrf(self, client=None):
        response = (client or self.client).get("/api/session")
        self.assertEqual(response.status_code, 200)
        return response.get_json()["csrf_token"]

    def mutate(self, path, body, client=None, method="post", token=None):
        client = client or self.client
        token = token or self.csrf(client)
        return getattr(client, method)(
            path, json=body, headers={"X-CSRF-Token": token}
        )

    def login(self, email, client=None, password=PASSWORD):
        return self.mutate(
            "/api/auth/login",
            {"email": email, "password": password},
            client,
        )

    def test_registration_verification_login_and_logout(self):
        sent = []
        with patch(
            "app.send_verification_email",
            side_effect=lambda email, token: sent.append((email, token)),
        ):
            response = self.mutate(
                "/api/auth/register",
                {
                    "name": "Student One",
                    "email": "student@example.test",
                    "password": PASSWORD,
                    "school": "north-campus",
                    "role": "administrator",
                },
            )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(len(sent), 1)
        self.assertEqual(self.login("student@example.test").status_code, 403)
        verified = self.mutate("/api/auth/verify", {"token": sent[0][1]})
        self.assertEqual(verified.status_code, 200)
        login = self.login("student@example.test")
        self.assertEqual(login.status_code, 200)
        self.assertEqual(login.get_json()["user"]["role"], "student")
        self.assertEqual(self.client.get("/api/student").status_code, 200)
        old_csrf = self.csrf()
        self.assertEqual(
            self.mutate("/api/auth/logout", {}, token=old_csrf).status_code, 200
        )
        self.assertEqual(self.client.get("/api/progress").status_code, 401)

    def test_email_failure_is_explicit_and_account_remains_unverified(self):
        response = self.mutate(
            "/api/auth/register",
            {
                "name": "Student Two",
                "email": "student2@example.test",
                "password": PASSWORD,
                "school": "north-campus",
            },
        )
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.get_json()["code"], "email_delivery_unavailable")
        self.assertEqual(self.login("student2@example.test").status_code, 403)
        self.assertEqual(
            self.login("student2@example.test", password="wrong-password").status_code,
            401,
        )

    def test_csrf_required_for_mutations_and_api_requires_authentication(self):
        self.assertEqual(
            self.client.post(
                "/api/auth/login",
                json={"email": "unknown@example.test", "password": PASSWORD},
            ).status_code,
            400,
        )
        for path in (
            "/api/student",
            "/api/students",
            "/api/progress",
            "/api/learning-plan",
            "/api/timetable",
            "/api/exams",
            "/api/papers",
        ):
            self.assertEqual(self.client.get(path).status_code, 401, path)

    def test_login_is_rate_limited(self):
        response = None
        for _ in range(6):
            response = self.login("unknown@example.test", password="wrong-password")
        self.assertEqual(response.status_code, 429)

    def test_student_data_is_private_and_progress_is_bound_to_session(self):
        self.create_user("north@example.test", self.school_a)
        self.assertEqual(self.login("north@example.test").status_code, 200)
        created = self.mutate(
            "/api/progress",
            {
                "student_id": 999999,
                "subject": "Mathematics",
                "percentage": 70,
            },
        )
        self.assertEqual(created.status_code, 201)
        own_data = self.client.get("/api/progress").get_json()["progress"]
        self.assertEqual(len(own_data), 1)
        self.assertEqual(own_data[0]["percentage"], 70)
        self.mutate(
            "/api/progress",
            {"subject": "Mathematics", "percentage": 82},
        )
        progress_result = self.client.get("/api/progress").get_json()
        self.assertEqual(progress_result["activity_count"], 2)
        self.assertEqual(progress_result["summary"][0]["percentage"], 82)
        self.assertEqual(
            self.client.get("/api/learning-plan?student_id=999999").status_code, 200
        )

        school_b = self.create_school("south-campus", "South Campus")
        self.create_user("south@example.test", school_b)
        other_client = self.app.test_client()
        self.assertEqual(self.login("south@example.test", other_client).status_code, 200)
        self.assertEqual(
            other_client.get("/api/progress").get_json()["progress"], []
        )
        self.assertEqual(
            other_client.get("/api/students").get_json()["students"][0]["email"],
            "south@example.test",
        )

    def test_administration_and_content_upload_require_school_admin(self):
        self.create_user("student@example.test", self.school_a)
        self.assertEqual(self.login("student@example.test").status_code, 200)
        denied = self.mutate(
            "/api/papers",
            {
                "grade": 12,
                "subject": "Mathematics",
                "title": "Paper",
                "file_url": "https://example.test/paper.pdf",
                "year": 2025,
            },
        )
        self.assertEqual(denied.status_code, 403)

        self.create_user(
            "admin@example.test", self.school_a, role="administrator"
        )
        admin = self.app.test_client()
        self.assertEqual(self.login("admin@example.test", admin).status_code, 200)
        saved = self.mutate(
            "/api/papers",
            {
                "grade": 12,
                "subject": "Mathematics",
                "title": "North paper",
                "file_url": "https://example.test/paper.pdf",
                "year": 2025,
            },
            admin,
        )
        self.assertEqual(saved.status_code, 201)
        self.assertEqual(len(admin.get("/api/papers?grade=12").get_json()), 1)

        school_b = self.create_school("west-campus", "West Campus")
        self.create_user("west@example.test", school_b)
        west = self.app.test_client()
        self.assertEqual(self.login("west@example.test", west).status_code, 200)
        self.assertEqual(west.get("/api/papers?grade=12").get_json(), [])

    def test_timetable_and_incident_routes_are_authenticated_and_isolated(self):
        self.create_user("student@example.test", self.school_a)
        self.assertEqual(self.login("student@example.test").status_code, 200)
        event = self.mutate(
            "/api/timetable",
            {
                "grade": 12,
                "day": "Monday",
                "start_time": "08:00",
                "end_time": "09:00",
                "subject": "Math",
            },
        )
        self.assertEqual(event.status_code, 201)
        period_id = self.client.get("/api/timetable").get_json()[0]["id"]

        second_school = self.create_school("another-campus", "Another Campus")
        self.create_user("other@example.test", second_school)
        other = self.app.test_client()
        self.assertEqual(self.login("other@example.test", other).status_code, 200)
        self.assertEqual(other.get("/api/timetable").get_json(), [])
        self.assertEqual(
            self.mutate(
                f"/api/timetable/{period_id}", {}, other, method="delete"
            ).status_code,
            404,
        )
        self.assertEqual(
            self.mutate(
                "/api/incident",
                {"incident_type": "Safety", "description": "Need support"},
            ).status_code,
            201,
        )
        self.assertEqual(other.get("/api/admin/incidents").status_code, 403)
        with self.app.app_context(), closing(connect_db()) as connection:
            connection.execute(
                """INSERT INTO users
                   (school_id, email, name, password_hash, role, verified_at)
                   VALUES (?, 'admin@example.test', 'Admin', ?, 'administrator', CURRENT_TIMESTAMP)""",
                (self.school_a, PASSWORD_HASH),
            )
            connection.commit()
        admin = self.app.test_client()
        self.assertEqual(self.login("admin@example.test", admin).status_code, 200)
        reports = admin.get("/api/admin/incidents").get_json()["incidents"]
        self.assertEqual(len(reports), 1)
        report_id = reports[0]["id"]
        self.assertEqual(
            self.mutate(
                f"/api/admin/incidents/{report_id}",
                {"status": "In review"},
                admin,
                method="patch",
            ).status_code,
            200,
        )
        self.assertEqual(
            self.mutate(
                f"/api/admin/incidents/{report_id}",
                {"status": "Resolved"},
                other,
                method="patch",
            ).status_code,
            403,
        )
        third_school = self.create_school("third-campus", "Third Campus")
        self.create_user(
            "third-admin@example.test", third_school, role="administrator"
        )
        third_admin = self.app.test_client()
        self.assertEqual(
            self.login("third-admin@example.test", third_admin).status_code, 200
        )
        self.assertEqual(
            self.mutate(
                f"/api/admin/incidents/{report_id}",
                {"status": "Resolved"},
                third_admin,
                method="patch",
            ).status_code,
            404,
        )

    def test_admin_bootstrap_cli_and_health_headers(self):
        runner = self.app.test_cli_runner()
        school_result = runner.invoke(
            args=["create-school"], input="North Campus\nnorth-cli\n"
        )
        self.assertEqual(school_result.exit_code, 0, school_result.output)
        admin_result = runner.invoke(
            args=["create-admin"],
            input=(
                "admin@example.test\nnorth-cli\n"
                f"{PASSWORD}\n{PASSWORD}\n"
            ),
        )
        self.assertEqual(admin_result.exit_code, 0, admin_result.output)
        admin = self.app.test_client()
        self.assertEqual(self.login("admin@example.test", admin).status_code, 200)
        self.assertEqual(admin.get("/api/admin/incidents").status_code, 200)
        health = self.client.get("/health")
        self.assertEqual(health.get_json()["status"], "ok")
        self.assertEqual(health.headers["X-Frame-Options"], "DENY")
        self.assertEqual(self.client.get("/api/session").headers["Cache-Control"], "no-store")
        secure_health = self.client.get(
            "/health", headers={"X-Forwarded-Proto": "https"}
        )
        self.assertIn("max-age=31536000", secure_health.headers["Strict-Transport-Security"])

    def test_authentication_shell_and_admin_assets_are_served(self):
        for path in ("/", "/learn.html", "/admin.html", "/auth.js", "/dashboard.js", "/admin.js"):
            with closing(self.client.get(path)) as response:
                self.assertEqual(response.status_code, 200, path)
        page = self.client.get("/")
        policy = page.headers["Content-Security-Policy"]
        page.close()
        self.assertIn("script-src 'self'", policy)
        self.assertNotIn("unsafe-inline'; style-src", policy)

    def test_existing_unscoped_records_are_not_exposed_after_migration(self):
        legacy_path = str(Path(self.temporary_directory.name) / "legacy.sqlite3")
        with closing(sqlite3.connect(legacy_path)) as connection:
            connection.execute(
                "CREATE TABLE students (id INTEGER PRIMARY KEY, full_name TEXT NOT NULL, "
                "email TEXT, phone TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP)"
            )
            connection.execute(
                "INSERT INTO students (full_name, email) VALUES ('Legacy Student', 'legacy@example.test')"
            )
            connection.commit()
        migrated = create_app(
            {
                "TESTING": True,
                "SECRET_KEY": "legacy-test-key",
                "DATABASE": legacy_path,
                "SESSION_COOKIE_SECURE": False,
            }
        )
        with migrated.app_context(), closing(connect_db()) as connection:
            cursor = connection.execute(
                "INSERT INTO schools (slug, name) VALUES ('new-school', 'New School')"
            )
            school_id = cursor.lastrowid
            user_cursor = connection.execute(
                """INSERT INTO users
                   (school_id, email, name, password_hash, verified_at)
                   VALUES (?, 'new@example.test', 'New User', ?, CURRENT_TIMESTAMP)""",
                (school_id, PASSWORD_HASH),
            )
            connection.execute(
                "INSERT INTO students (full_name, email, user_id, school_id) "
                "VALUES ('New User', 'new@example.test', ?, ?)",
                (user_cursor.lastrowid, school_id),
            )
            connection.commit()
        client = migrated.test_client()
        self.assertEqual(
            self.login("new@example.test", client).status_code, 200
        )
        students = client.get("/api/students").get_json()["students"]
        self.assertEqual([item["email"] for item in students], ["new@example.test"])


if __name__ == "__main__":
    unittest.main()
