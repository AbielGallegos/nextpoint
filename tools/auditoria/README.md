# Herramientas de auditoría

Scripts usados en la auditoría independiente (ver `docs/AUDITORIA.md`). Se ejecutan contra un servidor real en `127.0.0.1:8000` y requieren `NEXTPOINT_DEMO_PASSWORD` en el entorno.

| Script | Qué comprueba |
| --- | --- |
| `serve.sh` | Reinicia la base de **ensayo** PostgreSQL, ejecuta `collectstatic` y levanta el servidor sin DEBUG. Ajusta `DATABASE_URL` a tu entorno. |
| `crawl.py` | Rastrea todas las pantallas por rol; detecta 4xx/5xx, enlaces sin destino, botones sin comportamiento y formularios POST sin CSRF. |
| `e2e_browser.py` | E2E‑01…07 en Chrome real con clics, diálogos y dos sesiones simultáneas (gestor ↔ estudiante). Requiere `playwright`. |
| `security.py` | Matriz de acceso (anónimo, estudiante, docente, admin), IDOR, métodos, CSRF, redirección abierta, fijación de sesión, cabeceras, enumeración, fuerza bruta. Ejecuta `crawl.py` antes. |
| `inject.py` | XSS almacenado en campos libres e inyección de fórmulas en CSV. |
| `invariants.py` | 22 invariantes de la base: inventario ↔ préstamos, estados ↔ eventos, folios, auditoría, progreso. |
| `responsive.py` | Desbordamiento horizontal en 390/820/1366 px y menús móviles, sobre las URLs reales del rastreo. |

`evidencia/` contiene las salidas de la ejecución final del 22/11/2026.
