"""Control de acceso de NextPoint.

RBAC: cada rol tiene permisos (tablas Role/Permission/RolePermission).
ABAC: cada asignación UserRole tiene un alcance (área, campus o global) que limita QUÉ registros
se pueden tocar. Además, los registros propios se filtran por owner (creator/applicant) y
assigned_to. Todo se verifica en el servidor; la interfaz solo oculta lo que el servidor ya niega.
"""
from dataclasses import dataclass, field
from functools import wraps

from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied
from django.db.models import Q

# ---------------------------------------------------------------------------
# Catálogo maestro de roles y permisos (se carga en BD con una migración de datos)
# ---------------------------------------------------------------------------
ROLES = [
    # code, nombre, descripción, privilegiado, orden
    ("estudiante", "Estudiante", "Explora recursos, solicita materiales, sigue sus casos, cursos y avisos.", False, 1),
    ("docente", "Docente / instructor", "Prepara cursos (requieren aprobación) y atiende casos asignados.", True, 2),
    ("gestor", "Gestor de área", "Valida solicitudes, administra recursos y avisos de su área.", True, 3),
    ("coordinacion", "Coordinación institucional", "Supervisa áreas del campus, autoriza publicaciones y consulta métricas.", True, 4),
    ("soporte", "Soporte NextPoint", "Atiende tickets técnicos y salud del servicio; sin lectura de casos de alumnos.", True, 5),
    ("admin_plataforma", "Administrador de plataforma", "Usuarios, roles técnicos, parámetros, auditoría y salud.", True, 6),
]

PERMISSIONS = {
    # code: (módulo, descripción)
    "portal.student": ("portal", "Usar el portal del estudiante"),
    "panel.access": ("panel", "Entrar al panel administrativo"),
    "catalog.manage": ("catalog", "Crear y editar recursos, ejemplares y categorías de su alcance"),
    "loans.request": ("loans", "Solicitar préstamos propios"),
    "loans.manage": ("loans", "Revisar, aprobar, entregar y recibir préstamos de su alcance"),
    "loans.supervise": ("loans", "Consultar préstamos del campus (solo lectura)"),
    "cases.create": ("cases", "Crear solicitudes e incidencias propias"),
    "cases.manage": ("cases", "Clasificar, asignar, acusar, resolver y cerrar casos de su alcance"),
    "cases.attend_assigned": ("cases", "Responder casos asignados personalmente"),
    "cases.supervise": ("cases", "Consultar casos del campus (solo lectura)"),
    "smartmatch.use": ("smartmatch", "Consultar recomendaciones"),
    "smartmatch.test": ("smartmatch", "Probar reglas en el simulador"),
    "smartmatch.publish": ("smartmatch", "Publicar pesos y necesidades de SmartMatch"),
    "courses.enroll": ("courses", "Inscribirse y avanzar en cursos"),
    "courses.author": ("courses", "Crear y editar cursos propios en borrador"),
    "courses.publish": ("courses", "Validar y publicar cursos de su alcance"),
    "alerts.publish_area": ("alerts", "Crear y publicar avisos de su área"),
    "alerts.publish_campus": ("alerts", "Publicar avisos para todo el campus"),
    "alerts.publish_global": ("alerts", "Publicar avisos para toda la institución"),
    "reports.view": ("reports", "Consultar reportes de su alcance"),
    "reports.export": ("reports", "Exportar reportes (queda auditado)"),
    "users.view": ("users", "Consultar cuentas de su alcance (datos minimizados)"),
    "users.manage": ("users", "Invitar cuentas y asignar roles no técnicos en su campus"),
    "users.manage_technical": ("users", "Gestionar roles técnicos y cuentas de toda la plataforma"),
    "audit.view": ("audit", "Consultar la bitácora de su alcance"),
    "platform.health": ("platform", "Ver estado técnico del servicio"),
    "platform.config": ("platform", "Editar parámetros y políticas"),
    "support.attend": ("support", "Atender tickets de soporte técnico"),
}

ROLE_PERMISSIONS = {
    "estudiante": ["portal.student", "loans.request", "cases.create", "smartmatch.use", "courses.enroll"],
    "docente": ["panel.access", "courses.author", "cases.attend_assigned", "smartmatch.use"],
    "gestor": [
        "panel.access", "catalog.manage", "loans.manage", "cases.manage", "smartmatch.test", "courses.publish",
        "alerts.publish_area", "reports.view", "users.view", "audit.view",
    ],
    "coordinacion": [
        "panel.access", "loans.supervise", "cases.supervise", "smartmatch.test", "smartmatch.publish", "courses.publish",
        "alerts.publish_area", "alerts.publish_campus", "alerts.publish_global", "reports.view", "reports.export",
        "users.view", "users.manage", "audit.view", "platform.config",
    ],
    "soporte": ["panel.access", "platform.health", "support.attend"],
    "admin_plataforma": [
        "panel.access", "smartmatch.test", "smartmatch.publish", "users.view", "users.manage",
        "users.manage_technical", "audit.view", "platform.health", "platform.config", "support.attend",
    ],
}


# ---------------------------------------------------------------------------
# Alcance efectivo
# ---------------------------------------------------------------------------
@dataclass
class Scope:
    allowed: bool = False
    is_global: bool = False
    campus_ids: set = field(default_factory=set)
    area_ids: set = field(default_factory=set)

    def q(self, area_field="area_id", campus_field="campus_id"):
        """Filtro de queryset para registros dentro del alcance."""
        if not self.allowed:
            return Q(pk__in=[])
        if self.is_global:
            return Q()
        cond = Q(pk__in=[])
        if self.area_ids and area_field:
            cond |= Q(**{f"{area_field}__in": self.area_ids})
        if self.campus_ids and campus_field:
            cond |= Q(**{f"{campus_field}__in": self.campus_ids})
        return cond

    def covers(self, *, area_id=None, campus_id=None):
        if not self.allowed:
            return False
        if self.is_global:
            return True
        if area_id is not None and area_id in self.area_ids:
            return True
        if campus_id is not None and campus_id in self.campus_ids:
            return True
        return False


def _assignments(user):
    """[(role_code, campus_id, area_id, area_campus_id, perms:set)], cacheado en el objeto user por petición."""
    cache = getattr(user, "_np_assignments", None)
    if cache is not None:
        return cache
    from .models import RolePermission, UserRole

    rows = list(
        UserRole.objects.filter(user=user).select_related("role", "area").values_list(
            "role_id", "role__code", "campus_id", "area_id", "area__campus_id"
        )
    )
    role_ids = {r[0] for r in rows}
    perm_map = {}
    for role_id, code in RolePermission.objects.filter(role_id__in=role_ids).values_list("role_id", "permission__code"):
        perm_map.setdefault(role_id, set()).add(code)
    cache = [(r[1], r[2], r[3], r[4], perm_map.get(r[0], set())) for r in rows]
    user._np_assignments = cache
    return cache


def role_codes(user):
    if not user.is_authenticated:
        return set()
    return {a[0] for a in _assignments(user)}


def has_perm(user, perm: str) -> bool:
    if not user.is_authenticated or not user.is_active:
        return False
    return any(perm in a[4] for a in _assignments(user))


def scope_for(user, perm: str) -> Scope:
    scope = Scope()
    if not user.is_authenticated or not user.is_active:
        return scope
    for role_code, campus_id, area_id, area_campus_id, perms in _assignments(user):
        if perm not in perms:
            continue
        scope.allowed = True
        if area_id:
            scope.area_ids.add(area_id)
        elif campus_id:
            scope.campus_ids.add(campus_id)
        else:
            scope.is_global = True
    return scope


def can_on(user, perm: str, *, area_id=None, campus_id=None) -> bool:
    """¿El permiso aplica a un registro con este área/campus?"""
    scope = scope_for(user, perm)
    if area_id is not None and campus_id is None:
        from .models import Area

        campus_id = Area.objects.filter(pk=area_id).values_list("campus_id", flat=True).first()
    return scope.covers(area_id=area_id, campus_id=campus_id)


def managed_area_ids(user, perm: str):
    """Ids de áreas concretas sobre las que aplica el permiso (expande campus/global a sus áreas)."""
    from .models import Area

    scope = scope_for(user, perm)
    if not scope.allowed:
        return set()
    return set(Area.objects.filter(scope.q(area_field="id", campus_field="campus_id")).values_list("id", flat=True))


def is_student(user):
    return has_perm(user, "portal.student")


def is_staff_member(user):
    return has_perm(user, "panel.access")


# ---------------------------------------------------------------------------
# Decoradores de vistas
# ---------------------------------------------------------------------------
def require_perm(*perms, any_of=False):
    """Exige sesión y permiso. Sin sesión → login (AUTH_REQUIRED). Sin permiso → 403 (PERMISSION_DENIED)."""

    def decorator(view):
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            user = request.user
            if not user.is_authenticated:
                return redirect_to_login(request.get_full_path())
            checks = [has_perm(user, p) for p in perms]
            ok = any(checks) if any_of else all(checks)
            if not ok:
                from apps.audit.services import log_security

                log_security(request, "access.denied", detail={"path": request.path, "needed": list(perms)})
                raise PermissionDenied("PERMISSION_DENIED")
            return view(request, *args, **kwargs)

        return wrapped

    return decorator


student_required = require_perm("portal.student")
staff_required = require_perm("panel.access")
