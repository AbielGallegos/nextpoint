# Registro de funcionalidades

Estado real al 22/11/2026, después de la auditoría independiente (`docs/AUDITORIA.md`). «Terminado» = vista + validación en servidor + persistencia + permisos + prueba automatizada o verificación manual registrada.

## P0 — obligatorio para la demostración

| Funcionalidad | Estado | Evidencia |
| --- | --- | --- |
| Inicio/cierre de sesión, sesiones protegidas, límite de intentos por correo+IP y por IP | Terminado | TC‑001…004, TC‑010, F05 |
| Separación de roles (7 perfiles) con RBAC + alcance área/campus/propietario/asignado | Terminado | TC‑005, TC‑006, E2E‑06 |
| Alta de cuentas privilegiadas solo por invitación de un uso | Terminado | TC‑009, TC‑007 |
| Dashboard del estudiante con contadores reales, vencimientos, actividad, avisos y sugerencias | Terminado | `test_dashboard_counters_match_lists` |
| Catálogo con búsqueda, filtros, ficha y disponibilidad calculada | Terminado | E2E‑01, TC‑024 |
| SmartMatch determinista (40/25/15/15/5), explicación, desglose, comparación, acción de solicitud | Terminado | E2E‑03, TC‑038…045 |
| Préstamos: folio, aprobación transaccional, entrega, devolución, mantenimiento, historial | Terminado | E2E‑01, E2E‑07, TC‑017, TC‑020, TC‑023 |
| Inventario: recursos, ejemplares, ubicaciones, estados, movimientos append‑only | Terminado | TC‑033, TC‑064 |
| Solicitudes/incidencias: folio, acuse ≠ resolución, notas internas ocultas, asignación, cierre, valoración | Terminado | E2E‑02, TC‑026, TC‑032 |
| Avisos: borrador, ámbito autorizado, audiencia, vigencia, lectura individual | Terminado | E2E‑04, TC‑052, TC‑055, TC‑056 |
| Cursos: curso demo con 2 lecciones, inscripción, progreso 0→50→100 % | Terminado | E2E‑05 |
| Notificaciones internas idempotentes con verificación al abrir | Terminado | E2E‑01/02, notificación ajena 404 |
| Panel administrativo con KPIs reales, cola de trabajo, vencidos | Terminado | TC‑057 |
| Auditoría append‑only con actor, acción, fecha, entidad, antes/después, trace_id | Terminado | `test_audit_scoped_and_append_only`, TC‑062 |
| Seguridad básica: CSRF, XSS, ORM, CSP, no‑store, secretos en .env | Terminado | TC‑072…074, cabeceras |
| Datos sintéticos idempotentes y reinicio | Terminado | TC‑076, `reset_demo` |

## P1 — MVP institucional

| Funcionalidad | Estado | Nota |
| --- | --- | --- |
| Administración de usuarios: listado, invitar, suspender/reactivar (cierra sesiones), asignar/retirar roles | Terminado | TC‑008, TC‑062/063 |
| Recuperación de acceso con token de un solo uso (30 min), sin enumerar correos | Terminado | Envío por consola (sin SMTP) |
| Cambio de contraseña con reautenticación y notificación | Terminado | |
| Revisión editorial de cursos (borrador → revisión → publicado/devuelto → archivado) | Terminado | E2E‑05 |
| Panel de reglas SmartMatch: borrador validado, simulador, activación versionada, necesidades | Terminado | TC‑042…044 |
| Informes por periodo/área (tasa de acuse en días hábiles, medianas, préstamos, formación) | Terminado | E2E‑08 |
| Exportación CSV minimizada y auditada | Terminado | TC‑060/061 |
| Adjuntos privados validados por firma y tamaño | Terminado | TC‑034, TC‑075 |
| Mesa de soporte técnico (tickets, notas internas, resolución) | Terminado | Verificado manualmente |
| Parámetros operativos versionados y banderas de módulo (cursos, SmartMatch) | Terminado | Verificado manualmente |
| Respaldo y restauración de la base de ensayo | Terminado | TC‑067 |
| Accesibilidad: foco visible, etiquetas, errores anunciados, estados con texto+icono, reducción de movimiento | Parcial | Falta auditoría formal WCAG 2.2 con lector de pantalla |
| Evaluaciones / cuestionarios de curso | Pendiente | Modelo preparado para agregar `Quiz` por lección |
| Lista de espera y recordatorios automáticos de vencimiento | Pendiente | Se listan vencidos y por vencer en el panel; no hay tarea programada |
| MFA administrativa, verificación de correo | Pendiente | Requiere proveedor; no se simula |
| Encuesta de satisfacción configurable | Parcial | Valoración 1–5 opcional por caso cerrado |

## P2 — evolución

| Funcionalidad | Estado | Base preparada |
| --- | --- | --- |
| QR por ejemplar | Pendiente | `ResourceUnit.serial` único |
| Multisede / transferencias | Parcial | Modelo multi‑campus e institución; dos campus en la demo |
| Analítica avanzada / personalización | Pendiente | `MatchQuery` agregable sin datos sensibles |
| Constancias internas no oficiales | Pendiente | `Enrollment.completed_at` |
| Pagos reales | Excluido | `payments_enabled` bloqueado en código |

## Limitaciones conocidas

- Sin calendario institucional de asuetos: los días hábiles son lunes a viernes.
- La concurrencia real se probó en PostgreSQL 16; en SQLite se garantiza por serialización `IMMEDIATE`, no se ejecuta la prueba con hilos.
- La prueba visual responsive se hizo con Chrome headless en 1366 px y 390 px; falta una matriz formal de navegadores (NFR‑04) y prueba de carga (NFR‑01).
