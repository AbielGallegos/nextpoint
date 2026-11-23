"""Centro interno de notificaciones (sin SMTP externo). Idempotente por dedupe_key."""
from django.db import IntegrityError, transaction

from .models import Notification

ICONS = {
    "loan": "package", "case": "clipboard-list", "alert": "megaphone", "course": "graduation-cap",
    "support": "life-buoy", "account": "user",
}


def notify(recipient, event_type, title, *, body="", url="", dedupe_key):
    """Crea una notificación una sola vez por evento. No incluye datos sensibles en el texto."""
    if recipient is None:
        return None
    try:
        with transaction.atomic():
            return Notification.objects.create(
                recipient=recipient, event_type=event_type, title=title[:140], body=body[:300], target_url=url[:200],
                dedupe_key=dedupe_key[:120],
            )
    except IntegrityError:
        return Notification.objects.filter(dedupe_key=dedupe_key[:120]).first()


def notify_many(recipients, event_type, title, *, body="", url="", dedupe_prefix):
    for user in {u.pk: u for u in recipients if u is not None}.values():
        notify(user, event_type, title, body=body, url=url, dedupe_key=f"{dedupe_prefix}:{user.pk}")
