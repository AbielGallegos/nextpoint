"""Catálogo administrable, soporte técnico, políticas y banderas de módulo (TC‑011…016, TC‑021, P1)."""
from apps.catalog.models import Resource, ResourceCategory
from apps.core.models import SupportTicket

from .base import DemoTestCase


class AdminMiscTests(DemoTestCase):
    def test_tc011_category_appears_in_filters(self):
        gl = self.login("gestor.laboratorio")
        gl.post("/panel/recursos/categorias/", {"name": "Robótica", "slug": "robotica", "icon": "zap"})
        self.assertTrue(ResourceCategory.objects.filter(slug="robotica").exists())
        self.assertContains(self.login("alumno.demo1").get("/app/materiales/"), "Robótica")

    def test_tc012_to_015_create_publish_unpublish_resource(self):
        gl = self.login("gestor.laboratorio")
        cat = ResourceCategory.objects.get(slug="redes", campus__code="C2")
        from apps.accounts.models import Area

        area = Area.objects.get(code="LAB", campus__code="C2")
        gl.post("/panel/recursos/nuevo/", {"name": "Probador de cables", "code": "PROB-01", "category": cat.pk, "area": area.pk,
                                          "description": "Probador de continuidad", "status": "borrador", "tags_text": "redes"})
        res = Resource.objects.get(code="PROB-01")
        student = self.login("alumno.demo1")
        self.assertNotContains(student.get("/app/materiales/"), "Probador de cables")
        gl.post(f"/panel/recursos/{res.pk}/ejemplares/", {"serial": "pb-0001", "condition": "bueno"})
        self.assertEqual(res.units.get().serial, "PB-0001")
        data = {"name": "Probador de cables", "code": "PROB-01", "category": cat.pk, "area": area.pk, "description": "Probador de continuidad",
                "status": "publicado", "tags_text": "redes"}
        gl.post(f"/panel/recursos/{res.pk}/editar/", data)
        self.assertContains(student.get("/app/materiales/"), "Probador de cables")
        self.assertEqual(Resource.objects.get(pk=res.pk).availability()["available"], 1)  # TC-016
        data["status"] = "fuera_servicio"
        gl.post(f"/panel/recursos/{res.pk}/editar/", data)
        self.assertNotContains(student.get("/app/materiales/"), "Probador de cables")
        self.assertEqual(student.get(f"/app/materiales/{res.pk}/").status_code, 404)

    def test_manager_cannot_edit_other_campus_resource(self):
        gl = self.login("gestor.laboratorio")
        other = Resource.objects.get(code="KIT-RED-C1")
        self.assertEqual(gl.get(f"/panel/recursos/{other.pk}/").status_code, 403)

    def test_support_ticket_flow_and_internal_notes(self):
        s = self.login("alumno.demo1")
        s.post("/app/ayuda/", {"category": "cuenta", "subject": "No veo mi curso", "description": "Al entrar a cursos no aparece mi avance."})
        t = SupportTicket.objects.get(subject="No veo mi curso")
        self.assertRegex(t.folio, r"^NP-SOP-\d{5}$")
        admin = self.login("admin.demo")
        admin.post(f"/app/ayuda/tickets/{t.pk}/", {"action": "take"})
        admin.post(f"/app/ayuda/tickets/{t.pk}/", {"action": "message", "body": "NOTA-INTERNA-SOPORTE", "internal": "1"})
        admin.post(f"/app/ayuda/tickets/{t.pk}/", {"action": "resolve", "body": "Se recargó la caché del navegador."})
        self.assertEqual(SupportTicket.objects.get(pk=t.pk).status, "resuelto")
        self.assertNotContains(s.get(f"/app/ayuda/tickets/{t.pk}/"), "NOTA-INTERNA-SOPORTE")
        self.assertEqual(self.login("alumna.demo2").get(f"/app/ayuda/tickets/{t.pk}/").status_code, 404)

    def test_policy_versioned_and_module_flag(self):
        coord = self.login("coord.demo")
        coord.post("/panel/configuracion/", {"key": "module_courses_enabled", "value": "0"})
        self.assertEqual(self.login("alumno.demo1").get("/app/cursos/").status_code, 503)
        coord.post("/panel/configuracion/", {"key": "max_loan_days", "value": "999"})  # fuera de rango
        from apps.core.models import SystemPolicy

        self.assertFalse(SystemPolicy.objects.filter(key="max_loan_days").exists())
        coord.post("/panel/configuracion/", {"key": "payments_enabled", "value": "1"})
        self.assertFalse(SystemPolicy.objects.filter(key="payments_enabled").exists())
        self.assertEqual(self.login("gestor.laboratorio").get("/panel/configuracion/").status_code, 403)
