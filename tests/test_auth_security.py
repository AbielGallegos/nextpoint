"""E2E-06 y casos TC-001…TC-010, TC-072…TC-074: autenticación, autorización y aislamiento."""
from django.test import Client

from apps.accounts.models import User
from apps.cases.models import ServiceRequest
from apps.loans.models import LoanRequest

from .base import PW, DemoTestCase


class AuthTests(DemoTestCase):
    def test_tc001_student_login_redirects_to_portal(self):
        c = Client()
        r = c.post("/acceso/", {"email": "alumno.demo1@nextpoint.test", "password": PW}, follow=True)
        self.assertEqual(r.redirect_chain[-1][0], "/app/")

    def test_tc002_manager_login_redirects_to_panel(self):
        c = Client()
        r = c.post("/acceso/", {"email": "gestor.laboratorio@nextpoint.test", "password": PW}, follow=True)
        self.assertEqual(r.redirect_chain[-1][0], "/panel/")

    def test_tc003_wrong_password_no_session_and_generic_message(self):
        c = Client()
        r = c.post("/acceso/", {"email": "alumno.demo1@nextpoint.test", "password": "incorrecta-123"})
        self.assertEqual(r.status_code, 200)
        self.assertNotIn("_auth_user_id", c.session)
        r2 = c.post("/acceso/", {"email": "noexiste@nextpoint.test", "password": "incorrecta-123"})
        self.assertEqual(r.context["error"], r2.context["error"])  # no permite enumerar cuentas

    def test_rate_limit_after_five_failures(self):
        c = Client()
        for _ in range(5):
            c.post("/acceso/", {"email": "alumno.demo1@nextpoint.test", "password": "mala-mala-1"})
        r = c.post("/acceso/", {"email": "alumno.demo1@nextpoint.test", "password": PW})
        self.assertEqual(r.status_code, 429)
        self.assertNotIn("_auth_user_id", c.session)

    def test_tc004_logout_invalidates_session(self):
        c = self.login("alumno.demo1")
        self.assertEqual(c.get("/app/").status_code, 200)
        c.post("/salir/")
        r = c.get("/app/")
        self.assertEqual(r.status_code, 302)
        self.assertIn("/acceso/", r["Location"])

    def test_logout_requires_post(self):
        c = self.login("alumno.demo1")
        self.assertEqual(c.get("/salir/").status_code, 405)

    def test_tc005_student_denied_admin_routes_and_api(self):
        c = self.login("alumno.demo1")
        for url in ["/panel/", "/panel/solicitudes/", "/panel/prestamos/", "/panel/recursos/", "/panel/usuarios/", "/panel/auditoria/",
                    "/panel/informes/", "/panel/avisos/nuevo/", "/panel/cursos/", "/panel/smartmatch/", "/panel/configuracion/"]:
            self.assertEqual(c.get(url).status_code, 403, url)
        self.assertEqual(c.get("/api/v1/admin/kpis").status_code, 403)
        res = LoanRequest.objects.filter(applicant__email="alumna.demo2@nextpoint.test", status="solicitado").first()
        self.assertEqual(c.post(f"/panel/prestamos/{res.pk}/approve/").status_code, 403)
        self.assertEqual(LoanRequest.objects.get(pk=res.pk).status, "solicitado")

    def test_tc006_student_cannot_see_other_students_records(self):
        c = self.login("alumno.demo1")
        other_case = ServiceRequest.objects.filter(creator__email="alumna.demo2@nextpoint.test").first()
        other_loan = LoanRequest.objects.filter(applicant__email="alumna.demo2@nextpoint.test").first()
        self.assertEqual(c.get(f"/app/solicitudes/{other_case.pk}/").status_code, 404)
        self.assertEqual(c.get(f"/app/prestamos/{other_loan.pk}/").status_code, 404)
        self.assertEqual(c.post(f"/app/solicitudes/{other_case.pk}/message/", {"body": "intrusión"}).status_code, 404)
        self.assertEqual(c.post(f"/app/prestamos/{other_loan.pk}/cancelar/").status_code, 404)
        r = c.get("/app/solicitudes/?vista=abiertas")
        self.assertNotContains(r, other_case.folio)

    def test_e2e06_manager_of_other_area_denied(self):
        c = self.login("gestor.laboratorio")
        case = ServiceRequest.objects.filter(area__code="SERV").first()
        self.assertEqual(c.get(f"/panel/solicitudes/{case.pk}/").status_code, 404)
        self.assertEqual(c.post(f"/panel/solicitudes/{case.pk}/acknowledge/").status_code, 403)
        r = c.get("/panel/solicitudes/?estado=todos")
        self.assertNotContains(r, case.folio)
        c2 = self.login("gestor.servicios")
        loan = LoanRequest.objects.first()
        self.assertEqual(c2.get(f"/panel/prestamos/{loan.pk}/").status_code, 404)  # no revela registros de otra área

    def test_tc007_no_public_role_self_assignment(self):
        c = Client()
        r = c.post("/acceso/", {"email": "x@x.test", "password": "x", "role": "admin_plataforma"})
        self.assertFalse(User.objects.filter(email="x@x.test").exists())
        self.assertEqual(c.get("/registro/").status_code, 404)

    def test_tc008_suspended_account_rejected_and_sessions_killed(self):
        student = self.login("alumna.demo2")
        coord = self.login("coord.demo")
        target = self.user("alumna.demo2")
        r = coord.post(f"/panel/usuarios/{target.pk}/estado/", {"status": "suspendido", "reason": "Prueba de suspensión"})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(student.get("/app/").status_code, 302)  # sesión anterior ya no sirve
        c = Client()
        c.post("/acceso/", {"email": "alumna.demo2@nextpoint.test", "password": PW})
        self.assertNotIn("_auth_user_id", c.session)

    def test_tc009_invitation_single_use(self):
        coord = self.login("coord.demo")
        from apps.accounts.models import Area, Role

        area = Area.objects.get(code="LAB", campus__code="C2")
        r = coord.post("/panel/usuarios/invitar/", {"email": "nuevo.gestor@nextpoint.test", "display_name": "Nuevo Gestor",
                                                    "role": Role.objects.get(code="gestor").pk, "campus": area.campus_id, "area": area.pk})
        link = r.context["link"]
        path = link.split("testserver")[1]
        c = Client()
        r = c.post(path, {"password1": "Clave-Muy-Segura-91", "password2": "Clave-Muy-Segura-91"})
        self.assertEqual(r.status_code, 302)
        u = User.objects.get(email="nuevo.gestor@nextpoint.test")
        self.assertTrue(u.user_roles.filter(role__code="gestor", area=area).exists())
        r2 = Client().post(path, {"password1": "Clave-Muy-Segura-91", "password2": "Clave-Muy-Segura-91"})
        self.assertEqual(r2.status_code, 410)
        self.assertEqual(User.objects.filter(email="nuevo.gestor@nextpoint.test").count(), 1)

    def test_coordinator_cannot_grant_technical_roles(self):
        coord = self.login("coord.demo")
        from apps.accounts.models import Role

        target = self.user("alumno.demo1")
        coord.post(f"/panel/usuarios/{target.pk}/roles/", {"role": Role.objects.get(code="admin_plataforma").pk})
        self.assertFalse(target.user_roles.filter(role__code="admin_plataforma").exists())

    def test_tc062_063_role_assign_revoke_audited(self):
        from apps.accounts.models import Area, Role
        from apps.audit.models import AuditLog

        coord = self.login("coord.demo")
        target = self.user("docente.demo")
        area = Area.objects.get(code="SERV", campus__code="C2")
        coord.post(f"/panel/usuarios/{target.pk}/roles/", {"role": Role.objects.get(code="gestor").pk, "area": area.pk})
        ur = target.user_roles.get(role__code="gestor")
        log = AuditLog.objects.filter(action="account.role_assigned", target_id=str(target.pk)).first()
        self.assertIn("gestor@SERV", log.detail["after"])
        self.assertNotIn("gestor@SERV", log.detail["before"])
        doc = self.login("docente.demo")
        self.assertEqual(doc.get("/panel/solicitudes/").status_code, 200)
        coord.post(f"/panel/usuarios/{target.pk}/roles/{ur.pk}/retirar/")
        self.assertTrue(AuditLog.objects.filter(action="account.role_revoked").exists())
        self.assertEqual(doc.get("/panel/prestamos/").status_code, 403)

    def test_last_admin_protection_and_self_change_blocked(self):
        from apps.accounts.views import _last_admin

        admin = self.user("admin.demo")
        self.assertTrue(_last_admin(admin))
        c = self.login("admin.demo")
        r = c.post(f"/panel/usuarios/{admin.pk}/estado/", {"status": "suspendido", "reason": "autosuspensión"})
        self.assertEqual(r.status_code, 403)  # nadie modifica su propia cuenta desde el panel
        self.assertEqual(User.objects.get(pk=admin.pk).status, "activo")
        coord = self.login("coord.demo")  # coordinación no gestiona cuentas técnicas
        self.assertEqual(coord.post(f"/panel/usuarios/{admin.pk}/estado/", {"status": "suspendido", "reason": "intento"}).status_code, 403)

    def test_tc072_xss_is_escaped(self):
        c = self.login("alumno.demo1")
        from apps.cases.models import ServiceCategory

        cat = ServiceCategory.objects.filter(campus__code="C2").first()
        c.post("/app/solicitudes/nueva/", {"category": cat.pk, "subject": "<script>alert(1)</script> prueba", "description": "<img src=x onerror=alert(1)> descripción",
                                           "priority": "normal", "idempotency_key": "11111111-1111-4111-8111-111111111111"})
        case = ServiceRequest.objects.get(subject__startswith="<script>")
        r = c.get(f"/app/solicitudes/{case.pk}/")
        self.assertNotContains(r, "<script>alert(1)</script>")
        self.assertContains(r, "&lt;script&gt;")

    def test_tc073_sqli_in_search_harmless(self):
        c = self.login("alumno.demo1")
        before = LoanRequest.objects.count()
        r = c.get("/app/materiales/", {"q": "'; DROP TABLE loans_loanrequest; --"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(LoanRequest.objects.count(), before)

    def test_tc074_csrf_rejected(self):
        c = Client(enforce_csrf_checks=True)
        c.post("/acceso/", {"email": "alumno.demo1@nextpoint.test", "password": PW})
        self.assertEqual(c.post("/acceso/", {"email": "a@b.test", "password": "x"}).status_code, 403)

    def test_security_headers_and_no_store(self):
        c = self.login("alumno.demo1")
        r = c.get("/app/")
        self.assertIn("default-src 'self'", r["Content-Security-Policy"])
        self.assertEqual(r["X-Frame-Options"], "DENY")
        self.assertIn("no-store", r["Cache-Control"])
        self.assertTrue(r["X-Trace-Id"])

    def test_tc066_health_has_no_secrets(self):
        r = Client().get("/health")
        self.assertEqual(r.status_code, 200)
        body = r.content.decode()
        self.assertNotIn("SECRET", body)
        self.assertEqual(set(r.json().keys()), {"status", "database", "time"})

    def test_notification_of_other_user_404(self):
        from apps.communications.models import Notification

        other = Notification.objects.filter(recipient__email="alumna.demo2@nextpoint.test").first()
        c = self.login("alumno.demo1")
        self.assertEqual(c.post(f"/app/notificaciones/{other.pk}/abrir/").status_code, 404)
        self.assertIsNone(Notification.objects.get(pk=other.pk).read_at)
