from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import redirect, render
from django.urls import reverse_lazy
from django.views.generic import CreateView, TemplateView

from .forms import SignUpForm


class AccountView(LoginRequiredMixin, TemplateView):
    template_name = "accounts/account.html"


class SignUpView(CreateView):
    form_class = SignUpForm
    template_name = "registration/signup.html"
    success_url = reverse_lazy("task_list")

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            return redirect("task_list")
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        response = super().form_valid(form)
        login(self.request, self.object)
        messages.success(self.request, "Welcome! Your account is ready.")
        return response


@login_required
def delete_account(request):
    """Delete the current user (and, via CASCADE, all of their tasks)."""
    if request.method == "POST":
        if request.user.check_password(request.POST.get("password", "")):
            user = request.user
            logout(request)
            user.delete()
            messages.info(request, "Your account and all its tasks have been deleted.")
            return redirect("signup")
        messages.error(request, "Incorrect password. Your account was not deleted.")
    return render(request, "accounts/delete_account.html")
