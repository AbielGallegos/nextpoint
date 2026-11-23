"""E2E-02: incidencia institucional con acuse ≠ resolución, notas internas ocultas, TC-025…TC-036."""
import uuid

from django.core.files.uploadedfile import SimpleUploadedFile

from apps.cases import services
from apps.cases.models import RequestAttachment, ServiceCategory, ServiceRequest
from apps.communications.models import Notification
from apps.core.errors import DomainError

from .base import DemoTestCase


def cat(kind="consulta"):
    return ServiceCategory.objects.filter(campus__code="C2", kind=kind).first()


class CaseFlowTests(DemoTestCase):
    def test_e2e02_full_flow(self):
        student = self.login("alumno.demo1")
        r = student.post("/app/solicitudes/nueva/", {"category": cat().pk, "subject": "Consulta de disponibilidad de laboratorio",
                                                     "description": "¿Está libre la sala el viernes? (demo)", "priority": "normal",
                                                     "idempotency_key": str(uuid.uuid4())})
        case = ServiceRequest.objects.get(subject="Consulta de disponibilidad de laboratorio", creator__email="alumno.demo1@nextpoint.test")
        self.assertRedirects(r, f"/app/solicitudes/{case.pk}/")
        self.assertRegex(case.folio, r"^NP-SOL-\d{5}$")
        manager = self.login("gestor.servicios")
        self.assertContains(manager.get("/panel/solicitudes/"), case.folio)
        # Acuse: no cierra el caso
        manager.post(f"/panel/solicitudes/{case.pk}/acknowledge/")
        case.refresh_from_db()
        self.assertEqual(case.status, "acusado")
        self.assertIsNotNone(case.acknowledged_at)
        self.assertIsNone(case.resolved_at)
        self.assertIn(case.status, ServiceRequest.OPEN_STATES)
        page = student.get(f"/app/solicitudes/{case.pk}/")
        self.assertContains(page, "Recibido")
        self.assertContains(page, "Aún está en atención")
        # Nota interna invisible, respuesta pública visible
        manager.post(f"/panel/solicitudes/{case.pk}/note/", {"body": "NOTA-SECRETA-INTERNA"})
        manager.post(f"/panel/solicitudes/{case.pk}/reply/", {"body": "Sí hay espacio de 12 a 14 h."})
        page = student.get(f"/app/solicitudes/{case.pk}/")
        self.assertNotContains(page, "NOTA-SECRETA-INTERNA")
        self.assertContains(page, "Sí hay espacio de 12 a 14 h.")
        self.assertContains(manager.get(f"/panel/solicitudes/{case.pk}/"), "NOTA-SECRETA-INTERNA")
        # Resolver y cerrar
        manager.post(f"/panel/solicitudes/{case.pk}/resolve/", {"body": "Sala reservada para tu equipo el viernes."})
        manager.post(f"/panel/solicitudes/{case.pk}/close/")
        case.refresh_from_db()
        self.assertEqual(case.status, "cerrado")
        titles = list(Notification.objects.filter(recipient=case.creator, title__startswith=case.folio).values_list("title", flat=True))
        self.assertTrue(any("cerrado" in t for t in titles))
        self.assertTrue(any("recibimos" in t for t in titles))
        statuses = [e.status_after for e in case.events.filter(kind="estado")]
        self.assertEqual(statuses, ["acusado", "resuelto", "cerrado"])
        # Valoración
        student.post(f"/app/solicitudes/{case.pk}/rate/", {"rating": "5"})
        case.refresh_from_db()
        self.assertEqual(case.rating, 5)

    def test_tc032_cannot_close_or_resolve_without_attention(self):
        gs = self.user("gestor.servicios")
        case, _ = services.create_request(self.user("alumno.demo1"), cat().pk, "Asunto de prueba", "Descripción de prueba", "normal", uuid.uuid4())
        for action in ("close", "resolve"):
            with self.assertRaises(DomainError) as ctx:
                services.staff_action(gs, case.pk, action, body="Resolución suficientemente larga")
            self.assertEqual(ctx.exception.code, "INVALID_TRANSITION")

    def test_student_cannot_impose_resolved(self):
        c = self.login("alumno.demo1")
        case = ServiceRequest.objects.filter(creator__email="alumno.demo1@nextpoint.test", status="nuevo").first()
        r = c.post(f"/app/solicitudes/{case.pk}/resolve/")
        self.assertEqual(r.status_code, 404)
        self.assertEqual(ServiceRequest.objects.get(pk=case.pk).status, "nuevo")

    def test_tc026_assignment_to_instructor_allows_attending(self):
        gs, doc = self.user("gestor.servicios"), self.user("docente.demo")
        case = ServiceRequest.objects.filter(creator__email="alumno.demo1@nextpoint.test", status="nuevo").first()
        services.assign(gs, case.pk, doc.pk)
        case.refresh_from_db()
        self.assertEqual(case.assigned_to, doc)
        self.assertEqual(case.status, "asignado")
        d = self.login("docente.demo")
        self.assertEqual(d.get(f"/panel/solicitudes/{case.pk}/").status_code, 200)
        services.staff_action(doc, case.pk, "acknowledge")
        with self.assertRaises(DomainError):  # cerrar/rechazar es exclusivo del gestor
            services.staff_action(doc, case.pk, "reject", body="no corresponde")

    def test_reopen_after_resolution(self):
        a1, gs = self.user("alumno.demo1"), self.user("gestor.servicios")
        case, _ = services.create_request(a1, cat().pk, "Asunto de prueba", "Descripción de prueba", "normal", uuid.uuid4())
        services.staff_action(gs, case.pk, "acknowledge")
        services.staff_action(gs, case.pk, "resolve", body="Resuelto de forma completa")
        services.student_action(a1, case.pk, "reopen", body="Faltó confirmar el horario")
        self.assertEqual(ServiceRequest.objects.get(pk=case.pk).status, "en_proceso")

    def test_tc034_invalid_attachment_rejected_valid_private(self):
        c = self.login("alumno.demo1")
        fake = SimpleUploadedFile("malicioso.pdf", b"MZ\x90\x00 not a pdf", content_type="application/pdf")
        r = c.post("/app/solicitudes/nueva/", {"category": cat("incidencia").pk, "subject": "Con adjunto falso", "description": "Descripción de prueba",
                                               "priority": "normal", "idempotency_key": str(uuid.uuid4()), "attachment": fake})
        self.assertEqual(r.status_code, 400)
        self.assertFalse(ServiceRequest.objects.filter(subject="Con adjunto falso").exists())
        good = SimpleUploadedFile("evidencia.png", b"\x89PNG\r\n\x1a\n" + b"0" * 100, content_type="image/png")
        c.post("/app/solicitudes/nueva/", {"category": cat("incidencia").pk, "subject": "Con adjunto real", "description": "Descripción de prueba",
                                           "priority": "normal", "idempotency_key": str(uuid.uuid4()), "attachment": good})
        att = RequestAttachment.objects.get(request__subject="Con adjunto real")
        self.assertNotIn("evidencia", att.storage_key)
        self.assertEqual(c.get(f"/adjuntos/{att.pk}/").status_code, 200)
        self.assertEqual(self.login("alumna.demo2").get(f"/adjuntos/{att.pk}/").status_code, 404)
        self.assertEqual(self.login("gestor.laboratorio").get(f"/adjuntos/{att.pk}/").status_code, 404)

    def test_tc075_large_attachment_rejected(self):
        c = self.login("alumno.demo1")
        big = SimpleUploadedFile("grande.pdf", b"%PDF-" + b"0" * (5 * 1024 * 1024 + 10), content_type="application/pdf")
        r = c.post("/app/solicitudes/nueva/", {"category": cat().pk, "subject": "Archivo grande", "description": "Descripción de prueba",
                                               "priority": "normal", "idempotency_key": str(uuid.uuid4()), "attachment": big})
        self.assertIn(r.status_code, (400, 413))
        self.assertFalse(ServiceRequest.objects.filter(subject="Archivo grande").exists())

    def test_coordinator_supervises_read_only(self):
        coord = self.login("coord.demo")
        case = ServiceRequest.objects.filter(status="nuevo").first()
        self.assertEqual(coord.get(f"/panel/solicitudes/{case.pk}/").status_code, 200)
        self.assertEqual(coord.post(f"/panel/solicitudes/{case.pk}/acknowledge/").status_code, 403)
