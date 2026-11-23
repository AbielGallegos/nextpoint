"""E2E-03 y TC-037…TC-045: SmartMatch determinista y explicable."""
from apps.catalog.models import Resource
from apps.smartmatch.engine import recommend
from apps.smartmatch.models import MatchRule

from .base import DemoTestCase


class SmartMatchTests(DemoTestCase):
    def test_e2e03_need_to_request(self):
        c = self.login("alumno.demo1")
        r = c.get("/app/smartmatch/", {"need": "material-de-redes", "category": "materiales", "tags": "redes, laboratorio, cableado"})
        results = r.context["results"]
        top = results[0]
        self.assertEqual(top.candidate.title, "Kit de redes de laboratorio")
        self.assertEqual(top.score, 100)
        self.assertIn("coincide con tu necesidad", top.explanation)
        self.assertIn("pertenece a tu campus", top.explanation)
        self.assertIn("cuenta con disponibilidad", top.explanation)
        self.assertContains(r, "Recomendado porque")
        kit = Resource.objects.get(code="KIT-RED-01")
        self.assertEqual(c.get(top.candidate.url).status_code, 200)
        self.assertEqual(c.get(f"/app/materiales/{kit.pk}/solicitar/").status_code, 200)

    def test_tc038_campus_filter(self):
        user = self.user("alumno.demo1")
        results, _ = recommend(user, category="materiales", tags=["redes"])
        self.assertNotIn("Kit de redes (Campus 1)", [r.candidate.title for r in results])
        results_all, _ = recommend(user, category="materiales", tags=["redes"], campus_only=False)
        self.assertIn("Kit de redes (Campus 1)", [r.candidate.title for r in results_all])

    def test_tc039_disabled_or_unstocked_not_recommended(self):
        user = self.user("alumno.demo1")
        kit = Resource.objects.get(code="KIT-RED-01")
        kit.status = Resource.Status.OUT_OF_SERVICE
        kit.save()
        results, _ = recommend(user, category="materiales", tags=["redes"])
        self.assertNotIn(kit.name, [r.candidate.title for r in results])
        self.assertNotIn("Osciloscopio de dos canales", [r.candidate.title for r in results])  # borrador

    def test_tc041_no_results_shows_help(self):
        c = self.login("alumno.demo1")
        r = c.get("/app/smartmatch/", {"category": "", "tags": "astronomia, telescopio"})
        self.assertEqual(r.context["results"], [])
        self.assertContains(r, "No encontramos una coincidencia disponible")

    def test_tc044_invalid_weights_cannot_activate(self):
        coord = self.login("coord.demo")
        coord.post("/panel/smartmatch/borrador/", {"w_category": 50, "w_tags": 50, "w_campus": 15, "w_availability": 15, "w_freshness": 5, "min_score": 40})
        draft = MatchRule.objects.get(status="borrador", campus__code="C2")
        coord.post(f"/panel/smartmatch/reglas/{draft.pk}/activar/")
        self.assertEqual(MatchRule.objects.get(pk=draft.pk).status, "borrador")

    def test_tc043_manager_cannot_publish_rules(self):
        gl = self.login("gestor.laboratorio")
        self.assertEqual(gl.get("/panel/smartmatch/").status_code, 200)  # sí puede simular
        self.assertEqual(gl.post("/panel/smartmatch/borrador/", {"w_category": 40}).status_code, 403)

    def test_tc042_new_weights_change_ranking(self):
        coord = self.login("coord.demo")
        coord.post("/panel/smartmatch/borrador/", {"w_category": 10, "w_tags": 70, "w_campus": 10, "w_availability": 5, "w_freshness": 5, "min_score": 30})
        draft = MatchRule.objects.get(status="borrador", campus__code="C2")
        coord.post(f"/panel/smartmatch/reglas/{draft.pk}/activar/")
        self.assertEqual(MatchRule.objects.get(campus__code="C2", status="activa").pk, draft.pk)
        results, rule = recommend(self.user("alumno.demo1"), category="materiales", tags=["redes"])
        self.assertEqual(rule.pk, draft.pk)
        self.assertEqual(results[0].breakdown["tags"], 70)

    def test_tc045_deterministic_tie_order(self):
        user = self.user("alumno.demo1")
        a, _ = recommend(user, category="materiales", tags=[])
        b, _ = recommend(user, category="materiales", tags=[])
        self.assertEqual([r.key for r in a], [r.key for r in b])

    def test_no_sensitive_inputs(self):
        import inspect

        from apps.smartmatch import engine

        src = inspect.getsource(engine.score_candidate)
        for forbidden in ("semester", "program", "grade", "salud", "discapacidad"):
            self.assertNotIn(forbidden, src)
