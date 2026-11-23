from django.conf import settings
from django.db import models


class AuditLog(models.Model):
    """Bitácora append-only: no se edita ni se borra desde la aplicación."""

    class Kind(models.TextChoices):
        BUSINESS = "negocio", "Negocio"
        SECURITY = "seguridad", "Seguridad"

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="+")
    actor_label = models.CharField(max_length=160, blank=True)
    kind = models.CharField(max_length=12, choices=Kind.choices, default=Kind.BUSINESS)
    action = models.CharField(max_length=60, db_index=True)
    target_type = models.CharField(max_length=40, blank=True)
    target_id = models.CharField(max_length=40, blank=True)
    target_label = models.CharField(max_length=200, blank=True)
    status_before = models.CharField(max_length=40, blank=True)
    status_after = models.CharField(max_length=40, blank=True)
    detail = models.JSONField(default=dict, blank=True)
    campus = models.ForeignKey("accounts.Campus", on_delete=models.PROTECT, null=True, blank=True)
    area = models.ForeignKey("accounts.Area", on_delete=models.PROTECT, null=True, blank=True)
    trace_id = models.CharField(max_length=32, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["campus", "created_at"]), models.Index(fields=["target_type", "target_id"])]

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValueError("La bitácora de auditoría es de solo inserción")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError("La bitácora de auditoría no se puede borrar")
