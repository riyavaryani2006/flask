import os
import re
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app  # noqa: E402


class TodoTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.app = create_app(
            {
                "TESTING": True,
                "SECRET_KEY": "test-secret",
                "DATABASE": os.path.join(self.tmp, "test.sqlite"),
            }
        )
        self.client = self.app.test_client()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    # -- helpers ----------------------------------------------------------
    def token(self):
        html = self.client.get("/login", follow_redirects=True).get_data(as_text=True)
        return re.search(r'name="_csrf" value="([^"]+)"', html).group(1)

    def post(self, path, data=None, **kwargs):
        payload = dict(data or {})
        payload["_csrf"] = self.token()
        return self.client.post(path, data=payload, **kwargs)

    def signup(self, username="alice", email="alice@example.com", password="password123"):
        return self.post(
            "/signup",
            {"username": username, "email": email, "password": password, "confirm": password},
            follow_redirects=True,
        )

    def login(self, identifier="alice", password="password123"):
        return self.post(
            "/login", {"identifier": identifier, "password": password}, follow_redirects=True
        )

    def logout(self):
        return self.post("/logout", follow_redirects=True)

    def add(self, title="Buy milk", **extra):
        data = {"title": title, "priority": "medium"}
        data.update(extra)
        return self.post("/tasks/add", data, follow_redirects=True)

    def task_id(self, title):
        db_path = self.app.config["DATABASE"]
        import sqlite3

        conn = sqlite3.connect(db_path)
        try:
            row = conn.execute("SELECT id FROM tasks WHERE title = ?", (title,)).fetchone()
        finally:
            conn.close()
        return row[0]


class AuthTests(TodoTestCase):
    def test_index_requires_login(self):
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/login", resp.headers["Location"])

    def test_signup_logs_in_and_shows_tasks_page(self):
        resp = self.signup()
        self.assertIn("Your account is ready", resp.get_data(as_text=True))
        self.assertIn("alice", resp.get_data(as_text=True))

    def test_signup_validation(self):
        cases = [
            ({"username": "a", "email": "a@b.co", "password": "password123"}, "Username must be"),
            ({"username": "alice", "email": "nope", "password": "password123"}, "valid email"),
            ({"username": "alice", "email": "a@b.co", "password": "short"}, "at least 8"),
        ]
        for fields, message in cases:
            fields = {**fields, "confirm": fields["password"]}
            resp = self.post("/signup", fields, follow_redirects=True)
            self.assertIn(message, resp.get_data(as_text=True))

    def test_signup_password_mismatch(self):
        resp = self.post(
            "/signup",
            {"username": "alice", "email": "a@b.co", "password": "password123", "confirm": "different1"},
            follow_redirects=True,
        )
        self.assertIn("do not match", resp.get_data(as_text=True))

    def test_duplicate_signup_rejected_case_insensitively(self):
        self.signup()
        self.logout()
        resp = self.signup(username="ALICE", email="other@example.com")
        self.assertIn("already registered", resp.get_data(as_text=True))

    def test_login_by_username_and_email(self):
        self.signup()
        self.logout()
        self.assertIn("alice", self.login("alice").get_data(as_text=True))
        self.logout()
        self.assertIn("alice", self.login("alice@example.com").get_data(as_text=True))

    def test_wrong_password(self):
        self.signup()
        self.logout()
        resp = self.login(password="wrongpass1")
        self.assertIn("Invalid username/email or password", resp.get_data(as_text=True))

    def test_unknown_user(self):
        resp = self.login("ghost", "whatever123")
        self.assertIn("Invalid username/email or password", resp.get_data(as_text=True))

    def test_logout(self):
        self.signup()
        resp = self.logout()
        self.assertIn("logged out", resp.get_data(as_text=True))
        self.assertEqual(self.client.get("/").status_code, 302)

    def test_open_redirect_blocked(self):
        self.signup()
        self.logout()
        for target in ("https://evil.example", "//evil.example", "/\\evil.example"):
            resp = self.post(
                "/login",
                {"identifier": "alice", "password": "password123", "next": target},
            )
            self.assertEqual(resp.status_code, 302)
            self.assertEqual(resp.headers["Location"], "/", target)
            self.logout()

    def test_next_redirect_allowed_for_local_path(self):
        self.signup()
        self.logout()
        resp = self.post(
            "/login",
            {"identifier": "alice", "password": "password123", "next": "/account"},
        )
        self.assertEqual(resp.headers["Location"], "/account")

    def test_csrf_required(self):
        resp = self.client.post("/login", data={"identifier": "a", "password": "b"})
        self.assertEqual(resp.status_code, 400)
        self.signup()
        resp = self.client.post("/tasks/add", data={"title": "x"})
        self.assertEqual(resp.status_code, 400)


class TaskTests(TodoTestCase):
    def setUp(self):
        super().setUp()
        self.signup()

    def test_add_task(self):
        resp = self.add("Buy milk", description="2 litres", priority="high", due_date="2030-01-01")
        html = resp.get_data(as_text=True)
        self.assertIn("Task added", html)
        self.assertIn("Buy milk", html)
        self.assertIn("2 litres", html)
        self.assertIn("2030-01-01", html)

    def test_add_validation(self):
        self.assertIn("Title is required", self.add("   ").get_data(as_text=True))
        self.assertIn("200 characters", self.add("x" * 201).get_data(as_text=True))
        self.assertIn("valid date", self.add("T", due_date="not-a-date").get_data(as_text=True))
        self.assertIn("Priority must be", self.add("T", priority="urgent").get_data(as_text=True))

    def test_html_is_escaped(self):
        self.add("<script>alert(1)</script>")
        html = self.client.get("/").get_data(as_text=True)
        self.assertNotIn("<script>alert(1)</script>", html)
        self.assertIn("&lt;script&gt;", html)

    def test_edit_task(self):
        self.add("Old title")
        tid = self.task_id("Old title")
        page = self.client.get(f"/tasks/{tid}/edit")
        self.assertEqual(page.status_code, 200)
        self.assertIn("Old title", page.get_data(as_text=True))

        resp = self.post(
            f"/tasks/{tid}/edit",
            {
                "title": "New title",
                "description": "changed",
                "priority": "low",
                "due_date": "2031-05-06",
                "completed": "1",
            },
            follow_redirects=True,
        )
        html = resp.get_data(as_text=True)
        self.assertIn("Task updated", html)
        self.assertIn("New title", html)
        self.assertNotIn("Old title", html)
        self.assertIn("2031-05-06", html)
        self.assertIn("task prio-low done", html)

    def test_edit_validation_keeps_input(self):
        self.add("Keep me")
        tid = self.task_id("Keep me")
        resp = self.post(
            f"/tasks/{tid}/edit",
            {"title": "", "description": "typed text", "priority": "low"},
        )
        html = resp.get_data(as_text=True)
        self.assertIn("Title is required", html)
        self.assertIn("typed text", html)

    def test_toggle_task(self):
        self.add("Toggle me")
        tid = self.task_id("Toggle me")
        html = self.post(f"/tasks/{tid}/toggle", follow_redirects=True).get_data(as_text=True)
        self.assertIn("done", html)
        html = self.post(f"/tasks/{tid}/toggle", follow_redirects=True).get_data(as_text=True)
        self.assertNotIn("task prio-medium done", html)

    def test_delete_task(self):
        self.add("Delete me")
        tid = self.task_id("Delete me")
        resp = self.post(f"/tasks/{tid}/delete", follow_redirects=True)
        html = resp.get_data(as_text=True)
        self.assertIn("Task deleted", html)
        self.assertNotIn("Delete me", html)

    def test_clear_completed(self):
        self.add("Done one")
        self.add("Still open")
        self.post(f"/tasks/{self.task_id('Done one')}/toggle")
        html = self.post("/tasks/clear-completed", follow_redirects=True).get_data(as_text=True)
        self.assertIn("Removed 1 completed task", html)
        self.assertNotIn("Done one", html)
        self.assertIn("Still open", html)

    def test_filters_search_and_sort(self):
        self.add("Alpha report", priority="high", due_date="2030-03-01")
        self.add("Beta groceries", priority="low", due_date="2030-01-01")
        self.add("Gamma 100% call", priority="medium")
        self.post(f"/tasks/{self.task_id('Beta groceries')}/toggle")

        html = self.client.get("/?status=active").get_data(as_text=True)
        self.assertIn("Alpha report", html)
        self.assertNotIn("Beta groceries", html)

        html = self.client.get("/?status=completed").get_data(as_text=True)
        self.assertIn("Beta groceries", html)
        self.assertNotIn("Alpha report", html)

        html = self.client.get("/?priority=high").get_data(as_text=True)
        self.assertIn("Alpha report", html)
        self.assertNotIn("Gamma", html)

        html = self.client.get("/?q=groc").get_data(as_text=True)
        self.assertIn("Beta groceries", html)
        self.assertNotIn("Alpha report", html)

        # LIKE wildcards in the search box are treated literally
        html = self.client.get("/?q=100%25").get_data(as_text=True)
        self.assertIn("Gamma 100% call", html)
        html = self.client.get("/?q=%25").get_data(as_text=True)
        self.assertIn("Gamma 100% call", html)
        self.assertNotIn("Alpha report", html)

        html = self.client.get("/?sort=priority&status=active").get_data(as_text=True)
        self.assertLess(html.index("Alpha report"), html.index("Gamma 100% call"))

    def test_overdue_highlighted_and_counted(self):
        self.add("Late task", due_date="2000-01-01")
        html = self.client.get("/").get_data(as_text=True)
        self.assertIn("Overdue", html)
        self.assertIn('<div class="stat overdue"><strong>1</strong>', html)

    def test_users_cannot_touch_each_others_tasks(self):
        self.add("Alice private")
        tid = self.task_id("Alice private")
        self.logout()
        self.signup("bob", "bob@example.com")

        self.assertEqual(self.client.get(f"/tasks/{tid}/edit").status_code, 404)
        self.assertEqual(self.post(f"/tasks/{tid}/toggle").status_code, 404)
        self.assertEqual(self.post(f"/tasks/{tid}/delete").status_code, 404)
        self.assertEqual(
            self.post(f"/tasks/{tid}/edit", {"title": "hacked", "priority": "low"}).status_code,
            404,
        )
        self.assertNotIn("Alice private", self.client.get("/").get_data(as_text=True))

        self.logout()
        self.login("alice")
        html = self.client.get("/").get_data(as_text=True)
        self.assertIn("Alice private", html)


class AccountTests(TodoTestCase):
    def setUp(self):
        super().setUp()
        self.signup()

    def test_change_password(self):
        resp = self.post(
            "/account/password",
            {"current_password": "password123", "new_password": "newpassword9", "confirm": "newpassword9"},
            follow_redirects=True,
        )
        self.assertIn("Password updated", resp.get_data(as_text=True))
        self.logout()
        self.assertIn("Invalid", self.login(password="password123").get_data(as_text=True))
        self.assertIn("alice", self.login(password="newpassword9").get_data(as_text=True))

    def test_change_password_wrong_current(self):
        resp = self.post(
            "/account/password",
            {"current_password": "nope12345", "new_password": "newpassword9", "confirm": "newpassword9"},
            follow_redirects=True,
        )
        self.assertIn("Current password is incorrect", resp.get_data(as_text=True))

    def test_delete_account_removes_tasks(self):
        self.add("Will vanish")
        resp = self.post("/account/delete", {"password": "wrong"}, follow_redirects=True)
        self.assertIn("not deleted", resp.get_data(as_text=True))

        resp = self.post("/account/delete", {"password": "password123"}, follow_redirects=True)
        self.assertIn("deleted", resp.get_data(as_text=True))
        self.assertIn("Invalid", self.login().get_data(as_text=True))

        import sqlite3

        conn = sqlite3.connect(self.app.config["DATABASE"])
        try:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0], 0)
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
