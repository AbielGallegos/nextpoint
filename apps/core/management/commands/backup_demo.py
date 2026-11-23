"""Respaldo lógico de la base de ensayo (JSON). Para un piloto real usar respaldos cifrados del motor de BD."""
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Genera un respaldo JSON de los datos (sin sesiones) en backups/."

    def add_arguments(self, parser):
        parser.add_argument("--output", help="Ruta del archivo de salida")

    def handle(self, *args, **opts):
        out = Path(opts.get("output") or Path(settings.BASE_DIR) / "backups" / f"nextpoint_{datetime.now():%Y%m%d_%H%M%S}.json")
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("w", encoding="utf-8") as fh:
            call_command("dumpdata", exclude=["contenttypes", "sessions", "auth.permission"], natural_foreign=True, indent=1, stdout=fh)
        if out.stat().st_size < 100:
            out.unlink(missing_ok=True)
            self.stderr.write(self.style.ERROR("El respaldo quedó vacío: no se reporta éxito."))
            raise SystemExit(1)
        if opts.get("verbosity", 1):
            self.stdout.write(self.style.SUCCESS(f"Respaldo creado: {out} ({out.stat().st_size // 1024} KB)"))
