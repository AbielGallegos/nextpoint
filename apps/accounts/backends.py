from django.contrib.auth.backends import ModelBackend

from .models import User


class EmailBackend(ModelBackend):
    """Autenticación por correo normalizado. Usuarios no activos no pueden entrar ni conservar sesión."""

    def authenticate(self, request, username=None, password=None, email=None, **kwargs):
        email = (email or username or "").strip().lower()
        if not email or not password:
            return None
        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            User().set_password(password)  # tiempo de respuesta similar: no revela si existe
            return None
        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None

    def user_can_authenticate(self, user):
        return getattr(user, "status", None) == User.Status.ACTIVE and user.is_active
