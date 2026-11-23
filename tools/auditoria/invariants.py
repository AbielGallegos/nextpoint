"""Consistencia de la base de datos y de los estados de proceso (se ejecuta sobre la BD tras la auditoría)."""
import os
import sys

sys.path.insert(0, "/home/claude/nextpoint")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
import django  # noqa: E402

django.setup()
from collections import Counter  # noqa: E402

from apps.audit.models import AuditLog  # noqa: E402
from apps.cases.models import RequestEvent, ServiceRequest  # noqa: E402
from apps.catalog.models import InventoryMovement, Resource, ResourceUnit  # noqa: E402
from apps.communications.models import Notification  # noqa: E402
from apps.learning.models import Enrollment, LessonProgress  # noqa: E402
from apps.loans.models import Loan, LoanRequest  # noqa: E402

F, OK = [], []


def chk(cond, msg, detail=""):
    (OK if cond else F).append(msg)
    print(("OK    " if cond else "FALLA ") + msg + (f" → {detail}" if not cond and detail else ""))


# Inventario ↔ préstamos
bad = [u.serial for u in ResourceUnit.objects.all() if (u.state == "prestado") != Loan.objects.filter(unit=u, returned_at__isnull=True).exists()]
chk(not bad, f"Ejemplar 'prestado' ⇔ préstamo activo ({ResourceUnit.objects.count()} ejemplares)", bad)
bad = [r.folio for r in LoanRequest.objects.filter(status="entregado") if not Loan.objects.filter(request=r, returned_at__isnull=True).exists()]
chk(not bad, "Toda solicitud 'entregado' tiene préstamo abierto", bad)
bad = [r.folio for r in LoanRequest.objects.filter(status="devuelto") if not Loan.objects.filter(request=r, returned_at__isnull=False).exists()]
chk(not bad, "Toda solicitud 'devuelto' tiene devolución registrada", bad)
bad = [r.folio for r in LoanRequest.objects.filter(status__in=["aprobado", "entregado"], unit__isnull=True)]
chk(not bad, "Aprobados/entregados tienen ejemplar asignado", bad)
bad = [r.folio for r in LoanRequest.objects.filter(status__in=["solicitado", "en_revision", "rechazado", "cancelado"], unit__isnull=False)]
chk(not bad, "Solicitudes sin aprobar/canceladas no retienen ejemplar", bad)
overl = []
for u in ResourceUnit.objects.all():
    rs = list(LoanRequest.objects.filter(unit=u, status__in=["aprobado", "entregado"]).order_by("start_date"))
    for a, b in zip(rs, rs[1:]):
        if b.start_date <= a.due_date:
            overl.append((u.serial, a.folio, b.folio))
chk(not overl, "Sin apartados traslapados por ejemplar (no sobreasignación)", overl)
bad = [r.folio for r in LoanRequest.objects.all() if (last := r.events.order_by("-created_at", "-id").first()) is None or last.status_after != r.status]
chk(not bad, f"Último evento = estado actual en {LoanRequest.objects.count()} préstamos", bad)
bad = [r.folio for r in LoanRequest.objects.all() if r.campus_id != r.area.campus_id or r.resource.area_id != r.area_id]
chk(not bad, "Campus/área de préstamos coherentes con el recurso", bad)
c = Counter(LoanRequest.objects.values_list("folio", flat=True)) + Counter(ServiceRequest.objects.values_list("folio", flat=True))
chk(all(v == 1 for v in c.values()) and all(f for f in c), "Folios únicos y no vacíos")
bad = [m.pk for m in InventoryMovement.objects.filter(kind="entrega") if not m.loan_request_id]
chk(not bad, "Movimientos de entrega ligados a su folio", bad)

# Casos
def last_status(r):
    e = r.events.filter(kind__in=["estado", "creado"]).order_by("-created_at", "-id").first()
    return e.status_after if e else None


bad = [r.folio for r in ServiceRequest.objects.all() if last_status(r) != r.status]
chk(not bad, f"Último evento de estado = estado actual en {ServiceRequest.objects.count()} casos", bad)
bad = [r.folio for r in ServiceRequest.objects.all() if (r.acknowledged_at is not None) != r.events.filter(status_after="acusado").exists()]
chk(not bad, "acknowledged_at ⇔ existe evento de acuse", bad)
bad = [r.folio for r in ServiceRequest.objects.filter(status__in=["cerrado", "rechazado", "cancelado"], closed_at__isnull=True)]
bad += [r.folio for r in ServiceRequest.objects.exclude(status__in=["cerrado", "rechazado", "cancelado"]).filter(closed_at__isnull=False)]
chk(not bad, "closed_at solo en estados finales", bad)
bad = [r.folio for r in ServiceRequest.objects.filter(status__in=["resuelto"], resolution="")]
chk(not bad, "Casos resueltos tienen resolución documentada", bad)
bad = [r.folio for r in ServiceRequest.objects.all() if r.area_id != r.category.area_id or r.campus_id != r.area.campus_id]
chk(not bad, "Área del caso = área de su categoría", bad)
bad = [r.folio for r in ServiceRequest.objects.filter(rating__isnull=False).exclude(status="cerrado")]
chk(not bad, "Valoraciones solo en casos cerrados", bad)

# Formación
bad = [e.pk for e in Enrollment.objects.all() if not 0 <= e.progress() <= 100 or (e.status == "completada") != (e.progress() == 100)]
chk(not bad, "Progreso 0–100 y 'completada' ⇔ 100 %", bad)
bad = [p.pk for p in LessonProgress.objects.select_related("lesson__module", "enrollment") if p.lesson.module.course_id != p.enrollment.course_id]
chk(not bad, "Progreso solo en lecciones del propio curso", bad)

# Comunicación y auditoría
chk(Notification.objects.values("dedupe_key").distinct().count() == Notification.objects.count(), "Notificaciones sin duplicados (dedupe_key)")
from apps.loans.models import LoanEvent  # noqa: E402

chk(AuditLog.objects.filter(target_type="loanrequest", action__startswith="loan.").count() == LoanEvent.objects.count(),
    "Cada transición de préstamo tiene su registro de auditoría")
chk(AuditLog.objects.filter(target_type="servicerequest", action__startswith="case.", kind="negocio").exclude(action__in=["case.assignment", "case.attachment_downloaded"]).count()
    >= RequestEvent.objects.filter(kind__in=["estado", "creado"]).count(), "Cada transición de caso tiene auditoría")
bad = [r.code for r in Resource.objects.filter(status="publicado") if not r.units.exists()]
chk(not bad, "Ningún recurso publicado sin ejemplares", bad)
print(f"\n{len(OK)} OK · {len(F)} fallas")
