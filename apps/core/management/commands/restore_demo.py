"""Restaura un respaldo JSON sobre la base de ENSAYO (nunca producción)."""
import os
from pathlib import Path

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import connection


class Command(BaseCommand):
    help = "Borra la base de ensayo y carga un respaldo creado con backup_demo."

    def add_arguments(self, parser):
        parser.add_argument("file")
        parser.add_argument("--yes", action="store_true")

    def handle(self, *args, **opts):
        env = os.environ.get("NEXTPOINT_ENV", "demo").lower()
        if env not in ("demo", "dev", "test"):
            raise CommandError(f"restore_demo bloqueado en NEXTPOINT_ENV={env}.")
        path = Path(opts["file"])
        if not path.exists():
            raise CommandError("No existe el archivo de respaldo.")
        if not opts["yes"]:
            raise CommandError("Confirma con --yes. Se reemplazarán los datos de: " + str(connection.settings_dict.get("NAME")))
        call_command("flush", interactive=False, verbosity=0)
        call_command("loaddata", str(path), verbosity=0)
        if opts.get("verbosity", 1):
            self.stdout.write(self.style.SUCCESS("Respaldo restaurado en la base de ensayo."))
