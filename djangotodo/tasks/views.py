from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Case, Count, F, IntegerField, Q, When
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST
from django.views.generic import CreateView, DeleteView, ListView, UpdateView

from .forms import TaskCreateForm, TaskUpdateForm
from .models import Task


def _next_url(request, default="task_list"):
    """Return a safe same-site URL from the POSTed `next` field, else a default."""
    target = request.POST.get("next", "")
    if target and url_has_allowed_host_and_scheme(
        target,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return target
    return reverse(default)


class OwnTasksMixin(LoginRequiredMixin):
    """Restrict every query to the logged-in user's tasks (others get a 404)."""

    def get_queryset(self):
        return Task.objects.filter(user=self.request.user)


class TaskListView(LoginRequiredMixin, ListView):
    template_name = "tasks/task_list.html"
    context_object_name = "tasks"

    def get_queryset(self):
        qs = Task.objects.filter(user=self.request.user)
        params = self.request.GET

        status = params.get("status", "all")
        if status == "active":
            qs = qs.filter(completed=False)
        elif status == "completed":
            qs = qs.filter(completed=True)

        priority = params.get("priority", "")
        if priority in Task.Priority.values:
            qs = qs.filter(priority=priority)

        q = params.get("q", "").strip()
        if q:
            qs = qs.filter(Q(title__icontains=q) | Q(description__icontains=q))

        sort = params.get("sort", "newest")
        if sort == "oldest":
            order = ["completed", "created_at", "id"]
        elif sort == "due":
            order = ["completed", F("due_date").asc(nulls_last=True), "-id"]
        elif sort == "priority":
            qs = qs.annotate(
                priority_rank=Case(
                    When(priority=Task.Priority.HIGH, then=0),
                    When(priority=Task.Priority.MEDIUM, then=1),
                    default=2,
                    output_field=IntegerField(),
                )
            )
            order = ["completed", "priority_rank", "-id"]
        else:
            order = ["completed", "-created_at", "-id"]
        return qs.order_by(*order)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        params = self.request.GET
        today = timezone.localdate()

        context["stats"] = Task.objects.filter(user=self.request.user).aggregate(
            total=Count("id"),
            active=Count("id", filter=Q(completed=False)),
            done=Count("id", filter=Q(completed=True)),
            overdue=Count("id", filter=Q(completed=False, due_date__lt=today)),
        )
        status = params.get("status", "all")
        priority = params.get("priority", "")
        sort = params.get("sort", "newest")
        context.update(
            {
                "status": status if status in ("active", "completed") else "all",
                "priority": priority if priority in Task.Priority.values else "",
                "sort": sort if sort in ("oldest", "due", "priority") else "newest",
                "q": params.get("q", "").strip(),
                "priorities": Task.Priority.choices,
            }
        )
        return context


class TaskCreateView(LoginRequiredMixin, CreateView):
    form_class = TaskCreateForm
    template_name = "tasks/task_form.html"
    success_url = reverse_lazy("task_list")
    extra_context = {"heading": "New task", "submit_label": "Add task"}

    def form_valid(self, form):
        form.instance.user = self.request.user
        messages.success(self.request, "Task added.")
        return super().form_valid(form)


class TaskUpdateView(OwnTasksMixin, UpdateView):
    form_class = TaskUpdateForm
    template_name = "tasks/task_form.html"
    success_url = reverse_lazy("task_list")
    extra_context = {"heading": "Edit task", "submit_label": "Save changes"}

    def form_valid(self, form):
        messages.success(self.request, "Task updated.")
        return super().form_valid(form)


class TaskDeleteView(OwnTasksMixin, DeleteView):
    template_name = "tasks/task_confirm_delete.html"
    success_url = reverse_lazy("task_list")

    def form_valid(self, form):
        messages.success(self.request, "Task deleted.")
        return super().form_valid(form)


@login_required
@require_POST
def toggle_task(request, pk):
    task = get_object_or_404(Task, pk=pk, user=request.user)
    task.completed = not task.completed
    task.save()  # Task.save() keeps completed_at in sync
    return redirect(_next_url(request))


@login_required
@require_POST
def clear_completed(request):
    deleted, _ = Task.objects.filter(user=request.user, completed=True).delete()
    if deleted:
        messages.success(
            request, f"Removed {deleted} completed task{'s' if deleted != 1 else ''}."
        )
    else:
        messages.info(request, "No completed tasks to remove.")
    return redirect("task_list")
