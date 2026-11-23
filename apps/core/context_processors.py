from django.conf import settings

from apps.accounts.access import PERMISSIONS, has_perm, role_codes


class _Perms:
    """Acceso en plantillas: {% if perms_np.cases_manage %} (solo para mostrar/ocultar; el servidor decide)."""

    def __init__(self, user):
        self.user = user

    def __getattr__(self, name):
        code = name.replace("_", ".", 1)
        if code not in PERMISSIONS:
            raise AttributeError(name)
        return has_perm(self.user, code)


def nextpoint(request):
    ctx = {"NP_VERSION": settings.NEXTPOINT_VERSION, "NP_DEMO": True}
    user = getattr(request, "user", None)
    if user is not None and user.is_authenticated:
        from apps.accounts.models import Role
        from apps.communications.models import Notification

        codes = role_codes(user)
        ctx.update(
            perms_np=_Perms(user),
            unread_notifications=Notification.objects.filter(recipient=user, read_at__isnull=True).count(),
            role_names=list(Role.objects.filter(code__in=codes).values_list("name", flat=True)),
            is_student_user=has_perm(user, "portal.student"),
            is_staff_user=has_perm(user, "panel.access"),
        )
        if ctx["is_staff_user"]:
            from apps.accounts.models import UserRole

            ctx["panel_scopes"] = [
                f"{ur.role.name} · {ur.scope_label}"
                for ur in UserRole.objects.filter(user=user).select_related("role", "area", "campus").exclude(role__code="estudiante")
            ]
    return ctx
