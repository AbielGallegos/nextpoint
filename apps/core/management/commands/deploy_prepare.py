"""Paso de despliegue: verifica la conexión, aplica migraciones y carga los datos demo (idempotente)."""
import os

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import connection


class Command(BaseCommand):
    help = "Migraciones + datos demo para un despliegue (no borra nada)."

    def handle(self, *args, **opts):
        if connection.vendor != "postgresql":
            raise CommandError("deploy_prepare requiere DATABASE_URL de PostgreSQL.")
        with connection.cursor() as c:
            c.execute("select current_user, current_schema()")
            user, schema = c.fetchone()
        self.stdout.write(f"Conectado a PostgreSQL como rol '{user}' en el esquema '{schema}'.")
        call_command("migrate", interactive=False, verbosity=1)
        if os.environ.get("NEXTPOINT_DEMO_PASSWORD"):
            call_command("seed_demo", verbosity=1)
        else:
            self.stdout.write("NEXTPOINT_DEMO_PASSWORD no definida: se omite la carga de datos demo.")
