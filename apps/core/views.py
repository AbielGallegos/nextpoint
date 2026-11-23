from datetime import timedelta

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import connection, transaction
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.accounts.access import has_perm, require_perm, scope_for, student_required
from apps.audit.services import record
from apps.communications.services import notify, notify_many

from .models import POLICY_DEFAULTS, SupportMessage, SupportTicket, SystemPolicy, get_policy
from .views_utils import paginate


# --------------------------------------------------------------------------- sitio público
def landing(request):
    return render(request, "core/landing.html")


def about(request):
    return render(request, "core/about.html")


def help_center(request):
    return render(request, "core/help.html")


@login_required
def home_redirect(request):
    if has_perm(request.user, "portal.student"):
        return redirect("core:student_home")
    if has_perm(request.user, "panel.access"):
        return redirect("reporting:panel_home")
    messages.warning(request, "Tu cuenta no tiene roles asignados todavía. Contacta a la coordinación.")
    return redirect("accounts:profile")


# --------------------------------------------------------------------------- portal del estudiante
@student_required
def student_home(request):
    from apps.cases.models import RequestEvent, ServiceRequest
    from apps.communications.models import Alert, AlertRead
    from apps.learning.models import Enrollment
    from apps.loans.models import LoanEvent, LoanRequest
    from apps.smartmatch.engine import recommend
    from apps.smartmatch.models import MatchQuery, Need

    user = request.user
    today = timezone.localdate()
    open_cases = ServiceRequest.objects.filter(creator=user, status__in=ServiceRequest.OPEN_STATES)
    pending_loans = LoanRequest.objects.filter(applicant=user, status__in=["solicitado", "en_revision", "aprobado"])
    active_loans = LoanRequest.objects.filter(applicant=user, status="entregado").select_related("resource")
    upcoming = list(
        LoanRequest.objects.filter(applicant=user)
        .filter(Q(status="entregado", due_date__lte=today + timedelta(days=7)) | Q(status="aprobado", start_date__lte=today + timedelta(days=7)))
        .select_related("resource").order_by("due_date")[:5]
    )
    enrollments = list(Enrollment.objects.filter(student=user).exclude(status="cancelada").select_related("course"))
    for e in enrollments:
        e.pct = e.progress()
    started = [e for e in enrollments if e.status == "activa"]

    activity = []
    for ev in LoanEvent.objects.filter(request__applicant=user).select_related("request__resource").order_by("-created_at")[:20]:
        activity.append({"when": ev.created_at, "icon": "package", "title": f"{ev.request.folio} · {ev.request.resource.name}",
                         "status": ev.status_after, "url": reverse("loans:my_detail", args=[ev.request_id])})
    for ev in RequestEvent.objects.filter(request__creator=user, visibility="publico").exclude(kind="nota").select_related("request").order_by("-created_at")[:20]:
        activity.append({"when": ev.created_at, "icon": "clipboard-list", "title": f"{ev.request.folio} · {ev.request.subject}",
                         "status": ev.status_after or ("mensaje" if ev.kind == "mensaje" else ev.request.status),
                         "url": reverse("cases:my_detail", args=[ev.request_id])})
    activity.sort(key=lambda a: a["when"], reverse=True)
    seen, unique = set(), []
    for a in activity:  # un renglón por folio con su estado más reciente
        if a["url"] not in seen:
            seen.add(a["url"])
            unique.append(a)
    activity = unique

    read_ids = AlertRead.objects.filter(user=user).values_list("alert_id", flat=True)
    alerts = list(Alert.objects.filter(Alert.visible_q(user)).exclude(pk__in=read_ids).order_by("-priority", "-publish_at")[:3])
    priority_order = {"critica": 0, "alta": 1, "normal": 2}
    alerts.sort(key=lambda a: (priority_order.get(a.priority, 3), -a.publish_at.timestamp()))

    last_query = MatchQuery.objects.filter(user=user).exclude(need_code="").order_by("-created_at").first()
    need = Need.objects.filter(campus=user.campus, code=last_query.need_code, enabled=True).first() if last_query else None
    suggestions = []
    if get_policy("module_smartmatch_enabled", user.campus):
        suggestions, _ = recommend(user, category=need.category if need else "materiales", tags=need.tags if need else [], limit=3)

    return render(request, "core/student_home.html", {
        "open_cases_count": open_cases.count(), "pending_loans_count": pending_loans.count(), "active_loans": active_loans,
        "active_loans_count": active_loans.count(), "upcoming": upcoming, "started": started, "enrollments": enrollments,
        "activity": activity[:6], "alerts": alerts, "suggestions": suggestions, "need": need, "today": today,
        "now": timezone.now(),
    })


# --------------------------------------------------------------------------- soporte técnico
@login_required
def support_mine(request):
    tickets = SupportTicket.objects.filter(owner=request.user)
    if request.method == "POST":
        category = request.POST.get("category", "")
        subject = request.POST.get("subject", "").strip()
        description = request.POST.get("description", "").strip()
        errors = {}
        if category not in dict(SupportTicket.CATEGORIES):
            errors["category"] = "Selecciona una categoría."
        if len(subject) < 5:
            errors["subject"] = "Escribe un asunto (mínimo 5 caracteres)."
        if len(description) < 10:
            errors["description"] = "Describe el problema (mínimo 10 caracteres). No incluyas contraseñas."
        if not errors:
            t = SupportTicket.objects.create(owner=request.user, category=category, subject=subject[:140], description=description[:2000])
            record(request.user, "support.created", t, after="nuevo")
            from apps.accounts.models import User

            notify_many(User.objects.filter(status="activo", user_roles__role__code="soporte").distinct(), "support",
                        f"Nuevo ticket {t.folio}", url=reverse("core:support_detail", args=[t.pk]), dedupe_prefix=f"support:{t.pk}:new")
            messages.success(request, f"Ticket registrado con el folio {t.folio}.")
            return redirect("core:support_detail", pk=t.pk)
        messages.error(request, "Revisa los campos marcados.")
        return render(request, "core/support_mine.html", {"tickets": tickets, "errors": errors, "data": request.POST,
                                                          "categories": SupportTicket.CATEGORIES, "base": _base(request)}, status=400)
    return render(request, "core/support_mine.html", {"tickets": tickets, "categories": SupportTicket.CATEGORIES, "base": _base(request)})


def _base(request):
    return "layouts/portal.html" if has_perm(request.user, "portal.student") else "layouts/panel.html"


@login_required
def support_detail(request, pk):
    is_agent = has_perm(request.user, "support.attend")
    qs = SupportTicket.objects.all() if is_agent else SupportTicket.objects.filter(owner=request.user)
    ticket = get_object_or_404(qs, pk=pk)
    if request.method == "POST":
        action = request.POST.get("action", "")
        body = request.POST.get("body", "").strip()
        with transaction.atomic():
            ticket = SupportTicket.objects.select_for_update(of=("self",)).get(pk=ticket.pk)
            before = ticket.status
            if action == "message" and len(body) >= 2 and ticket.status != "cerrado":
                internal = is_agent and request.POST.get("internal") == "1"
                SupportMessage.objects.create(ticket=ticket, author=request.user, body=body[:2000], internal=internal)
                if is_agent and not internal:
                    if ticket.status in ("nuevo", "asignado"):
                        ticket.status = "atendiendo"
                    notify(ticket.owner, "support", f"{ticket.folio}: respuesta de soporte", url=reverse("core:support_detail", args=[ticket.pk]),
                           dedupe_key=f"support:{ticket.pk}:reply:{timezone.now().timestamp()}")
            elif action == "take" and is_agent and ticket.status == "nuevo":
                ticket.assignee, ticket.status = request.user, "asignado"
            elif action == "resolve" and is_agent and ticket.status in ("asignado", "atendiendo") and len(body) >= 5:
                ticket.status, ticket.result = "resuelto", body[:2000]
                SupportMessage.objects.create(ticket=ticket, author=request.user, body=body[:2000])
                notify(ticket.owner, "support", f"{ticket.folio}: ticket resuelto", url=reverse("core:support_detail", args=[ticket.pk]),
                       dedupe_key=f"support:{ticket.pk}:resolved")
            elif action == "close" and ticket.status == "resuelto" and (is_agent or ticket.owner_id == request.user.pk):
                ticket.status = "cerrado"
            else:
                messages.error(request, "La acción no está disponible para el estado actual o falta información.")
                return redirect("core:support_detail", pk=ticket.pk)
            ticket.save()
            if before != ticket.status:
                record(request.user, f"support.{ticket.status}", ticket, before=before, after=ticket.status)
        messages.success(request, "Ticket actualizado.")
        return redirect("core:support_detail", pk=ticket.pk)
    msgs = ticket.messages.select_related("author")
    if not is_agent:
        msgs = msgs.filter(internal=False)
    return render(request, "core/support_detail.html", {"ticket": ticket, "msgs": msgs, "is_agent": is_agent,
                                                        "base": "layouts/panel.html" if is_agent else _base(request)})


@require_perm("support.attend")
def support_queue(request):
    status = request.GET.get("estado", "")
    qs = SupportTicket.objects.select_related("owner", "assignee")
    if status:
        qs = qs.filter(status=status)
    return render(request, "core/support_queue.html", {"page": paginate(request, qs), "status": status, "statuses": SupportTicket.Status.choices})


# --------------------------------------------------------------------------- técnico y configuración
def health(request):
    """Salud del servicio sin datos sensibles (no expone versiones de dependencias ni configuración)."""
    db_ok = True
    try:
        with connection.cursor() as c:
            c.execute("SELECT 1")
    except Exception:  # noqa: BLE001
        db_ok = False
    return JsonResponse({"status": "ok" if db_ok else "degraded", "database": "ok" if db_ok else "error",
                         "time": timezone.now().isoformat()}, status=200 if db_ok else 503)


@require_perm("platform.health")
def tech(request):
    from django.db.migrations.executor import MigrationExecutor

    from apps.audit.models import AuditLog

    executor = MigrationExecutor(connection)
    pending = executor.migration_plan(executor.loader.graph.leaf_nodes())
    security = AuditLog.objects.filter(kind="seguridad").order_by("-created_at")[:15]
    return render(request, "core/tech.html", {
        "db_vendor": connection.vendor, "pending_migrations": len(pending), "security": security,
        "debug": settings.DEBUG, "secure_cookies": settings.SESSION_COOKIE_SECURE,
    })


@require_perm("platform.config")
def policies(request):
    scope = scope_for(request.user, "platform.config")
    campus = None if scope.is_global else request.user.campus
    if request.method == "POST":
        key = request.POST.get("key", "")
        if key not in POLICY_DEFAULTS or key == "payments_enabled":
            messages.error(request, "Parámetro no editable.")
            return redirect("core:policies")
        default, typ, _desc, lo, hi = POLICY_DEFAULTS[key]
        raw = request.POST.get("value", "")
        try:
            value = (raw in ("1", "true", "on")) if typ is bool else int(raw)
            if typ is int and not (lo <= value <= hi):
                raise ValueError
        except ValueError:
            messages.error(request, f"Valor fuera de rango para {key} ({lo}–{hi}).")
            return redirect("core:policies")
        with transaction.atomic():
            current = get_policy(key, campus)
            last = SystemPolicy.objects.filter(key=key, campus=campus).order_by("-version").first()
            SystemPolicy.objects.filter(key=key, campus=campus, active=True).update(active=False)
            row = SystemPolicy.objects.create(key=key, campus=campus, value=value, version=(last.version + 1 if last else 1), updated_by=request.user)
            record(request.user, "policy.updated", row, before=str(current), after=str(value), label=key, campus=campus)
        messages.success(request, "Parámetro actualizado. Aplica a operaciones nuevas; los préstamos existentes conservan sus condiciones.")
        return redirect("core:policies")
    rows = []
    for key, (default, typ, desc, lo, hi) in POLICY_DEFAULTS.items():
        last = SystemPolicy.objects.filter(key=key, campus=campus, active=True).select_related("updated_by").order_by("-version").first()
        rows.append({"key": key, "desc": desc, "value": get_policy(key, campus), "default": default, "typ": typ.__name__,
                     "lo": lo, "hi": hi, "version": last.version if last else 0, "by": last.updated_by if last else None,
                     "at": last.effective_at if last else None, "locked": key == "payments_enabled"})
    return render(request, "core/policies.html", {"rows": rows, "campus": campus})


# --------------------------------------------------------------------------- errores
def error_403(request, exception=None):
    return render(request, "errors/403.html", status=403)


def error_404(request, exception=None):
    return render(request, "errors/404.html", status=404)


def error_500(request):
    return render(request, "errors/500.html", {"trace_id": getattr(request, "trace_id", "-")}, status=500)
