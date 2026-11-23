"""Indicadores calculados SOLO con registros de la base (consultas de solo lectura).

Las definiciones siguen el §22.1 de la especificación. Si no hay datos, se devuelve None y la
interfaz muestra "Sin datos" en lugar de inventar una cifra.
"""
from datetime import datetime, time, timedelta
from statistics import median

from django.db.models import Q
from django.utils import timezone

from apps.accounts.access import has_perm, scope_for
from apps.cases.models import ServiceRequest
from apps.cases.services import staff_queryset
from apps.catalog.models import Resource, ResourceUnit
from apps.learning.models import Course, Enrollment
from apps.loans.models import LoanRequest


def add_business_days(dt, days):
    """Suma días hábiles (lunes a viernes). El prototipo no tiene calendario de asuetos configurado."""
    current = dt
    added = 0
    while added < days:
        current += timedelta(days=1)
        if current.weekday() < 5:
            added += 1
    return current


def period_bounds(start, end):
    tz = timezone.get_current_timezone()
    return (timezone.make_aware(datetime.combine(start, time.min), tz), timezone.make_aware(datetime.combine(end, time.max), tz))


def loan_scope_q(user):
    return scope_for(user, "loans.manage").q() | scope_for(user, "loans.supervise").q()


def resource_scope_q(user):
    return scope_for(user, "catalog.manage").q() | scope_for(user, "loans.supervise").q() | scope_for(user, "reports.view").q()


def case_metrics(user, start=None, end=None, area_id=None, target_days=2):
    qs = staff_queryset(user)
    if area_id:
        qs = qs.filter(area_id=area_id)
    if start and end:
        lo, hi = period_bounds(start, end)
        qs = qs.filter(created_at__gte=lo, created_at__lte=hi)
    total = qs.count()
    by_status = {s: qs.filter(status=s).count() for s in ServiceRequest.Status.values}
    now = timezone.now()
    eligible = within = 0
    ack_hours, res_hours = [], []
    for created, acked, resolved in qs.values_list("created_at", "acknowledged_at", "resolved_at"):
        deadline = add_business_days(created, target_days)
        if acked is not None or deadline <= now:
            eligible += 1
            if acked is not None and acked <= deadline:
                within += 1
        if acked:
            ack_hours.append((acked - created).total_seconds() / 3600)
        if resolved:
            res_hours.append((resolved - created).total_seconds() / 3600)
    resolved_or_closed = by_status["resuelto"] + by_status["cerrado"]
    return {
        "total": total,
        "by_status": by_status,
        "new": by_status["nuevo"] + by_status["clasificado"] + by_status["asignado"],
        "in_attention": by_status["acusado"] + by_status["en_proceso"] + by_status["requiere_info"],
        "acknowledged": qs.filter(acknowledged_at__isnull=False).count(),
        "resolved": resolved_or_closed,
        "ack_rate": round(within * 100 / eligible, 1) if eligible else None,
        "ack_eligible": eligible,
        "median_ack_h": round(median(ack_hours), 1) if ack_hours else None,
        "median_resolve_h": round(median(res_hours), 1) if res_hours else None,
        "close_rate": round(resolved_or_closed * 100 / total, 1) if total else None,
        "ratings": (ratings := list(qs.filter(rating__isnull=False).values_list("rating", flat=True))),
        "rating_avg": round(sum(ratings) / len(ratings), 1) if ratings else None,
        "rating_positive": sum(1 for r in ratings if r >= 4),
    }


def loan_metrics(user, start=None, end=None, area_id=None):
    qs = LoanRequest.objects.filter(loan_scope_q(user))
    if area_id:
        qs = qs.filter(area_id=area_id)
    period = qs
    if start and end:
        lo, hi = period_bounds(start, end)
        period = qs.filter(created_at__gte=lo, created_at__lte=hi)
    today = timezone.localdate()
    delivered_cohort = period.filter(loan__isnull=False)
    returned = delivered_cohort.filter(loan__returned_at__isnull=False).count()
    return {
        "requests": period.count(),
        "pending": qs.filter(status__in=["solicitado", "en_revision"]).count(),
        "approved_waiting": qs.filter(status="aprobado").count(),
        "active": qs.filter(status="entregado").count(),  # entregados sin devolución
        "overdue": qs.filter(status="entregado", due_date__lt=today).count(),
        "returned": returned,
        "return_rate": round(returned * 100 / delivered_cohort.count(), 1) if delivered_cohort.count() else None,
        "rejected": period.filter(status="rechazado").count(),
    }


def inventory_metrics(user, area_id=None):
    resources = Resource.objects.filter(resource_scope_q(user))
    if area_id:
        resources = resources.filter(area_id=area_id)
    units = ResourceUnit.objects.filter(resource__in=resources)
    return {
        "resources": resources.count(),
        "published": resources.filter(status="publicado").count(),
        "units": units.count(),
        "available": units.filter(state="disponible").count(),
        "on_loan": units.filter(state="prestado").count(),
        "out_of_service": units.filter(state__in=["revision", "mantenimiento"]).count(),
    }


def course_metrics(user, area_id=None):
    scope = scope_for(user, "courses.publish").q() | scope_for(user, "reports.view").q()
    if has_perm(user, "courses.author"):
        scope |= Q(author=user)
    courses = Course.objects.filter(scope)
    if area_id:
        courses = courses.filter(area_id=area_id)
    enroll = Enrollment.objects.filter(course__in=courses).exclude(status="cancelada")
    pcts = [e.progress() for e in enroll.select_related("course")]
    return {
        "published": courses.filter(status="publicado").count(),
        "in_review": courses.filter(status="en_revision").count(),
        "drafts": courses.filter(status="borrador").count(),
        "enrollments": enroll.count(),
        "completed": enroll.filter(status="completada").count(),
        "avg_progress": round(sum(pcts) / len(pcts)) if pcts else None,
    }
