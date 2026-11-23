import uuid
from datetime import timedelta

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.accounts.access import has_perm, require_perm, student_required
from apps.accounts.models import Area, User
from apps.audit.services import record
from apps.core.errors import DomainError
from apps.core.models import get_policy
from apps.core.views_utils import paginate

from . import services
from .models import RequestAttachment, RequestEvent, ServiceCategory, ServiceRequest

STEPS = [("nuevo", "Registrado"), ("acusado", "Recibido"), ("en_proceso", "En proceso"), ("resuelto", "Resuelto"), ("cerrado", "Cerrado")]
STEP_OF = {"nuevo": 0, "clasificado": 0, "asignado": 0, "acusado": 1, "en_proceso": 2, "requiere_info": 2, "resuelto": 3, "cerrado": 4}


def _steps(req):
    idx = STEP_OF.get(req.status)
    out = []
    for i, (_, label) in enumerate(STEPS):
        if idx is None:
            state = ""
        elif i < idx or (req.status == "cerrado" and i == idx):
            state = "done"
        elif i == idx:
            state = "current"
        else:
            state = ""
        out.append({"label": label, "state": state, "n": i + 1})
    if idx is None:
        reached = max((STEP_OF.get(e.status_after, 0) for e in req.events.all() if e.status_after), default=0)
        out = [dict(s, state="done") for s in out[: reached + 1]] + [{"label": req.get_status_display(), "state": "stopped", "n": "×"}]
    return out


# --------------------------------------------------------------------------- estudiante
@student_required
def mine(request):
    base = ServiceRequest.objects.filter(creator=request.user)
    tab = request.GET.get("vista", "abiertas")
    qs = base.filter(status__in=ServiceRequest.OPEN_STATES) if tab == "abiertas" else base.exclude(status__in=ServiceRequest.OPEN_STATES)
    counts = {"abiertas": base.filter(status__in=ServiceRequest.OPEN_STATES).count(), "cerradas": base.exclude(status__in=ServiceRequest.OPEN_STATES).count()}
    return render(request, "cases/mine.html", {"page": paginate(request, qs.select_related("category", "area")), "tab": tab, "counts": counts})


@student_required
def new(request):
    categories = ServiceCategory.objects.filter(campus_id=request.user.campus_id, active=True).select_related("area")
    errors, data = {}, {}
    if request.method == "POST":
        data = request.POST
        try:
            key = uuid.UUID(data.get("idempotency_key", ""))
        except ValueError:
            key = uuid.uuid4()
        try:
            req, created = services.create_request(request.user, data.get("category"), data.get("subject"), data.get("description"),
                                                   data.get("priority", "normal"), key, request.FILES.get("attachment"))
            if created:
                messages.success(request, f"Tu solicitud quedó registrada con el folio {req.folio}. Puedes consultar su estado en cualquier momento.")
            else:
                messages.info(request, f"Esta solicitud ya estaba registrada con el folio {req.folio}.")
            return redirect("cases:my_detail", pk=req.pk)
        except DomainError as e:
            errors = e.fields
            messages.error(request, e.message)
    preselected = data.get("category") or request.GET.get("categoria", "")
    if not data and request.GET.get("asunto"):
        data = {"subject": request.GET.get("asunto", "")[:140]}
    similar = []
    return render(request, "cases/new.html", {"categories": categories, "errors": errors, "data": data, "preselected": str(preselected),
                                              "key": data.get("idempotency_key") or uuid.uuid4(), "similar": similar,
                                              "priorities": ServiceRequest.Priority.choices}, status=400 if errors else 200)


@student_required
def my_detail(request, pk):
    req = get_object_or_404(ServiceRequest.objects.select_related("category", "area", "assigned_to"), pk=pk, creator=request.user)
    events = req.events.filter(visibility=RequestEvent.Visibility.PUBLIC).select_related("actor")  # nunca notas internas
    return render(request, "cases/my_detail.html", {"req": req, "events": events, "steps": _steps(req),
                                                    "attachments": req.attachments.all()})


@require_POST
@student_required
def my_action(request, pk, action):
    get_object_or_404(ServiceRequest, pk=pk, creator=request.user)
    try:
        if action == "message":
            services.student_message(request.user, pk, request.POST.get("body", ""))
            messages.success(request, "Mensaje enviado al área responsable.")
        elif action in services.STUDENT_TRANSITIONS:
            services.student_action(request.user, pk, action, request.POST.get("body", ""))
            messages.success(request, {"cancel": "Solicitud cancelada; el registro se conserva.", "confirm": "Gracias por confirmar. El caso quedó cerrado.",
                                       "reopen": "Solicitaste revisión: el caso vuelve a atención."}[action])
        elif action == "rate":
            services.rate(request.user, pk, request.POST.get("rating"), request.POST.get("comment", ""))
            messages.success(request, "Gracias por valorar la atención.")
        else:
            raise Http404
    except DomainError as e:
        messages.error(request, e.message + (" " + "; ".join(e.fields.values()) if e.fields else ""))
    return redirect("cases:my_detail", pk=pk)


@require_perm("cases.create", "cases.manage", "cases.supervise", "cases.attend_assigned", any_of=True)
def attachment(request, pk):
    att = get_object_or_404(RequestAttachment.objects.select_related("request"), pk=pk)
    req = att.request
    if not (req.creator_id == request.user.pk or services.can_view_staff(request.user, req)):
        raise Http404
    from django.conf import settings

    path = settings.PRIVATE_MEDIA_ROOT / att.storage_key
    if not path.exists():
        raise Http404
    record(request.user, "case.attachment_downloaded", req, detail={"attachment": att.pk})
    return FileResponse(open(path, "rb"), content_type=att.mime, as_attachment=True, filename=att.original_name)


# --------------------------------------------------------------------------- panel
@require_perm("cases.manage", "cases.supervise", "cases.attend_assigned", any_of=True)
def queue(request):
    base = services.staff_queryset(request.user)
    status = request.GET.get("estado", "pendientes")
    area = request.GET.get("area", "")
    assignee = request.GET.get("responsable", "")
    age = request.GET.get("antiguedad", "")
    q = request.GET.get("q", "").strip()
    groups = {
        "pendientes": Q(status__in=["nuevo", "clasificado", "asignado"]),
        "en_atencion": Q(status__in=["acusado", "en_proceso", "requiere_info"]),
        "resueltos": Q(status="resuelto"),
        "cerrados": Q(status__in=ServiceRequest.FINAL_STATES),
        "todos": Q(),
    }
    counts = {k: base.filter(v).count() for k, v in groups.items()}
    qs = base.filter(groups.get(status, Q())).select_related("category", "area", "assigned_to", "creator")
    if area:
        qs = qs.filter(area_id=area)
    if assignee == "yo":
        qs = qs.filter(assigned_to=request.user)
    elif assignee == "sin":
        qs = qs.filter(assigned_to__isnull=True)
    if age in ("1", "2", "7"):
        qs = qs.filter(created_at__lte=timezone.now() - timedelta(days=int(age)))
    if q:
        qs = qs.filter(Q(folio__icontains=q) | Q(subject__icontains=q))
    areas = Area.objects.filter(pk__in=base.values_list("area_id", flat=True).distinct())
    return render(request, "cases/queue.html", {"page": paginate(request, qs.order_by("created_at")), "status": status, "counts": counts,
                                                "areas": areas, "f": {"area": area, "responsable": assignee, "antiguedad": age, "q": q},
                                                "now": timezone.now()})


@require_perm("cases.manage", "cases.supervise", "cases.attend_assigned", any_of=True)
def manage_detail(request, pk):
    req = get_object_or_404(ServiceRequest.objects.select_related("category", "area", "assigned_to", "creator", "campus"), pk=pk)
    if not services.can_view_staff(request.user, req):
        raise Http404  # caso de otra área: no se revela su existencia
    can_manage = services.can_manage(request.user, req) and req.creator_id != request.user.pk
    can_attend = services.can_attend(request.user, req) and req.creator_id != request.user.pk
    allowed = {a for a, (src, _) in services.STAFF_TRANSITIONS.items() if req.status in src}
    if not can_manage:
        allowed -= services.MANAGER_ONLY
    if not can_attend:
        allowed = set()
    candidates = []
    if can_manage:
        candidates = [u for u in User.objects.filter(status="activo", campus_id=req.campus_id).exclude(pk=req.creator_id).distinct()
                      if services.can_manage(u, req) or has_perm(u, "cases.attend_assigned")]
    target_days = get_policy("request_ack_target_days", req.campus)
    return render(request, "cases/manage_detail.html", {
        "req": req, "events": req.events.select_related("actor"), "steps": _steps(req), "can_manage": can_manage, "can_attend": can_attend,
        "allowed": allowed, "categories": ServiceCategory.objects.filter(campus_id=req.campus_id, active=True), "candidates": candidates,
        "priorities": ServiceRequest.Priority.choices, "attachments": req.attachments.all(), "target_days": target_days,
    })


@require_POST
@require_perm("cases.manage", "cases.attend_assigned", any_of=True)
def manage_action(request, pk, action):
    get_object_or_404(ServiceRequest, pk=pk)
    body = request.POST.get("body", "")
    ok_labels = {
        "classify": "Caso clasificado.", "acknowledge": "Acuse registrado. El caso sigue abierto: el acuse no equivale a resolverlo.",
        "start": "Caso en proceso.", "request_info": "Se pidió información al estudiante.", "resolve": "Caso resuelto; el estudiante puede confirmar o pedir revisión.",
        "close": "Caso cerrado.", "reject": "Solicitud rechazada.", "assign": "Responsable asignado.", "reply": "Respuesta enviada al estudiante.",
        "note": "Nota interna guardada (no visible para el estudiante).",
    }
    try:
        if action == "assign":
            services.assign(request.user, pk, request.POST.get("assignee"))
        elif action in ("reply", "note"):
            services.staff_message(request.user, pk, body, internal=(action == "note"))
        elif action in services.STAFF_TRANSITIONS:
            services.staff_action(request.user, pk, action, body=body, category_id=request.POST.get("category"), priority=request.POST.get("priority"))
        else:
            raise Http404
        messages.success(request, ok_labels[action])
    except DomainError as e:
        if e.code == "PERMISSION_DENIED":
            raise PermissionDenied
        messages.error(request, e.message + (" " + "; ".join(e.fields.values()) if e.fields else ""))
    return redirect("cases:manage_detail", pk=pk)
