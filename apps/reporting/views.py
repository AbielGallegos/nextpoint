import csv
from datetime import timedelta

from django.contrib import messages
from django.db.models import Count, Q
from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.utils import timezone

from apps.accounts.access import has_perm, require_perm, role_codes, scope_for, staff_required
from apps.accounts.models import Area
from apps.audit.models import AuditLog
from apps.audit.services import record
from apps.cases.models import ServiceRequest
from apps.cases.services import staff_queryset
from apps.communications.models import Alert
from apps.core.models import get_policy
from apps.core.views_utils import int_or_none, paginate, parse_date
from apps.learning.models import Course
from apps.loans.models import LoanRequest

from . import metrics


@staff_required
def panel_home(request):
    user = request.user
    ctx = {"now": timezone.now(), "roles": role_codes(user)}
    for key in ("cases", "loans", "work_queue", "loan_queue", "inventory", "courses", "users_total", "alerts_draft", "tickets_open"):
        ctx[key] = None
    if has_perm(user, "cases.manage") or has_perm(user, "cases.supervise") or has_perm(user, "cases.attend_assigned"):
        ctx["cases"] = metrics.case_metrics(user, target_days=get_policy("request_ack_target_days", user.campus))
        queue = staff_queryset(user).filter(status__in=["nuevo", "clasificado", "asignado", "acusado", "en_proceso", "requiere_info"])
        ctx["work_queue"] = queue.select_related("category", "area", "assigned_to").order_by("created_at")[:6]
        ctx["mine_assigned"] = queue.filter(assigned_to=user).count()
    if has_perm(user, "loans.manage") or has_perm(user, "loans.supervise"):
        ctx["loans"] = metrics.loan_metrics(user)
        ctx["loan_queue"] = LoanRequest.objects.filter(metrics.loan_scope_q(user), status__in=["solicitado", "en_revision", "aprobado"]).select_related("resource").order_by("created_at")[:5]
        ctx["overdue"] = LoanRequest.objects.filter(metrics.loan_scope_q(user), status="entregado", due_date__lt=timezone.localdate()).select_related("resource")[:5]
        ctx["due_soon"] = LoanRequest.objects.filter(metrics.loan_scope_q(user), status="entregado", due_date__gte=timezone.localdate(),
                                                     due_date__lte=timezone.localdate() + timedelta(days=3)).select_related("resource")[:5]
    if has_perm(user, "catalog.manage") or has_perm(user, "reports.view"):
        ctx["inventory"] = metrics.inventory_metrics(user)
    if has_perm(user, "courses.publish") or has_perm(user, "courses.author"):
        ctx["courses"] = metrics.course_metrics(user)
        ctx["courses_review"] = Course.objects.filter(scope_for(user, "courses.publish").q(), status="en_revision")[:5] if has_perm(user, "courses.publish") else []
        ctx["my_courses"] = Course.objects.filter(author=user)[:5] if has_perm(user, "courses.author") else []
    if has_perm(user, "alerts.publish_area") or has_perm(user, "alerts.publish_campus"):
        cond = scope_for(user, "alerts.publish_area").q() | scope_for(user, "alerts.publish_campus").q()
        ctx["alerts_draft"] = Alert.objects.filter(cond, status="borrador").count()
        ctx["alerts_live"] = sum(1 for a in Alert.objects.filter(cond, status="publicado") if a.lifecycle == "vigente")
    if has_perm(user, "platform.health"):
        from apps.core.models import SupportTicket

        ctx["tickets_open"] = SupportTicket.objects.exclude(status__in=["resuelto", "cerrado"]).count()
    if has_perm(user, "users.manage_technical"):
        from apps.accounts.models import User

        ctx["users_total"] = User.objects.count()
        ctx["users_suspended"] = User.objects.filter(status="suspendido").count()
        ctx["security_events"] = AuditLog.objects.filter(kind="seguridad", created_at__gte=timezone.now() - timedelta(days=7)).count()
    return render(request, "reporting/panel_home.html", ctx)


def _report_filters(request):
    today = timezone.localdate()
    start = parse_date(request.GET.get("desde")) or (today - timedelta(days=30))
    end = parse_date(request.GET.get("hasta")) or today
    if end < start:
        start, end = end, start
    if (end - start).days > 366:
        start = end - timedelta(days=366)
    area_id = int_or_none(request.GET.get("area"))
    return start, end, area_id


def _report_areas(user):
    cond = scope_for(user, "reports.view").q(area_field="id", campus_field="campus_id")
    return Area.objects.filter(cond).select_related("campus")


@require_perm("reports.view")
def reports(request):
    start, end, area_id = _report_filters(request)
    areas = _report_areas(request.user)
    if area_id and not areas.filter(pk=area_id).exists():
        area_id = None  # un área fuera del alcance se ignora (no filtra datos ajenos)
    target = get_policy("request_ack_target_days", request.user.campus)
    cases = metrics.case_metrics(request.user, start, end, area_id, target)
    loans = metrics.loan_metrics(request.user, start, end, area_id)
    lo, hi = metrics.period_bounds(start, end)
    by_area = (staff_queryset(request.user).filter(created_at__gte=lo, created_at__lte=hi)
               .values("area__name").annotate(n=Count("id"), closed=Count("id", filter=Q(status__in=["resuelto", "cerrado"]))).order_by("-n"))
    if area_id:
        by_area = by_area.filter(area_id=area_id)
    by_category = (staff_queryset(request.user).filter(created_at__gte=lo, created_at__lte=hi, **({"area_id": area_id} if area_id else {}))
                   .values("category__name").annotate(n=Count("id")).order_by("-n")[:8])
    max_cat = max([c["n"] for c in by_category], default=0)
    return render(request, "reporting/reports.html", {
        "start": start, "end": end, "area_id": area_id, "areas": areas, "cases": cases, "loans": loans,
        "inventory": metrics.inventory_metrics(request.user, area_id), "courses": metrics.course_metrics(request.user, area_id),
        "by_area": by_area, "by_category": by_category, "max_cat": max_cat, "target": target,
        "can_export": has_perm(request.user, "reports.export"), "tz": timezone.get_current_timezone_name(), "generated": timezone.now(),
    })


@require_perm("reports.export")
def export(request):
    start, end, area_id = _report_filters(request)
    if area_id and not _report_areas(request.user).filter(pk=area_id).exists():
        area_id = None
    kind = request.GET.get("tipo", "solicitudes")
    lo, hi = metrics.period_bounds(start, end)
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="nextpoint_{kind}_{start}_{end}.csv"'
    response.write("﻿")
    writer = csv.writer(response)
    if kind == "prestamos":
        qs = LoanRequest.objects.filter(metrics.loan_scope_q(request.user), created_at__gte=lo, created_at__lte=hi)
        if area_id:
            qs = qs.filter(area_id=area_id)
        writer.writerow(["folio", "recurso", "area", "estado", "inicio", "devolucion_prevista", "creado"])
        for r in qs.select_related("resource", "area"):
            writer.writerow([r.folio, r.resource.name, r.area.name, r.status, r.start_date, r.due_date, timezone.localtime(r.created_at).isoformat()])
    else:
        kind = "solicitudes"
        qs = staff_queryset(request.user).filter(created_at__gte=lo, created_at__lte=hi)
        if area_id:
            qs = qs.filter(area_id=area_id)
        # Exportación minimizada: sin nombres, correos ni descripciones de los casos.
        writer.writerow(["folio", "categoria", "area", "estado", "prioridad", "creado", "acuse", "resuelto", "cerrado"])
        for r in qs.select_related("category", "area"):
            fmt = lambda d: timezone.localtime(d).isoformat() if d else ""  # noqa: E731
            writer.writerow([r.folio, r.category.name, r.area.name, r.status, r.priority, fmt(r.created_at), fmt(r.acknowledged_at), fmt(r.resolved_at), fmt(r.closed_at)])
    record(request.user, "report.exported", detail={"tipo": kind, "desde": str(start), "hasta": str(end), "area": area_id, "filas": qs.count()},
           campus=request.user.campus, label=f"Exportación {kind}")
    return response


@require_perm("audit.view")
def audit(request):
    scope = scope_for(request.user, "audit.view")
    if scope.is_global:
        qs = AuditLog.objects.all()
    else:
        qs = AuditLog.objects.filter(Q(area_id__in=scope.area_ids) | Q(campus_id__in=scope.campus_ids))
        if scope.area_ids and not scope.campus_ids:
            qs = qs.exclude(kind="seguridad")
    action = request.GET.get("accion", "").strip()
    kind = request.GET.get("tipo", "")
    folio = request.GET.get("q", "").strip()
    if action:
        qs = qs.filter(action__startswith=action)
    if kind in ("negocio", "seguridad"):
        qs = qs.filter(kind=kind)
    if folio:
        qs = qs.filter(Q(target_label__icontains=folio) | Q(actor_label__icontains=folio))
    prefixes = ["loan", "case", "resource", "unit", "alert", "course", "account", "smartmatch", "policy", "report", "auth", "access"]
    return render(request, "reporting/audit.html", {"page": paginate(request, qs.select_related("area", "campus")), "f": {"accion": action, "tipo": kind, "q": folio},
                                                    "prefixes": prefixes, "global": scope.is_global})


# --------------------------------------------------------------------------- API mínima (JSON)
def _json_error(code, status, message):
    from apps.core.middleware import current_trace_id

    return JsonResponse({"code": code, "message": message, "trace_id": current_trace_id()}, status=status)


def api_me(request):
    if not request.user.is_authenticated:
        return _json_error("AUTH_REQUIRED", 401, "Necesitas iniciar sesión.")
    u = request.user
    from apps.accounts.access import PERMISSIONS

    return JsonResponse({"id": u.pk, "display_name": u.display_name, "campus": u.campus.name if u.campus else None,
                         "roles": sorted(role_codes(u)), "permissions": sorted(p for p in PERMISSIONS if has_perm(u, p))})


def api_admin_kpis(request):
    if not request.user.is_authenticated:
        return _json_error("AUTH_REQUIRED", 401, "Necesitas iniciar sesión.")
    if not has_perm(request.user, "panel.access"):
        return _json_error("PERMISSION_DENIED", 403, "No tienes permiso para consultar esta información.")
    data = {"generated_at": timezone.now().isoformat()}
    if has_perm(request.user, "cases.manage") or has_perm(request.user, "cases.supervise"):
        c = metrics.case_metrics(request.user)
        data["cases"] = {k: c[k] for k in ("total", "new", "in_attention", "resolved", "ack_rate")}
    if has_perm(request.user, "loans.manage") or has_perm(request.user, "loans.supervise"):
        data["loans"] = metrics.loan_metrics(request.user)
    return JsonResponse(data)
