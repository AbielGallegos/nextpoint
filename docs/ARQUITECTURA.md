# Arquitectura de NextPoint (prototipo)

## 1. Decisión de stack (auditoría, fase 1)

| Opción | Hallazgo | Decisión |
| --- | --- | --- |
| Repositorio existente `AbielGallegos/HackPony2026` | Next.js 16 + Supabase. Implementa **otro producto** (marketplace de micro‑retos del HackPony: retos, postulaciones, % de compatibilidad). No contiene catálogo, préstamos, casos, cursos ni avisos. Exige Supabase en la nube (responde 503 sin él). | **Se conserva intacto** como entrega del HackPony. No se reemplaza ni modifica. |
| Desarrollo nuevo | La especificación (§18.2) recomienda Django + PostgreSQL + HTML/JS ligero para un desarrollo nuevo; exige demo sin dependencia de internet (§21.3, TC‑077). | **Django 5.2, monolito modular.** |

Se reutilizó del repo anterior: logotipo y paleta (morado `#592CCD`, naranja `#F79C0F`, azul noche `#171B40`), la convención de contraseña demo generada localmente y nunca publicada, y la falla segura ante configuración incompleta.

## 2. Módulos (apps por dominio)

```
config/            settings (todo por variables de entorno), urls, wsgi
apps/
  accounts/        usuarios, institución/campus/áreas, roles, permisos, invitaciones, RBAC+ABAC (access.py)
  catalog/         categorías, ubicaciones, recursos, ejemplares, movimientos de inventario
  loans/           solicitudes de préstamo, préstamos, eventos; services.py = máquina de estados transaccional
  cases/           solicitudes de servicio/incidencias, eventos públicos/internos, adjuntos privados
  smartmatch/      pesos versionados, necesidades, motor determinista (engine.py), registro mínimo de consultas
  learning/        cursos, módulos, lecciones, inscripciones, progreso
  communications/  avisos/oportunidades, lecturas, notificaciones internas
  reporting/       panel, métricas (metrics.py), informes, exportación CSV, auditoría, API JSON mínima
  audit/           bitácora append-only y servicio de registro
  core/            sitio público, inicio del estudiante, soporte técnico, políticas versionadas, salud,
                   middleware (trace_id, CSP, no‑store), comandos (init_env, seed_demo, reset_demo, backup/restore)
templates/         layouts (public, portal, panel), parciales y vistas por módulo
static/            CSS del sistema visual, JS ligero, fuente Inter e imágenes (sin CDN)
tests/             pruebas de extremo a extremo y de seguridad
```

Reglas de dependencia: las vistas solo orquestan; **toda transición de estado vive en `services.py`** de cada dominio, dentro de transacciones, y registra evento + auditoría + notificación en la misma transacción. SmartMatch solo lee catálogo publicado; reportes solo leen.

## 3. Control de acceso

- **RBAC**: tablas `Role`, `Permission`, `RolePermission` (cargadas por la migración `accounts.0002` desde `access.py`).
- **ABAC**: cada `UserRole` tiene alcance **área**, **campus** o **global**. `scope_for(user, perm)` produce un filtro de queryset; `can_on(user, perm, area_id, campus_id)` valida un registro.
- Registros propios: el estudiante solo consulta filas con `applicant/creator = request.user`; un ID ajeno responde **404** (no revela existencia). Gestores de otra área también reciben 404 en detalle y 403 en acciones.
- Separación de funciones: nadie aprueba su propio préstamo ni atiende su propio caso; el autor de un curso no lo publica; soporte/administración técnica no leen casos de estudiantes.
- Roles privilegiados solo por **invitación** de un solo uso (token aleatorio, se guarda solo su hash SHA‑256, caduca en 7 días). Coordinación no puede otorgar roles técnicos; no se puede suspender la última cuenta de administración.
- Usuarios suspendidos: `is_active=False` + borrado de sus sesiones → no pueden usar enlaces antiguos.

| Permiso | Est. | Docente | Gestor (área) | Coord. (campus) | Soporte | Admin (global) |
| --- | :-: | :-: | :-: | :-: | :-: | :-: |
| portal.student / loans.request / cases.create | ✓ | | | | | |
| catalog.manage / loans.manage / cases.manage | | | ✓ | | | |
| cases.attend_assigned / courses.author | | ✓ | | | | |
| loans.supervise / cases.supervise (lectura) | | | | ✓ | | |
| courses.publish | | | ✓ | ✓ | | |
| alerts.publish_area / _campus / _global | | | área | ✓ / ✓ / ✓ | | |
| smartmatch.test / smartmatch.publish | | | ✓ / – | ✓ / ✓ | | ✓ / ✓ |
| reports.view / reports.export | | | ✓ / – | ✓ / ✓ | | |
| users.view / users.manage / users.manage_technical | | | ✓ / – / – | ✓ / ✓ / – | | ✓ / ✓ / ✓ |
| audit.view | | | área (negocio) | campus | | global |
| platform.health / platform.config / support.attend | | | | – / ✓ / – | ✓ / – / ✓ | ✓ / ✓ / ✓ |

## 4. Integridad de inventario

- La existencia **nunca** se toma del navegador. `approve()` bloquea la solicitud y **toca la fila del recurso** (`UPDATE … lock_version+1`), lo que serializa aprobaciones concurrentes en PostgreSQL (bloqueo de fila) y en SQLite (transacciones `IMMEDIATE`). Después elige un ejemplar operable sin apartados que se traslapen con las fechas.
- Restricción de BD: `UniqueConstraint(unit) WHERE returned_at IS NULL` en `Loan` (un préstamo activo por ejemplar) y `CHECK due_date >= start_date`.
- Estados del ejemplar: disponible → prestado → disponible / revisión / mantenimiento / baja. Movimientos `InventoryMovement` de solo inserción.
- Idempotencia: `idempotency_key` único por solicitante en préstamos y casos (doble clic = mismo folio).

## 5. Máquinas de estado

- **Préstamo:** solicitado → en_revision → aprobado → entregado → devuelto; desvíos rechazado (motivo obligatorio) y cancelado (libera el ejemplar).
- **Caso:** nuevo → clasificado → asignado → acusado → en_proceso → resuelto → cerrado; desvíos requiere_info, rechazado, cancelado. El **acuse** registra `acknowledged_at` y nunca cierra el caso; resolver exige texto; el estudiante confirma o pide revisión.
- **Curso:** borrador → en_revision → publicado → archivado; progreso secuencial y solo propio.
- **Aviso:** borrador → publicado → (programado/vigente/expirado calculado por fechas) → retirado.

## 6. Modelo de datos (equivalencias con la especificación)

| Especificación | Implementación |
| --- | --- |
| institutions, campuses, areas | `accounts.Institution`, `Campus`, `Area` |
| users, roles, permissions, user_roles | `accounts.User` (correo único, estado), `Role`, `Permission`, `RolePermission`, `UserRole` (alcance) |
| — | `StudentProfile`, `StaffProfile`, `Invitation`, `LoginAttempt` |
| resource_categories, resources, resource_units | `catalog.ResourceCategory`, `Resource`, `ResourceUnit`, `Location`, `InventoryMovement` |
| loan_requests, loans | `loans.LoanRequest` (folio `NP-PRE-xxxxx`), `Loan`, `LoanEvent` |
| service_requests, request_events | `cases.ServiceRequest` (folio `NP-SOL-xxxxx`), `RequestEvent` (público/interno), `ServiceCategory`, `RequestAttachment` |
| smartmatch_rules | `smartmatch.MatchRule` (pesos versionados), `Need`, `MatchQuery` |
| courses, course_modules, lessons, enrollments, lesson_progress | `learning.*` con las mismas entidades |
| alerts, alert_reads, notifications | `communications.Alert`, `AlertRead`, `Notification` (dedupe_key único) |
| audit_logs | `audit.AuditLog` (append‑only, trace_id) |
| system_policy, support_ticket | `core.SystemPolicy` (versionada), `SupportTicket`, `SupportMessage` |

Índices en (campus, status, created_at), (owner, status), (assigned_to, status), (resource, status). Migraciones versionadas en `apps/*/migrations`. Datos maestros (roles/permisos) separados de los datos demo (`seed_demo`).

## 7. SmartMatch

Determinista, sin IA externa. Candidatos: recursos publicados con ejemplares en servicio, asesorías y trámites activos, cursos publicados y oportunidades vigentes visibles para el usuario. Puntaje = categoría 40 + etiquetas 25 × (coincidencias / etiquetas pedidas) + campus 15 + disponibilidad 15 + vigencia 5 (≤ 90 días; mitad hasta 1 año). Solo se muestran resultados pertinentes (categoría o etiqueta) con puntaje ≥ mínimo de la versión activa. Desempate: disponibilidad → actualización → nombre → id. Entradas: necesidad, filtros y campus; **nunca** calificaciones, salud, discapacidad, origen o nivel socioeconómico. Cada resultado incluye desglose y frase explicativa. Pesos editables por coordinación, validados (suma 100) y probables en simulador antes de activarse.

## 8. Seguridad transversal

Hash PBKDF2 de Django; sesión con cookie HttpOnly/SameSite=Lax (Secure con HTTPS), caducidad por inactividad (2 h) y logout por POST que invalida la sesión; límite de 5 intentos/15 min por correo+IP (hash); mensajes de error que no enumeran cuentas; CSRF del framework; escape automático + CSP estricta sin scripts en línea; ORM (sin SQL concatenado); `Cache-Control: no-store` en páginas autenticadas; adjuntos validados por firma binaria, ≤ 5 MB, nombre regenerado, fuera de `static`, descarga autenticada; logs JSON con `trace_id` y redacción de secretos; secretos solo en `.env`; admin de Django no publicado.

## 9. Decisiones provisionales registradas

| Tema no definido en la especificación | Decisión provisional |
| --- | --- |
| Área de revisión de cursos | Cada curso declara un área; la publica un gestor de esa área o coordinación. |
| Reservas a futuro | Se aprueban por ventana de fechas; un ejemplar no puede tener ventanas traslapadas. |
| Calendario de días hábiles | Lunes a viernes sin asuetos; se rotula así en informes. |
| Correo | No hay SMTP: recuperación de contraseña a consola; invitaciones muestran el enlace una vez a quien invita. |
| Alcance de soporte técnico | Rol `soporte` sin acceso a casos/préstamos; ve salud y tickets técnicos. |
