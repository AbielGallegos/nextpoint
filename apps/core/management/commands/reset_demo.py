"""Restablece la base de ENSAYO al estado inicial de demostración. Exige confirmación explícita."""
import os

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import connection


class Command(BaseCommand):
    help = "Borra TODOS los datos de la base configurada y vuelve a cargar la demo. Solo para entornos demo/dev."

    def add_arguments(self, parser):
        parser.add_argument("--yes", action="store_true", help="Confirma que entiendes que se borrarán los datos de esta base.")
        parser.add_argument("--without-history", action="store_true")

    def handle(self, *args, **opts):
        env = os.environ.get("NEXTPOINT_ENV", "demo").lower()
        if env not in ("demo", "dev", "test"):
            raise CommandError(f"reset_demo está bloqueado en NEXTPOINT_ENV={env}. Nunca se ejecuta sobre producción.")
        if not opts["yes"]:
            raise CommandError("Confirma con --yes. Se borrarán todos los registros de: " + str(connection.settings_dict.get("NAME")))
        call_command("flush", interactive=False, verbosity=0)
        call_command("seed_demo", without_history=opts["without_history"], verbosity=0)
        self.stdout.write(self.style.SUCCESS("Base de ensayo restablecida al estado inicial de la demo."))
