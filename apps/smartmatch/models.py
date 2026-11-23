"""SmartMatch: pesos configurables y versionados, catálogo de necesidades y registro mínimo de consultas."""
from django.conf import settings
from django.db import models

CATEGORIES = [
    ("materiales", "Materiales"),
    ("asesorias", "Asesorías"),
    ("cursos", "Cursos"),
    ("tramites", "Trámites informativos"),
    ("oportunidades", "Oportunidades académicas"),
]
CATEGORY_LABELS = dict(CATEGORIES)
CATEGORY_ICONS = {"materiales": "package", "asesorias": "hand-helping", "cursos": "graduation-cap",
                  "tramites": "file-text", "oportunidades": "trophy"}


class MatchRule(models.Model):
    """Versión de pesos del motor. Solo una versión activa por campus; las demás son borradores o históricas."""

    class Status(models.TextChoices):
        DRAFT = "borrador", "Borrador"
        ACTIVE = "activa", "Activa"
        RETIRED = "retirada", "Retirada"

    campus = models.ForeignKey("accounts.Campus", on_delete=models.CASCADE, related_name="match_rules")
    version = models.PositiveIntegerField()
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT)
    w_category = models.PositiveSmallIntegerField("categoría", default=40)
    w_tags = models.PositiveSmallIntegerField("etiquetas", default=25)
    w_campus = models.PositiveSmallIntegerField("campus", default=15)
    w_availability = models.PositiveSmallIntegerField("disponibilidad", default=15)
    w_freshness = models.PositiveSmallIntegerField("vigencia y actualización", default=5)
    min_score = models.PositiveSmallIntegerField("puntaje mínimo para mostrar", default=40)
    note = models.CharField(max_length=200, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    activated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-version"]
        constraints = [models.UniqueConstraint(fields=["campus", "version"], name="uniq_rule_version")]

    @property
    def weights(self):
        return {"category": self.w_category, "tags": self.w_tags, "campus": self.w_campus,
                "availability": self.w_availability, "freshness": self.w_freshness}

    def validation_errors(self):
        errors = []
        total = sum(self.weights.values())
        if total != 100:
            errors.append(f"Los pesos deben sumar 100 (suman {total}).")
        if any(v > 100 for v in self.weights.values()):
            errors.append("Ningún peso puede superar 100.")
        if self.w_category == 0 and self.w_tags == 0:
            errors.append("Categoría y etiquetas no pueden ser ambas 0: el motor no tendría criterio de pertinencia.")
        if not 0 <= self.min_score <= 90:
            errors.append("El puntaje mínimo debe estar entre 0 y 90.")
        return errors


class Need(models.Model):
    """Necesidad que el estudiante selecciona ("Material de redes", "Asesoría de programación"...)."""

    campus = models.ForeignKey("accounts.Campus", on_delete=models.CASCADE, related_name="needs")
    code = models.SlugField(max_length=60)
    label = models.CharField(max_length=100)
    category = models.CharField(max_length=20, choices=CATEGORIES)
    tags = models.JSONField(default=list)
    enabled = models.BooleanField(default=True)
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["order", "label"]
        constraints = [models.UniqueConstraint(fields=["campus", "code"], name="uniq_need_code")]

    def __str__(self):
        return self.label


class MatchQuery(models.Model):
    """Registro agregable y mínimo: no guarda texto libre ni datos personales sensibles."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    campus = models.ForeignKey("accounts.Campus", on_delete=models.SET_NULL, null=True)
    need_code = models.CharField(max_length=60, blank=True)
    category = models.CharField(max_length=20, blank=True)
    results_count = models.PositiveSmallIntegerField(default=0)
    rule_version = models.PositiveIntegerField(null=True)
    created_at = models.DateTimeField(auto_now_add=True)
