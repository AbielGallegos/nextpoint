"""Etiquetas de plantilla compartidas: iconos, estados (color + texto + icono), campos accesibles."""
from django import template
from django.utils.html import escape, format_html, format_html_join
from django.utils.safestring import mark_safe

register = template.Library()

# estado → (tono, icono). El texto siempre acompaña al color (no depender solo del color).
STATUS_STYLE = {
    # préstamos
    "solicitado": ("info", "send"), "en_revision": ("brand", "eye"), "aprobado": ("ok", "check"), "rechazado": ("danger", "ban"),
    "cancelado": ("off", "x"), "entregado": ("warn", "package"), "devuelto": ("ok", "check-circle-2"), "cerrado": ("off", "lock"),
    # casos
    "nuevo": ("info", "inbox"), "clasificado": ("brand", "tag"), "asignado": ("brand", "user"), "acusado": ("brand", "mail"),
    "en_proceso": ("warn", "refresh-cw"), "requiere_info": ("warn", "circle-help"), "resuelto": ("ok", "check-circle-2"),
    # inventario
    "disponible": ("ok", "check-circle-2"), "prestado": ("warn", "package"), "revision": ("warn", "eye"),
    "mantenimiento": ("danger", "wrench"), "baja": ("off", "ban"),
    # publicación
    "borrador": ("off", "edit-3"), "publicado": ("ok", "check-circle-2"), "retirado": ("off", "ban"), "archivado": ("off", "lock"),
    "fuera_servicio": ("danger", "wrench"), "vigente": ("ok", "check-circle-2"), "programado": ("info", "clock"), "expirado": ("off", "clock"),
    # cuentas, tickets, reglas
    "activo": ("ok", "check-circle-2"), "pendiente": ("info", "clock"), "suspendido": ("danger", "ban"), "desactivado": ("off", "ban"),
    "atendiendo": ("warn", "refresh-cw"), "activa": ("ok", "check-circle-2"), "retirada": ("off", "lock"), "completada": ("ok", "trophy"),
    "aceptada": ("ok", "check"), "vencida": ("off", "clock"), "revocada": ("off", "ban"),
    # prioridades
    "alta": ("warn", "flag"), "critica": ("danger", "alert-triangle"), "normal": ("off", "flag"), "baja": ("off", "flag"),
}

STUDENT_LABELS = {"acusado": "Recibido", "en_revision": "En revisión"}


@register.simple_tag
def icon(name, extra=""):
    cls = "i" + (f" {extra}" if extra else "")
    return format_html('<svg class="{}" aria-hidden="true" focusable="false"><use href="#i-{}"></use></svg>', cls, name)


@register.simple_tag
def badge(value, label=None, tone=None):
    style = STATUS_STYLE.get(value, ("off", "circle"))
    tone = tone or style[0]
    text = label or STUDENT_LABELS.get(value) or str(value).replace("_", " ").capitalize()
    return format_html('<span class="badge t-{}">{}{}</span>', tone, icon(style[1]), text)


@register.simple_tag
def status(obj, field="status"):
    value = getattr(obj, field)
    display = getattr(obj, f"get_{field}_display", lambda: value)()
    return badge(value, display)


@register.filter
def tone(value):
    return STATUS_STYLE.get(value, ("off", ""))[0]


@register.inclusion_tag("partials/field.html")
def field(bound, help_text=None, wide=False):
    widget = bound.field.widget
    css = {"Select": "select", "Textarea": "textarea", "SelectMultiple": "select"}.get(widget.__class__.__name__, "input")
    attrs = {"class": css}
    if bound.errors:
        attrs["aria-invalid"] = "true"
        attrs["aria-describedby"] = f"{bound.auto_id}_error"
    elif help_text or bound.help_text:
        attrs["aria-describedby"] = f"{bound.auto_id}_help"
    is_check = widget.input_type == "checkbox" if hasattr(widget, "input_type") else False
    if is_check:
        attrs = {k: v for k, v in attrs.items() if k != "class"}
    return {"f": bound, "widget": bound.as_widget(attrs=attrs), "help": help_text or bound.help_text, "wide": wide, "is_check": is_check}


@register.filter
def paragraphs(text):
    """Convierte texto plano en párrafos, viñetas ('- ') y subtítulos ('## '), escapando todo el contenido."""
    blocks = [b.strip("\n") for b in (text or "").replace("\r\n", "\n").split("\n\n") if b.strip()]
    out = []
    for block in blocks:
        lines = block.split("\n")
        if all(l.strip().startswith("- ") for l in lines):
            out.append("<ul>" + "".join(f"<li>{escape(l.strip()[2:])}</li>" for l in lines) + "</ul>")
        elif lines[0].startswith("## "):
            out.append(f"<h3>{escape(lines[0][3:])}</h3>")
            if len(lines) > 1:
                out.append(f"<p>{escape(' '.join(lines[1:]))}</p>")
        else:
            out.append("<p>" + "<br>".join(escape(l) for l in lines) + "</p>")
    return mark_safe("".join(out))


@register.simple_tag(takes_context=True)
def nav_current(context, *prefixes):
    path = context["request"].path
    for p in prefixes:
        if p.startswith("="):
            if path == p[1:]:
                return mark_safe('aria-current="page"')
            continue
        if p == path or (p.endswith("/") and path.startswith(p) and len(p) > 1):
            return mark_safe('aria-current="page"')
    return ""


@register.filter
def get_item(d, key):
    try:
        return d.get(key)
    except AttributeError:
        return None


@register.filter
def pct(value, total):
    try:
        return round(int(value) * 100 / int(total)) if int(total) else 0
    except (TypeError, ValueError):
        return 0


@register.simple_tag
def tags_list(tags, hits=()):
    hits = set(hits or ())
    return format_html_join(" ", '<span class="tag{}">{}</span>', ((" hit" if t in hits else "", t) for t in (tags or [])))


@register.simple_tag(takes_context=True)
def qs(context, **kwargs):
    """Conserva los filtros actuales en enlaces de paginación."""
    params = context["request"].GET.copy()
    for k, v in kwargs.items():
        if v in (None, ""):
            params.pop(k, None)
        else:
            params[k] = v
    return "?" + params.urlencode() if params else "?"
