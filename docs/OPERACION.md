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
