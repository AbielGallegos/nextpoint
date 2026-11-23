"""Casos de uso de préstamos. Toda modificación de inventario ocurre aquí, dentro de transacciones.

Máquina de estados:
  solicitado → en_revision → aprobado → entregado → devuelto → (cerrado)
  solicitado/en_revision → rechazado        solicitado/en_revision/aprobado → cancelado
"""
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.db.models import F, Q
from django.urls import reverse
from django.utils import timezone

from apps.accounts.access import can_on
from apps.audit.services import record
from apps.catalog.models import InventoryMovement, Resource, ResourceUnit
from apps.communications.services import notify, notify_many
from apps.core.errors import DomainError
from apps.core.models import get_policy

from .models import Loan, LoanEvent, LoanRequest

S = LoanRequest.Status

TRANSITIONS = {
    "review": ({S.REQUESTED}, S.IN_REVIEW),
    "approve": ({S.REQUESTED, S.IN_REVIEW}, S.APPROVED),
    "reject": ({S.REQUESTED, S.IN_REVIEW}, S.REJECTED),
    "cancel": ({S.REQUESTED, S.IN_REVIEW, S.APPROVED}, S.CANCELLED),
    "deliver": ({S.APPROVED}, S.DELIVERED),
    "return": ({S.DELIVERED}, S.RETURNED),
}


def unit_is_free(unit, start, end, exclude_request_id=None):
    """¿El ejemplar no tiene apartados/préstamos que se traslapen con [start, end]?"""
    qs = LoanRequest.objects.filter(unit=unit, status__in=LoanRequest.RESERVING_STATES).filter(
        start_date__lte=end, due_date__gte=start
    )
    if exclude_request_id:
        qs = qs.exclude(pk=exclude_request_id)
    return not qs.exists()


def _event(req, before, after, actor, note=""):
    LoanEvent.objects.create(request=req, status_before=before, status_after=after, actor=actor, note=note[:300])
    record(actor, f"loan.{after}", req, before=before, after=after, detail={"note": note[:120]} if note else {})


def _managers_of(area):
    from apps.accounts.models import User

    return User.objects.filter(
        status=User.Status.ACTIVE, user_roles__role__code="gestor", user_roles__area=area
    ).distinct()


def _check_transition(req, action):
    allowed, target = TRANSITIONS[action]
    if req.status not in allowed:
        raise DomainError("INVALID_TRANSITION")
    return target


def _require_manager(actor, req):
    if not can_on(actor, "loans.manage", area_id=req.area_id, campus_id=req.campus_id):
        raise DomainError("PERMISSION_DENIED")
    if req.applicant_id == actor.pk:
        raise DomainError("PERMISSION_DENIED", "Nadie puede decidir sobre su propia solicitud.")


# --------------------------------------------------------------------------- estudiante
def create_request(applicant, resource_id, start_date, due_date, purpose, idempotency_key):
    """Crea una solicitud. El solicitante y el campus salen de la sesión, nunca del formulario."""
    errors = {}
    today = timezone.localdate()
    purpose = (purpose or "").strip()
    if not purpose or len(purpose) < 5:
        errors["purpose"] = "Describe brevemente la finalidad (mínimo 5 caracteres)."
    if start_date is None:
        errors["start_date"] = "Indica la fecha de inicio."
    if due_date is None:
        errors["due_date"] = "Indica la fecha de devolución."
    if errors:
        raise DomainError("VALIDATION_FAILED", fields=errors)

    with transaction.atomic():
        # Idempotencia: el mismo envío (doble clic/reintento) devuelve el folio previo.
        previous = LoanRequest.objects.filter(applicant=applicant, idempotency_key=idempotency_key).first()
        if previous:
            return previous, False

        resource = (
            Resource.objects.select_related("area", "campus")
            .filter(pk=resource_id, campus_id=applicant.campus_id, status=Resource.Status.PUBLISHED)
            .first()
        )
        if resource is None or not resource.is_requestable:
            raise DomainError("RESOURCE_UNAVAILABLE", "Este recurso no está disponible para solicitud.")

        max_days = resource.max_loan_days or get_policy("max_loan_days", resource.campus)
        if start_date < today:
            errors["start_date"] = "La fecha de inicio no puede ser anterior a hoy."
        elif start_date > today + timedelta(days=60):
            errors["start_date"] = "Solo se aceptan solicitudes con hasta 60 días de anticipación."
        if due_date < start_date:
            errors["due_date"] = "La devolución debe ser igual o posterior al inicio."
        elif (due_date - start_date).days + 1 > max_days:
            errors["due_date"] = f"El plazo máximo para este recurso es de {max_days} días."
        if errors:
            raise DomainError("VALIDATION_FAILED", fields=errors)

        duplicate = LoanRequest.objects.filter(applicant=applicant, resource=resource, status__in=LoanRequest.OPEN_STATES).first()
        if duplicate:
            raise DomainError("DUPLICATE_REQUEST", f"Ya tienes una solicitud abierta de este recurso ({duplicate.folio}).", existing=duplicate)

        operable = resource.units.filter(state__in=ResourceUnit.OPERABLE_STATES)
        if not operable.exists():
            raise DomainError("RESOURCE_UNAVAILABLE", "El recurso no tiene ejemplares en servicio.")

        limit = get_policy("max_concurrent_loans", resource.campus)
        if LoanRequest.objects.filter(applicant=applicant, status__in=LoanRequest.OPEN_STATES).count() >= limit:
            raise DomainError("VALIDATION_FAILED", f"Alcanzaste el máximo de {limit} solicitudes o préstamos activos.")

        try:
            req = LoanRequest.objects.create(
                applicant=applicant, resource=resource, campus=resource.campus, area=resource.area,
                start_date=start_date, due_date=due_date, purpose=purpose[:300], idempotency_key=idempotency_key,
            )
        except IntegrityError:
            return LoanRequest.objects.get(applicant=applicant, idempotency_key=idempotency_key), False
        _event(req, "", S.REQUESTED, applicant, "Solicitud registrada por el estudiante")
        url = reverse("loans:manage_detail", args=[req.pk])
        notify_many(_managers_of(resource.area), "loan", f"Nueva solicitud {req.folio}", body=f"{resource.name}",
                    url=url, dedupe_prefix=f"loan:{req.pk}:created")
        notify(applicant, "loan", f"Solicitud {req.folio} registrada",
               body="Puedes consultar su estado en cualquier momento.", url=reverse("loans:my_detail", args=[req.pk]),
               dedupe_key=f"loan:{req.pk}:created:applicant")
    return req, True


def cancel_by_applicant(applicant, req_id):
    with transaction.atomic():
        req = LoanRequest.objects.select_for_update(of=("self",)).filter(pk=req_id, applicant=applicant).first()
        if req is None:
            raise DomainError("PERMISSION_DENIED")
        before = req.status
        target = _check_transition(req, "cancel")
        _release_unit(req, applicant, "Cancelación del solicitante")
        req.status = target
        req.save(update_fields=["status", "unit", "updated_at"])
        _event(req, before, target, applicant, "Cancelada por el estudiante")
    return req


# --------------------------------------------------------------------------- gestor
def mark_in_review(actor, req_id):
    with transaction.atomic():
        req = LoanRequest.objects.select_for_update(of=("self",)).get(pk=req_id)
        _require_manager(actor, req)
        before = req.status
        req.status = _check_transition(req, "review")
        req.save(update_fields=["status", "updated_at"])
        _event(req, before, req.status, actor, "Revisión iniciada")
    return req


def approve(actor, req_id, note=""):
    """Aprueba y aparta un ejemplar concreto. Serializado por recurso: nunca sobreasigna el último ejemplar."""
    with transaction.atomic():
        req = LoanRequest.objects.select_for_update(of=("self",)).select_related("resource").get(pk=req_id)
        _require_manager(actor, req)
        before = req.status
        target = _check_transition(req, "approve")
        # Candado: tocar la fila del recurso serializa aprobaciones concurrentes (PostgreSQL y SQLite).
        Resource.objects.filter(pk=req.resource_id).update(lock_version=F("lock_version") + 1)
        units = list(
            ResourceUnit.objects.select_for_update(of=("self",))
            .filter(resource_id=req.resource_id, state__in=ResourceUnit.OPERABLE_STATES)
            .order_by("serial")
        )
        chosen = next((u for u in units if unit_is_free(u, req.start_date, req.due_date, exclude_request_id=req.pk)), None)
        if chosen is None:
            raise DomainError(
                "RESOURCE_UNAVAILABLE",
                "No hay ejemplares libres para esas fechas: otra solicitud ya ocupa el último ejemplar.",
            )
        req.unit = chosen
        req.status = target
        req.decided_by = actor
        req.decided_at = timezone.now()
        req.decision_note = (note or "")[:300]
        req.save(update_fields=["unit", "status", "decided_by", "decided_at", "decision_note", "updated_at"])
        InventoryMovement.objects.create(unit=chosen, kind=InventoryMovement.Kind.RESERVE, state_before=chosen.state,
                                         state_after=chosen.state, actor=actor, loan_request=req,
                                         note=f"Apartado {req.start_date:%d/%m} – {req.due_date:%d/%m}")
        _event(req, before, target, actor, note or "Aprobada")
        notify(req.applicant, "loan", f"Préstamo aprobado · {req.folio}",
               body="Tu solicitud fue aprobada. Revisa las indicaciones de entrega con el área responsable.",
               url=reverse("loans:my_detail", args=[req.pk]), dedupe_key=f"loan:{req.pk}:approved")
    return req


def reject(actor, req_id, reason):
    reason = (reason or "").strip()
    if len(reason) < 5:
        raise DomainError("VALIDATION_FAILED", fields={"reason": "El motivo de rechazo es obligatorio."})
    with transaction.atomic():
        req = LoanRequest.objects.select_for_update(of=("self",)).get(pk=req_id)
        _require_manager(actor, req)
        before = req.status
        req.status = _check_transition(req, "reject")
        req.decided_by, req.decided_at, req.decision_note = actor, timezone.now(), reason[:300]
        req.save(update_fields=["status", "decided_by", "decided_at", "decision_note", "updated_at"])
        _event(req, before, req.status, actor, reason)
        notify(req.applicant, "loan", f"Solicitud rechazada · {req.folio}", body="Consulta el motivo en el detalle.",
               url=reverse("loans:my_detail", args=[req.pk]), dedupe_key=f"loan:{req.pk}:rejected")
    return req


def cancel_by_manager(actor, req_id, reason):
    reason = (reason or "").strip()
    if len(reason) < 5:
        raise DomainError("VALIDATION_FAILED", fields={"reason": "Indica el motivo de la cancelación."})
    with transaction.atomic():
        req = LoanRequest.objects.select_for_update(of=("self",)).get(pk=req_id)
        _require_manager(actor, req)
        before = req.status
        target = _check_transition(req, "cancel")
        _release_unit(req, actor, reason)
        req.status = target
        req.decision_note = reason[:300]
        req.save(update_fields=["status", "unit", "decision_note", "updated_at"])
        _event(req, before, target, actor, reason)
        notify(req.applicant, "loan", f"Solicitud cancelada · {req.folio}", body="Consulta el motivo en el detalle.",
               url=reverse("loans:my_detail", args=[req.pk]), dedupe_key=f"loan:{req.pk}:cancelled")
    return req


def _release_unit(req, actor, note):
    if req.unit_id and req.status == S.APPROVED:
        unit = req.unit
        InventoryMovement.objects.create(unit=unit, kind=InventoryMovement.Kind.RELEASE, state_before=unit.state,
                                         state_after=unit.state, actor=actor, loan_request=req, note=note[:200])
        req.unit = None


def deliver(actor, req_id, condition, note=""):
    if condition not in ResourceUnit.Condition.values:
        raise DomainError("VALIDATION_FAILED", fields={"condition": "Selecciona la condición del ejemplar."})
    with transaction.atomic():
        req = LoanRequest.objects.select_for_update(of=("self",)).select_related("unit").get(pk=req_id)
        _require_manager(actor, req)
        before = req.status
        target = _check_transition(req, "deliver")
        unit = ResourceUnit.objects.select_for_update(of=("self",)).get(pk=req.unit_id)
        if unit.state != ResourceUnit.State.AVAILABLE:
            raise DomainError("RESOURCE_UNAVAILABLE", f"El ejemplar {unit.serial} no está disponible físicamente ({unit.get_state_display()}).")
        try:
            with transaction.atomic():
                Loan.objects.create(request=req, unit=unit, delivered_at=timezone.now(), delivered_by=actor,
                                    delivery_condition=condition, due_date=req.due_date)
        except IntegrityError:
            raise DomainError("RESOURCE_UNAVAILABLE", "El ejemplar ya tiene un préstamo activo.")
        old_state = unit.state
        unit.state = ResourceUnit.State.ON_LOAN
        unit.condition = condition
        unit.save(update_fields=["state", "condition", "updated_at"])
        InventoryMovement.objects.create(unit=unit, kind=InventoryMovement.Kind.DELIVER, state_before=old_state,
                                         state_after=unit.state, actor=actor, loan_request=req, note=note[:200])
        req.status = target
        req.save(update_fields=["status", "updated_at"])
        _event(req, before, target, actor, note or f"Entregado ejemplar {unit.serial}")
        notify(req.applicant, "loan", f"Entrega registrada · {req.folio}",
               body=f"Devolución prevista: {req.due_date:%d/%m/%Y}.", url=reverse("loans:my_detail", args=[req.pk]),
               dedupe_key=f"loan:{req.pk}:delivered")
    return req


RETURN_DESTINATIONS = {
    "disponible": ResourceUnit.State.AVAILABLE,
    "revision": ResourceUnit.State.REVIEW,
    "mantenimiento": ResourceUnit.State.MAINTENANCE,
}


def register_return(actor, req_id, condition, destination, note=""):
    errors = {}
    if condition not in ResourceUnit.Condition.values:
        errors["condition"] = "Selecciona la condición del ejemplar."
    if destination not in RETURN_DESTINATIONS:
        errors["destination"] = "Decide si el ejemplar queda disponible, en revisión o en mantenimiento."
    if condition == ResourceUnit.Condition.DAMAGED and destination == "disponible":
        errors["destination"] = "Un ejemplar dañado no puede quedar disponible: envíalo a revisión o mantenimiento."
    if condition == ResourceUnit.Condition.DAMAGED and len((note or "").strip()) < 5:
        errors["note"] = "Describe el daño observado."
    if errors:
        raise DomainError("VALIDATION_FAILED", fields=errors)
    with transaction.atomic():
        req = LoanRequest.objects.select_for_update(of=("self",)).get(pk=req_id)
        _require_manager(actor, req)
        before = req.status
        target = _check_transition(req, "return")
        loan = Loan.objects.select_for_update(of=("self",)).get(request=req)
        unit = ResourceUnit.objects.select_for_update(of=("self",)).get(pk=loan.unit_id)
        loan.returned_at = timezone.now()
        loan.received_by = actor
        loan.return_condition = condition
        loan.return_note = (note or "")[:300]
        loan.save()
        old_state = unit.state
        unit.state = RETURN_DESTINATIONS[destination]
        unit.condition = condition
        unit.save(update_fields=["state", "condition", "updated_at"])
        InventoryMovement.objects.create(unit=unit, kind=InventoryMovement.Kind.RETURN, state_before=old_state,
                                         state_after=unit.state, actor=actor, loan_request=req, note=(note or "")[:200])
        req.status = target
        req.save(update_fields=["status", "updated_at"])
        late = timezone.localdate() > req.due_date
        _event(req, before, target, actor, (note or "Devolución registrada") + (" · devolución tardía (sin cargo)" if late else ""))
        notify(req.applicant, "loan", f"Devolución registrada · {req.folio}", body="Gracias. El préstamo quedó concluido.",
               url=reverse("loans:my_detail", args=[req.pk]), dedupe_key=f"loan:{req.pk}:returned")
    return req


def overdue_q():
    return Q(status=S.DELIVERED, due_date__lt=timezone.localdate())
