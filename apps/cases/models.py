"""Solicitudes de servicio e incidencias institucionales con historial público/interno."""
import uuid

from django.conf import settings
from django.db import models


class ServiceCategory(models.Model):
    class Kind(models.TextChoices):
        INCIDENT = "incidencia", "Incidencia"
        INQUIRY = "consulta", "Consulta de servicio"
        PROCEDURE = "tramite", "Trámite informativo"
        ADVISING = "asesoria", "Asesoría"
        RESOURCE_REPORT = "reporte_recurso", "Reporte de recurso"

    campus = models.ForeignKey("accounts.Campus", on_delete=models.PROTECT, related_name="service_categories")
    area = models.ForeignKey("accounts.Area", on_delete=models.PROTECT, related_name="service_categories")
    name = models.CharField("nombre", max_length=120)
    kind = models.CharField(max_length=20, choices=Kind.choices)
    description = models.CharField("descripción", max_length=400)
    tags = models.JSONField(default=list, blank=True)
    modality = models.CharField(max_length=20, default="presencial",
                                choices=[("presencial", "Presencial"), ("en_linea", "En línea"), ("mixta", "Mixta")])
    active = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "categoría de servicio"
        ordering = ["name"]

    def __str__(self):
        return self.name


class ServiceRequest(models.Model):
    class Status(models.TextChoices):
        NEW = "nuevo", "Nuevo"
        CLASSIFIED = "clasificado", "Clasificado"
        ASSIGNED = "asignado", "Asignado"
        ACKNOWLEDGED = "acusado", "Recibido (acuse)"
        IN_PROGRESS = "en_proceso", "En proceso"
        NEEDS_INFO = "requiere_info", "Requiere información"
        RESOLVED = "resuelto", "Resuelto"
        CLOSED = "cerrado", "Cerrado"
        REJECTED = "rechazado", "Rechazado"
        CANCELLED = "cancelado", "Cancelado"

    OPEN_STATES = ("nuevo", "clasificado", "asignado", "acusado", "en_proceso", "requiere_info", "resuelto")
    FINAL_STATES = ("cerrado", "rechazado", "cancelado")

    class Priority(models.TextChoices):
        LOW = "baja", "Baja"
        NORMAL = "normal", "Normal"
        HIGH = "alta", "Alta"

    folio = models.CharField(max_length=20, unique=True, blank=True)
    creator = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="service_requests")
    institution = models.ForeignKey("accounts.Institution", on_delete=models.PROTECT)
    campus = models.ForeignKey("accounts.Campus", on_delete=models.PROTECT)
    area = models.ForeignKey("accounts.Area", on_delete=models.PROTECT)
    category = models.ForeignKey(ServiceCategory, on_delete=models.PROTECT, related_name="requests")
    subject = models.CharField("asunto", max_length=140)
    description = models.TextField("descripción", max_length=3000)
    priority = models.CharField(max_length=10, choices=Priority.choices, default=Priority.NORMAL)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.NEW)
    assigned_to = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="assigned_cases")
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    resolution = models.TextField("resolución", blank=True, max_length=2000)
    rating = models.PositiveSmallIntegerField(null=True, blank=True)
    rating_comment = models.CharField(max_length=300, blank=True)
    idempotency_key = models.UUIDField(default=uuid.uuid4)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "solicitud de servicio"
        ordering = ["-created_at"]
        constraints = [models.UniqueConstraint(fields=["creator", "idempotency_key"], name="uniq_case_idempotency")]
        indexes = [
            models.Index(fields=["campus", "status", "created_at"]),
            models.Index(fields=["creator", "status"]),
            models.Index(fields=["assigned_to", "status"]),
            models.Index(fields=["area", "status"]),
        ]

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if not self.folio:
            self.folio = f"NP-SOL-{self.pk:05d}"
            super().save(update_fields=["folio"])

    def __str__(self):
        return self.folio

    @property
    def is_open(self):
        return self.status in self.OPEN_STATES

    @property
    def student_status_label(self):
        """Etiqueta para el estudiante: el acuse se presenta como "Recibido", nunca como resuelto."""
        return self.get_status_display()


class RequestEvent(models.Model):
    class Kind(models.TextChoices):
        CREATED = "creado", "Creación"
        STATUS = "estado", "Cambio de estado"
        MESSAGE = "mensaje", "Mensaje"
        NOTE = "nota", "Nota interna"
        ASSIGNMENT = "asignacion", "Asignación"
        RATING = "valoracion", "Valoración"

    class Visibility(models.TextChoices):
        PUBLIC = "publico", "Visible para el estudiante"
        INTERNAL = "interno", "Solo personal"

    request = models.ForeignKey(ServiceRequest, on_delete=models.CASCADE, related_name="events")
    kind = models.CharField(max_length=20, choices=Kind.choices)
    visibility = models.CharField(max_length=10, choices=Visibility.choices, default=Visibility.PUBLIC)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    body = models.TextField(blank=True, max_length=2000)
    status_before = models.CharField(max_length=20, blank=True)
    status_after = models.CharField(max_length=20, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]


class RequestAttachment(models.Model):
    request = models.ForeignKey(ServiceRequest, on_delete=models.CASCADE, related_name="attachments")
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    storage_key = models.CharField(max_length=80, unique=True)  # nombre regenerado, nunca el original
    original_name = models.CharField(max_length=120)
    mime = models.CharField(max_length=40)
    size = models.PositiveIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)
