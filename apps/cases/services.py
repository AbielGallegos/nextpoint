"""Casos de uso de solicitudes e incidencias con máquina de estados validada en servidor.

nuevo → clasificado → asignado → acusado → en_proceso → resuelto → cerrado
desvíos: requiere_info (vuelve a en_proceso), rechazado, cancelado.
El acuse es una confirmación inicial y NUNCA equivale a resolver.
"""
import mimetypes
import secrets

from django.conf import settings
from django.db import IntegrityError, transaction
from django.urls import reverse
from django.utils import timezone

from apps.accounts.access import can_on, has_perm
from apps.audit.services import record
from apps.communications.services import notify, notify_many
from apps.core.errors import DomainError
from apps.core.models import get_policy

from .models import RequestAttachment, RequestEvent, ServiceCategory, ServiceRequest

S = ServiceRequest.Status

STAFF_TRANSITIONS = {
    "classify": ({S.NEW, S.CLASSIFIED}, S.CLASSIFIED),
    "acknowledge": ({S.NEW, S.CLASSIFIED, S.ASSIGNED}, S.ACKNOWLEDGED),
    "start": ({S.ACKNOWLEDGED, S.NEEDS_INFO}, S.IN_PROGRESS),
    "request_info": ({S.ACKNOWLEDGED, S.IN_PROGRESS}, S.NEEDS_INFO),
    "resolve": ({S.ACKNOWLEDGED, S.IN_PROGRESS, S.NEEDS_INFO}, S.RESOLVED),
    "close": ({S.RESOLVED}, S.CLOSED),
    "reject": ({S.NEW, S.CLASSIFIED, S.ASSIGNED, S.ACKNOWLEDGED}, S.REJECTED),
}
STUDENT_TRANSITIONS = {
    "cancel": ({S.NEW, S.CLASSIFIED, S.ASSIGNED, S.ACKNOWLEDGED, S.NEEDS_INFO}, S.CANCELLED),
    "confirm": ({S.RESOLVED}, S.CLOSED),
    "reopen": ({S.RESOLVED}, S.IN_PROGRESS),
}
# Acciones que solo el gestor del área (no el docente asignado) puede ejecutar
MANAGER_ONLY = {"classify", "close", "reject", "assign"}

ALLOWED_UPLOADS = {
    "application/pdf": (b"%PDF-",),
    "image/png": (b"\x89PNG\r\n\x1a\n",),
    "image/jpeg": (b"\xff\xd8\xff",),
}


# --------------------------------------------------------------------------- permisos
def can_manage(user, req):
    return can_on(user, "cases.manage", area_id=req.area_id, campus_id=req.campus_id)


def can_attend(user, req):
    return can_manage(user, req) or (req.assigned_to_id == user.pk and has_perm(user, "cases.attend_assigned"))


def can_view_staff(user, req):
    return can_attend(user, req) or can_on(user, "cases.supervise", area_id=req.area_id, campus_id=req.campus_id)


def staff_queryset(user):
    """Casos visibles en el panel: área gestionada, casos asignados o supervisión de campus."""
    from django.db.models import Q

    from apps.accounts.access import scope_for

    cond = scope_for(user, "cases.manage").q() | scope_for(user, "cases.supervise").q()
    if has_perm(user, "cases.attend_assigned"):
        cond |= Q(assigned_to=user)
    return ServiceRequest.objects.filter(cond)


def _event(req, actor, kind, *, body="", visibility=RequestEvent.Visibility.PUBLIC, before="", after=""):
    ev = RequestEvent.objects.create(request=req, actor=actor, kind=kind, body=body[:2000], visibility=visibility,
                                     status_before=before, status_after=after)
    if kind in (RequestEvent.Kind.STATUS, RequestEvent.Kind.ASSIGNMENT, RequestEvent.Kind.CREATED):
        # La auditoría no copia el texto del caso (privacidad): solo la transición.
        record(actor, f"case.{after or kind}", req, before=before, after=after)
    return ev


def _area_managers(area):
    from apps.accounts.models import User

    return User.objects.filter(status=User.Status.ACTIVE, user_roles__role__code="gestor", user_roles__area=area).distinct()


def _student_url(req):
    return reverse("cases:my_detail", args=[req.pk])


def _staff_url(req):
    return reverse("cases:manage_detail", args=[req.pk])


def _set_status(req, target, actor, *, body="", visibility=RequestEvent.Visibility.PUBLIC):
    before = req.status
    req.status = target
    now = timezone.now()
    fields = ["status", "updated_at"]
    if target == S.ACKNOWLEDGED and req.acknowledged_at is None:
        req.acknowledged_at = now
        fields.append("acknowledged_at")
    if target == S.RESOLVED:
        req.resolved_at = now
        fields.append("resolved_at")
    if target in (S.CLOSED, S.REJECTED, S.CANCELLED):
        req.closed_at = now
        fields.append("closed_at")
    req.save(update_fields=fields)
    return _event(req, actor, RequestEvent.Kind.STATUS, body=body, visibility=visibility, before=before, after=target)


# --------------------------------------------------------------------------- estudiante
def validate_upload(upload, campus=None):
    if upload is None:
        return None
    max_mb = get_policy("max_attachment_mb", campus)
    if upload.size > max_mb * 1024 * 1024:
        raise DomainError("VALIDATION_FAILED", fields={"attachment": f"El archivo supera {max_mb} MB."})
    head = upload.read(16)
    upload.seek(0)
    mime = next((m for m, sigs in ALLOWED_UPLOADS.items() if any(head.startswith(s) for s in sigs)), None)
    guessed = mimetypes.guess_type(upload.name or "")[0]
    if mime is None or guessed != mime:
        raise DomainError("VALIDATION_FAILED", fields={"attachment": "Solo se aceptan PDF, PNG o JPG válidos."})
    return mime


def _store_upload(req, actor, upload, mime):
    root = settings.PRIVATE_MEDIA_ROOT
    root.mkdir(parents=True, exist_ok=True)
    key = secrets.token_hex(16) + {"application/pdf": ".pdf", "image/png": ".png", "image/jpeg": ".jpg"}[mime]
    try:
        with open(root / key, "wb") as fh:
            for chunk in upload.chunks():
                fh.write(chunk)
    except OSError:
        raise DomainError("STORAGE_FAILURE")
    safe_name = "".join(c for c in (upload.name or "adjunto") if c.isalnum() or c in "._- ")[:100] or "adjunto"
    return RequestAttachment.objects.create(request=req, uploaded_by=actor, storage_key=key, original_name=safe_name,
                                            mime=mime, size=upload.size)


def create_request(creator, category_id, subject, description, priority, idempotency_key, upload=None):
    errors = {}
    subject = (subject or "").strip()
    description = (description or "").strip()
    if len(subject) < 5:
        errors["subject"] = "Escribe un asunto de al menos 5 caracteres."
    if len(description) < 10:
        errors["description"] = "Describe la situación (mínimo 10 caracteres)."
    if priority not in ServiceRequest.Priority.values:
        priority = ServiceRequest.Priority.NORMAL
    category = ServiceCategory.objects.filter(pk=category_id, campus_id=creator.campus_id, active=True).select_related("area", "campus").first()
    if category is None:
        errors["category"] = "Selecciona una categoría válida."
    if errors:
        raise DomainError("VALIDATION_FAILED", fields=errors)
    mime = validate_upload(upload, creator.campus)

    with transaction.atomic():
        previous = ServiceRequest.objects.filter(creator=creator, idempotency_key=idempotency_key).first()
        if previous:
            return previous, False
        try:
            req = ServiceRequest.objects.create(
                creator=creator, institution=category.campus.institution, campus=category.campus, area=category.area,
                category=category, subject=subject[:140], description=description[:3000], priority=priority,
                idempotency_key=idempotency_key,
            )
        except IntegrityError:
            return ServiceRequest.objects.get(creator=creator, idempotency_key=idempotency_key), False
        _event(req, creator, RequestEvent.Kind.CREATED, body="Solicitud registrada.", after=S.NEW)
        if mime:
            _store_upload(req, creator, upload, mime)
        notify_many(_area_managers(req.area), "case", f"Nuevo caso {req.folio}", body=category.name,
                    url=_staff_url(req), dedupe_prefix=f"case:{req.pk}:created")
        notify(creator, "case", f"Solicitud {req.folio} registrada", body="Puedes consultar su estado en cualquier momento.",
               url=_student_url(req), dedupe_key=f"case:{req.pk}:created:owner")
    return req, True


def _owned(user, req_id):
    req = ServiceRequest.objects.select_for_update(of=("self",)).filter(pk=req_id, creator=user).first()
    if req is None:
        raise DomainError("PERMISSION_DENIED")
    return req


def student_action(user, req_id, action, body=""):
    body = (body or "").strip()
    with transaction.atomic():
        req = _owned(user, req_id)
        allowed, target = STUDENT_TRANSITIONS[action]
        if req.status not in allowed:
            raise DomainError("INVALID_TRANSITION")
        if action == "reopen" and len(body) < 5:
            raise DomainError("VALIDATION_FAILED", fields={"body": "Explica por qué necesitas revisión."})
        labels = {"cancel": "Cancelada por el estudiante.", "confirm": "El estudiante confirmó la resolución.",
                  "reopen": "El estudiante solicitó revisión: "}
        _set_status(req, target, user, body=labels[action] + (body if action == "reopen" else ""))
        if action == "reopen":
            notify_many([req.assigned_to] if req.assigned_to else _area_managers(req.area), "case",
                        f"{req.folio}: revisión solicitada", url=_staff_url(req), dedupe_prefix=f"case:{req.pk}:reopen:{req.updated_at.timestamp()}")
    return req


def student_message(user, req_id, body):
    body = (body or "").strip()
    if len(body) < 2:
        raise DomainError("VALIDATION_FAILED", fields={"body": "Escribe un mensaje."})
    with transaction.atomic():
        req = _owned(user, req_id)
        if req.status in ServiceRequest.FINAL_STATES:
            raise DomainError("INVALID_TRANSITION", "El caso ya terminó; no admite mensajes nuevos.")
        ev = _event(req, user, RequestEvent.Kind.MESSAGE, body=body)
        if req.status == S.NEEDS_INFO:
            _set_status(req, S.IN_PROGRESS, user, body="El estudiante envió la información solicitada.")
        notify_many([req.assigned_to] if req.assigned_to else _area_managers(req.area), "case",
                    f"{req.folio}: nuevo mensaje del estudiante", url=_staff_url(req), dedupe_prefix=f"case:{req.pk}:msg:{ev.pk}")
    return req


def rate(user, req_id, rating, comment=""):
    try:
        rating = int(rating)
    except (TypeError, ValueError):
        rating = 0
    if not 1 <= rating <= 5:
        raise DomainError("VALIDATION_FAILED", fields={"rating": "Elige una calificación de 1 a 5."})
    with transaction.atomic():
        req = _owned(user, req_id)
        if req.status != S.CLOSED or req.rating is not None:
            raise DomainError("INVALID_TRANSITION", "Solo puedes valorar una vez un caso cerrado.")
        req.rating, req.rating_comment = rating, (comment or "").strip()[:300]
        req.save(update_fields=["rating", "rating_comment", "updated_at"])
        _event(req, user, RequestEvent.Kind.RATING, body=f"Valoración: {rating}/5", visibility=RequestEvent.Visibility.INTERNAL)
    return req


# --------------------------------------------------------------------------- personal
def staff_action(actor, req_id, action, *, body="", category_id=None, priority=None):
    body = (body or "").strip()
    with transaction.atomic():
        req = ServiceRequest.objects.select_for_update(of=("self",)).get(pk=req_id)
        if action in MANAGER_ONLY:
            if not can_manage(actor, req):
                raise DomainError("PERMISSION_DENIED")
        elif not can_attend(actor, req):
            raise DomainError("PERMISSION_DENIED")
        if req.creator_id == actor.pk:
            raise DomainError("PERMISSION_DENIED", "No puedes atender un caso propio.")
        allowed, target = STAFF_TRANSITIONS[action]
        if req.status not in allowed:
            raise DomainError("INVALID_TRANSITION")

        if action == "classify":
            category = ServiceCategory.objects.filter(pk=category_id, campus_id=req.campus_id, active=True).first()
            if category is None:
                raise DomainError("VALIDATION_FAILED", fields={"category": "Selecciona una categoría del campus."})
            changes = []
            if category.pk != req.category_id:
                changes.append(f"categoría: {req.category.name} → {category.name}")
                req.category, req.area = category, category.area
            if priority in ServiceRequest.Priority.values and priority != req.priority:
                changes.append(f"prioridad: {req.get_priority_display()} → {dict(ServiceRequest.Priority.choices)[priority]}")
                req.priority = priority
            req.save(update_fields=["category", "area", "priority", "updated_at"])
            _set_status(req, target, actor, body="Clasificado. " + "; ".join(changes), visibility=RequestEvent.Visibility.INTERNAL)
        elif action == "acknowledge":
            msg = body or "Recibimos tu solicitud. Aún está en atención; recibirás una actualización cuando cambie su estado."
            _set_status(req, target, actor, body=msg)
            notify(req.creator, "case", f"{req.folio}: recibimos tu solicitud", body="El caso sigue en atención.",
                   url=_student_url(req), dedupe_key=f"case:{req.pk}:ack")
        elif action == "start":
            _set_status(req, target, actor, body=body or "El caso está en proceso de atención.")
        elif action == "request_info":
            if len(body) < 5:
                raise DomainError("VALIDATION_FAILED", fields={"body": "Indica qué información necesitas."})
            _set_status(req, target, actor, body=body)
            notify(req.creator, "case", f"{req.folio}: se requiere información", url=_student_url(req),
                   dedupe_key=f"case:{req.pk}:info:{timezone.now().timestamp()}")
        elif action == "resolve":
            if len(body) < 10:
                raise DomainError("VALIDATION_FAILED", fields={"body": "Documenta la resolución (mínimo 10 caracteres)."})
            req.resolution = body[:2000]
            req.save(update_fields=["resolution"])
            _set_status(req, target, actor, body=body)
            notify(req.creator, "case", f"{req.folio}: caso resuelto", body="Confirma la resolución o solicita revisión.",
                   url=_student_url(req), dedupe_key=f"case:{req.pk}:resolved:{req.resolved_at.timestamp()}")
        elif action == "close":
            _set_status(req, target, actor, body=body or "Caso cerrado por el área responsable.")
            notify(req.creator, "case", f"{req.folio}: caso cerrado", body="Puedes valorar la atención recibida.",
                   url=_student_url(req), dedupe_key=f"case:{req.pk}:closed")
        elif action == "reject":
            if len(body) < 5:
                raise DomainError("VALIDATION_FAILED", fields={"body": "El motivo de rechazo es obligatorio."})
            _set_status(req, target, actor, body=body)
            notify(req.creator, "case", f"{req.folio}: solicitud rechazada", body="Consulta el motivo en el detalle.",
                   url=_student_url(req), dedupe_key=f"case:{req.pk}:rejected")
    return req


def assign(actor, req_id, assignee_id):
    from apps.accounts.models import User

    with transaction.atomic():
        req = ServiceRequest.objects.select_for_update(of=("self",)).get(pk=req_id)
        if not can_manage(actor, req):
            raise DomainError("PERMISSION_DENIED")
        if req.status in ServiceRequest.FINAL_STATES or req.status == S.RESOLVED:
            raise DomainError("INVALID_TRANSITION")
        assignee = User.objects.filter(pk=assignee_id, status=User.Status.ACTIVE).first()
        if assignee is None or assignee.pk == req.creator_id or not (
            can_manage(assignee, req) or (has_perm(assignee, "cases.attend_assigned") and assignee.campus_id == req.campus_id)
        ):
            raise DomainError("VALIDATION_FAILED", fields={"assignee": "Elige a una persona autorizada para esta área."})
        previous = req.assigned_to
        req.assigned_to = assignee
        req.save(update_fields=["assigned_to", "updated_at"])
        before = req.status
        _event(req, actor, RequestEvent.Kind.ASSIGNMENT, body=f"Responsable: {assignee.display_name}",
               visibility=RequestEvent.Visibility.PUBLIC, before=before, after=before)
        if req.status in (S.NEW, S.CLASSIFIED):
            _set_status(req, S.ASSIGNED, actor, body="Caso asignado a un responsable.", visibility=RequestEvent.Visibility.INTERNAL)
        record(actor, "case.assignment", req, before=getattr(previous, "pk", ""), after=assignee.pk)
        notify(assignee, "case", f"Se te asignó el caso {req.folio}", url=_staff_url(req),
               dedupe_key=f"case:{req.pk}:assign:{assignee.pk}:{timezone.now().timestamp()}")
    return req


def staff_message(actor, req_id, body, internal=False):
    body = (body or "").strip()
    if len(body) < 2:
        raise DomainError("VALIDATION_FAILED", fields={"body": "Escribe el mensaje."})
    with transaction.atomic():
        req = ServiceRequest.objects.select_for_update(of=("self",)).get(pk=req_id)
        if not can_attend(actor, req):
            raise DomainError("PERMISSION_DENIED")
        if req.status in ServiceRequest.FINAL_STATES:
            raise DomainError("INVALID_TRANSITION", "El caso ya terminó.")
        vis = RequestEvent.Visibility.INTERNAL if internal else RequestEvent.Visibility.PUBLIC
        ev = _event(req, actor, RequestEvent.Kind.NOTE if internal else RequestEvent.Kind.MESSAGE, body=body, visibility=vis)
        if not internal:
            notify(req.creator, "case", f"{req.folio}: nueva respuesta", body="El área responsable respondió a tu caso.",
                   url=_student_url(req), dedupe_key=f"case:{req.pk}:reply:{ev.pk}")
    return req
