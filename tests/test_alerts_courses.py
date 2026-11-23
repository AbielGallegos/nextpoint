"""E2E-04 (avisos) y E2E-05 (cursos), TC-046…TC-056."""
from datetime import timedelta

from django.utils import timezone

from apps.communications.models import Alert, AlertRead
from apps.learning.models import Course, Lesson

from .base import DemoTestCase


class AlertTests(DemoTestCase):
    def test_e2e04_draft_publish_read_expire(self):
        gl = self.login("gestor.laboratorio")
        from apps.accounts.models import Area

        lab = Area.objects.get(code="LAB", campus__code="C2")
        r = gl.post("/panel/avisos/nuevo/", {"title": "Aviso de prueba E2E", "summary": "Resumen del aviso de prueba", "body": "Contenido del aviso de prueba",
                                            "scope": f"area:{lab.pk}", "audience": "estudiantes", "category": "materiales", "priority": "alta"})
        self.assertEqual(r.status_code, 302)
        alert = Alert.objects.get(title="Aviso de prueba E2E")
        student = self.login("alumno.demo1")
        self.assertNotContains(student.get("/app/avisos/"), "Aviso de prueba E2E")  # borrador invisible
        self.assertEqual(student.get(f"/app/avisos/{alert.pk}/").status_code, 404)
        gl.post(f"/panel/avisos/{alert.pk}/publicar/")
        self.assertContains(student.get("/app/avisos/"), "Aviso de prueba E2E")
        student.post(f"/app/avisos/{alert.pk}/leido/")
        self.assertTrue(AlertRead.objects.filter(alert=alert, user__email="alumno.demo1@nextpoint.test").exists())
        self.assertFalse(AlertRead.objects.filter(alert=alert, user__email="alumna.demo2@nextpoint.test").exists())
        Alert.objects.filter(pk=alert.pk).update(expires_at=timezone.now() - timedelta(minutes=1))
        self.assertNotContains(student.get("/app/avisos/"), "Aviso de prueba E2E")
        self.assertNotContains(student.get("/app/"), "Aviso de prueba E2E")
        self.assertEqual(Alert.objects.get(pk=alert.pk).lifecycle, "expirado")

    def test_tc052_other_campus_alert_hidden(self):
        student = self.login("alumno.demo1")
        self.assertNotContains(student.get("/app/avisos/"), "Aviso exclusivo del Campus 1")
        self.assertNotContains(student.get("/app/avisos/"), "Aviso vencido de semana anterior")

    def test_tc056_manager_cannot_publish_global_or_campus(self):
        gl = self.login("gestor.laboratorio")
        r = gl.post("/panel/avisos/nuevo/", {"title": "Aviso global indebido", "summary": "Resumen del aviso global", "body": "Contenido del aviso",
                                            "scope": "global", "audience": "todos", "category": "general", "priority": "normal"})
        self.assertEqual(r.status_code, 400)
        self.assertFalse(Alert.objects.filter(title="Aviso global indebido").exists())

    def test_tc055_external_link_requires_https(self):
        gl = self.login("gestor.laboratorio")
        from apps.accounts.models import Area

        lab = Area.objects.get(code="LAB", campus__code="C2")
        r = gl.post("/panel/avisos/nuevo/", {"title": "Aviso con enlace", "summary": "Resumen del aviso", "body": "Contenido del aviso",
                                            "scope": f"area:{lab.pk}", "category": "general", "source_url": "javascript:alert(1)"})
        self.assertEqual(r.status_code, 400)

    def test_critical_requires_verification(self):
        coord = self.login("coord.demo")
        from apps.accounts.models import Campus

        r = coord.post("/panel/avisos/nuevo/", {"title": "Aviso crítico", "summary": "Resumen del aviso", "body": "Contenido del aviso",
                                               "scope": f"campus:{Campus.objects.get(code='C2').pk}", "category": "general", "priority": "critica"})
        self.assertEqual(r.status_code, 400)


class CourseTests(DemoTestCase):
    def test_e2e05_author_review_enroll_progress(self):
        doc = self.login("docente.demo")
        from apps.accounts.models import Area

        lab = Area.objects.get(code="LAB", campus__code="C2")
        doc.post("/panel/cursos/nuevo/", {"title": "Curso E2E de cableado", "summary": "Resumen del curso", "description": "Descripción del curso de prueba",
                                         "level": "introductorio", "mode": "en_linea", "duration_minutes": 20, "area": lab.pk, "content_license_ok": "on",
                                         "tags_text": "redes"})
        course = Course.objects.get(title="Curso E2E de cableado")
        self.assertEqual(course.status, "borrador")
        for i in (1, 2):
            doc.post(f"/panel/cursos/{course.pk}/lecciones/", {"module_title": "Módulo 1", "title": f"Lección {i}", "kind": "texto",
                                                              "duration_minutes": 10, "content": f"Contenido original {i}", "published": "on"})
        doc.post(f"/panel/cursos/{course.pk}/submit/")
        self.assertEqual(Course.objects.get(pk=course.pk).status, "en_revision")
        student = self.login("alumno.demo1")
        self.assertNotContains(student.get("/app/cursos/"), "Curso E2E de cableado")  # TC-046
        self.assertEqual(student.get(f"/app/cursos/{course.pk}/").status_code, 404)
        self.assertEqual(doc.post(f"/panel/cursos/{course.pk}/approve/").status_code, 403)  # el autor no se autopublica
        self.assertEqual(Course.objects.get(pk=course.pk).status, "en_revision")
        gl = self.login("gestor.laboratorio")
        gl.post(f"/panel/cursos/{course.pk}/approve/")
        self.assertEqual(Course.objects.get(pk=course.pk).status, "publicado")
        self.assertContains(student.get("/app/cursos/"), "Curso E2E de cableado")
        student.post(f"/app/cursos/{course.pk}/inscribirme/")
        student.post(f"/app/cursos/{course.pk}/inscribirme/")  # TC-050 sin duplicar
        self.assertEqual(course.enrollments.count(), 1)
        l1, l2 = list(course.published_lessons())
        r = student.post(f"/app/lecciones/{l2.pk}/completar/")  # fuera de orden
        self.assertEqual(course.enrollments.get().progress(), 0)
        student.post(f"/app/lecciones/{l1.pk}/completar/")
        self.assertEqual(course.enrollments.get().progress(), 50)
        student.post(f"/app/lecciones/{l2.pk}/completar/")
        self.assertEqual(course.enrollments.get().progress(), 100)
        # Persiste al volver a entrar
        again = self.login("alumno.demo1")
        self.assertEqual(again.get(f"/app/cursos/{course.pk}/").context["pct"], 100)

    def test_demo_course_two_lessons_50_100(self):
        c = self.login("alumna.demo2")
        course = Course.objects.get(title__startswith="Introducción a redes")
        self.assertEqual(course.published_lessons().count(), 2)
        c.post(f"/app/cursos/{course.pk}/inscribirme/")
        pcts = []
        for lesson in course.published_lessons():
            c.post(f"/app/lecciones/{lesson.pk}/completar/")
            pcts.append(course.enrollments.get(student__email="alumna.demo2@nextpoint.test").progress())
        self.assertEqual(pcts, [50, 100])

    def test_tc049_progress_only_own(self):
        course = Course.objects.get(title__startswith="Introducción a redes")
        a = self.login("alumno.demo1")
        a.post(f"/app/cursos/{course.pk}/inscribirme/")
        b = self.login("alumna.demo2")  # no inscrita
        lesson = course.published_lessons().first()
        self.assertEqual(b.post(f"/app/lecciones/{lesson.pk}/completar/").status_code, 404)
        self.assertFalse(course.enrollments.filter(student__email="alumna.demo2@nextpoint.test").exists())

    def test_draft_course_hidden(self):
        c = self.login("alumno.demo1")
        self.assertNotContains(c.get("/app/cursos/"), "Buenas prácticas de documentación")
        draft = Course.objects.get(title__startswith="Buenas prácticas")
        lesson = Lesson.objects.filter(module__course=draft).first()
        self.assertEqual(c.get(f"/app/lecciones/{lesson.pk}/").status_code, 404)
