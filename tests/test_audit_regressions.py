"""Regresiones de los hallazgos de la auditoría (ver docs/AUDITORIA.md)."""
import uuid
from datetime import timedelta

from django.contrib.sessions.models import Session
from django.test import Client
from django.utils import timezone

from apps.catalog.models import Resource, ResourceUnit
from apps.loans import services as loans
from apps.loans.models import LoanRequest

from .base import PW, DemoTestCase


class AuditRegressionTests(DemoTestCase):
    def test_f01_staff_no_dead_link_to_student_form(self):
        for who in ("gestor.laboratorio", "admin.demo", "coord.demo"):
            self.assertNotContains(self.login(who).get("/app/ayuda/"), "/app/solicitudes/nueva/")
        self.assertContains(self.login("alumno.demo1").get("/app/ayuda/"), "/app/solicitudes/nueva/")

    def test_f02_report_material_preselects_category_and_subject(self):
        st = self.login("alumno.demo1")
        req = LoanRequest.objects.filter(applicant__email="alumno.demo1@nextpoint.test").first()
        page = st.get(f"/app/prestamos/{req.pk}/")
        link = page.context["report_category"]
        self.assertEqual(link.kind, "reporte_recurso")
        form = st.get(f"/app/solicitudes/nueva/?categoria={link.pk}&asunto={req.folio}")
        self.assertEqual(form.context["preselected"], str(link.pk))
        self.assertContains(form, f'value="{req.folio}"')

    def test_f03_modality_filter_really_filters(self):
        st = self.login("alumno.demo1")
        r = st.get("/app/smartmatch/", {"category": "materiales", "tags": "redes", "modalidad": "en línea"})
        self.assertFalse(any(x.candidate.kind == "materiales" for x in r.context["results"]))
        r = st.get("/app/smartmatch/", {"category": "cursos", "tags": "redes", "modalidad": "en línea"})
        self.assertTrue(any(x.candidate.kind == "cursos" for x in r.context["results"]))

    def test_f04_topbar_search_only_with_case_inbox(self):
        self.assertNotContains(self.login("admin.demo").get("/panel/"), 'id="topsearch"')
        self.assertContains(self.login("gestor.servicios").get("/panel/"), 'id="topsearch"')

    def test_f05_rate_limit_per_ip_with_rotating_emails(self):
        c = Client()
        codes = [c.post("/acceso/", {"email": f"x{i}@nextpoint.test", "password": "mala-mala-1"}).status_code for i in range(21)]
        self.assertEqual(codes[-1], 429)
        r = c.post("/acceso/", {"email": "alumno.demo1@nextpoint.test", "password": PW})
        self.assertEqual(r.status_code, 429)

    def test_f06_csv_formula_injection_neutralized(self):
        kit = Resource.objects.get(code="MULT-01")
        Resource.objects.filter(pk=kit.pk).update(name='=HYPERLINK("http://evil.example","x")')
        coord = self.login("coord.demo")
        body = coord.get("/panel/informes/exportar/?tipo=prestamos").content.decode("utf-8-sig")
        self.assertIn("'=HYPERLINK", body)
        self.assertNotIn(',=HYPERLINK', body)

    def test_f09_simulator_sees_student_opportunities(self):
        gl = self.login("gestor.laboratorio")
        r = gl.get("/panel/smartmatch/", {"simular": "1", "category": "oportunidades", "tags": "convocatoria, taller"})
        self.assertTrue(any(x.candidate.kind == "oportunidades" for x in r.context["sim_results"]))

    def test_f08_warning_when_unit_with_reservation_goes_to_maintenance(self):
        a1, gl = self.user("alumno.demo1"), self.user("gestor.laboratorio")
        kit = Resource.objects.get(code="KIT-RED-01")
        today = timezone.localdate()
        req, _ = loans.create_request(a1, kit.pk, today, today, "Práctica de redes", uuid.uuid4())
        loans.approve(gl, req.pk)
        c = self.login("gestor.laboratorio")
        unit = ResourceUnit.objects.get(pk=LoanRequest.objects.get(pk=req.pk).unit_id)
        r = c.post(f"/panel/recursos/{kit.pk}/ejemplares/{unit.pk}/estado/", {"state": "mantenimiento", "note": "Switch dañado"}, follow=True)
        self.assertContains(r, req.folio)
        self.assertContains(r, "apartado")

    def test_f21_page_size_policy_per_campus_applies(self):
        coord = self.login("coord.demo")
        coord.post("/panel/configuracion/", {"key": "list_page_size", "value": "5"})
        r = coord.get("/panel/usuarios/")
        self.assertEqual(r.context["page"].paginator.per_page, 5)

    def test_tc010_expired_session_requires_login(self):
        c = self.login("alumno.demo1")
        Session.objects.filter(session_key=c.session.session_key).update(expire_date=timezone.now() - timedelta(seconds=1))
        r = c.get("/app/")
        self.assertEqual(r.status_code, 302)
        self.assertIn("/acceso/", r["Location"])

    def test_favicon(self):
        r = Client().get("/favicon.ico")
        self.assertEqual(r.status_code, 301)

    def test_satisfaction_average(self):
        from apps.cases.models import ServiceRequest

        ServiceRequest.objects.filter(status="cerrado").update(rating=4)
        r = self.login("coord.demo").get("/panel/informes/")
        self.assertEqual(r.context["cases"]["rating_avg"], 4.0)
