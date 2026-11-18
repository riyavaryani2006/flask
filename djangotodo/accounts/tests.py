from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from tasks.models import Task

User = get_user_model()
PASSWORD = "S3cure-Pass-9x!"


class SignUpTests(TestCase):
    def signup(self, **overrides):
        data = {
            "username": "alice",
            "email": "alice@example.com",
            "password1": PASSWORD,
            "password2": PASSWORD,
        }
        data.update(overrides)
        return self.client.post(reverse("signup"), data, follow=True)

    def test_signup_creates_user_and_logs_in(self):
        response = self.signup()
        self.assertContains(response, "Your account is ready")
        self.assertTrue(User.objects.filter(username="alice").exists())
        self.assertEqual(response.context["user"].username, "alice")
        self.assertEqual(response.redirect_chain[-1][0], reverse("task_list"))

    def test_signup_requires_email(self):
        response = self.signup(email="")
        self.assertFalse(User.objects.exists())
        self.assertIn("email", response.context["form"].errors)

    def test_duplicate_email_rejected(self):
        User.objects.create_user("bob", "ALICE@example.com", PASSWORD)
        response = self.signup()
        self.assertIn("email", response.context["form"].errors)
        self.assertFalse(User.objects.filter(username="alice").exists())

    def test_password_validation(self):
        response = self.signup(password1="123", password2="123")
        self.assertFalse(User.objects.exists())
        self.assertIn("password2", response.context["form"].errors)

    def test_password_mismatch(self):
        response = self.signup(password2="Different-Pass-1!")
        self.assertFalse(User.objects.exists())
        self.assertIn("password2", response.context["form"].errors)

    def test_logged_in_user_is_redirected_away_from_signup(self):
        self.signup()
        response = self.client.get(reverse("signup"))
        self.assertRedirects(response, reverse("task_list"))


class LoginLogoutTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("alice", "alice@example.com", PASSWORD)

    def test_login(self):
        response = self.client.post(
            reverse("login"), {"username": "alice", "password": PASSWORD}, follow=True
        )
        self.assertEqual(response.redirect_chain[-1][0], reverse("task_list"))
        self.assertTrue(response.context["user"].is_authenticated)

    def test_login_wrong_password(self):
        response = self.client.post(
            reverse("login"), {"username": "alice", "password": "wrong"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context["user"].is_authenticated)

    def test_login_honours_safe_next_only(self):
        url = reverse("login")
        response = self.client.post(
            url, {"username": "alice", "password": PASSWORD, "next": "/accounts/"}
        )
        self.assertEqual(response["Location"], "/accounts/")
        self.client.post(reverse("logout"))
        response = self.client.post(
            url, {"username": "alice", "password": PASSWORD, "next": "https://evil.example/"}
        )
        self.assertEqual(response["Location"], reverse("task_list"))

    def test_logout_requires_post(self):
        self.client.login(username="alice", password=PASSWORD)
        self.assertEqual(self.client.get(reverse("logout")).status_code, 405)
        response = self.client.post(reverse("logout"))
        self.assertRedirects(response, reverse("login"))
        self.assertEqual(self.client.get(reverse("task_list")).status_code, 302)


class AccountTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("alice", "alice@example.com", PASSWORD)
        self.client.login(username="alice", password=PASSWORD)

    def test_account_requires_login(self):
        self.client.logout()
        self.assertEqual(self.client.get(reverse("account")).status_code, 302)

    def test_change_password(self):
        new = "An0ther-Pass-77?"
        response = self.client.post(
            reverse("password_change"),
            {"old_password": PASSWORD, "new_password1": new, "new_password2": new},
        )
        self.assertRedirects(response, reverse("password_change_done"))
        self.client.logout()
        self.assertFalse(self.client.login(username="alice", password=PASSWORD))
        self.assertTrue(self.client.login(username="alice", password=new))

    def test_delete_account_requires_correct_password(self):
        response = self.client.post(reverse("delete_account"), {"password": "wrong"})
        self.assertContains(response, "not deleted")
        self.assertTrue(User.objects.filter(pk=self.user.pk).exists())

    def test_delete_account_removes_user_and_tasks(self):
        Task.objects.create(user=self.user, title="Will vanish")
        response = self.client.post(
            reverse("delete_account"), {"password": PASSWORD}, follow=True
        )
        self.assertContains(response, "deleted")
        self.assertFalse(User.objects.filter(pk=self.user.pk).exists())
        self.assertEqual(Task.objects.count(), 0)
        self.assertEqual(self.client.get(reverse("task_list")).status_code, 302)
