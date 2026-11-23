"""Configuración de NextPoint.

Todos los secretos y parámetros de entorno se leen de variables de entorno
(o de un archivo .env local que nunca se versiona). Ver .env.example.
"""
from pathlib import Path
import os

import dj_database_url

BASE_DIR = Path(__file__).resolve().parent.parent


def _load_dotenv(path: Path) -> None:
    """Carga un .env sencillo (CLAVE=valor) sin sobrescribir variables ya definidas."""
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv(BASE_DIR / ".env")


def env_bool(name: str, default: bool = False) -> bool:
    return os.environ.get(name, str(default)).strip().lower() in {"1", "true", "yes", "si", "sí"}


DEBUG = env_bool("NEXTPOINT_DEBUG", False)
import sys as _sys

TESTING = env_bool("NEXTPOINT_TESTING", False) or (len(_sys.argv) > 1 and _sys.argv[1] == "test")

SECRET_KEY = os.environ.get("NEXTPOINT_SECRET_KEY", "")
import sys

if not SECRET_KEY:
    if DEBUG or TESTING or (len(sys.argv) > 1 and sys.argv[1] in {"init_env", "test"}):
        # Solo para desarrollo/pruebas locales: una llave efímera distinta en cada arranque.
        import secrets

        SECRET_KEY = "dev-only-" + secrets.token_urlsafe(48)
    else:
        from django.core.exceptions import ImproperlyConfigured

        raise ImproperlyConfigured(
            "Falta NEXTPOINT_SECRET_KEY. Ejecuta `python manage.py init_env` o copia .env.example como .env."
        )

ALLOWED_HOSTS = [h.strip() for h in os.environ.get("NEXTPOINT_ALLOWED_HOSTS", "localhost,127.0.0.1,[::1]").split(",") if h.strip()]
CSRF_TRUSTED_ORIGINS = [o.strip() for o in os.environ.get("NEXTPOINT_CSRF_TRUSTED_ORIGINS", "").split(",") if o.strip()]

# Despliegue en Vercel: los dominios del despliegue llegan como variables de sistema.
ON_VERCEL = bool(os.environ.get("VERCEL"))
for _var in ("VERCEL_URL", "VERCEL_BRANCH_URL", "VERCEL_PROJECT_PRODUCTION_URL"):
    _host = os.environ.get(_var, "").strip()
    if _host:
        ALLOWED_HOSTS.append(_host)
        CSRF_TRUSTED_ORIGINS.append(f"https://{_host}")
if ON_VERCEL:
    # Vercel solo enruta a esta función las peticiones de los dominios del proyecto
    # (alias de producción, rama y despliegue), así que aceptar *.vercel.app es seguro aquí.
    ALLOWED_HOSTS.append(".vercel.app")
    CSRF_TRUSTED_ORIGINS.append("https://*.vercel.app")
# Detrás de un proxy de confianza (Vercel): esquema HTTPS e IP real del cliente.
BEHIND_PROXY = env_bool("NEXTPOINT_BEHIND_PROXY", ON_VERCEL)
if BEHIND_PROXY:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
CLIENT_IP_HEADER = os.environ.get("NEXTPOINT_CLIENT_IP_HEADER", "HTTP_X_REAL_IP" if ON_VERCEL else "")

INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
    # Dominios de NextPoint
    "apps.core",
    "apps.audit",
    "apps.accounts",
    "apps.catalog",
    "apps.loans",
    "apps.cases",
    "apps.smartmatch",
    "apps.learning",
    "apps.communications",
    "apps.reporting",
]

MIDDLEWARE = [
    "apps.core.middleware.TraceIdMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "apps.core.middleware.SecurityHeadersMiddleware",
    "apps.core.middleware.NoStoreForAuthenticatedMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "apps.core.context_processors.nextpoint",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# Base de datos: PostgreSQL recomendado (DATABASE_URL); SQLite como respaldo sin configuración.
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
if DATABASE_URL:
    # En funciones serverless no se conservan conexiones; con el pooler en modo transacción
    # (Supabase, puerto 6543) se desactivan los cursores del lado del servidor.
    DATABASES = {"default": dj_database_url.parse(DATABASE_URL, conn_max_age=0 if ON_VERCEL else 60)}
    if env_bool("NEXTPOINT_DB_TRANSACTION_POOLER", ":6543" in DATABASE_URL):
        DATABASES["default"]["DISABLE_SERVER_SIDE_CURSORS"] = True
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / os.environ.get("NEXTPOINT_SQLITE_NAME", "nextpoint.sqlite3"),
            # IMMEDIATE: cada transacción toma el candado de escritura al iniciar, de modo que
            # dos aprobaciones del último ejemplar se serializan también en SQLite.
            "OPTIONS": {"transaction_mode": "IMMEDIATE", "timeout": 20},
        }
    }

AUTH_USER_MODEL = "accounts.User"
AUTHENTICATION_BACKENDS = ["apps.accounts.backends.EmailBackend"]
LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "core:home_redirect"
LOGOUT_REDIRECT_URL = "core:landing"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 10}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2SHA1PasswordHasher",
]
if TESTING:
    PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"] + PASSWORD_HASHERS

LANGUAGE_CODE = "es-mx"
TIME_ZONE = "America/Mexico_City"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
        if (DEBUG or TESTING)
        else "whitenoise.storage.CompressedManifestStaticFilesStorage"
    },
}
WHITENOISE_USE_FINDERS = True

# Adjuntos privados: fuera de STATIC y sin URL pública; se descargan por una vista autenticada.
PRIVATE_MEDIA_ROOT = Path(os.environ.get("NEXTPOINT_PRIVATE_MEDIA", BASE_DIR / "media_private"))
FILE_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024
# En serverless el disco es efímero: los adjuntos se guardan en la base (bytea).
ATTACHMENTS_IN_DB = env_bool("NEXTPOINT_ATTACHMENTS_IN_DB", ON_VERCEL)
# Vercel limita el cuerpo de la petición a 4.5 MB.
MAX_UPLOAD_MB = int(os.environ.get("NEXTPOINT_MAX_UPLOAD_MB", 4 if ON_VERCEL else 5))
DATA_UPLOAD_MAX_MEMORY_SIZE = 6 * 1024 * 1024

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Sesiones y cookies
SESSION_COOKIE_AGE = int(os.environ.get("NEXTPOINT_SESSION_SECONDS", 60 * 60 * 2))  # 2 h de inactividad
SESSION_SAVE_EVERY_REQUEST = True
SESSION_EXPIRE_AT_BROWSER_CLOSE = True
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"
SECURE_COOKIES = env_bool("NEXTPOINT_SECURE_COOKIES", ON_VERCEL)  # activar al servir por HTTPS
SESSION_COOKIE_SECURE = SECURE_COOKIES
CSRF_COOKIE_SECURE = SECURE_COOKIES
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"
if SECURE_COOKIES:
    SECURE_HSTS_SECONDS = 60 * 60 * 24 * 30

MESSAGE_STORAGE = "django.contrib.messages.storage.session.SessionStorage"

# Correo: el prototipo NO usa SMTP externo. Los correos (recuperación de acceso) se imprimen en consola.
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
DEFAULT_FROM_EMAIL = "NextPoint (demo) <no-reply@nextpoint.test>"
PASSWORD_RESET_TIMEOUT = 60 * 30  # 30 minutos, token de un solo uso

NEXTPOINT_VERSION = "1.0.0-prototipo"
NEXTPOINT_SHOW_DEMO_ACCOUNTS = env_bool("NEXTPOINT_SHOW_DEMO_ACCOUNTS", True)

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {"trace": {"()": "apps.core.logging.TraceIdFilter"}},
    "formatters": {"json": {"()": "apps.core.logging.JsonFormatter"}},
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "json", "filters": ["trace"]},
    },
    "root": {"handlers": ["console"], "level": "WARNING"},
    "loggers": {
        "nextpoint": {"handlers": ["console"], "level": os.environ.get("NEXTPOINT_LOG_LEVEL", "WARNING"), "propagate": False},
        "django.request": {"handlers": ["console"], "level": "ERROR", "propagate": False},
    },
}
