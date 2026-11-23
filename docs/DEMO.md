# Demostración de NextPoint

## Preparación (30 minutos antes)

```bash
python manage.py reset_demo --yes     # estado inicial conocido (solo base de ensayo)
python manage.py runserver
```

- La contraseña de **todas** las cuentas demo está en `NEXTPOINT_DEMO_PASSWORD` de tu `.env`. No la proyectes.
- La app funciona sin internet: no usa CDN, fuentes externas, correo ni servicios de terceros.
- Usa dos navegadores (o una ventana privada) para tener estudiante y gestor a la vez.

## Cuentas

| Cuenta | Perfil | Alcance |
| --- | --- | --- |
| alumno.demo1@nextpoint.test | Estudiante | Campus 2 · sin préstamos activos (historial: un préstamo devuelto y un caso cerrado) |
| alumna.demo2@nextpoint.test | Estudiante | Campus 2 · laptop prestada **vencida**, solicitud de multímetro pendiente, caso en proceso con nota interna |
| gestor.laboratorio@nextpoint.test | Gestor de materiales | Área «Laboratorios y materiales» |
| gestor.servicios@nextpoint.test | Gestor de solicitudes | Área «Atención y servicios estudiantiles» |
| docente.demo@nextpoint.test | Instructor | Autor de los cursos demo |
| coord.demo@nextpoint.test | Coordinación | Campus 2 (supervisión, informes, usuarios, SmartMatch) |
| admin.demo@nextpoint.test | Administración técnica | Plataforma (roles técnicos, auditoría, salud, soporte) |

## Datos sintéticos incluidos

Kit de redes de laboratorio (**1 ejemplar**), multímetros (2), kits de microcontrolador (2), laptops (3), proyector (1), osciloscopio en borrador sin ejemplares, kit del Campus 1 (aislamiento); 6 categorías de servicio; curso publicado «Introducción a redes» con **2 lecciones originales** y curso en borrador; avisos: borrador «Entrega de materiales del laboratorio esta semana», convocatoria vigente, aviso de mantenimiento, aviso vencido y aviso exclusivo del Campus 1; reglas SmartMatch v1 (40/25/15/15/5) y 7 necesidades.

## Guion de 5 minutos

| Min | Acción | Mensaje |
| --- | --- | --- |
| 0:00 | Entra como **alumno.demo1** → Inicio. | Contadores calculados con sus registros. |
| 0:40 | **SmartMatch** → «Material de redes» → Buscar. El kit sale con 100 pts; abre «Ver desglose». | Orientación explicable y con disponibilidad real. |
| 1:25 | «Solicitar» → fechas → Enviar. Se muestra el folio `NP-PRE-…` y su línea de tiempo. | Ya no depende de mensajes dispersos. |
| 2:00 | Otra ventana: **gestor.laboratorio** → Préstamos → folio → Aprobar → Registrar entrega → Registrar devolución (disponible). En Recursos el kit pasa Disponible → Ocupado → Disponible. | Control, transacción e historial. |
| 2:50 | Estudiante: **Solicitudes → Nueva** («Consulta de disponibilidad de laboratorio»). **gestor.servicios** → Acusar recibo (el estudiante ve «Recibido», sigue abierto) → Resolver → Cerrar. | Acuse ≠ resolución; cada evento tiene responsable. |
| 3:35 | Estudiante: **Avisos** (convocatoria) y **Cursos** → inscribirse → completar lección 1 (50 %) y 2 (100 %). | Información y aprendizaje en un lugar. |
| 4:15 | **coord.demo** → Resumen, Informes (cifras = registros), Auditoría con el préstamo y el caso recién hechos. | Datos reales dentro de la demo ficticia. |

## Escenarios E2E (todos automatizados en `tests/`)

| ID | Recorrido manual | Prueba automatizada |
| --- | --- | --- |
| E2E‑01 | Estudiante → Kit → Solicitud → Folio → Gestor aprueba → Entrega → Devolución → Inventario disponible | `test_loans.LoanFlowTests.test_e2e01_full_loan_flow_inventory_available_busy_available` |
| E2E‑02 | Nueva solicitud → Folio → Acuse → Respuesta → Nota interna oculta → Resolución → Cierre → Notificación → Historial | `test_cases.CaseFlowTests.test_e2e02_full_flow` |
| E2E‑03 | SmartMatch → Recomendación → Explicación → Detalle → Solicitud | `test_smartmatch.SmartMatchTests.test_e2e03_need_to_request` |
| E2E‑04 | Gestor crea borrador → Publica → Estudiante lee → Marca leído → Expira | `test_alerts_courses.AlertTests.test_e2e04_draft_publish_read_expire` (en vivo puedes publicar el borrador sembrado «Entrega de materiales…») |
| E2E‑05 | Docente crea curso y 2 lecciones → Envía a revisión → Gestor publica → Estudiante 0 → 50 → 100 % | `test_alerts_courses.CourseTests.test_e2e05_author_review_enroll_progress` |
| E2E‑06 | alumno.demo1 abre `/app/solicitudes/<id de alumna>/` → 404; abre `/panel/` → 403; gestor.laboratorio abre un caso de servicios → 404 | `test_auth_security` (TC‑005, TC‑006, E2E‑06) |
| E2E‑07 | Dos solicitudes compiten por el único kit; dos gestores aprueban en paralelo → una gana, la otra recibe «No hay ejemplares libres» | `test_loans.ConcurrencyTests` (PostgreSQL, hilos reales) y `test_tc017_…` |

Para mostrar E2E‑06 en vivo: como **alumno.demo1** abre `http://127.0.0.1:8000/app/solicitudes/1/` (caso de la alumna 2) → página «No encontramos esta página»; y `http://127.0.0.1:8000/panel/` → «Acceso restringido · 403».

## Plan de respaldo

- `python manage.py backup_demo` antes de presentar; `restore_demo <archivo> --yes` si algo se descompone.
- Graba un video del recorrido y rotula las capturas como evidencias del prototipo (no como funcionamiento en vivo).
