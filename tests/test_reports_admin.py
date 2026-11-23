"""E2E-08 y TC-057…TC-067, TC-076: KPIs reales, exportación auditada, semilla idempotente, respaldo."""
import uuid

from django.core.management import call_command
from django.test import TransactionTestCase

from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.cases import services
from apps.cases.models import ServiceCategory, ServiceRequest
from apps.catalog.models import Resource, ResourceUnit
from apps.loans.models import LoanRequest

from .base import DemoTestCase, PW, load_demo


class ReportTests(DemoTestCase):
    def test_tc057_kpi_matches_database(self):
        c = self.login("gestor.servicios")
        ctx = c.get("/panel/").context
        serv = ServiceRequest.objects.filter(area__code="SERV", area__campus__code="C2")
        self.assertEqual(ctx["cases"]["total"], serv.count())
        self.assertEqual(ctx["cases"]["new"], serv.filter(status__in=["nuevo", "clasificado", "asignado"]).count())
        queue = c.get("/panel/solicitudes/?estado=pendientes").context["counts"]["pendientes"]
        self.assertEqual(queue, ctx["cases"]["new"])
        # Al acusar, el KPI cambia al recargar
        case = serv.filter(status="nuevo").first()
        c.post(f"/panel/solicitudes/{case.pk}/acknowledge/")
        self.assertEqual(c.get("/panel/").context["cases"]["new"], ctx["cases"]["new"] - 1)

    def test_e2e08_report_and_export(self):
        a1, gs = User.objects.get(email="alumno.demo1@nextpoint.test"), User.objects.get(email="gestor.servicios@nextpoint.test")
        cat = ServiceCategory.objects.filter(campus__code="C2", area__code="SERV").first()
        for i in range(2):
            case, _ = services.create_request(a1, cat.pk, f"Caso de reporte {i}", "Descripción del caso", "normal", uuid.uuid4())
            services.staff_action(gs, case.pk, "acknowledge")
            services.staff_action(gs, case.pk, "resolve", body="Resolución del caso de reporte")
        coord = self.login("coord.demo")
        r = coord.get("/panel/informes/")
        total = ServiceRequest.objects.filter(campus__code="C2").count()
        self.assertEqual(r.context["cases"]["total"], total)
        resp = coord.get("/panel/informes/exportar/?tipo=solicitudes")
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode("utf-8-sig")
        self.assertEqual(len(body.strip().splitlines()) - 1, total)
        self.assertNotIn("@nextpoint.test", body)  # exportación minimizada
        self.assertTrue(AuditLog.objects.filter(action="report.exported").exists())

    def test_tc061_export_without_permission_denied(self):
        self.assertEqual(self.login("gestor.laboratorio").get("/panel/informes/exportar/").status_code, 403)

    def test_tc059_area_filter_no_leak(self):
        gl = self.login("gestor.laboratorio")
        r = gl.get("/panel/informes/")
        self.assertEqual(r.context["cases"]["total"], ServiceRequest.objects.filter(area__code="LAB", area__campus__code="C2").count())

    def test_tc064_edit_resource_audited(self):
        gl = self.login("gestor.laboratorio")
        res = Resource.objects.get(code="KIT-RED-01")
        r = gl.post(f"/panel/recursos/{res.pk}/editar/", {"name": "Kit de redes de laboratorio", "code": "KIT-RED-01", "category": res.category_id,
                                                          "area": res.area_id, "description": "Descripción actualizada", "status": "publicado",
                                                          "max_loan_days": 3, "tags_text": "redes, laboratorio"})
        self.assertEqual(r.status_code, 302)
        log = AuditLog.objects.filter(action="resource.updated", target_id=str(res.pk)).first()
        self.assertEqual(log.actor.email, "gestor.laboratorio@nextpoint.test")
        self.assertIn("description", log.detail["changed"])

    def test_publish_resource_without_units_blocked(self):
        gl = self.login("gestor.laboratorio")
        draft = Resource.objects.get(code="OSC-01")
        gl.post(f"/panel/recursos/{draft.pk}/editar/", {"name": draft.name, "code": "OSC-01", "category": draft.category_id, "area": draft.area_id,
                                                        "description": "x" * 10, "status": "publicado"})
        self.assertEqual(Resource.objects.get(pk=draft.pk).status, "borrador")

    def test_tc033_maintenance_blocks_loans(self):
        gl = self.login("gestor.laboratorio")
        res = Resource.objects.get(code="PROY-01")
        unit = res.units.get()
        gl.post(f"/panel/recursos/{res.pk}/ejemplares/{unit.pk}/estado/", {"state": "mantenimiento", "note": "Lámpara fundida"})
        self.assertEqual(ResourceUnit.objects.get(pk=unit.pk).state, "mantenimiento")
        self.assertEqual(res.availability()["operable"], 0)

    def test_audit_scoped_and_append_only(self):
        entry = AuditLog.objects.first()
        with self.assertRaises(ValueError):
            entry.save()
        with self.assertRaises(ValueError):
            entry.delete()
        gl = self.login("gestor.laboratorio")
        page = gl.get("/panel/auditoria/").context["page"]
        self.assertTrue(all(e.kind == "negocio" for e in page))
        self.assertEqual(self.login("alumno.demo1").get("/panel/auditoria/").status_code, 403)

    def test_tc065_empty_dataset_shows_no_invented_values(self):
        ServiceRequest.objects.all().delete()
        c = self.login("coord.demo")
        r = c.get("/panel/informes/")
        self.assertIsNone(r.context["cases"]["ack_rate"])
        self.assertIsNone(r.context["cases"]["close_rate"])
        self.assertContains(r, "Sin datos")


class SeedTests(DemoTestCase):
    def test_tc076_seed_is_idempotent(self):
        counts = (User.objects.count(), Resource.objects.count(), ResourceUnit.objects.count(), LoanRequest.objects.count(), ServiceRequest.objects.count())
        load_demo()
        self.assertEqual(counts, (User.objects.count(), Resource.objects.count(), ResourceUnit.objects.count(), LoanRequest.objects.count(), ServiceRequest.objects.count()))

    def test_reset_requires_confirmation(self):
        from django.core.management.base import CommandError

        with self.assertRaises(CommandError):
            call_command("reset_demo")


class BackupRestoreTests(TransactionTestCase):
    """TC-067 / NFR-07: respaldo y restauración (fuera de transacción, como en uso real)."""

    def test_tc067_backup_restore_roundtrip(self):
        import os
        import tempfile

        load_demo()
        path = os.path.join(tempfile.mkdtemp(), "b.json")
        call_command("backup_demo", output=path, verbosity=0)
        n = LoanRequest.objects.count()
        LoanRequest.objects.filter(status="solicitado").update(purpose="modificado")
        call_command("restore_demo", path, yes=True, verbosity=0)
        self.assertEqual(LoanRequest.objects.count(), n)
        self.assertFalse(LoanRequest.objects.filter(purpose="modificado").exists())
        from django.test import Client

        self.assertEqual(Client().post("/acceso/", {"email": "alumno.demo1@nextpoint.test", "password": PW}).status_code, 302)

