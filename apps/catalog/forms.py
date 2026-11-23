from django import forms

from .models import Location, Resource, ResourceCategory, ResourceUnit, normalize_tags


class ResourceForm(forms.ModelForm):
    tags_text = forms.CharField(label="Etiquetas", required=False, help_text="Separadas por coma. SmartMatch las usa para explicar coincidencias.")

    class Meta:
        model = Resource
        fields = ["name", "code", "category", "area", "description", "requirements", "loan_policy", "max_loan_days", "location", "status"]
        widgets = {"description": forms.Textarea(attrs={"rows": 4})}

    def __init__(self, *args, areas=None, campus=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.campus = campus
        self.fields["area"].queryset = areas
        self.fields["category"].queryset = ResourceCategory.objects.filter(campus=campus, active=True)
        self.fields["location"].queryset = Location.objects.filter(campus=campus)
        self.fields["location"].required = False
        if self.instance.pk:
            self.fields["tags_text"].initial = ", ".join(self.instance.tags or [])
        self.fields["status"].choices = [c for c in Resource.Status.choices]

    def clean_code(self):
        code = self.cleaned_data["code"].strip().upper()
        qs = Resource.objects.filter(campus=self.campus, code=code)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError("Ya existe un recurso con ese código en el campus.")
        return code

    def clean(self):
        data = super().clean()
        if data.get("status") == Resource.Status.PUBLISHED:
            has_units = self.instance.pk and self.instance.units.exclude(state=ResourceUnit.State.RETIRED).exists()
            if not has_units:
                self.add_error("status", "No se puede publicar un recurso sin ejemplares: guárdalo como borrador y registra al menos uno.")
        return data

    def save(self, commit=True):
        self.instance.tags = normalize_tags(self.cleaned_data.get("tags_text", ""))
        self.instance.campus = self.campus
        return super().save(commit)


class UnitForm(forms.ModelForm):
    class Meta:
        model = ResourceUnit
        fields = ["serial", "condition", "location", "notes"]

    def __init__(self, *args, campus=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["location"].queryset = Location.objects.filter(campus=campus)
        self.fields["location"].required = False
        for name, f in self.fields.items():
            f.widget.attrs["class"] = "select" if name in ("condition", "location") else "input"

    def clean_serial(self):
        return self.cleaned_data["serial"].strip().upper()


class CategoryForm(forms.ModelForm):
    class Meta:
        model = ResourceCategory
        fields = ["name", "slug", "parent", "icon"]

    def __init__(self, *args, campus=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.campus = campus
        self.fields["parent"].queryset = ResourceCategory.objects.filter(campus=campus)
        self.fields["parent"].required = False

    def clean_slug(self):
        slug = self.cleaned_data["slug"]
        if ResourceCategory.objects.filter(campus=self.campus, slug=slug).exclude(pk=self.instance.pk or 0).exists():
            raise forms.ValidationError("Ya existe una categoría con ese identificador.")
        return slug

    def save(self, commit=True):
        self.instance.campus = self.campus
        return super().save(commit)
