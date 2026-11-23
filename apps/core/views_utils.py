"""Utilidades de vistas: paginación, manejo uniforme de errores de dominio y lectura segura de parámetros."""
from datetime import date

from django.contrib import messages
from django.core.paginator import Paginator
from django.http import Http404

from .errors import DomainError
from .models import get_policy


def paginate(request, queryset, campus=None):
    if campus is None and getattr(request, "user", None) is not None and request.user.is_authenticated:
        campus = request.user.campus
    size = get_policy("list_page_size", campus)
    paginator = Paginator(queryset, size)
    try:
        page_number = max(1, int(request.GET.get("page", 1)))
    except ValueError:
        page_number = 1
    return paginator.get_page(page_number)


def domain_message(request, err: DomainError):
    text = err.message
    if err.fields and not err.message.startswith("Revisa"):
        pass
    messages.error(request, f"{text}")


def parse_date(value):
    try:
        return date.fromisoformat((value or "").strip())
    except ValueError:
        return None


def int_or_404(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        raise Http404


def int_or_none(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
