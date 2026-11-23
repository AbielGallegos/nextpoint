"""E2E-01 (préstamo completo), E2E-07 (último ejemplar) y TC-016…TC-024."""
import threading
import uuid
from datetime import timedelta
from unittest import skipUnless

from django.db import connection
from django.test import TransactionTestCase
from django.utils import timezone

from apps.catalog.models import Resource, ResourceUnit
from apps.communications.models import Notification
from apps.core.errors import DomainError
from apps.loans import services
from apps.loans.models import Loan, LoanRequest

from .base import DemoTestCase, load_demo


def kit():
    return Resource.objects.get(code="KIT-RED-01")


class LoanFlowTests(DemoTestCase):
    def test_e2e01_full_loan_flow_inventory_available_busy_available(self):
        student = self.login("alumno.demo1")
        r = kit()
        self.assertEqual(r.availability()["label"], "Disponible")
        # Catálogo → ficha → solicitud
        self.assertContains(student.get("/app/materiales/"), "Kit de redes de laboratorio")
        self.assertContains(student.get(f"/app/materiales/{r.pk}/"), "Solicitar préstamo")
        today = timezone.localdate()
        resp = student.post(f"/app/materiales/{r.pk}/solicitar/", {"start_date": today.isoformat(), "due_date": (today + timedelta(days=2)).isoformat(),
                                                                   "purpose": "Práctica de redes (demostración)", "idempotency_key": str(uuid.uuid4())})
        req = LoanRequest.objects.get(applicant__email="alumno.demo1@nextpoint.test", resource=r)
        self.assertRedirects(resp, f"/app/prestamos/{req.pk}/")
        self.assertRegex(req.folio, r"^NP-PRE-\d{5}$")
        self.assertEqual(req.status, "solicitado")
        # Gestor recibe notificación y aprueba
        manager = self.login("gestor.laboratorio")
        self.assertTrue(Notification.objects.filter(recipient__email="gestor.laboratorio@nextpoint.test", title__contains=req.folio).exists())
        self.assertContains(manager.get("/panel/prestamos/"), req.folio)
        manager.post(f"/panel/prestamos/{req.pk}/approve/", {"note": "Recoger en ventanilla"})
        req.refresh_from_db()
        self.assertEqual(req.status, "aprobado")
        self.assertIsNotNone(req.unit)
        self.assertTrue(Notification.objects.filter(recipient=req.applicant, title__startswith="Préstamo aprobado").exists())
        # Entrega → ocupado
        manager.post(f"/panel/prestamos/{req.pk}/deliver/", {"condition": "bueno"})
        req.refresh_from_db()
        self.assertEqual(req.status, "entregado")
        self.assertEqual(ResourceUnit.objects.get(pk=req.unit_id).state, "prestado")
        self.assertEqual(kit().availability()["label"], "Ocupado")
        self.assertContains(student.get(f"/app/prestamos/{req.pk}/"), "Entregado")
        # Devolución → disponible
        manager.post(f"/panel/prestamos/{req.pk}/return/", {"condition": "bueno", "destination": "disponible"})
        req.refresh_from_db()
        self.assertEqual(req.status, "devuelto")
        self.assertEqual(kit().availability()["label"], "Disponible")
        # Historial completo y auditoría
        self.assertEqual([e.status_after for e in req.events.all()], ["solicitado", "aprobado", "entregado", "devuelto"])
        from apps.audit.models import AuditLog

        self.assertEqual(AuditLog.objects.filter(target_type="loanrequest", target_id=str(req.pk)).count(), 4)
        self.assertEqual(req.movements.count(), 3)

    def test_tc020_damaged_return_goes_to_maintenance(self):
        a1, gl = self.user("alumno.demo1"), self.user("gestor.laboratorio")
        today = timezone.localdate()
        req, _ = services.create_request(a1, kit().pk, today, today, "Práctica dañada", uuid.uuid4())
        services.approve(gl, req.pk)
        services.deliver(gl, req.pk, "bueno")
        with self.assertRaises(DomainError):
            services.register_return(gl, req.pk, "danado", "disponible", "Conector roto")
        services.register_return(gl, req.pk, "danado", "mantenimiento", "Conector roto")
        self.assertEqual(kit().availability()["label"], "Sin existencias")
        # Sin ejemplares en servicio: no se puede solicitar
        with self.assertRaises(DomainError) as ctx:
            services.create_request(self.user("alumna.demo2"), kit().pk, today, today, "Otra práctica", uuid.uuid4())
        self.assertEqual(ctx.exception.code, "RESOURCE_UNAVAILABLE")

    def test_tc035_double_submit_same_folio(self):
        a1 = self.user("alumno.demo1")
        today = timezone.localdate()
        key = uuid.uuid4()
        r1, c1 = services.create_request(a1, kit().pk, today, today, "Práctica de redes", key)
        r2, c2 = services.create_request(a1, kit().pk, today, today, "Práctica de redes", key)
        self.assertEqual(r1.pk, r2.pk)
        self.assertTrue(c1)
        self.assertFalse(c2)

    def test_duplicate_open_request_rejected(self):
        a1 = self.user("alumno.demo1")
        today = timezone.localdate()
        services.create_request(a1, kit().pk, today, today, "Práctica de redes", uuid.uuid4())
        with self.assertRaises(DomainError) as ctx:
            services.create_request(a1, kit().pk, today, today, "Práctica de redes", uuid.uuid4())
        self.assertEqual(ctx.exception.code, "DUPLICATE_REQUEST")

    def test_validation_dates_and_max_days(self):
        a1 = self.user("alumno.demo1")
        today = timezone.localdate()
        with self.assertRaises(DomainError) as ctx:
            services.create_request(a1, kit().pk, today - timedelta(days=1), today, "Práctica", uuid.uuid4())
        self.assertIn("start_date", ctx.exception.fields)
        with self.assertRaises(DomainError) as ctx:
            services.create_request(a1, kit().pk, today, today + timedelta(days=10), "Práctica", uuid.uuid4())
        self.assertIn("due_date", ctx.exception.fields)

    def test_tc017_second_approval_of_single_unit_rejected(self):
        a1, a2, gl = self.user("alumno.demo1"), self.user("alumna.demo2"), self.user("gestor.laboratorio")
        a2_open = LoanRequest.objects.filter(applicant=a2, status__in=LoanRequest.OPEN_STATES)
        for r in a2_open:  # liberar cupo de solicitudes de la alumna 2
            if r.status == "solicitado":
                services.cancel_by_applicant(a2, r.pk)
        today = timezone.localdate()
        r1, _ = services.create_request(a1, kit().pk, today, today + timedelta(days=1), "Práctica A", uuid.uuid4())
        r2, _ = services.create_request(a2, kit().pk, today + timedelta(days=1), today + timedelta(days=2), "Práctica B", uuid.uuid4())
        services.approve(gl, r1.pk)
        with self.assertRaises(DomainError) as ctx:
            services.approve(gl, r2.pk)
        self.assertEqual(ctx.exception.code, "RESOURCE_UNAVAILABLE")
        self.assertEqual(LoanRequest.objects.get(pk=r2.pk).status, "solicitado")
        # Fechas compatibles sí pueden aprobarse
        r3, _ = services.create_request(a1, Resource.objects.get(code="PROY-01").pk, today, today, "Exposición", uuid.uuid4())
        services.approve(gl, r3.pk)

    def test_tc023_cancelled_cannot_be_delivered(self):
        a1, gl = self.user("alumno.demo1"), self.user("gestor.laboratorio")
        today = timezone.localdate()
        req, _ = services.create_request(a1, kit().pk, today, today, "Práctica", uuid.uuid4())
        services.approve(gl, req.pk)
        services.cancel_by_applicant(a1, req.pk)
        with self.assertRaises(DomainError) as ctx:
            services.deliver(gl, req.pk, "bueno")
        self.assertEqual(ctx.exception.code, "INVALID_TRANSITION")
        self.assertEqual(kit().availability()["available"], 1)

    def test_no_self_approval(self):
        from apps.accounts.models import Role, StudentProfile, UserRole

        gl = self.user("gestor.laboratorio")
        UserRole.objects.create(user=gl, role=Role.objects.get(code="estudiante"), campus=gl.campus)
        StudentProfile.objects.create(user=gl)
        today = timezone.localdate()
        req, _ = services.create_request(gl, kit().pk, today, today, "Uso propio", uuid.uuid4())
        with self.assertRaises(DomainError) as ctx:
            services.approve(gl, req.pk)
        self.assertEqual(ctx.exception.code, "PERMISSION_DENIED")

    def test_student_cannot_change_stock_via_form_fields(self):
        c = self.login("alumno.demo1")
        unit = kit().units.first()
        c.post(f"/panel/recursos/{kit().pk}/ejemplares/{unit.pk}/estado/", {"state": "baja", "note": "hack hack"})
        self.assertEqual(ResourceUnit.objects.get(pk=unit.pk).state, "disponible")

    def test_db_constraint_one_active_loan_per_unit(self):
        from django.db import IntegrityError, transaction

        a1, gl = self.user("alumno.demo1"), self.user("gestor.laboratorio")
        today = timezone.localdate()
        req, _ = services.create_request(a1, kit().pk, today, today, "Práctica", uuid.uuid4())
        services.approve(gl, req.pk)
        services.deliver(gl, req.pk, "bueno")
        other = LoanRequest.objects.exclude(pk=req.pk).filter(loan__isnull=True).first()
        with self.assertRaises(IntegrityError), transaction.atomic():
            Loan.objects.create(request=other, unit=req.unit, delivered_at=timezone.now(), delivered_by=gl, delivery_condition="bueno", due_date=today)

    def test_tc024_empty_search_state(self):
        c = self.login("alumno.demo1")
        self.assertContains(c.get("/app/materiales/", {"q": "zzz-inexistente"}), "No encontramos materiales")

    def test_dashboard_counters_match_lists(self):
        c = self.login("alumno.demo1")
        before = c.get("/app/").context["open_cases_count"]
        from apps.cases.models import ServiceCategory

        cat = ServiceCategory.objects.filter(campus__code="C2", kind="consulta").first()
        c.post("/app/solicitudes/nueva/", {"category": cat.pk, "subject": "Consulta de procedimiento de préstamo", "description": "¿Cuál es el procedimiento?",
                                           "priority": "normal", "idempotency_key": str(uuid.uuid4())})
        after = c.get("/app/").context["open_cases_count"]
        self.assertEqual(after, before + 1)
        self.assertEqual(c.get("/app/solicitudes/").context["counts"]["abiertas"], after)


@skipUnless(connection.vendor == "postgresql", "Prueba concurrente real: requiere PostgreSQL")
class ConcurrencyTests(TransactionTestCase):
    """E2E-07 / NFR-02: dos gestores aprueban casi al mismo tiempo el último ejemplar."""

    def test_e2e07_parallel_approvals_only_one_wins(self):
        load_demo(history=False)
        from apps.accounts.models import Role, User, UserRole

        a1 = User.objects.get(email="alumno.demo1@nextpoint.test")
        a2 = User.objects.get(email="alumna.demo2@nextpoint.test")
        gl = User.objects.get(email="gestor.laboratorio@nextpoint.test")
        gl2 = User.objects.create_user("gestor.lab2@nextpoint.test", "Clave-Muy-Segura-91", display_name="Gestor 2", campus=gl.campus)
        UserRole.objects.create(user=gl2, role=Role.objects.get(code="gestor"), area=kit().area)
        today = timezone.localdate()
        r1, _ = services.create_request(a1, kit().pk, today, today + timedelta(days=1), "Práctica A", uuid.uuid4())
        r2, _ = services.create_request(a2, kit().pk, today, today + timedelta(days=1), "Práctica B", uuid.uuid4())
        barrier = threading.Barrier(2)
        outcomes = []

        def worker(actor, req_id):
            from django.db import connection as conn

            barrier.wait()
            try:
                services.approve(actor, req_id)
                outcomes.append("ok")
            except DomainError as e:
                outcomes.append(e.code)
            finally:
                conn.close()

        threads = [threading.Thread(target=worker, args=(gl, r1.pk)), threading.Thread(target=worker, args=(gl2, r2.pk))]
        [t.start() for t in threads]
        [t.join() for t in threads]
        self.assertEqual(sorted(outcomes), ["RESOURCE_UNAVAILABLE", "ok"])
        self.assertEqual(LoanRequest.objects.filter(resource=kit(), status="aprobado").count(), 1)
