from django import forms

from apps.catalog.models import normalize_tags

from .models import Course, Lesson


class CourseForm(forms.ModelForm):
    tags_text = forms.CharField(label="Etiquetas", required=False, help_text="Separadas por coma (SmartMatch las usa).")

    class Meta:
        model = Course
        fields = ["title", "summary", "description", "level", "mode", "duration_minutes", "capacity", "area", "content_license_ok"]
        widgets = {"description": forms.Textarea(attrs={"rows": 4})}
        labels = {"content_license_ok": "Confirmo que el contenido es original o cuenta con permiso de uso"}

    def __init__(self, *args, areas=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["area"].queryset = areas
        self.fields["area"].label = "Área responsable de la revisión"
        if self.instance.pk:
            self.fields["tags_text"].initial = ", ".join(self.instance.tags or [])

    def save(self, commit=True):
        self.instance.tags = normalize_tags(self.cleaned_data.get("tags_text", ""))
        self.instance.campus = self.cleaned_data["area"].campus
        return super().save(commit)


class LessonForm(forms.ModelForm):
    module_title = forms.CharField(label="Módulo", max_length=140, help_text="Si el módulo no existe, se crea.")

    class Meta:
        model = Lesson
        fields = ["title", "kind", "duration_minutes", "content", "published"]
        widgets = {"content": forms.Textarea(attrs={"rows": 12})}
        labels = {"published": "Lección visible al publicarse el curso", "duration_minutes": "Duración (min)"}
