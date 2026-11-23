"""Parámetros operativos versionados y mesa de soporte técnico."""
from django.conf import settings
from django.db import models
from django.utils import timezone

# clave: (valor por defecto, tipo, descripción, mínimo, máximo)
POLICY_DEFAULTS = {
    "max_loan_days": (7, int, "Días máximos de préstamo (ejemplo, política no aprobada)", 1, 60),
    "max_concurrent_loans": (2, int, "Solicitudes/préstamos activos simultáneos por estudiante (ejemplo)", 1, 10),
    "request_ack_target_days": (2, int, "Meta de primer acuse en días hábiles (propuesta)", 1, 15),
    "max_attachment_mb": (5, int, "Tamaño máximo de adjuntos en MB", 1, 5),
    "list_page_size": (20, int, "Elementos por página en listados", 5, 100),
    "smartmatch_max_results": (10, int, "Resultados máximos de SmartMatch", 3, 20),
    "module_courses_enabled": (True, bool, "Módulo de cursos habilitado", None, None),
    "module_smartmatch_enabled": (True, bool, "Módulo SmartMatch habilitado", None, None),
    "payments_enabled": (False, bool, "Pagos reales (siempre deshabilitado en el prototipo)", None, None),
}


class SystemPolicy(models.Model):
    campus = models.ForeignKey("accounts.Campus", on_delete=models.CASCADE, null=True, blank=True)
    key = models.CharField(max_length=60)
    value = models.JSONField()
    version = models.PositiveIntegerField(default=1)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    effective_at = models.DateTimeField(default=timezone.now)
    active = models.BooleanField(default=True)

    class Meta:
        verbose_name = "política"
        ordering = ["key", "-version"]
        indexes = [models.Index(fields=["key", "campus", "active"])]


def get_policy(key, campus=None):
    default, typ, *_ = POLICY_DEFAULTS[key]
    if key == "payments_enabled":
        return False  # bloqueado por diseño en el prototipo
    qs = SystemPolicy.objects.filter(key=key, active=True)
    row = None
    if campus is not None:
        row = qs.filter(campus=campus).order_by("-version").first()
    if row is None:
        row = qs.filter(campus__isnull=True).order_by("-version").first()
    if row is None:
        return default
    try:
        return typ(row.value)
    except (TypeError, ValueError):
        return default


class SupportTicket(models.Model):
    class Status(models.TextChoices):
        NEW = "nuevo", "Nuevo"
        ASSIGNED = "asignado", "Asignado"
        WORKING = "atendiendo", "Atendiendo"
        RESOLVED = "resuelto", "Resuelto"
        CLOSED = "cerrado", "Cerrado"

    CATEGORIES = [("cuenta", "Cuenta y acceso"), ("navegacion", "Navegación o error de pantalla"), ("otro", "Otro problema técnico")]

    folio = models.CharField(max_length=20, unique=True, blank=True)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="support_tickets")
    category = models.CharField(max_length=20, choices=CATEGORIES)
    subject = models.CharField(max_length=140)
    description = models.TextField(max_length=2000)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.NEW)
    assignee = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    result = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if not self.folio:
            self.folio = f"NP-SOP-{self.pk:05d}"
            super().save(update_fields=["folio"])

    def __str__(self):
        return self.folio


class SupportMessage(models.Model):
    ticket = models.ForeignKey(SupportTicket, on_delete=models.CASCADE, related_name="messages")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    body = models.TextField(max_length=2000)
    internal = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]
