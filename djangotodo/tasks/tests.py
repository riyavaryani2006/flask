from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import Task

User = get_user_model()
PASSWORD = "S3cure-Pass-9x!"


class TaskTestBase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("alice", "alice@example.com", PASSWORD)
        self.other = User.objects.create_user("bob", "bob@example.com", PASSWORD)
        self.client.login(username="alice", password=PASSWORD)

    def make_task(self, title="Task", user=None, **kwargs):
        return Task.objects.create(user=user or self.user, title=title, **kwargs)

    def titles(self, response):
        return [t.title for t in response.context["tasks"]]


class AccessTests(TaskTestBase):
    def test_list_requires_login(self):
        self.client.logout()
        response = self.client.get(reverse("task_list"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response["Location"])

    def test_write_views_require_login(self):
        task = self.make_task()
        self.client.logout()
        for name, args in [
            ("task_create", []),
            ("task_update", [task.pk]),
            ("task_delete", [task.pk]),
        ]:
            response = self.client.get(reverse(name, args=args))
            self.assertEqual(response.status_code, 302, name)
            self.assertIn(reverse("login"), response["Location"], name)
        for name, args in [("task_toggle", [task.pk]), ("task_clear_completed", [])]:
            response = self.client.post(reverse(name, args=args))
            self.assertEqual(response.status_code, 302, name)
            self.assertIn(reverse("login"), response["Location"], name)
        self.assertTrue(Task.objects.filter(pk=task.pk).exists())

    def test_users_cannot_touch_each_others_tasks(self):
        theirs = self.make_task("Bob private", user=self.other)
        self.assertNotContains(self.client.get(reverse("task_list")), "Bob private")
        self.assertEqual(
            self.client.get(reverse("task_update", args=[theirs.pk])).status_code, 404
        )
        self.assertEqual(
            self.client.post(
                reverse("task_update", args=[theirs.pk]),
                {"title": "hacked", "priority": "low"},
            ).status_code,
            404,
        )
        self.assertEqual(
            self.client.post(reverse("task_toggle", args=[theirs.pk])).status_code, 404
        )
        self.assertEqual(
            self.client.post(reverse("task_delete", args=[theirs.pk])).status_code, 404
        )
        theirs.refresh_from_db()
        self.assertEqual(theirs.title, "Bob private")
        self.assertFalse(theirs.completed)


class CrudTests(TaskTestBase):
    def test_create_task(self):
        response = self.client.post(
            reverse("task_create"),
            {
                "title": "Buy milk",
                "description": "2 litres",
                "priority": "high",
                "due_date": "2030-01-01",
            },
            follow=True,
        )
        self.assertContains(response, "Task added")
        task = Task.objects.get(title="Buy milk")
        self.assertEqual(task.user, self.user)
        self.assertEqual(task.priority, "high")
        self.assertEqual(str(task.due_date), "2030-01-01")
        self.assertFalse(task.completed)

    def test_create_requires_title(self):
        response = self.client.post(
            reverse("task_create"), {"title": "   ", "priority": "low"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("title", response.context["form"].errors)
        self.assertEqual(Task.objects.count(), 0)

    def test_create_rejects_bad_priority_and_date(self):
        response = self.client.post(
            reverse("task_create"),
            {"title": "x", "priority": "urgent", "due_date": "not-a-date"},
        )
        self.assertEqual(response.status_code, 200)
        errors = response.context["form"].errors
        self.assertIn("priority", errors)
        self.assertIn("due_date", errors)

    def test_html_is_escaped(self):
        self.make_task("<script>alert(1)</script>")
        response = self.client.get(reverse("task_list"))
        self.assertNotContains(response, "<script>alert(1)</script>")
        self.assertContains(response, "&lt;script&gt;")

    def test_update_task_and_completed_at(self):
        task = self.make_task("Old title")
        response = self.client.post(
            reverse("task_update", args=[task.pk]),
            {
                "title": "New title",
                "description": "changed",
                "priority": "low",
                "due_date": "2031-05-06",
                "completed": "on",
            },
            follow=True,
        )
        self.assertContains(response, "Task updated")
        task.refresh_from_db()
        self.assertEqual(task.title, "New title")
        self.assertEqual(task.priority, "low")
        self.assertTrue(task.completed)
        self.assertIsNotNone(task.completed_at)

        # un-completing clears completed_at
        self.client.post(
            reverse("task_update", args=[task.pk]),
            {"title": "New title", "priority": "low"},
        )
        task.refresh_from_db()
        self.assertFalse(task.completed)
        self.assertIsNone(task.completed_at)

    def test_toggle_task(self):
        task = self.make_task()
        self.client.post(reverse("task_toggle", args=[task.pk]))
        task.refresh_from_db()
        self.assertTrue(task.completed)
        self.assertIsNotNone(task.completed_at)
        self.client.post(reverse("task_toggle", args=[task.pk]))
        task.refresh_from_db()
        self.assertFalse(task.completed)
        self.assertIsNone(task.completed_at)

    def test_toggle_get_not_allowed(self):
        task = self.make_task()
        response = self.client.get(reverse("task_toggle", args=[task.pk]))
        self.assertEqual(response.status_code, 405)

    def test_toggle_redirects_to_safe_next_only(self):
        task = self.make_task()
        url = reverse("task_toggle", args=[task.pk])
        response = self.client.post(url, {"next": "/?status=active"})
        self.assertEqual(response["Location"], "/?status=active")
        response = self.client.post(url, {"next": "https://evil.example/"})
        self.assertEqual(response["Location"], reverse("task_list"))

    def test_delete_task(self):
        task = self.make_task("Delete me")
        page = self.client.get(reverse("task_delete", args=[task.pk]))
        self.assertContains(page, "Delete me")
        response = self.client.post(reverse("task_delete", args=[task.pk]), follow=True)
        self.assertContains(response, "Task deleted")
        self.assertFalse(Task.objects.filter(pk=task.pk).exists())

    def test_clear_completed(self):
        self.make_task("Done", completed=True)
        self.make_task("Open")
        self.make_task("Bob done", user=self.other, completed=True)
        response = self.client.post(reverse("task_clear_completed"), follow=True)
        self.assertContains(response, "Removed 1 completed task")
        self.assertEqual(
            sorted(Task.objects.values_list("title", flat=True)), ["Bob done", "Open"]
        )
        response = self.client.post(reverse("task_clear_completed"), follow=True)
        self.assertContains(response, "No completed tasks to remove")


class ListViewTests(TaskTestBase):
    def test_empty_state(self):
        self.assertContains(self.client.get(reverse("task_list")), "No tasks yet")

    def test_filters_and_search(self):
        self.make_task("Alpha report", priority="high")
        self.make_task("Beta groceries", priority="low", completed=True)
        self.make_task("Gamma call", priority="medium", description="phone the bank")
        url = reverse("task_list")

        self.assertEqual(
            set(self.titles(self.client.get(url, {"status": "active"}))),
            {"Alpha report", "Gamma call"},
        )
        self.assertEqual(
            self.titles(self.client.get(url, {"status": "completed"})), ["Beta groceries"]
        )
        self.assertEqual(
            self.titles(self.client.get(url, {"priority": "high"})), ["Alpha report"]
        )
        self.assertEqual(self.titles(self.client.get(url, {"q": "GROC"})), ["Beta groceries"])
        self.assertEqual(self.titles(self.client.get(url, {"q": "bank"})), ["Gamma call"])
        self.assertContains(
            self.client.get(url, {"q": "nothing-matches"}), "No tasks match your filters"
        )

    def test_sorting(self):
        today = timezone.localdate()
        self.make_task("Low", priority="low", due_date=today + timedelta(days=1))
        self.make_task("High", priority="high", due_date=today + timedelta(days=9))
        self.make_task("Medium", priority="medium")
        url = reverse("task_list")

        self.assertEqual(
            self.titles(self.client.get(url, {"sort": "priority"})), ["High", "Medium", "Low"]
        )
        due = self.titles(self.client.get(url, {"sort": "due"}))
        self.assertEqual(due[:2], ["Low", "High"])
        self.assertEqual(
            self.titles(self.client.get(url, {"sort": "oldest"})), ["Low", "High", "Medium"]
        )
        self.assertEqual(
            self.titles(self.client.get(url, {"sort": "newest"})), ["Medium", "High", "Low"]
        )

    def test_completed_tasks_sink_to_bottom(self):
        self.make_task("Done early", completed=True)
        self.make_task("Open later")
        self.assertEqual(
            self.titles(self.client.get(reverse("task_list"))), ["Open later", "Done early"]
        )

    def test_stats_and_overdue(self):
        yesterday = timezone.localdate() - timedelta(days=1)
        self.make_task("Late", due_date=yesterday)
        self.make_task("Late but done", due_date=yesterday, completed=True)
        self.make_task("Fine")
        self.make_task("Bob late", user=self.other, due_date=yesterday)
        response = self.client.get(reverse("task_list"))
        self.assertEqual(
            response.context["stats"], {"total": 3, "active": 2, "done": 1, "overdue": 1}
        )
        self.assertContains(response, "Overdue")

    def test_is_overdue_property(self):
        yesterday = timezone.localdate() - timedelta(days=1)
        tomorrow = timezone.localdate() + timedelta(days=1)
        self.assertTrue(self.make_task(due_date=yesterday).is_overdue)
        self.assertFalse(self.make_task(due_date=tomorrow).is_overdue)
        self.assertFalse(self.make_task(due_date=yesterday, completed=True).is_overdue)
        self.assertFalse(self.make_task().is_overdue)
