"""Graba un recorrido real de NextPoint con subtítulos. Las acciones ocurren de verdad en el servidor."""
import os
import re

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8000"
PW = os.environ["NEXTPOINT_DEMO_PASSWORD"]
OUT = "/home/claude/audit/video"

CAPTION_JS = """(t) => {
  let el = document.getElementById('__cap');
  if (!el) { el = document.createElement('div'); el.id='__cap'; document.body.appendChild(el); }
  el.setAttribute('style','position:fixed;left:50%;bottom:28px;transform:translateX(-50%);z-index:9999;max-width:82%;'+
   'background:rgba(15,20,48,.92);color:#fff;font:600 19px Inter,system-ui,sans-serif;padding:12px 22px;border-radius:14px;'+
   'box-shadow:0 10px 30px rgba(0,0,0,.35);text-align:center;pointer-events:none;'+(innerWidth<600?'bottom:auto;top:70px;font-size:15px;max-width:92%;':'')+'line-height:1.35;border:1px solid rgba(247,156,15,.6)');
  el.textContent = t;
}"""


def run(width=1366, height=800, mobile=False):
    with sync_playwright() as p:
        b = p.chromium.launch(channel="chrome", args=["--no-sandbox"], slow_mo=280)
        ctx = b.new_context(viewport={"width": width, "height": height}, record_video_dir=OUT, record_video_size={"width": width, "height": height})
        pg = ctx.new_page()

        def cap(text, wait=2600):
            pg.evaluate(CAPTION_JS, text)
            pg.wait_for_timeout(wait)

        def go(url):
            pg.goto(BASE + url)
            pg.wait_for_load_state("networkidle")

        def login(email_btn, label):
            go("/acceso/")
            cap(f"Inicio de sesión como {label}", 1800)
            pg.get_by_role("button", name=re.compile(email_btn)).click()
            pg.fill("#id_password", PW)
            pg.get_by_role("button", name="Entrar").click()
            pg.wait_for_load_state("networkidle")

        def logout():
            pg.locator("details.user-menu summary").click()
            pg.get_by_role("button", name="Cerrar sesión").click()
            pg.wait_for_load_state("networkidle")

        def scroll(px=500, wait=1200):
            pg.mouse.wheel(0, px)
            pg.wait_for_timeout(wait)

        if mobile:
            login("alumno.demo1", "estudiante (celular)")
            cap("Portal del estudiante en celular: navegación inferior", 2600)
            scroll(700); scroll(700)
            pg.locator(".bottom-nav a", has_text="SmartMatch").click(); pg.wait_for_load_state("networkidle")
            pg.locator("label", has_text="Material de redes").click()
            pg.get_by_role("button", name="Buscar coincidencias").click(); pg.wait_for_load_state("networkidle")
            pg.locator("#h-res").scroll_into_view_if_needed()
            cap("SmartMatch también funciona en pantalla pequeña", 2800)
            pg.locator(".bottom-nav a", has_text="Más").click()
            cap("«Más» abre el menú completo", 2400)
            ctx.close(); b.close()
            return

        go("/")
        cap("NextPoint · recursos, préstamos, solicitudes y oportunidades educativas (datos sintéticos)", 3200)
        scroll(650, 1500)

        # 1. Estudiante
        login("alumno.demo1", "estudiante")
        cap("Inicio del estudiante: los contadores se calculan con sus registros reales", 3200)
        pg.get_by_role("link", name="SmartMatch").first.click(); pg.wait_for_load_state("networkidle")
        cap("SmartMatch: el estudiante elige qué necesita", 2200)
        pg.locator("label", has_text="Material de redes").click()
        cap("Al elegir la necesidad se completan categoría y etiquetas", 2400)
        pg.get_by_role("button", name="Buscar coincidencias").click(); pg.wait_for_load_state("networkidle")
        pg.locator("#h-res").scroll_into_view_if_needed()
        cap("Cada recomendación dice por qué aparece: puntaje determinista, sin IA externa", 3200)
        first = pg.locator("article.match-card").first
        first.locator("summary").click()
        cap("Desglose: categoría 40 · etiquetas 25 · campus 15 · disponibilidad 15 · vigencia 5", 3200)
        first.get_by_role("link", name=re.compile("Ver y solicitar")).click(); pg.wait_for_load_state("networkidle")
        cap("Ficha del Kit de redes: 1 ejemplar disponible hoy", 2600)
        pg.get_by_role("link", name="Solicitar préstamo").click(); pg.wait_for_load_state("networkidle")
        pg.locator("#f-purpose").type("Práctica de redes de la materia (demostración)", delay=25)
        cap("Fechas y finalidad; el servidor valida políticas y existencias", 2200)
        pg.get_by_role("button", name="Enviar solicitud").click(); pg.wait_for_load_state("networkidle")
        folio = pg.locator(".page-head .tag").first.inner_text()
        cap(f"Solicitud registrada con folio {folio} y línea de tiempo", 3200)
        logout()

        # 2. Gestor de laboratorio
        login("gestor.laboratorio", "gestor de laboratorio")
        cap("Panel administrativo: indicadores reales de su área", 3000)
        pg.get_by_role("link", name="Préstamos").first.click(); pg.wait_for_load_state("networkidle")
        cap(f"La solicitud {folio} llegó a la cola del gestor", 2600)
        pg.get_by_role("link", name=folio).click(); pg.wait_for_load_state("networkidle")
        pg.fill("#ap-note", "Recoger en ventanilla de 9 a 13 h")
        cap("Aprobar vuelve a validar existencias dentro de una transacción", 2600)
        pg.get_by_role("button", name="Aprobar y apartar ejemplar").click(); pg.wait_for_load_state("networkidle")
        cap("Aprobado: el ejemplar KR-0001 queda apartado", 2600)
        pg.get_by_role("button", name="Registrar entrega").click(); pg.wait_for_load_state("networkidle")
        cap("Entrega registrada: el inventario pasa a «Ocupado»", 2600)
        go("/panel/recursos/")
        cap("Inventario: Kit de redes 0/1 · Ocupado", 2800)
        logout()

        # 3. El estudiante ve el cambio
        login("alumno.demo1", "estudiante")
        cap("De vuelta como estudiante: el inicio ya muestra 1 préstamo activo", 3000)
        pg.locator(".topbar a[href*=notificaciones]").click(); pg.wait_for_load_state("networkidle")
        cap("Notificaciones internas generadas por las acciones del gestor", 3000)
        go("/app/prestamos/")
        pg.get_by_role("link", name=folio).click(); pg.wait_for_load_state("networkidle")
        cap("Seguimiento: Solicitado → Aprobado → Entregado, con fecha y responsable", 3200)
        # Reporte de incidencia
        go("/app/solicitudes/nueva/")
        pg.locator("label", has_text="Incidencia en instalaciones o equipo").click()
        pg.locator("#f-subject").type("Proyector del aula sin señal", delay=25)
        pg.locator("#f-description").type("El proyector no detecta la laptop en el aula de prácticas.", delay=15)
        pg.get_by_role("button", name="Registrar solicitud").click(); pg.wait_for_load_state("networkidle")
        case_folio = pg.locator(".page-head .tag").first.inner_text()
        cap(f"Reporte registrado con folio {case_folio}", 2600)
        logout()

        # 4. Gestor de servicios: acuse ≠ resolución
        login("gestor.servicios", "gestora de servicios")
        go("/panel/solicitudes/")
        cap("Bandeja de solicitudes con filtros por estado, área, responsable y antigüedad", 2800)
        pg.get_by_role("link", name=case_folio).click(); pg.wait_for_load_state("networkidle")
        pg.get_by_role("button", name="Acusar recibo").click(); pg.wait_for_load_state("networkidle")
        cap("Acuse de recibo: confirma la recepción, pero el caso sigue abierto", 3000)
        pg.fill("#reply", "Revisar cable HDMI del aula 3")
        pg.get_by_role("button", name="Guardar como nota interna").click(); pg.wait_for_load_state("networkidle")
        cap("Nota interna: el estudiante nunca la ve", 2600)
        pg.get_by_role("button", name="Resolver").click()
        pg.locator("#res").type("Se cambió el cable HDMI; el proyector funciona.", delay=15)
        cap("Acción sensible: confirmación con texto obligatorio", 2200)
        pg.locator("#dlg-resolve").get_by_role("button", name="Marcar como resuelto").click(); pg.wait_for_load_state("networkidle")
        pg.locator(".timeline").scroll_into_view_if_needed()
        cap("Historial completo con actor, fecha y estados", 3000)
        logout()

        # 5. Estudiante confirma
        login("alumno.demo1", "estudiante")
        go("/app/solicitudes/")
        pg.get_by_role("link", name=case_folio).click(); pg.wait_for_load_state("networkidle")
        cap("El estudiante ve la resolución, pero no la nota interna", 3000)
        pg.get_by_role("button", name="Confirmar resolución").click(); pg.wait_for_load_state("networkidle")
        cap("Confirmó: caso cerrado, puede valorar la atención", 2600)
        # Curso
        go("/app/cursos/")
        pg.get_by_role("link", name=re.compile("Introducción a redes")).first.click(); pg.wait_for_load_state("networkidle")
        pg.get_by_role("button", name="Inscribirme").click(); pg.wait_for_load_state("networkidle")
        pg.get_by_role("link", name=re.compile("Comenzar")).click(); pg.wait_for_load_state("networkidle")
        cap("Curso de ejemplo con lecciones originales", 2400)
        scroll(500, 900)
        pg.get_by_role("button", name=re.compile("Marcar como completada")).click(); pg.wait_for_load_state("networkidle")
        cap("Lección 1 completada: avance 50 %", 2600)
        pg.get_by_role("button", name=re.compile("Marcar como completada")).click(); pg.wait_for_load_state("networkidle")
        cap("Lección 2 completada: avance 100 % (guardado en la base de datos)", 3000)
        # Seguridad
        pg.goto(BASE + "/app/solicitudes/1/")
        cap("Si intenta abrir la solicitud de otra alumna: no encontrada (404)", 3000)
        pg.goto(BASE + "/panel/")
        cap("Y el panel administrativo: acceso restringido (403), validado en el servidor", 3000)
        go("/app/")
        logout()

        # 6. Coordinación
        login("coord.demo", "coordinación")
        go("/panel/informes/")
        cap("Informes calculados con los registros: tasas, medianas, préstamos, formación", 3400)
        scroll(600, 1500)
        go("/panel/auditoria/")
        cap("Auditoría: cada acción de la demo quedó registrada (solo inserción)", 3400)
        go("/panel/smartmatch/?simular=1&category=materiales&tags=redes")
        cap("Reglas de SmartMatch versionadas y simulador sin publicar cambios", 3200)
        go("/")
        cap("NextPoint · prototipo funcional con datos sintéticos", 2400)
        ctx.close()
        b.close()


if __name__ == "__main__":
    import shutil
    import sys

    shutil.rmtree(OUT, ignore_errors=True)
    run(mobile="mobile" in sys.argv, width=390 if "mobile" in sys.argv else 1366, height=780 if "mobile" in sys.argv else 800)
    print([f for f in os.listdir(OUT)])
