from django import forms

from .models import Task


class TaskCreateForm(forms.ModelForm):
    class Meta:
        model = Task
        fields = ["title", "description", "priority", "due_date"]
        widgets = {
            "title": forms.TextInput(attrs={"placeholder": "What needs doing?"}),
            "description": forms.Textarea(attrs={"rows": 4}),
            "due_date": forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}),
        }


class TaskUpdateForm(TaskCreateForm):
    class Meta(TaskCreateForm.Meta):
        fields = TaskCreateForm.Meta.fields + ["completed"]
