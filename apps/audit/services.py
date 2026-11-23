"""Registro de eventos de negocio y seguridad. Nunca guarda contraseñas, tokens ni texto completo de casos."""
import logging

from apps.core.middleware import current_trace_id

from .models import AuditLog

logger = logging.getLogger("nextpoint.audit")


def record(actor, action, target=None, *, before="", after="", detail=None, campus=None, area=None, label=None, kind=AuditLog.Kind.BUSINESS):
    target_type = target_id = ""
    if target is not None:
        target_type = target._meta.model_name
        target_id = str(target.pk)
        if campus is None:
            campus = getattr(target, "campus", None)
        if area is None:
            area = getattr(target, "area", None)
    if label is None and target is not None:
        label = getattr(target, "folio", None) or str(target)
    entry = AuditLog.objects.create(
        actor=actor if (actor is not None and getattr(actor, "pk", None)) else None,
        actor_label=(str(actor) if actor is not None and getattr(actor, "pk", None) else "sistema")[:160],
        kind=kind,
        action=action,
        target_type=target_type,
        target_id=target_id,
        target_label=(label or "")[:200],
        status_before=str(before or "")[:40],
        status_after=str(after or "")[:40],
        detail=detail or {},
        campus=campus if hasattr(campus, "pk") else None,
        area=area if hasattr(area, "pk") else None,
        trace_id=current_trace_id(),
    )
    logger.info(action, extra={"event": action, "actor": entry.actor_id, "outcome": "ok"})
    return entry


def log_security(request, action, *, detail=None, actor=None):
    user = actor or (request.user if request is not None and request.user.is_authenticated else None)
    return record(user, action, detail=detail or {}, kind=AuditLog.Kind.SECURITY, campus=getattr(user, "campus", None))
