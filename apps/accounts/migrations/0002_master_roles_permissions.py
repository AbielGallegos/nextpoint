"""Datos maestros (no demo): roles, permisos y matriz rol-permiso. Idempotente."""
from django.db import migrations


def load(apps, schema_editor):
    from apps.accounts.access import PERMISSIONS, ROLE_PERMISSIONS, ROLES

    Role = apps.get_model("accounts", "Role")
    Permission = apps.get_model("accounts", "Permission")
    RolePermission = apps.get_model("accounts", "RolePermission")
    for code, name, desc, privileged, order in ROLES:
        Role.objects.update_or_create(code=code, defaults={"name": name, "description": desc, "is_privileged": privileged, "order": order})
    for code, (module, desc) in PERMISSIONS.items():
        Permission.objects.update_or_create(code=code, defaults={"module": module, "description": desc})
    for role_code, perms in ROLE_PERMISSIONS.items():
        role = Role.objects.get(code=role_code)
        for p in perms:
            RolePermission.objects.get_or_create(role=role, permission=Permission.objects.get(code=p))


class Migration(migrations.Migration):
    dependencies = [("accounts", "0001_initial")]
    operations = [migrations.RunPython(load, migrations.RunPython.noop)]
