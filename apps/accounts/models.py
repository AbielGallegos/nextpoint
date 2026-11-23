"""Identidad, estructura institucional y control de acceso (RBAC + alcance contextual)."""
import hashlib
import secrets
from datetime import timedelta

from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models
from django.utils import timezone


class Institution(models.Model):
    code = models.CharField("código", max_length=30, unique=True)
    name = models.CharField("nombre", max_length=200)
    status = models.CharField(max_length=20, default="activa", choices=[("activa", "Activa"), ("inactiva", "Inactiva")])
    data_controller_contact = models.CharField("contacto responsable de datos", max_length=200, blank=True)

    class Meta:
        verbose_name = "institución"
        verbose_name_plural = "instituciones"

    def __str__(self):
        return self.name


class Campus(models.Model):
    institution = models.ForeignKey(Institution, on_delete=models.PROTECT, related_name="campuses")
    code = models.CharField("código", max_length=30)
    name = models.CharField("nombre", max_length=120)
    timezone = models.CharField(max_length=60, default="America/Mexico_City")
    active = models.BooleanField(default=True)

    class Meta:
        verbose_name_plural = "campus"
        constraints = [models.UniqueConstraint(fields=["institution", "code"], name="uniq_campus_code")]
        ordering = ["name"]

    def __str__(self):
        return self.name


class Area(models.Model):
    campus = models.ForeignKey(Campus, on_delete=models.PROTECT, related_name="areas")
    code = models.CharField("código", max_length=30)
    name = models.CharField("nombre", max_length=120)
    contact_email = models.EmailField("correo de contacto", blank=True)
    active = models.BooleanField(default=True)

    class Meta:
        verbose_name = "área"
        constraints = [models.UniqueConstraint(fields=["campus", "code"], name="uniq_area_code")]
        ordering = ["name"]

    def __str__(self):
        return self.name


class UserManager(BaseUserManager):
    use_in_migrations = True

    def create_user(self, email, password=None, **extra):
        if not email:
            raise ValueError("El correo es obligatorio")
        email = self.normalize_email(email).lower()
        user = self.model(email=email, **extra)
        user.set_password(password)
        user.save(using=self._db)
        return user


class User(AbstractBaseUser, PermissionsMixin):
    """Cuenta de NextPoint. PII mínima: nombre mostrado y correo (ficticio en la demo)."""

    class Status(models.TextChoices):
        PENDING = "pendiente", "Pendiente"
        ACTIVE = "activo", "Activo"
        SUSPENDED = "suspendido", "Suspendido"
        DISABLED = "desactivado", "Desactivado"

    email = models.EmailField("correo", unique=True)
    display_name = models.CharField("nombre mostrado", max_length=120)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE)
    campus = models.ForeignKey(Campus, on_delete=models.PROTECT, null=True, blank=True, related_name="users")
    is_active = models.BooleanField(default=True, editable=False)
    is_staff = models.BooleanField(default=False, editable=False)  # el admin de Django no se publica
    date_joined = models.DateTimeField(default=timezone.now)
    notify_opportunities = models.BooleanField("avisarme de oportunidades", default=True)

    objects = UserManager()
    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["display_name"]

    class Meta:
        verbose_name = "usuario"
        indexes = [models.Index(fields=["campus", "status"])]

    def save(self, *args, **kwargs):
        self.email = (self.email or "").strip().lower()
        self.is_active = self.status == self.Status.ACTIVE
        super().save(*args, **kwargs)

    def __str__(self):
        return self.display_name or self.email

    @property
    def first_name(self):
        return (self.display_name or "").split(" ")[0]

    @property
    def initials(self):
        parts = [p for p in (self.display_name or self.email).split() if p]
        return "".join(p[0] for p in parts[:2]).upper()

    @property
    def masked_email(self):
        """Dato minimizado para listados administrativos."""
        local, _, domain = self.email.partition("@")
        return f"{local[:3]}…@{domain}"


class Role(models.Model):
    STUDENT = "estudiante"
    INSTRUCTOR = "docente"
    MANAGER = "gestor"
    COORDINATOR = "coordinacion"
    SUPPORT = "soporte"
    ADMIN = "admin_plataforma"

    code = models.CharField(max_length=40, unique=True)
    name = models.CharField(max_length=80)
    description = models.CharField(max_length=300, blank=True)
    is_privileged = models.BooleanField(default=False)
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["order"]

    def __str__(self):
        return self.name


class Permission(models.Model):
    code = models.CharField(max_length=60, unique=True)
    module = models.CharField(max_length=40)
    description = models.CharField(max_length=200)

    class Meta:
        verbose_name = "permiso"
        ordering = ["module", "code"]

    def __str__(self):
        return self.code


class RolePermission(models.Model):
    role = models.ForeignKey(Role, on_delete=models.CASCADE, related_name="role_permissions")
    permission = models.ForeignKey(Permission, on_delete=models.CASCADE)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["role", "permission"], name="uniq_role_permission")]


class UserRole(models.Model):
    """Asignación contextual: el alcance lo dan area (área), campus (campus) o ninguno (global)."""

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="user_roles")
    role = models.ForeignKey(Role, on_delete=models.PROTECT, related_name="assignments")
    campus = models.ForeignKey(Campus, on_delete=models.PROTECT, null=True, blank=True)
    area = models.ForeignKey(Area, on_delete=models.PROTECT, null=True, blank=True)
    granted_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    granted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "role", "campus", "area"], name="uniq_user_role_scope")]

    @property
    def scope_label(self):
        if self.area_id:
            return f"Área: {self.area.name}"
        if self.campus_id:
            return f"Campus: {self.campus.name}"
        return "Global (plataforma)"

    def __str__(self):
        return f"{self.user} · {self.role} · {self.scope_label}"


class StudentProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="student_profile")
    program = models.CharField("carrera / programa", max_length=120, blank=True)
    semester = models.PositiveSmallIntegerField("semestre", null=True, blank=True)


class StaffProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="staff_profile")
    area = models.ForeignKey(Area, on_delete=models.SET_NULL, null=True, blank=True)
    position = models.CharField("puesto", max_length=120, blank=True)


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class Invitation(models.Model):
    """Alta de cuentas privilegiadas: solo por invitación, de un solo uso y con caducidad."""

    email = models.EmailField()
    display_name = models.CharField(max_length=120)
    role = models.ForeignKey(Role, on_delete=models.PROTECT)
    campus = models.ForeignKey(Campus, on_delete=models.PROTECT, null=True, blank=True)
    area = models.ForeignKey(Area, on_delete=models.PROTECT, null=True, blank=True)
    token_hash = models.CharField(max_length=64, unique=True)
    created_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name="invitations_sent")
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    accepted_at = models.DateTimeField(null=True, blank=True)
    accepted_user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    revoked = models.BooleanField(default=False)

    @classmethod
    def issue(cls, *, created_by, days=7, **fields):
        token = secrets.token_urlsafe(32)
        inv = cls.objects.create(
            token_hash=_hash_token(token), created_by=created_by, expires_at=timezone.now() + timedelta(days=days), **fields
        )
        return inv, token

    @classmethod
    def find(cls, token: str):
        return cls.objects.filter(token_hash=_hash_token(token)).select_related("role", "campus", "area").first()

    @property
    def status(self):
        if self.revoked:
            return "revocada"
        if self.accepted_at:
            return "aceptada"
        if self.expires_at <= timezone.now():
            return "vencida"
        return "pendiente"

    @property
    def usable(self):
        return self.status == "pendiente"


class LoginAttempt(models.Model):
    """Conteo de intentos fallidos para limitar fuerza bruta (se guarda un hash, no el correo)."""

    key_hash = models.CharField(max_length=64, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    @staticmethod
    def key_for(email: str, ip: str) -> str:
        return _hash_token(f"{(email or '').strip().lower()}|{ip}")
