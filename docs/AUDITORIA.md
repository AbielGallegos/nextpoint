# Auditoría independiente del prototipo NextPoint

Fecha: 22/11/2026 · Versión auditada: commit inicial `2d8bf9a` · Versión corregida: commit de esta auditoría.
Entorno: servidor real sin DEBUG (`collectstatic` + WhiteNoise), **PostgreSQL 16**, Chrome headless (Playwright), Python 3.13, Django 5.2.19. Datos restablecidos con `reset_demo` antes de cada bloque. Scripts y salidas en `tools/auditoria/`.

## 1. Método

| Bloque | Técnica | Alcance |
| --- | --- | --- |
| Rastreo de interfaces | `crawl.py`: sigue todos los enlaces internos de cada rol, analiza cada formulario y botón, y prueba cada destino POST | 8 perfiles (incluido anónimo), 346 páginas, 224 destinos POST |
| E2E en navegador | `e2e_browser.py`: clics reales, diálogos modales, dos sesiones simultáneas gestor ↔ estudiante | E2E‑01…07, 68 comprobaciones |
| Roles y seguridad | `security.py` + `inject.py` | 124 rutas privadas como anónimo, 75 rutas y 95 acciones POST de panel como estudiante, IDOR, métodos, CSRF, sesión, cabeceras, XSS, CSV |
| Base de datos | `invariants.py` tras ejecutar todos los E2E | 22 invariantes de inventario, estados, folios, auditoría y progreso |
| Responsive | `responsive.py`: mide desbordamiento horizontal con JS en cada plantilla | 384 vistas (7 perfiles × 3 anchos) + menús móviles |
| Regresión | `manage.py test tests` | 89 pruebas en PostgreSQL y SQLite |

## 2. Hallazgos y correcciones

| ID | Severidad | Hallazgo (cómo se detectó) | Corrección | Evidencia de cierre |
| --- | --- | --- | --- | --- |
| F01 | Media | El personal veía en «Ayuda» un enlace a `/app/solicitudes/nueva/` que respondía 403 (rastreo: 5 perfiles) | Enlace visible solo para estudiantes | Rastreo final sin 403; `test_f01` |
| F02 | Baja | «Reportar un problema con este material» abría el formulario sin categoría ni referencia (función aparente) | Preselecciona «Reporte de material dañado» y prellena el asunto con folio y recurso | `test_f02` |
| F03 | Media | El filtro «Modalidad» de SmartMatch no excluía materiales y el filtro «Nivel» era ambiguo (función aparente) | Materiales declaran modalidad presencial; sin modalidad no se presume compatibilidad; nivel solo afecta cursos y así se rotula | `test_f03` |
| F04 | Media | El buscador superior del panel enviaba a la bandeja de casos aun a perfiles sin acceso (admin/soporte → 403) | Buscador solo para perfiles con bandeja de casos | `test_f04` |
| F05 | Alta | Sin límite por IP: 25 intentos con correos rotativos no se bloqueaban (`security.py`) | Límite adicional de 20 intentos / 15 min por IP (además de 5 por correo+IP) | Sonda final 429; `test_f05` |
| F06 | Media | El CSV de préstamos podía contener fórmulas (`=HYPERLINK…`) en nombres de recursos (inyección latente) | Celdas que empiezan con `= + - @` se prefijan con `'` en todas las exportaciones | `test_f06` |
| F07 | Baja | `/favicon.ico` respondía 404 en cada visita (consola del navegador) | Redirección permanente al icono | Consola final sin ese 404; `test_favicon` |
| F08 | Media | Pasar a mantenimiento un ejemplar con apartado vigente no avisaba; el préstamo quedaba bloqueado sin explicación | Aviso con los folios afectados y la acción recomendada | `test_f08` |
| F09 | Media | El simulador de SmartMatch evaluaba como personal y omitía oportunidades dirigidas a estudiantes (resultado distinto al real) | Simulación con la audiencia estudiantil | `test_f09` |
| F10 | Alta | **Desbordamiento horizontal** en 10 vistas: acceso e inicio en 390 px, panel e informes en 390 px, SmartMatch admin en 820 px (columnas `1fr` con contenido ancho) | Rejillas `minmax(0,1fr)`, cabeceras de tarjeta con ajuste de línea, botones de cuentas demo ajustables | 384 vistas, 0 desbordamientos |
| F11 | Media | Las tarjetas de selección (categoría/necesidad) tenían el `input` invisible encima de la etiqueta; la automatización no podía pulsar la etiqueta | `input` reducido a 1 px; la etiqueta recibe el clic y el foco sigue visible | E2E‑02/03 en navegador |
| F12 | Media | El tamaño de página configurado por coordinación para su campus no se aplicaba (se leía la política global) — función aparente | La paginación usa la política del campus de la cuenta | `test_f21` |
| F13 | Baja | «Satisfacción» en informes solo contaba valoraciones | Promedio, positivas (4–5) y tamaño de muestra | `test_satisfaction_average` |
| F14 | Baja | La maqueta del sitio público mostraba un folio sin aclarar que es ilustrativo | Rótulo «Vista ilustrativa · no son registros reales» | Revisión visual |
| F15 | Info | TC‑010 (expiración de sesión) no tenía prueba | Prueba que fuerza la caducidad en BD y exige login | `test_tc010` |

Comprobaciones sin hallazgos: CSRF en los 224 destinos POST, sin 500 en ninguna ruta, IDOR horizontal (404), escalamiento vertical (403/404), métodos GET sobre acciones (405), redirección abierta en el login, rotación de la sesión al entrar, cookies HttpOnly, CSP/XFO/no‑store, recuperación sin enumeración, XSS almacenado en casos, respuestas, recursos y avisos (se muestra como texto), notas internas ocultas y separación de funciones.

## 3. Matriz por módulo

Estado: **Verificado** = funciona con evidencia de navegador, servidor y BD. **Verificado con límites** = funciona, pero con alcance documentado.

| Módulo | Estado real | Pruebas ejecutadas (evidencia) | Errores encontrados | Correcciones |
| --- | --- | --- | --- | --- |
| A. Sitio público y autenticación | Verificado | Rastreo anónimo 5/5; login por rol 7/7; rate limit; recuperación sin enumeración; fijación de sesión; logout POST; sesión caducada | F05, F07, F14, F15 | Límite por IP, favicon, rótulo, prueba TC‑010 |
| Usuarios, roles e invitaciones | Verificado | Invitación → activación → panel (E2E‑07 en navegador); un solo uso; suspensión cierra sesiones; coordinación no otorga roles técnicos; última cuenta admin protegida | — | — |
| Control de acceso (RBAC+ABAC) | Verificado | 124 rutas anónimas → login; 75 GET + 95 POST de panel como estudiante → 403/404; IDOR; admin sin casos; docente fuera de módulos ajenos | F01, F04 | Enlaces y buscador según permiso |
| B. Dashboard del estudiante | Verificado | Contadores = listados (E2E‑01/02 en navegador); 1 préstamo activo durante el préstamo | F10 (390 px) | Rejilla responsive |
| C. SmartMatch | Verificado | E2E‑03: necesidad → JS rellena criterios → kit 100 pts → explicación → desglose → comparar → detalle → solicitud → cancelación; regla inválida no se activa; simulador | F03, F09, F11 | Filtros reales, simulador estudiantil, clic en tarjetas |
| D. Catálogo e inventario | Verificado | Alta de categoría, recurso, ejemplar; publicar exige ejemplares; fuera de servicio desaparece; movimientos append‑only; invariante prestado ⇔ préstamo activo | F08 | Aviso de apartados afectados |
| E. Préstamos | Verificado | E2E‑01 en navegador (disponible → ocupado → disponible, 17 comprobaciones); E2E‑07 con dos gestores reales y prueba de hilos en PostgreSQL; daño → mantenimiento; cancelado no se entrega; sin autoaprobación; 0 traslapes en BD | F02 | Reporte de material vinculado |
| F. Solicitudes e incidencias | Verificado | E2E‑02 en navegador: acuse ≠ resolución, nota interna oculta, respuesta pública, mensaje del estudiante, resolver (diálogo), cerrar, notificación que abre el caso, valoración, historial completo | F11 | Clic en tarjetas de categoría |
| G. Alertas y oportunidades | Verificado | E2E‑04 en navegador: borrador invisible → publicar → inicio y bandeja → leído → conteo de lecturas → retirar; expiración (prueba automatizada); otro campus oculto; global sin permiso negado | — | — |
| H. Cursos y tutoriales | Verificado | E2E‑05 en navegador: docente crea curso y 2 lecciones → revisión invisible → gestor publica → 0 → 50 → 100 % → persiste en nueva sesión → vista admin 100 % | — | — |
| I. Notificaciones y soporte | Verificado | Notificaciones de creación, aprobación, entrega, devolución, acuse, respuesta, cierre y aviso; ajena → 404; sin duplicados en BD; ticket técnico con nota interna oculta | — | — |
| J. Panel administrativo | Verificado | KPIs = consultas BD y = contadores de bandeja (TC‑057); cambian al recargar tras una acción; cola, vencidos, accesos rápidos | F10 | Responsive |
| K. Reportes, exportación y auditoría | Verificado | Conteos = BD por periodo/área; CSV minimizado y auditado; gestor sin exportación; auditoría append‑only acotada; 22 invariantes | F06, F13 | CSV seguro, satisfacción real |
| Configuración y parámetros | Verificado | Versionado de políticas; rango validado; pagos bloqueados; bandera de módulo de cursos → 503 | F12 | Política por campus |
| Responsive y accesibilidad | Verificado con límites | 384 vistas sin desbordamiento; menú lateral en 390/820; navegación inferior móvil y «Más» | F10, F11 | CSS |
| Salud, respaldo y operación | Verificado | `/health` sin secretos; backup → restore idéntico; reset exige confirmación; producción sin DEBUG sirve estáticos | — | — |

Límites que siguen abiertos (no se presentan como terminados): auditoría WCAG 2.2 con lector de pantalla, matriz formal de navegadores y prueba de carga (NFR‑01/04), cuestionarios de curso, lista de espera y recordatorios programados, MFA y verificación de correo, revisión formal de logs (TC‑079) y respaldo fallido forzado (TC‑080). Detalle en `docs/FUNCIONALIDADES.md`.

## 4. Resultados de la re‑ejecución final

| Bloque | Resultado |
| --- | --- |
| Pruebas automatizadas, PostgreSQL 16 | **89/89 OK** (incluye concurrencia real con hilos) |
| Pruebas automatizadas, SQLite | **88 OK, 1 omitida** (concurrencia con hilos solo en PostgreSQL) |
| E2E en navegador | **68/68** comprobaciones OK; consola solo con los 5 rechazos 403/404 provocados a propósito en E2E‑06 |
| Rastreo | 346 páginas en 8 perfiles: 0 respuestas 4xx/5xx inesperadas, 0 enlaces sin destino, 0 botones sin comportamiento, 0 POST sin CSRF |
| Seguridad | 16/16 sondas OK; inyección 7/7 OK |
| Invariantes de BD | 22/22 OK tras todos los E2E |
| Responsive | 384 vistas, 0 desbordamientos; menús móviles OK |
