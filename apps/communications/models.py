"""Avisos/oportunidades con audiencia y vigencia, lecturas individuales y notificaciones internas."""
from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone


class Alert(models.Model):
    class Category(models.TextChoices):
        GENERAL = "general", "General"
        MATERIALS = "materiales", "Materiales"
        MAINTENANCE = "mantenimiento", "Mantenimiento"
        COURSES = "cursos", "Cursos"
        SCHOLARSHIPS = "becas", "Becas"
        CALLS = "convocatorias", "Convocatorias"
        OPPORTUNITY = "oportunidad", "Oportunidad académica"

    OPPORTUNITY_CATEGORIES = ("becas", "convocatorias", "oportunidad")

    class Priority(models.TextChoices):
        NORMAL = "normal", "Normal"
        HIGH = "alta", "Alta"
        CRITICAL = "critica", "Crítica (verificada)"

    class Status(models.TextChoices):
        DRAFT = "borrador", "Borrador"
        PUBLISHED = "publicado", "Publicado"
        WITHDRAWN = "retirado", "Retirado"

    class Audience(models.TextChoices):
        ALL = "todos", "Toda la comunidad"
        STUDENTS = "estudiantes", "Estudiantes"
        STAFF = "personal", "Personal"

    title = models.CharField("título", max_length=140)
    summary = models.CharField("resumen", max_length=240)
    body = models.TextField("contenido", max_length=4000)
    source_url = models.URLField("enlace de la fuente", blank=True)
    category = models.CharField(max_length=20, choices=Category.choices, default=Category.GENERAL)
    priority = models.CharField(max_length=10, choices=Priority.choices, default=Priority.NORMAL)
    tags = models.JSONField(default=list, blank=True)
    institution = models.ForeignKey("accounts.Institution", on_delete=models.PROTECT)
    campus = models.ForeignKey("accounts.Campus", on_delete=models.PROTECT, null=True, blank=True,
                               help_text="Vacío = aviso global de la institución")
    area = models.ForeignKey("accounts.Area", on_delete=models.PROTECT, null=True, blank=True)
    audience = models.CharField("audiencia", max_length=20, choices=Audience.choices, default=Audience.STUDENTS)
    program = models.CharField("programa (opcional)", max_length=120, blank=True)
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    approver = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="+")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    publish_at = models.DateTimeField("publicar desde", default=timezone.now)
    expires_at = models.DateTimeField("vigente hasta", null=True, blank=True)
    published_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-publish_at"]
        indexes = [models.Index(fields=["campus", "status", "publish_at"])]

    def __str__(self):
        return self.title

    @property
    def is_opportunity(self):
        return self.category in self.OPPORTUNITY_CATEGORIES

    @property
    def lifecycle(self):
        now = timezone.now()
        if self.status != self.Status.PUBLISHED:
            return self.status
        if self.expires_at and self.expires_at <= now:
            return "expirado"
        if self.publish_at > now:
            return "programado"
        return "vigente"

    @classmethod
    def visible_q(cls, user, now=None):
        """Condición de visibilidad para un usuario (estado, vigencia, campus y audiencia)."""
        from apps.accounts.access import is_staff_member, is_student

        now = now or timezone.now()
        cond = Q(status=cls.Status.PUBLISHED, publish_at__lte=now) & (Q(expires_at__isnull=True) | Q(expires_at__gt=now))
        campus_cond = Q(campus__isnull=True)
        if user.campus_id:
            campus_cond |= Q(campus_id=user.campus_id)
        audiences = [cls.Audience.ALL]
        if is_student(user):
            audiences.append(cls.Audience.STUDENTS)
        if is_staff_member(user):
            audiences.append(cls.Audience.STAFF)
        program_cond = Q(program="")
        profile = getattr(user, "student_profile", None) if hasattr(user, "student_profile") else None
        if profile is not None and profile.program:
            program_cond |= Q(program__iexact=profile.program)
        return cond & campus_cond & Q(audience__in=audiences) & program_cond


class AlertRead(models.Model):
    alert = models.ForeignKey(Alert, on_delete=models.CASCADE, related_name="reads")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    read_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["alert", "user"], name="uniq_alert_read")]


class Notification(models.Model):
    recipient = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications")
    event_type = models.CharField(max_length=40)
    title = models.CharField(max_length=140)
    body = models.CharField(max_length=300, blank=True)
    target_url = models.CharField(max_length=200, blank=True)  # ruta interna; se verifica permiso al abrir
    dedupe_key = models.CharField(max_length=120, unique=True)
    read_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["recipient", "read_at"])]

    @property
    def is_read(self):
        return self.read_at is not None
