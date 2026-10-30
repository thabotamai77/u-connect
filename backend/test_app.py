import os
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("UCONNECT_SECRET_KEY", "unit-test-key-not-for-deployment")

from app import connect_db, create_app, generate_password_hash

TEST_PASSWORD_HASH = generate_password_hash(
    "correct-horse-battery", method="pbkdf2:sha256:1000"
)


class ApplicationTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.database = str(Path(self.temporary_directory.name) / "test.sqlite3")
        self.app = create_app(
            {
                "TESTING": True,
                "SECRET_KEY": "test-secret-key",
                "DATABASE": self.database,
                "SESSION_COOKIE_SECURE": False,
                "PUBLIC_BASE_URL": "https://u-connect.test",
                "SMTP_HOST": "",
            }
        )
        self.client = self.app.test_client()
        self.school_id = self.add_school("north-campus", "North Campus")

    def tearDown(self):
        self.temporary_directory.cleanup()

    def add_school(self, slug, name):
        with self.app.app_context(), closing(connect_db()) as connection:
            cursor = connection.execute(
                "INSERT INTO schools (slug, name) VALUES (?, ?)", (slug, name)
            )
            connection.commit()
            return cursor.lastrowid

    def add_user(self, email, school_id, role="student", verified=True):
        with self.app.app_context(), closing(connect_db()) as connection:
            cursor = connection.execute(
                """INSERT INTO users
                   (school_id, email, name, password_hash, role, verified_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    school_id,
                    email,
                    email.split("@", 1)[0],
                    TEST_PASSWORD_HASH,
                    role,
                    "2026-01-01T00:00:00Z" if verified else None,
                ),
            )
            connection.commit()
            return cursor.lastrowid

    def csrf(self, client=None):
        client = client or self.client
        response = client.get("/api/session")
        self.assertEqual(response.status_code, 200)
        return response.get_json()["csrf_token"]

    def mutate(self, path, data, client=None, method="post", token=None):
        client = client or self.client
        csrf = token or self.csrf(client)
        return getattr(client, method)(
            path, json=data, headers={"X-CSRF-Token": csrf}
        )

    def login(self, email, client=None, password="correct-horse-battery"):
        client = client or self.client
        return self.mutate(
            "/api/auth/login", {"email": email, "password": password}, client
        )

    def test_registration_requires_email_verification_before_login(self):
        sent = []
        with patch("app.send_verification_email", side_effect=lambda email, token: sent.append((email, token))):
            response = self.mutate(
                "/api/auth/register",
                {
                    "name": "Student One",
                    "email": "student@example.test",
                    "password": "correct-horse-battery",
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
        self.assertEqual(self.client.get("/api/requests").status_code, 200)

    def test_failed_email_delivery_is_explicit_and_account_remains_unverified(self):
        response = self.mutate(
            "/api/auth/register",
            {
                "name": "Student Two",
                "email": "student2@example.test",
                "password": "correct-horse-battery",
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

    def test_csrf_and_authentication_are_required(self):
        missing_csrf = self.client.post(
            "/api/auth/login",
            json={"email": "nobody@example.test", "password": "incorrect"},
        )
        self.assertEqual(missing_csrf.status_code, 400)
        self.assertEqual(self.client.get("/api/requests").status_code, 401)
        self.assertEqual(self.client.get("/api/admin/requests").status_code, 401)

    def test_application_refuses_to_start_without_a_secret_key(self):
        with self.assertRaisesRegex(RuntimeError, "UCONNECT_SECRET_KEY"):
            create_app(
                {
                    "SECRET_KEY": None,
                    "DATABASE": self.database,
                    "SESSION_COOKIE_SECURE": False,
                }
            )

    def test_student_cannot_access_administration(self):
        self.add_user("student@example.test", self.school_id)
        self.assertEqual(self.login("student@example.test").status_code, 200)
        response = self.client.get("/api/admin/requests")
        self.assertEqual(response.status_code, 403)

    def test_school_requests_are_persisted_and_isolated(self):
        other_school = self.add_school("south-campus", "South Campus")
        self.add_user("student@example.test", self.school_id)
        self.add_user("north-admin@example.test", self.school_id, role="administrator")
        self.add_user("south-admin@example.test", other_school, role="administrator")
        self.assertEqual(self.login("student@example.test").status_code, 200)

        created = self.mutate(
            "/api/requests",
            {
                "category": "Academic support",
                "description": "Help with study planning",
            },
        )
        self.assertEqual(created.status_code, 201)
        request_id = created.get_json()["id"]
        own_list = self.client.get("/api/requests").get_json()["requests"]
        self.assertEqual([item["id"] for item in own_list], [request_id])
        self.assertNotIn("confidential", own_list[0])

        south_client = self.app.test_client()
        self.assertEqual(self.login("south-admin@example.test", south_client).status_code, 200)
        self.assertEqual(south_client.get("/api/admin/requests").get_json()["requests"], [])
        cross_school_update = self.mutate(
            f"/api/admin/requests/{request_id}",
            {"status": "Resolved"},
            south_client,
            method="patch",
        )
        self.assertEqual(cross_school_update.status_code, 404)

        north_client = self.app.test_client()
        self.assertEqual(self.login("north-admin@example.test", north_client).status_code, 200)
        admin_list = north_client.get("/api/admin/requests").get_json()["requests"]
        self.assertEqual([item["id"] for item in admin_list], [request_id])
        changed = self.mutate(
            f"/api/admin/requests/{request_id}",
            {"status": "In review", "assigned": "Academic team"},
            north_client,
            method="patch",
        )
        self.assertEqual(changed.status_code, 200)

        reopened_app = create_app(
            {
                "TESTING": True,
                "SECRET_KEY": "test-secret-key",
                "DATABASE": self.database,
                "SESSION_COOKIE_SECURE": False,
            }
        )
        with reopened_app.test_client() as persistent_client:
            self.assertEqual(self.login("student@example.test", persistent_client).status_code, 200)
            saved_request = persistent_client.get("/api/requests").get_json()["requests"][0]
            self.assertEqual(saved_request["status"], "In review")

    def test_logout_clears_the_session_and_csrf_must_be_refreshed(self):
        self.add_user("student@example.test", self.school_id)
        self.assertEqual(self.login("student@example.test").status_code, 200)
        old_token = self.csrf()
        signed_out = self.mutate(
            "/api/auth/logout", {}, token=old_token
        )
        self.assertEqual(signed_out.status_code, 200)
        self.assertEqual(self.client.get("/api/requests").status_code, 401)
        new_token = self.csrf()
        self.assertNotEqual(old_token, new_token)
        self.assertEqual(
            self.client.post(
                "/api/auth/login",
                json={
                    "email": "student@example.test",
                    "password": "correct-horse-battery",
                },
                headers={"X-CSRF-Token": new_token},
            ).status_code,
            200,
        )

    def test_security_headers_and_health_route(self):
        response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["status"], "online")
        self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(response.headers["X-Frame-Options"], "DENY")
        self.assertIn("frame-ancestors 'none'", response.headers["Content-Security-Policy"])

    def test_frontend_is_served_with_static_assets(self):
        page = self.client.get("/")
        self.assertEqual(page.status_code, 200)
        self.assertIn(b"/static/app.js", page.data)
        self.assertNotIn(b"Admin demo", page.data)
        page.close()
        for path, expected_status in (
            ("/static/app.js", 200),
            ("/static/style.css", 200),
            ("/static/backend/app.py", 404),
            ("/static/school/work/Untitled-1.ipynb", 404),
        ):
            response = self.client.get(path)
            self.assertEqual(response.status_code, expected_status)
            response.close()

    def test_administrator_is_created_only_by_trusted_cli(self):
        runner = self.app.test_cli_runner()
        school_result = runner.invoke(
            args=["create-school"], input="North Campus\nnorth-cli\n"
        )
        self.assertEqual(school_result.exit_code, 0, school_result.output)
        admin_result = runner.invoke(
            args=["create-admin"],
            input=(
                "admin@example.test\nnorth-cli\n"
                "correct-horse-battery\ncorrect-horse-battery\n"
            ),
        )
        self.assertEqual(admin_result.exit_code, 0, admin_result.output)
        self.assertEqual(self.login("admin@example.test").status_code, 200)
        self.assertEqual(self.client.get("/api/admin/requests").status_code, 200)


if __name__ == "__main__":
    unittest.main()
