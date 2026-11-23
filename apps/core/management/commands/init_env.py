"""Crea el archivo .env local con secretos aleatorios. Nunca imprime los valores."""
import secrets
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Genera .env con NEXTPOINT_SECRET_KEY y NEXTPOINT_DEMO_PASSWORD aleatorios (no sobrescribe valores existentes)."

    def add_arguments(self, parser):
        parser.add_argument("--debug", action="store_true", help="Activa NEXTPOINT_DEBUG=1 (solo desarrollo local).")

    def handle(self, *args, **opts):
        path = Path(settings.BASE_DIR) / ".env"
        existing = {}
        lines = []
        if path.exists():
            lines = path.read_text(encoding="utf-8").splitlines()
            for line in lines:
                if "=" in line and not line.strip().startswith("#"):
                    k, v = line.split("=", 1)
                    existing[k.strip()] = v.strip()
        additions = []
        if not existing.get("NEXTPOINT_SECRET_KEY"):
            additions.append(f"NEXTPOINT_SECRET_KEY={secrets.token_urlsafe(50)}")
        if not existing.get("NEXTPOINT_DEMO_PASSWORD"):
            # Legible para dictarla en la demo, pero aleatoria y fuerte (≥ 16 caracteres).
            words = ["Nodo", "Ruta", "Enlace", "Puerto", "Trama", "Switch", "Cable", "Red", "Kit", "Folio"]
            pw = "-".join(secrets.choice(words) for _ in range(3)) + "-" + str(secrets.randbelow(9000) + 1000)
            additions.append(f"NEXTPOINT_DEMO_PASSWORD={pw}")
        if "NEXTPOINT_ENV" not in existing:
            additions.append("NEXTPOINT_ENV=demo")
        if opts["debug"] and "NEXTPOINT_DEBUG" not in existing:
            additions.append("NEXTPOINT_DEBUG=1")
        if additions:
            with path.open("a", encoding="utf-8") as fh:
                if lines and lines[-1].strip():
                    fh.write("\n")
                fh.write("# Generado por `python manage.py init_env` — no versionar este archivo\n")
                fh.write("\n".join(additions) + "\n")
        self.stdout.write(self.style.SUCCESS(
            f".env listo ({len(additions)} valor(es) nuevo(s)). La contraseña de las cuentas demo está en NEXTPOINT_DEMO_PASSWORD; no se muestra aquí."
        ))
