# Operación del prototipo

## Variables de entorno
Ver `.env.example`. Secretos solo en `.env` (ignorado por git) o en el gestor de secretos del hosting. `init_env` genera valores aleatorios sin imprimirlos.

## Modo seguro (no DEBUG)
```bash
NEXTPOINT_DEBUG=0
python manage.py collectstatic --noinput
python manage.py runserver           # WhiteNoise sirve los estáticos; para producción usa un servidor WSGI (gunicorn/waitress) apuntando a config.wsgi
```
Con HTTPS activa `NEXTPOINT_SECURE_COOKIES=1` y define `NEXTPOINT_ALLOWED_HOSTS` y `NEXTPOINT_CSRF_TRUSTED_ORIGINS`.

## Salud y observabilidad
- `GET /health` → `{"status","database","time"}` sin datos sensibles (503 si la BD falla).
- Panel → **Estado técnico** (soporte/admin): motor de BD, migraciones pendientes, modo y eventos de seguridad.
- Logs en JSON por consola con `trace_id` (también en la cabecera `X-Trace-Id` y en la página de error 500). Se redactan contraseñas/tokens.

## Respaldo y restauración (base de ensayo)
```bash
python manage.py backup_demo                         # backups/nextpoint_AAAAMMDD_HHMMSS.json
python manage.py restore_demo backups/archivo.json --yes
python manage.py reset_demo --yes                    # vuelve al estado inicial de la demo
```
Bloqueados con `NEXTPOINT_ENV=production`. Un respaldo vacío se reporta como error (no éxito falso). Para un piloto real usa `pg_dump` cifrado y prueba la restauración en una base aislada.

## PostgreSQL local (ejemplo)
```sql
CREATE ROLE nextpoint LOGIN PASSWORD 'cambia-esto' CREATEDB;
CREATE DATABASE nextpoint OWNER nextpoint;
```
`DATABASE_URL=postgres://nextpoint:cambia-esto@127.0.0.1:5432/nextpoint`

## Despliegue público (Vercel + Supabase)

Demo pública: https://nextpoint-ashen.vercel.app — cada `git push` a `main` vuelve a desplegar.

- **Base de datos:** esquema propio `nextpoint` dentro de un proyecto Supabase existente, con un rol dedicado
  (`nextpoint_app`) dueño solo de ese esquema (`search_path=nextpoint`, `statement_timeout=30s`, sin `CREATE` en `public`).
  No toca tablas de otros proyectos.
- **Conexión:** pooler de Supabase en modo transacción (puerto 6543). Con ese puerto se desactivan los cursores del
  lado del servidor y en Vercel `CONN_MAX_AGE=0`.
- **Build:** `pyproject.toml` declara dependencias y `[tool.vercel.scripts] build = "python manage.py deploy_prepare"`,
  que verifica PostgreSQL, aplica migraciones y (si existe `NEXTPOINT_DEMO_PASSWORD`) carga datos demo de forma
  idempotente. Vercel ejecuta `collectstatic` y sirve `/static/` por CDN.
- **Variables en Vercel (Production y Preview):** `DATABASE_URL` (sensible), `NEXTPOINT_SECRET_KEY`,
  `NEXTPOINT_DEMO_PASSWORD` (sensible), `NEXTPOINT_ENV=production`, `NEXTPOINT_SHOW_DEMO_ACCOUNTS=1`.
  Ningún secreto vive en el repositorio.
- **Comportamiento con `VERCEL` presente:** HTTPS detrás de proxy, cookies seguras + HSTS, IP del cliente desde
  `X-Real-IP` (límite de intentos de acceso), hosts `*.vercel.app` del proyecto, adjuntos guardados en la BD
  (el disco de la función es efímero) con tope de 4 MB.
- **Limitaciones conocidas:** los correos de recuperación de contraseña se escriben en los logs de la función
  (no hay SMTP); los despliegues de vista previa exigen sesión de Vercel; los datos demo son compartidos por
  todos los visitantes — usa `python manage.py reset_demo` con `DATABASE_URL` apuntando al pooler para reiniciarlos.
