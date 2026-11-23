"""Errores de dominio con los códigos de aplicación del §16.2 de la especificación."""


class DomainError(Exception):
    MESSAGES = {
        "AUTH_REQUIRED": "Necesitas iniciar sesión.",
        "PERMISSION_DENIED": "No tienes permiso para consultar esta información.",
        "RESOURCE_UNAVAILABLE": "El recurso no tiene ejemplares disponibles para esas fechas.",
        "INVALID_TRANSITION": "Esa acción ya no está disponible para el estado actual. Recarga la página.",
        "VALIDATION_FAILED": "Revisa los campos marcados.",
        "DUPLICATE_REQUEST": "Ya existe una solicitud abierta equivalente.",
        "RATE_LIMITED": "Demasiados intentos. Espera unos minutos e intenta de nuevo.",
        "STORAGE_FAILURE": "No pudimos guardar el archivo; el registro no se completó.",
        "SERVICE_UNAVAILABLE": "Este módulo no está disponible por ahora.",
    }
    STATUS = {"PERMISSION_DENIED": 403, "INVALID_TRANSITION": 409, "RESOURCE_UNAVAILABLE": 409, "DUPLICATE_REQUEST": 409,
              "VALIDATION_FAILED": 400, "RATE_LIMITED": 429, "SERVICE_UNAVAILABLE": 503, "STORAGE_FAILURE": 500}

    def __init__(self, code, message=None, fields=None, existing=None):
        self.code = code
        self.message = message or self.MESSAGES.get(code, "No pudimos completar la operación.")
        self.fields = fields or {}
        self.existing = existing
        super().__init__(f"{code}: {self.message}")

    @property
    def http_status(self):
        return self.STATUS.get(self.code, 400)
