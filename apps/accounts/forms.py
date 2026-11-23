from django import forms
from django.contrib.auth.password_validation import validate_password

from .models import Area, Campus, Role, StudentProfile, User


class LoginForm(forms.Form):
    email = forms.EmailField(label="Correo", max_length=254, widget=forms.EmailInput(attrs={"autocomplete": "username", "autofocus": True}))
    password = forms.CharField(label="Contraseña", strip=False, widget=forms.PasswordInput(attrs={"autocomplete": "current-password"}))
    next = forms.CharField(required=False, widget=forms.HiddenInput)


class ProfileForm(forms.ModelForm):
    program = forms.CharField(label="Carrera / programa", max_length=120, required=False)
    semester = forms.IntegerField(label="Semestre", min_value=1, max_value=14, required=False)

    class Meta:
        model = User
        fields = ["display_name", "notify_opportunities"]
        labels = {"display_name": "Nombre mostrado"}
        help_texts = {"display_name": "Así te verán las áreas que atienden tus solicitudes."}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        profile = getattr(self.instance, "student_profile", None) if self.instance.pk and hasattr(self.instance, "student_profile") else None
        if profile:
            self.fields["program"].initial = profile.program
            self.fields["semester"].initial = profile.semester
        else:
            del self.fields["program"]
            del self.fields["semester"]

    def save(self, commit=True):
        user = super().save(commit)
        if "program" in self.fields:
            StudentProfile.objects.update_or_create(
                user=user, defaults={"program": self.cleaned_data.get("program") or "", "semester": self.cleaned_data.get("semester")}
            )
        return user


class AcceptInvitationForm(forms.Form):
    password1 = forms.CharField(label="Crea una contraseña", strip=False, widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
                                help_text="Mínimo 10 caracteres; evita contraseñas comunes o solo numéricas.")
    password2 = forms.CharField(label="Confirma la contraseña", strip=False, widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}))

    def __init__(self, *args, user=None, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

    def clean(self):
        data = super().clean()
        p1, p2 = data.get("password1"), data.get("password2")
        if p1 and p2 and p1 != p2:
            self.add_error("password2", "Las contraseñas no coinciden.")
        if p1:
            try:
                validate_password(p1, self.user)
            except forms.ValidationError as e:
                self.add_error("password1", e)
        return data


class InvitationForm(forms.Form):
    email = forms.EmailField(label="Correo de la persona invitada")
    display_name = forms.CharField(label="Nombre mostrado", max_length=120)
    role = forms.ModelChoiceField(label="Rol", queryset=Role.objects.none(), empty_label="Selecciona un rol")
    campus = forms.ModelChoiceField(label="Campus", queryset=Campus.objects.none(), required=False)
    area = forms.ModelChoiceField(label="Área (obligatoria para gestores)", queryset=Area.objects.none(), required=False,
                                  help_text="El gestor solo verá y operará registros de esta área.")

    def __init__(self, *args, roles=None, campuses=None, areas=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["role"].queryset = roles
        self.fields["campus"].queryset = campuses
        self.fields["area"].queryset = areas

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email=email).exists():
            raise forms.ValidationError("Ya existe una cuenta con ese correo. Usa la recuperación de acceso.")
        return email

    def clean(self):
        data = super().clean()
        role, area, campus = data.get("role"), data.get("area"), data.get("campus")
        if role is None:
            return data
        if role.code == Role.MANAGER and area is None:
            self.add_error("area", "Un gestor necesita un área específica.")
        if role.code != Role.ADMIN and campus is None and area is None:
            self.add_error("campus", "Selecciona el campus de la cuenta.")
        if area is not None and campus is not None and area.campus_id != campus.pk:
            self.add_error("area", "El área no pertenece al campus seleccionado.")
        if area is not None and campus is None:
            data["campus"] = area.campus
        return data


class RoleAssignForm(forms.Form):
    role = forms.ModelChoiceField(label="Rol", queryset=Role.objects.none(), empty_label="Selecciona un rol")
    area = forms.ModelChoiceField(label="Área", queryset=Area.objects.none(), required=False)

    def __init__(self, *args, roles=None, areas=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["role"].queryset = roles
        self.fields["area"].queryset = areas

    def clean(self):
        data = super().clean()
        if data.get("role") and data["role"].code == Role.MANAGER and not data.get("area"):
            self.add_error("area", "Un gestor necesita un área específica.")
        return data
