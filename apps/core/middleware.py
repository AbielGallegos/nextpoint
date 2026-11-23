"""Middleware transversal: identificador de traza, cabeceras de seguridad y no-cache de páginas privadas."""
import threading
import uuid

_local = threading.local()


def current_trace_id() -> str:
    return getattr(_local, "trace_id", "-")


class TraceIdMiddleware:
    """Asigna un trace_id a cada petición (logs, auditoría y página de error lo comparten)."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        trace_id = uuid.uuid4().hex[:16]
        request.trace_id = trace_id
        _local.trace_id = trace_id
        try:
            response = self.get_response(request)
        finally:
            _local.trace_id = "-"
        response["X-Trace-Id"] = trace_id
        return response


class SecurityHeadersMiddleware:
    """CSP estricta: sin scripts en línea ni recursos de terceros (la demo funciona sin internet)."""

    CSP = (
        "default-src 'self'; script-src 'self'; style-src 'self'; style-src-attr 'unsafe-inline'; img-src 'self' data:; "
        "font-src 'self'; connect-src 'self'; form-action 'self'; frame-ancestors 'none'; "
        "base-uri 'self'; object-src 'none'"
    )

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        response.setdefault("Content-Security-Policy", self.CSP)
        response.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        response.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        return response


class NoStoreForAuthenticatedMiddleware:
    """Evita que el botón "atrás" muestre páginas protegidas después de cerrar sesión."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated:
            response["Cache-Control"] = "no-store, private"
            response["Pragma"] = "no-cache"
        return response
