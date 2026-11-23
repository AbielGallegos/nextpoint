"""Motor determinista y explicable de SmartMatch (sin IA externa).

Puntaje (pesos configurables, total 100):
  categoría 40 · etiquetas 25 · campus 15 · disponibilidad 15 · vigencia/actualización 5

Solo considera elementos publicados y visibles para el usuario; excluye elementos deshabilitados,
vencidos o sin ejemplares en servicio. No usa desempeño académico, salud, discapacidad, origen
étnico ni información socioeconómica: las únicas entradas son la necesidad declarada, los filtros
y el campus de la cuenta.

Desempate documentado: disponibilidad (desc) → fecha de actualización (desc) → nombre → id.
"""
from dataclasses import dataclass, field
from datetime import timedelta

from django.db.models import Q
from django.urls import reverse
from django.utils import timezone

from apps.catalog.models import Resource, ResourceUnit, normalize_tags

from .models import CATEGORY_LABELS, MatchRule

DEFAULT_WEIGHTS = {"category": 40, "tags": 25, "campus": 15, "availability": 15, "freshness": 5}


@dataclass
class Candidate:
    kind: str  # materiales | asesorias | cursos | tramites | oportunidades
    obj_id: int
    title: str
    summary: str
    tags: list
    campus_id: int | None
    campus_name: str
    available: bool
    availability_label: str
    updated_at: object
    url: str
    action_label: str
    modality: str = ""
    level: str = ""
    meta: dict = field(default_factory=dict)


@dataclass
class Result:
    candidate: Candidate
    score: int
    breakdown: dict
    matched_tags: list
    reasons: list
    weights: dict = field(default_factory=dict)

    LABELS = (("category", "Categoría"), ("tags", "Etiquetas"), ("campus", "Campus"), ("availability", "Disponibilidad"),
              ("freshness", "Vigencia"))

    @property
    def rows(self):
        out = []
        for key, label in self.LABELS:
            mx = self.weights.get(key, 0)
            got = self.breakdown.get(key, 0)
            out.append({"key": key, "label": label, "got": got, "max": mx, "pct": round(got * 100 / mx) if mx else 0})
        return out

    @property
    def kind_label(self):
        return CATEGORY_LABELS.get(self.candidate.kind, self.candidate.kind)

    @property
    def key(self):
        return f"{self.candidate.kind}:{self.candidate.obj_id}"

    @property
    def explanation(self):
        return "Recomendado porque " + _join(self.reasons) + "."


def _join(parts):
    parts = [p for p in parts if p]
    if not parts:
        return "es el elemento más cercano disponible"
    if len(parts) == 1:
        return parts[0]
    return ", ".join(parts[:-1]) + " y " + parts[-1]


def active_rule(campus):
    return MatchRule.objects.filter(campus=campus, status=MatchRule.Status.ACTIVE).order_by("-version").first()


# --------------------------------------------------------------------------- candidatos
def gather_candidates(user, *, campus_only=True, as_student=False):
    """Elementos publicados que el usuario puede ver (reutiliza las reglas de visibilidad de cada módulo)."""
    from apps.cases.models import ServiceCategory
    from apps.communications.models import Alert
    from apps.learning.models import Course

    today = timezone.localdate()
    out = []
    campus_filter = Q(campus_id=user.campus_id) if campus_only else Q(campus__institution_id=user.campus.institution_id)

    resources = (
        Resource.objects.filter(campus_filter, status=Resource.Status.PUBLISHED, kind=Resource.Kind.UNIT)
        .select_related("campus", "category", "location").prefetch_related("units")
    )
    for r in resources:
        av = r.availability(today)
        if av["operable"] == 0:
            continue  # stock imposible de solicitar: no se recomienda
        out.append(Candidate(
            "materiales", r.pk, r.name, r.description[:180], list(r.tags) + [r.category.slug], r.campus_id, r.campus.name,
            av["available"] > 0, f"{av['available']} de {av['operable']} disponible(s)" if av["available"] else "Sin disponibilidad inmediata",
            r.updated_at, reverse("catalog:detail", args=[r.pk]), "Ver y solicitar", modality="Presencial",
            meta={"category": r.category.name, "location": r.location.public_hint if r.location else ""},
        ))

    services = ServiceCategory.objects.filter(campus_filter, active=True, kind__in=["asesoria", "tramite", "consulta"]).select_related("campus", "area")
    for s in services:
        kind = "asesorias" if s.kind == "asesoria" else "tramites"
        out.append(Candidate(
            kind, s.pk, s.name, s.description, list(s.tags), s.campus_id, s.campus.name, True, f"Atiende: {s.area.name}",
            s.updated_at, reverse("cases:new") + f"?categoria={s.pk}", "Iniciar solicitud", modality=s.get_modality_display(),
        ))

    for c in Course.objects.filter(campus_filter, status=Course.Status.PUBLISHED).select_related("campus"):
        full = c.capacity is not None and c.enrollments.exclude(status="cancelada").count() >= c.capacity
        out.append(Candidate(
            "cursos", c.pk, c.title, c.summary, list(c.tags), c.campus_id, c.campus.name, not full,
            "Cupo lleno" if full else "Inscripción abierta · gratuita", c.published_at or c.updated_at,
            reverse("learning:detail", args=[c.pk]), "Ver curso", modality=c.get_mode_display(), level=c.get_level_display(),
        ))

    alerts = Alert.objects.filter(Alert.visible_q(user), category__in=Alert.OPPORTUNITY_CATEGORIES).select_related("campus")
    if as_student or not campus_only:
        alerts = Alert.objects.filter(
            Q(status=Alert.Status.PUBLISHED, publish_at__lte=timezone.now()) & (Q(expires_at__isnull=True) | Q(expires_at__gt=timezone.now())),
            category__in=Alert.OPPORTUNITY_CATEGORIES, institution_id=user.campus.institution_id,
            audience__in=["todos", "estudiantes"],
        ).select_related("campus")
        if campus_only:
            alerts = alerts.filter(Q(campus__isnull=True) | Q(campus_id=user.campus_id))
    for a in alerts:
        out.append(Candidate(
            "oportunidades", a.pk, a.title, a.summary, list(a.tags) + [a.category], a.campus_id, a.campus.name if a.campus else "Toda la institución",
            True, f"Vigente hasta {timezone.localtime(a.expires_at):%d/%m/%Y}" if a.expires_at else "Vigente",
            a.published_at or a.updated_at, reverse("communications:alert_detail", args=[a.pk]), "Ver convocatoria",
        ))
    return out


# --------------------------------------------------------------------------- puntuación
def score_candidate(c: Candidate, *, category, tags, user_campus_id, weights, now=None):
    now = now or timezone.now()
    tags = normalize_tags(tags)
    breakdown = {}
    reasons = []

    breakdown["category"] = weights["category"] if (category and c.kind == category) else 0
    if breakdown["category"]:
        reasons.append(f"pertenece a la categoría {CATEGORY_LABELS[category].lower()}")

    matched = [t for t in tags if t in set(normalize_tags(c.tags))]
    breakdown["tags"] = round(weights["tags"] * len(matched) / len(tags)) if tags else 0
    if matched:
        reasons.append("coincide con tu necesidad de " + _join([f"«{t}»" for t in matched]))

    breakdown["campus"] = weights["campus"] if (c.campus_id is None or c.campus_id == user_campus_id) else 0
    if breakdown["campus"]:
        reasons.append("pertenece a tu campus" if c.campus_id else "está abierto a toda la institución")

    breakdown["availability"] = weights["availability"] if c.available else 0
    if c.available:
        reasons.append("cuenta con disponibilidad")

    age_days = (now - c.updated_at).days if c.updated_at else 9999
    if age_days <= 90:
        breakdown["freshness"] = weights["freshness"]
    elif age_days <= 365:
        breakdown["freshness"] = round(weights["freshness"] / 2)
    else:
        breakdown["freshness"] = 0
    if breakdown["freshness"] == weights["freshness"] and weights["freshness"]:
        reasons.append("su información está actualizada")

    return Result(c, sum(breakdown.values()), breakdown, matched, reasons, dict(weights))


def recommend(user, *, category="", tags=(), campus_only=True, only_available=False, modality="", level="",
              weights=None, min_score=None, limit=10, as_student=False):
    """Devuelve (resultados ordenados, regla usada). Sin coincidencias pertinentes → lista vacía."""
    rule = active_rule(user.campus) if user.campus_id else None
    if weights is None:
        weights = rule.weights if rule else DEFAULT_WEIGHTS
    if min_score is None:
        min_score = rule.min_score if rule else 40
    tags = normalize_tags(tags)
    results = []
    for c in gather_candidates(user, campus_only=campus_only, as_student=as_student):
        if only_available and not c.available:
            continue
        if modality and modality.lower() not in (c.modality or "").lower():
            continue  # sin modalidad declarada no se presume compatible
        if level and c.kind == "cursos" and level.lower() != c.level.lower():
            continue
        r = score_candidate(c, category=category, tags=tags, user_campus_id=user.campus_id, weights=weights)
        relevant = r.breakdown["category"] > 0 or r.matched_tags
        if relevant and r.score >= min_score:
            results.append(r)
    far_past = timezone.now() - timedelta(days=36500)
    results.sort(key=lambda r: (-r.score, -int(r.candidate.available), -(r.candidate.updated_at or far_past).timestamp(),
                                r.candidate.title.lower(), r.candidate.obj_id))
    return results[:limit], rule
