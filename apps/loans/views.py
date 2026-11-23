import uuid

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.accounts.access import can_on, has_perm, require_perm, scope_for, student_required
from apps.catalog.models import InventoryMovement, Resource, ResourceUnit
from apps.core.errors import DomainError
from apps.core.models import get_policy
from apps.core.views_utils import paginate, parse_date

from . import services
from .models import LoanRequest

STEPS = [("solicitado", "Solicitado"), ("en_revision", "En revisión"), ("aprobado", "Aprobado"), ("entregado", "Entregado"), ("devuelto", "Devuelto")]


def _steps(req):
    order = [s for s, _ in STEPS]
    if req.status in order:
        idx = order.index(req.status)
        final = req.status == "devuelto"
    else:  # rechazado / cancelado: se marca hasta el último estado alcanzado
        reached = [e.status_after for e in req.events.all() if e.status_after in order]
        idx = max((order.index(s) for s in reached), default=0) + 1
        final = False
    out = []
    for i, (code, label) in enumerate(STEPS):
        if i < idx or (final and i == idx):
            state = "done"
        elif i == idx and req.status in order:
            state = "current"
        else:
            state = ""
        out.append({"label": label, "state": state, "n": i + 1})
    if req.status not in order:
        out = out[:idx] + [{"label": req.get_status_display(), "state": "stopped", "n": "×"}]
    return out


# --------------------------------------------------------------------------- estudiante
@student_required
def request_form(request, resource_id):
    resource = get_object_or_404(Resource.objects.select_related("area", "location", "category"), pk=resource_id,
                                 campus_id=request.user.campus_id, status=Resource.Status.PUBLISHED)
    today = timezone.localdate()
    max_days = resource.max_loan_days or get_policy("max_loan_days", resource.campus)
    errors, data = {}, {}
    if request.method == "POST":
        data = request.POST
        try:
            key = uuid.UUID(request.POST.get("idempotency_key", ""))
        except ValueError:
            key = uuid.uuid4()
        try:
            req, created = services.create_request(request.user, resource.pk, parse_date(data.get("start_date")), parse_date(data.get("due_date")),
                                                   data.get("purpose", ""), key)
            if created:
                messages.success(request, f"Tu solicitud quedó registrada con el folio {req.folio}. Puedes consultar su estado en cualquier momento.")
            else:
                messages.info(request, f"Esta solicitud ya estaba registrada con el folio {req.folio}.")
            return redirect("loans:my_detail", pk=req.pk)
        except DomainError as e:
            errors = e.fields
            if e.code == "DUPLICATE_REQUEST" and e.existing:
                messages.warning(request, e.message)
                return redirect("loans:my_detail", pk=e.existing.pk)
            messages.error(request, e.message)
    return render(request, "loans/request_form.html", {
        "r": resource, "av": resource.availability(), "today": today, "max_days": max_days, "errors": errors, "data": data,
        "key": data.get("idempotency_key") or uuid.uuid4(),
        "default_due": today + timezone.timedelta(days=min(max_days, 3) - 1),
    }, status=400 if errors else 200)


@student_required
def mine(request):
    qs = LoanRequest.objects.filter(applicant=request.user).select_related("resource", "unit")
    tab = request.GET.get("vista", "activas")
    if tab == "activas":
        qs = qs.filter(status__in=LoanRequest.OPEN_STATES)
    elif tab == "historial":
        qs = qs.exclude(status__in=LoanRequest.OPEN_STATES)
    counts = {
        "activas": LoanRequest.objects.filter(applicant=request.user, status__in=LoanRequest.OPEN_STATES).count(),
        "historial": LoanRequest.objects.filter(applicant=request.user).exclude(status__in=LoanRequest.OPEN_STATES).count(),
    }
    return render(request, "loans/mine.html", {"page": paginate(request, qs), "tab": tab, "counts": counts, "today": timezone.localdate()})


@student_required
def my_detail(request, pk):
    # Filtrar por solicitante: un folio ajeno responde 404 (no revela su existencia).
    req = get_object_or_404(LoanRequest.objects.select_related("resource", "unit", "area", "decided_by"), pk=pk, applicant=request.user)
    return render(request, "loans/my_detail.html", {"req": req, "events": req.events.select_related("actor"), "steps": _steps(req),
                                                    "today": timezone.localdate()})


@require_POST
@student_required
def cancel(request, pk):
    try:
        req = services.cancel_by_applicant(request.user, pk)
        messages.success(request, f"Solicitud {req.folio} cancelada. El registro se conserva en tu historial.")
    except DomainError as e:
        if e.code == "PERMISSION_DENIED":
            from django.http import Http404

            raise Http404
        messages.error(request, e.message)
    return redirect("loans:my_detail", pk=pk)


# --------------------------------------------------------------------------- gestor
def _queue_scope(user):
    return scope_for(user, "loans.manage").q() | scope_for(user, "loans.supervise").q()


@require_perm("loans.manage", "loans.supervise", any_of=True)
def queue(request):
    qs = LoanRequest.objects.filter(_queue_scope(request.user)).select_related("resource", "applicant", "unit", "area")
    status = request.GET.get("estado", "pendientes")
    q = request.GET.get("q", "").strip()
    today = timezone.localdate()
    filters = {
        "pendientes": Q(status__in=["solicitado", "en_revision"]),
        "aprobados": Q(status="aprobado"),
        "activos": Q(status="entregado"),
        "vencidos": services.overdue_q(),
        "cerrados": Q(status__in=["devuelto", "rechazado", "cancelado", "cerrado"]),
        "todos": Q(),
    }
    base = LoanRequest.objects.filter(_queue_scope(request.user))
    counts = {k: base.filter(v).count() for k, v in filters.items()}
    qs = qs.filter(filters.get(status, Q()))
    if q:
        qs = qs.filter(Q(folio__icontains=q) | Q(resource__name__icontains=q))
    order = "due_date" if status in ("activos", "vencidos") else "created_at"
    return render(request, "loans/queue.html", {"page": paginate(request, qs.order_by(order)), "status": status, "counts": counts, "q": q, "today": today})


@require_perm("loans.manage", "loans.supervise", any_of=True)
def manage_detail(request, pk):
    req = get_object_or_404(LoanRequest.objects.select_related("resource", "applicant", "unit", "area", "decided_by"), pk=pk)
    can_manage = can_on(request.user, "loans.manage", area_id=req.area_id, campus_id=req.campus_id)
    if not can_manage and not can_on(request.user, "loans.supervise", area_id=req.area_id, campus_id=req.campus_id):
        from django.http import Http404

        raise Http404  # registros de otra área: no se revela su existencia
    loan = getattr(req, "loan", None) if hasattr(req, "loan") else None
    units = req.resource.units.all()
    conflicts = LoanRequest.objects.filter(resource=req.resource, status__in=LoanRequest.RESERVING_STATES).exclude(pk=req.pk).filter(
        start_date__lte=req.due_date, due_date__gte=req.start_date).select_related("unit")
    own = req.applicant_id == request.user.pk
    return render(request, "loans/manage_detail.html", {
        "req": req, "loan": loan, "events": req.events.select_related("actor"), "steps": _steps(req), "can_manage": can_manage and not own,
        "units": units, "conflicts": conflicts, "conditions": ResourceUnit.Condition.choices,
        "movements": InventoryMovement.objects.filter(loan_request=req).select_related("unit", "actor"), "today": timezone.localdate(),
        "allowed": {a for a, (src, _) in services.TRANSITIONS.items() if req.status in src},
    })


@require_POST
@require_perm("loans.manage")
def manage_action(request, pk, action):
    handlers = {
        "review": lambda: services.mark_in_review(request.user, pk),
        "approve": lambda: services.approve(request.user, pk, request.POST.get("note", "")),
        "reject": lambda: services.reject(request.user, pk, request.POST.get("reason", "")),
        "cancel": lambda: services.cancel_by_manager(request.user, pk, request.POST.get("reason", "")),
        "deliver": lambda: services.deliver(request.user, pk, request.POST.get("condition", ""), request.POST.get("note", "")),
        "return": lambda: services.register_return(request.user, pk, request.POST.get("condition", ""), request.POST.get("destination", ""),
                                                   request.POST.get("note", "")),
    }
    if action not in handlers:
        raise PermissionDenied
    get_object_or_404(LoanRequest, pk=pk)
    labels = {"review": "Revisión iniciada.", "approve": "Préstamo aprobado y ejemplar apartado.", "reject": "Solicitud rechazada.",
              "cancel": "Solicitud cancelada.", "deliver": "Entrega registrada: el ejemplar quedó ocupado.",
              "return": "Devolución registrada e inventario actualizado."}
    try:
        handlers[action]()
        messages.success(request, labels[action])
    except DomainError as e:
        if e.code == "PERMISSION_DENIED" and "propia" not in e.message:
            raise PermissionDenied
        detail = "; ".join(e.fields.values()) if e.fields else ""
        messages.error(request, f"{e.message} {detail}".strip())
    return redirect("loans:manage_detail", pk=pk)
