# NextPoint — prototipo funcional

Plataforma web para gestionar **recursos educativos, préstamos de materiales, solicitudes institucionales, cursos y oportunidades académicas**, con un **portal del estudiante** y un **panel administrativo** que comparten la misma base de datos, permisos verificados en servidor y bitácora de auditoría.

> Prototipo con **datos 100 % sintéticos**. El escenario propuesto (Instituto Tecnológico de Morelia, Campus 2) no implica convenio ni autorización institucional. NextPoint no emite certificados oficiales ni procesa pagos.

**Stack:** Django 5.2 (monolito modular) · PostgreSQL (recomendado) o SQLite (sin configuración) · plantillas HTML + CSS propio + JavaScript ligero sin dependencias · funciona **sin internet** (fuente e iconos empaquetados).

---

## 1. Requisitos

- Python 3.11 o superior (probado con 3.13).
- Opcional: PostgreSQL 14+ (probado con 16). Sin él se usa SQLite automáticamente.

## 2. Instalación

```bash
cd nextpoint
python -m venv .venv
# Windows: .venv\Scripts\activate      macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
```

## 3. Configuración

```bash
python manage.py init_env --debug
```

Crea `.env` con una `NEXTPOINT_SECRET_KEY` y una `NEXTPOINT_DEMO_PASSWORD` **aleatorias** (no las imprime). Revisa `.env.example` para el resto de variables. `.env` está en `.gitignore`: nunca se sube al repositorio.

Para PostgreSQL agrega a `.env`:

```
DATABASE_URL=postgres://usuario:clave@127.0.0.1:5432/nextpoint
```

## 4. Base de datos y datos de demostración

```bash
python manage.py migrate        # esquema + roles/permisos maestros
python manage.py seed_demo      # datos sintéticos (idempotente: puedes repetirlo)
```

## 5. Ejecución

```bash
python manage.py runserver
```

Abre http://127.0.0.1:8000 → **Entrar al prototipo**.

## 6. Acceso a los perfiles

Todas las cuentas demo usan la contraseña guardada en `NEXTPOINT_DEMO_PASSWORD` dentro de **tu** `.env` (no se publica en el código ni en este README). La pantalla de acceso lista los correos para elegirlos con un clic.

| Cuenta | Perfil | Para demostrar |
| --- | --- | --- |
| `alumno.demo1@nextpoint.test` | Estudiante | SmartMatch, solicitar el kit de redes, crear reporte, curso |
| `alumna.demo2@nextpoint.test` | Estudiante | Aislamiento entre estudiantes (tiene préstamo vencido y casos propios) |
| `gestor.laboratorio@nextpoint.test` | Gestor · Laboratorios y materiales | Aprobar, entregar y recibir; inventario; avisos; aprobar cursos |
| `gestor.servicios@nextpoint.test` | Gestor · Atención y servicios | Acusar, responder, resolver y cerrar casos |
| `docente.demo@nextpoint.test` | Docente / instructor | Crear curso y enviarlo a revisión; atender casos asignados |
| `coord.demo@nextpoint.test` | Coordinación institucional | Informes, exportación, usuarios/invitaciones, reglas SmartMatch, avisos de campus |
| `admin.demo@nextpoint.test` | Administración de plataforma | Roles técnicos, auditoría global, estado técnico, soporte |

Guion completo de la demostración: [`docs/DEMO.md`](docs/DEMO.md).

## 7. Pruebas

```bash
python manage.py test tests            # 72 pruebas automatizadas
```

La prueba de concurrencia real **E2E-07** (dos gestores aprueban a la vez el último ejemplar) solo se ejecuta con PostgreSQL (`DATABASE_URL` definida); con SQLite aparece como *skipped* y la integridad se cubre con pruebas secuenciales y el modo de transacción `IMMEDIATE`. Resultados y matriz de casos: [`docs/PRUEBAS.md`](docs/PRUEBAS.md).

## 8. Reinicio del entorno

```bash
python manage.py reset_demo --yes                 # borra la base de ENSAYO y vuelve a sembrar
python manage.py backup_demo                      # respaldo JSON en backups/
python manage.py restore_demo backups/archivo.json --yes
```

`reset_demo` y `restore_demo` se niegan a ejecutarse si `NEXTPOINT_ENV=production`.

## 9. Documentación

- [`docs/ARQUITECTURA.md`](docs/ARQUITECTURA.md) — decisiones, módulos, modelo de datos, seguridad.
- [`docs/DEMO.md`](docs/DEMO.md) — cuentas, escenarios E2E y guion de 5 minutos.
- [`docs/FUNCIONALIDADES.md`](docs/FUNCIONALIDADES.md) — registro de lo terminado y lo pendiente (P0/P1/P2).
- [`docs/PRUEBAS.md`](docs/PRUEBAS.md) — pruebas ejecutadas y resultados reales.
- [`docs/OPERACION.md`](docs/OPERACION.md) — despliegue, respaldos, salud y variables.

## Licencias de terceros

Django (BSD-3), WhiteNoise (MIT), dj-database-url (BSD), psycopg (LGPL-3), fuente Inter (SIL OFL 1.1), iconos Lucide (ISC). Logotipo NextPoint: propiedad del equipo NextPoint.
