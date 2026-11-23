from datetime import datetime

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, transaction
from django.db.models import Count, Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from apps.accounts.access import can_on, has_perm, managed_area_ids, require_perm, scope_for, student_required
from apps.accounts.models import Area, Campus, User
from apps.audit.services import record
from apps.catalog.models import normalize_tags
from apps.core.views_utils import paginate

from .models import Alert, AlertRead, Notification
from .services import notify


def _visible_alerts(user):
    return Alert.objects.filter(Alert.visible_q(user)).select_related("campus", "area", "author")


# --------------------------------------------------------------------------- lectores
@login_required
def alerts(request):
    user = request.user
    qs = _visible_alerts(user)
    tab = request.GET.get("vista", "todos")
    read_ids = set(AlertRead.objects.filter(user=user).values_list("alert_id", flat=True))
    if tab == "oportunidades":
        qs = qs.filter(category__in=Alert.OPPORTUNITY_CATEGORIES)
    elif tab == "no_leidos":
        qs = qs.exclude(pk__in=read_ids)
    cat = request.GET.get("categoria", "")
    if cat in Alert.Category.values:
        qs = qs.filter(category=cat)
    items = list(qs.order_by("-publish_at"))
    for a in items:
        a.is_read = a.pk in read_ids
    base = _visible_alerts(user)
    counts = {"todos": base.count(), "no_leidos": base.exclude(pk__in=read_ids).count(),
              "oportunidades": base.filter(category__in=Alert.OPPORTUNITY_CATEGORIES).count()}
    return render(request, "communications/alerts.html", {"items": items, "tab": tab, "counts": counts, "cat": cat,
                                                          "categories": Alert.Category.choices, "base": _base(request)})


def _base(request):
    return "layouts/portal.html" if has_perm(request.user, "portal.student") else "layouts/panel.html"


@login_required
def alert_detail(request, pk):
    alert = get_object_or_404(_visible_alerts(request.user), pk=pk)  # borrador/vencido/otra audiencia → 404
    is_read = AlertRead.objects.filter(alert=alert, user=request.user).exists()
    return render(request, "communications/alert_detail.html", {"a": alert, "is_read": is_read, "base": _base(request)})


@require_POST
@login_required
def alert_read(request, pk):
    alert = get_object_or_404(_visible_alerts(request.user), pk=pk)
    try:
        with transaction.atomic():
            AlertRead.objects.create(alert=alert, user=request.user)
    except IntegrityError:
        pass
    messages.success(request, "Aviso marcado como leído.")
    return redirect("communications:alert_detail", pk=pk)


@login_required
def notifications(request):
    qs = Notification.objects.filter(recipient=request.user)
    tab = request.GET.get("vista", "todas")
    if tab == "no_leidas":
        qs = qs.filter(read_at__isnull=True)
    return render(request, "communications/notifications.html", {"page": paginate(request, qs), "tab": tab, "base": _base(request),
                                                                 "unread": Notification.objects.filter(recipient=request.user, read_at__isnull=True).count()})


@require_POST
@login_required
def notification_open(request, pk):
    n = get_object_or_404(Notification, pk=pk, recipient=request.user)  # ajena → 404
    if n.read_at is None:
        n.read_at = timezone.now()
        n.save(update_fields=["read_at"])
    # El destino vuelve a verificar permisos al abrirse; solo se aceptan rutas internas.
    if n.target_url and url_has_allowed_host_and_scheme(n.target_url, allowed_hosts={request.get_host()}) and n.target_url.startswith("/"):
        return redirect(n.target_url)
    return redirect("communications:notifications")


@require_POST
@login_required
def notifications_read_all(request):
    n = Notification.objects.filter(recipient=request.user, read_at__isnull=True).update(read_at=timezone.now())
    messages.success(request, f"{n} notificación(es) marcadas como leídas.")
    return redirect("communications:notifications")


# --------------------------------------------------------------------------- editores
def _scope_options(user):
    """Ámbitos en los que la persona puede publicar: (valor, etiqueta)."""
    opts = []
    for area in Area.objects.filter(pk__in=managed_area_ids(user, "alerts.publish_area")).select_related("campus"):
        opts.append((f"area:{area.pk}", f"Área: {area.name} ({area.campus.name})"))
    for campus in Campus.objects.filter(scope_for(user, "alerts.publish_campus").q(area_field=None, campus_field="id")):
        opts.append((f"campus:{campus.pk}", f"Todo el campus: {campus.name}"))
    if has_perm(user, "alerts.publish_global"):
        opts.append(("global", "Toda la institución (global)"))
    return opts


def _can_edit(user, alert):
    if alert.campus_id is None:
        return has_perm(user, "alerts.publish_global")
    if alert.area_id:
        return can_on(user, "alerts.publish_area", area_id=alert.area_id, campus_id=alert.campus_id) or can_on(user, "alerts.publish_campus", campus_id=alert.campus_id)
    return can_on(user, "alerts.publish_campus", campus_id=alert.campus_id)


def _editable_q(user):
    cond = scope_for(user, "alerts.publish_area").q() | scope_for(user, "alerts.publish_campus").q()
    if has_perm(user, "alerts.publish_global"):
        cond |= Q(campus__isnull=True)
    return cond


@require_perm("alerts.publish_area", "alerts.publish_campus", any_of=True)
def manage_alerts(request):
    qs = Alert.objects.filter(_editable_q(request.user)).select_related("campus", "area", "author").annotate(nreads=Count("reads"))
    items = list(qs.order_by("-updated_at"))
    tab = request.GET.get("vista", "")
    if tab:
        items = [a for a in items if a.lifecycle == tab]
    return render(request, "communications/manage_alerts.html", {"items": items, "tab": tab})


def _parse_dt(value):
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return "invalid"
    return timezone.make_aware(dt) if timezone.is_naive(dt) else dt


@require_perm("alerts.publish_area", "alerts.publish_campus", any_of=True)
def alert_form(request, pk=None):
    alert = get_object_or_404(Alert.objects.filter(_editable_q(request.user)), pk=pk) if pk else None
    if alert and alert.status != Alert.Status.DRAFT:
        messages.info(request, "Solo se editan borradores. Retira el aviso para crear una versión nueva.")
        return redirect("communications:manage_alerts")
    options = _scope_options(request.user)
    errors, data = {}, request.POST if request.method == "POST" else {}
    if request.method == "POST":
        title = data.get("title", "").strip()
        summary = data.get("summary", "").strip()
        body = data.get("body", "").strip()
        scope = data.get("scope", "")
        source_url = data.get("source_url", "").strip()
        publish_at = _parse_dt(data.get("publish_at")) or timezone.now()
        expires_at = _parse_dt(data.get("expires_at"))
        if len(title) < 5:
            errors["title"] = "El título debe tener al menos 5 caracteres."
        if len(summary) < 10:
            errors["summary"] = "Escribe un resumen (mínimo 10 caracteres)."
        if len(body) < 10:
            errors["body"] = "Escribe el contenido del aviso."
        if scope not in dict(options):
            errors["scope"] = "Selecciona un ámbito autorizado."
        if source_url and not source_url.startswith("https://"):
            errors["source_url"] = "El enlace de la fuente debe iniciar con https://."
        if publish_at == "invalid":
            errors["publish_at"] = "Fecha no válida."
        if expires_at == "invalid":
            errors["expires_at"] = "Fecha no válida."
        elif expires_at and publish_at != "invalid" and expires_at <= publish_at:
            errors["expires_at"] = "La vigencia debe terminar después de la publicación."
        if data.get("priority") == "critica" and data.get("verified") != "1":
            errors["priority"] = "Una alerta crítica requiere confirmar que la información está verificada."
        if data.get("category") not in Alert.Category.values:
            errors["category"] = "Selecciona una categoría."
        if not errors:
            kind, _, ident = scope.partition(":")
            area = Area.objects.select_related("campus").get(pk=ident) if kind == "area" else None
            campus = area.campus if area else (Campus.objects.get(pk=ident) if kind == "campus" else None)
            institution = (campus or request.user.campus).institution
            with transaction.atomic():
                obj = alert or Alert(author=request.user, institution=institution)
                obj.title, obj.summary, obj.body, obj.source_url = title[:140], summary[:240], body[:4000], source_url
                obj.category, obj.priority = data.get("category"), data.get("priority", "normal") if data.get("priority") in Alert.Priority.values else "normal"
                obj.campus, obj.area = campus, area
                obj.audience = data.get("audience") if data.get("audience") in Alert.Audience.values else "estudiantes"
                obj.program = data.get("program", "").strip()[:120]
                obj.publish_at, obj.expires_at = publish_at, expires_at
                obj.tags = normalize_tags(data.get("tags", ""))
                obj.save()
                record(request.user, "alert.updated" if alert else "alert.created", obj, after=obj.status, campus=campus, area=area)
            messages.success(request, "Borrador guardado. No es visible para nadie hasta que lo publiques.")
            return redirect("communications:manage_alerts")
        messages.error(request, "Revisa los campos marcados.")
    initial = {}
    if alert:
        initial = {"title": alert.title, "summary": alert.summary, "body": alert.body, "source_url": alert.source_url, "category": alert.category,
                   "priority": alert.priority, "audience": alert.audience, "program": alert.program, "tags": ", ".join(alert.tags),
                   "scope": f"area:{alert.area_id}" if alert.area_id else (f"campus:{alert.campus_id}" if alert.campus_id else "global"),
                   "publish_at": timezone.localtime(alert.publish_at).strftime("%Y-%m-%dT%H:%M"),
                   "expires_at": timezone.localtime(alert.expires_at).strftime("%Y-%m-%dT%H:%M") if alert.expires_at else ""}
    return render(request, "communications/alert_form.html", {
        "alert": alert, "errors": errors, "d": data or initial, "options": options, "categories": Alert.Category.choices,
        "priorities": Alert.Priority.choices, "audiences": Alert.Audience.choices,
        "now_local": timezone.localtime().strftime("%Y-%m-%dT%H:%M"),
    }, status=400 if errors else 200)


@require_POST
@require_perm("alerts.publish_area", "alerts.publish_campus", any_of=True)
def alert_publish(request, pk):
    with transaction.atomic():
        alert = get_object_or_404(Alert.objects.select_for_update(of=("self",)).filter(_editable_q(request.user)), pk=pk)
        if not _can_edit(request.user, alert):
            raise PermissionDenied
        if alert.status != Alert.Status.DRAFT:
            messages.error(request, "Solo se publican borradores.")
            return redirect("communications:manage_alerts")
        if alert.expires_at and alert.expires_at <= timezone.now():
            messages.error(request, "La vigencia ya terminó: ajusta la fecha antes de publicar.")
            return redirect("communications:alert_edit", pk=pk)
        alert.status, alert.approver, alert.published_at = Alert.Status.PUBLISHED, request.user, timezone.now()
        alert.save(update_fields=["status", "approver", "published_at", "updated_at"])
        record(request.user, "alert.published", alert, before="borrador", after="publicado")
        if alert.priority in ("alta", "critica") or alert.is_opportunity:
            audience = User.objects.filter(status="activo")
            audience = audience.filter(campus=alert.campus) if alert.campus_id else audience.filter(campus__institution=alert.institution)
            if alert.audience == "estudiantes":
                audience = audience.filter(user_roles__role__code="estudiante")
            if alert.is_opportunity:
                audience = audience.filter(notify_opportunities=True)
            recipients = [u for u in audience.distinct() if Alert.objects.filter(Alert.visible_q(u), pk=alert.pk).exists()]
            for u in recipients:
                notify(u, "alert", f"Nuevo aviso: {alert.title}", body=alert.summary[:200], url=f"/app/avisos/{alert.pk}/", dedupe_key=f"alert:{alert.pk}:{u.pk}")
    messages.success(request, "Aviso publicado para su audiencia." + (" Se verá a partir de la fecha programada." if alert.publish_at > timezone.now() else ""))
    return redirect("communications:manage_alerts")


@require_POST
@require_perm("alerts.publish_area", "alerts.publish_campus", any_of=True)
def alert_withdraw(request, pk):
    alert = get_object_or_404(Alert.objects.filter(_editable_q(request.user)), pk=pk)
    if not _can_edit(request.user, alert) or alert.status != Alert.Status.PUBLISHED:
        raise PermissionDenied
    alert.status = Alert.Status.WITHDRAWN
    alert.save(update_fields=["status", "updated_at"])
    record(request.user, "alert.withdrawn", alert, before="publicado", after="retirado")
    messages.success(request, "Aviso retirado: ya no aparece a la audiencia; su registro se conserva.")
    return redirect("communications:manage_alerts")
