"""Solicitudes de préstamo, préstamos efectivos y su bitácora de transiciones."""
import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q


class LoanRequest(models.Model):
    class Status(models.TextChoices):
        REQUESTED = "solicitado", "Solicitado"
        IN_REVIEW = "en_revision", "En revisión"
        APPROVED = "aprobado", "Aprobado"
        REJECTED = "rechazado", "Rechazado"
        CANCELLED = "cancelado", "Cancelado"
        DELIVERED = "entregado", "Entregado"
        RETURNED = "devuelto", "Devuelto"
        CLOSED = "cerrado", "Cerrado"

    OPEN_STATES = ("solicitado", "en_revision", "aprobado", "entregado")
    RESERVING_STATES = ("aprobado", "entregado")

    folio = models.CharField(max_length=20, unique=True, blank=True)
    applicant = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="loan_requests")
    resource = models.ForeignKey("catalog.Resource", on_delete=models.PROTECT, related_name="loan_requests")
    campus = models.ForeignKey("accounts.Campus", on_delete=models.PROTECT)
    area = models.ForeignKey("accounts.Area", on_delete=models.PROTECT)
    start_date = models.DateField("fecha de inicio")
    due_date = models.DateField("devolución prevista")
    purpose = models.CharField("finalidad", max_length=300)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.REQUESTED)
    unit = models.ForeignKey("catalog.ResourceUnit", on_delete=models.PROTECT, null=True, blank=True, related_name="loan_requests")
    decided_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="+")
    decided_at = models.DateTimeField(null=True, blank=True)
    decision_note = models.CharField("motivo / indicaciones", max_length=300, blank=True)
    idempotency_key = models.UUIDField(default=uuid.uuid4)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "solicitud de préstamo"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["applicant", "idempotency_key"], name="uniq_loan_idempotency"),
            models.CheckConstraint(condition=Q(due_date__gte=models.F("start_date")), name="loan_dates_order"),
        ]
        indexes = [
            models.Index(fields=["campus", "status", "created_at"]),
            models.Index(fields=["applicant", "status"]),
            models.Index(fields=["resource", "status"]),
        ]

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if not self.folio:
            self.folio = f"NP-PRE-{self.pk:05d}"
            super().save(update_fields=["folio"])

    def __str__(self):
        return self.folio

    @property
    def is_open(self):
        return self.status in self.OPEN_STATES


class Loan(models.Model):
    """Préstamo efectivo (existe desde la entrega). Un ejemplar no puede tener dos préstamos activos."""

    request = models.OneToOneField(LoanRequest, on_delete=models.PROTECT, related_name="loan")
    unit = models.ForeignKey("catalog.ResourceUnit", on_delete=models.PROTECT, related_name="loans")
    delivered_at = models.DateTimeField()
    delivered_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    delivery_condition = models.CharField(max_length=20)
    due_date = models.DateField()
    returned_at = models.DateTimeField(null=True, blank=True)
    received_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="+")
    return_condition = models.CharField(max_length=20, blank=True)
    return_note = models.CharField(max_length=300, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["unit"], condition=Q(returned_at__isnull=True), name="one_active_loan_per_unit"),
        ]


class LoanEvent(models.Model):
    request = models.ForeignKey(LoanRequest, on_delete=models.CASCADE, related_name="events")
    status_before = models.CharField(max_length=20, blank=True)
    status_after = models.CharField(max_length=20)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    note = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]
