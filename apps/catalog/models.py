"""Catálogo de recursos, ejemplares físicos, ubicaciones y movimientos de inventario."""
from django.conf import settings
from django.db import models
from django.utils import timezone


def normalize_tags(raw):
    if isinstance(raw, (list, tuple)):
        items = raw
    else:
        items = (raw or "").replace(";", ",").split(",")
    seen = []
    for t in items:
        t = t.strip().lower()
        if t and t not in seen and len(t) <= 30:
            seen.append(t)
    return seen[:12]


class ResourceCategory(models.Model):
    campus = models.ForeignKey("accounts.Campus", on_delete=models.PROTECT, related_name="resource_categories")
    name = models.CharField("nombre", max_length=80)
    slug = models.SlugField(max_length=80)
    parent = models.ForeignKey("self", on_delete=models.PROTECT, null=True, blank=True, related_name="children")
    icon = models.CharField(max_length=30, default="package")
    active = models.BooleanField(default=True)

    class Meta:
        verbose_name = "categoría de recurso"
        verbose_name_plural = "categorías de recurso"
        ordering = ["name"]
        constraints = [models.UniqueConstraint(fields=["campus", "slug"], name="uniq_category_slug")]

    def __str__(self):
        return self.name


class Location(models.Model):
    campus = models.ForeignKey("accounts.Campus", on_delete=models.PROTECT, related_name="locations")
    name = models.CharField("nombre", max_length=120)
    public_hint = models.CharField("indicación pública", max_length=160, blank=True)
    access_rules = models.CharField("reglas de acceso (solo gestores)", max_length=200, blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Resource(models.Model):
    class Kind(models.TextChoices):
        UNIT = "unitario", "Unitario (ejemplares)"
        SERVICE = "servicio", "Servicio / espacio"

    class Status(models.TextChoices):
        DRAFT = "borrador", "Borrador"
        PUBLISHED = "publicado", "Publicado"
        OUT_OF_SERVICE = "fuera_servicio", "Fuera de servicio"
        ARCHIVED = "archivado", "Archivado"

    campus = models.ForeignKey("accounts.Campus", on_delete=models.PROTECT, related_name="resources")
    area = models.ForeignKey("accounts.Area", on_delete=models.PROTECT, related_name="resources")
    category = models.ForeignKey(ResourceCategory, on_delete=models.PROTECT, related_name="resources")
    code = models.CharField("código público", max_length=30)
    name = models.CharField("nombre", max_length=140)
    description = models.TextField("descripción", max_length=2000)
    requirements = models.CharField("requisitos", max_length=300, blank=True)
    loan_policy = models.CharField("política de préstamo", max_length=300, blank=True)
    kind = models.CharField(max_length=20, choices=Kind.choices, default=Kind.UNIT)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    tags = models.JSONField(default=list, blank=True)
    max_loan_days = models.PositiveSmallIntegerField("días máximos de préstamo", null=True, blank=True,
                                                     help_text="Vacío = política del campus")
    location = models.ForeignKey(Location, on_delete=models.SET_NULL, null=True, blank=True)
    lock_version = models.PositiveIntegerField(default=0)  # se toca al aprobar para serializar transacciones
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "recurso"
        ordering = ["name"]
        constraints = [models.UniqueConstraint(fields=["campus", "code"], name="uniq_resource_code")]
        indexes = [models.Index(fields=["campus", "status"]), models.Index(fields=["area", "status"])]

    def __str__(self):
        return self.name

    @property
    def is_requestable(self):
        return self.status == self.Status.PUBLISHED and self.kind == self.Kind.UNIT

    def availability(self, on_date=None):
        """Disponibilidad calculada en servidor a partir de ejemplares y reservas vigentes."""
        from apps.loans.services import unit_is_free

        on_date = on_date or timezone.localdate()
        units = list(self.units.all())
        operable = [u for u in units if u.state in ResourceUnit.OPERABLE_STATES]
        free_now = [u for u in operable if u.state == ResourceUnit.State.AVAILABLE and unit_is_free(u, on_date, on_date)]
        return {
            "total": len(units),
            "operable": len(operable),
            "available": len(free_now),
            "label": "Disponible" if free_now else ("Ocupado" if operable else "Sin existencias"),
            "tone": "ok" if free_now else ("warn" if operable else "off"),
        }


class ResourceUnit(models.Model):
    class State(models.TextChoices):
        AVAILABLE = "disponible", "Disponible"
        ON_LOAN = "prestado", "Prestado (ocupado)"
        REVIEW = "revision", "En revisión"
        MAINTENANCE = "mantenimiento", "En mantenimiento"
        RETIRED = "baja", "Dado de baja"

    class Condition(models.TextChoices):
        GOOD = "bueno", "Bueno"
        FAIR = "regular", "Regular"
        DAMAGED = "danado", "Dañado"

    OPERABLE_STATES = ("disponible", "prestado")

    resource = models.ForeignKey(Resource, on_delete=models.PROTECT, related_name="units")
    serial = models.CharField("código de ejemplar", max_length=40, unique=True)
    state = models.CharField(max_length=20, choices=State.choices, default=State.AVAILABLE)
    condition = models.CharField(max_length=20, choices=Condition.choices, default=Condition.GOOD)
    location = models.ForeignKey(Location, on_delete=models.SET_NULL, null=True, blank=True)
    notes = models.CharField(max_length=200, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "ejemplar"
        verbose_name_plural = "ejemplares"
        ordering = ["serial"]
        indexes = [models.Index(fields=["resource", "state"])]

    def __str__(self):
        return self.serial


class InventoryMovement(models.Model):
    """Movimientos append-only de cada ejemplar."""

    class Kind(models.TextChoices):
        REGISTER = "alta", "Alta de ejemplar"
        RESERVE = "apartado", "Apartado por aprobación"
        RELEASE = "liberacion", "Liberación de apartado"
        DELIVER = "entrega", "Entrega en préstamo"
        RETURN = "devolucion", "Devolución"
        STATE = "estado", "Cambio de estado"
        EDIT = "edicion", "Edición"

    unit = models.ForeignKey(ResourceUnit, on_delete=models.PROTECT, related_name="movements")
    kind = models.CharField(max_length=20, choices=Kind.choices)
    state_before = models.CharField(max_length=20, blank=True)
    state_after = models.CharField(max_length=20, blank=True)
    note = models.CharField(max_length=200, blank=True)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, related_name="+")
    loan_request = models.ForeignKey("loans.LoanRequest", on_delete=models.PROTECT, null=True, blank=True, related_name="movements")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValueError("Los movimientos de inventario son de solo inserción")
        super().save(*args, **kwargs)
