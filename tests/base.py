import os

from django.conf import settings
from django.core.management import call_command
from django.test import Client, TestCase

PW = "Prueba-Demo-Segura-2026"


def load_demo(history=True):
    os.environ["NEXTPOINT_DEMO_PASSWORD"] = PW
    call_command("seed_demo", without_history=not history, verbosity=0)


class DemoTestCase(TestCase):
    """Cada prueba parte del dataset sintético de demostración."""

    history = True

    @classmethod
    def setUpTestData(cls):
        load_demo(cls.history)

    def setUp(self):
        if "testserver" not in settings.ALLOWED_HOSTS:
            settings.ALLOWED_HOSTS.append("testserver")

    def login(self, who):
        c = Client()
        r = c.post("/acceso/", {"email": f"{who}@nextpoint.test", "password": PW})
        self.assertEqual(r.status_code, 302, f"no pudo entrar {who}")
        return c

    def user(self, who):
        from apps.accounts.models import User

        return User.objects.get(email=f"{who}@nextpoint.test")
