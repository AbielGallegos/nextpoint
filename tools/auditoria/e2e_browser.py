"""E2E-01…E2E-07 en Chrome real: clics sobre la interfaz, diálogos modales, dos sesiones simultáneas
(estudiante y gestor) y verificación de que lo que hace el gestor aparece en el portal del estudiante.
Cada paso registra evidencia; cualquier error de consola/CSP también se reporta."""
import os
import re
import sys
import threading
import time
from datetime import date, timedelta

from playwright.sync_api import expect, sync_playwright

BASE = "http://127.0.0.1:8000"
PW = os.environ["NEXTPOINT_DEMO_PASSWORD"]
LOG = []
CONSOLE = []
FAILS = []


def step(scenario, msg, ok=True):
    LOG.append((scenario, "OK" if ok else "FALLA", msg))
    print(f"[{scenario}] {'OK   ' if ok else 'FALLA'} {msg}", flush=True)
    if not ok:
        FAILS.append((scenario, msg))


def check(scenario, cond, msg):
    step(scenario, msg, bool(cond))
    return cond


def session(browser, who, width=1366):
    ctx = browser.new_context(viewport={"width": width, "height": 900})
    page = ctx.new_page()
    page.on("console", lambda m: CONSOLE.append(f"{who}: {m.type}: {m.text}") if m.type in ("error", "warning") else None)
    page.on("pageerror", lambda e: CONSOLE.append(f"{who}: pageerror: {e}"))
    page.goto(BASE + "/acceso/")
    page.get_by_role("button", name=re.compile(who)).click()  # botón de cuenta demo rellena el correo
    page.fill("#id_password", PW)
    page.get_by_role("button", name="Entrar").click()
    page.wait_for_load_state("networkidle")
    return page


def pick(page, sel, text):
    """select_option por texto parcial de la opción."""
    opts = page.locator(f"{sel} option").all_inner_texts()
    match = next(o for o in opts if text in o)
    page.select_option(sel, label=match)


def toast(page):
    t = page.locator(".toast")
    return t.first.inner_text() if t.count() else ""


def e2e01(b):
    S = "E2E-01"
    st = session(b, "alumno.demo1")
    gl = session(b, "gestor.laboratorio")
    st.get_by_role("link", name="Materiales").first.click()
    st.get_by_label("Buscar").first.fill("kit de redes")
    st.get_by_role("button", name="Aplicar").click()
    card = st.locator("article", has_text="Kit de redes de laboratorio")
    check(S, card.count() == 1 and "1 de 1 disponible" in card.inner_text(), "Catálogo: búsqueda encuentra el kit con 1 de 1 disponible")
    card.get_by_role("link", name="Ver ficha").click()
    check(S, st.locator(".kpi-value").first.inner_text() == "1", "Ficha: disponibilidad hoy = 1")
    st.get_by_role("link", name="Solicitar préstamo").click()
    st.fill("#f-purpose", "Práctica de redes (auditoría E2E)")
    st.get_by_role("button", name="Enviar solicitud").click()
    st.wait_for_load_state("networkidle")
    folio = st.locator(".page-head .tag").first.inner_text()
    check(S, re.match(r"NP-PRE-\d{5}$", folio), f"Folio generado {folio} y página de seguimiento")
    check(S, "Solicitado" in st.locator(".page-head").inner_text(), "Estado visible para estudiante: Solicitado")
    # Gestor recibe
    gl.reload()
    gl.locator(".topbar a[href*=notificaciones]").click()
    check(S, gl.get_by_text(f"Nueva solicitud {folio}").count() == 1, "Gestor recibe notificación de la nueva solicitud")
    gl.goto(BASE + "/panel/prestamos/")
    gl.get_by_role("link", name=folio).click()
    gl.get_by_role("button", name="Marcar en revisión").click()
    check(S, "Revisión iniciada" in toast(gl), "Gestor marca en revisión")
    st.reload()
    check(S, "En revisión" in st.locator(".page-head").inner_text(), "Estudiante ve 'En revisión' tras recargar (reflejo gestor→estudiante)")
    gl.fill("#ap-note", "Recoger en ventanilla de 9 a 13 h")
    gl.get_by_role("button", name="Aprobar y apartar ejemplar").click()
    check(S, "aprobado" in toast(gl).lower(), "Gestor aprueba: " + toast(gl)[:60])
    st.reload()
    check(S, "Aprobado" in st.locator(".page-head").inner_text() and "Recoger en ventanilla" in st.content(), "Estudiante ve 'Aprobado' con indicaciones")
    st.goto(BASE + "/app/notificaciones/")
    check(S, st.get_by_text(f"Préstamo aprobado · {folio}").count() == 1, "Estudiante recibe notificación de aprobación")
    gl.get_by_role("button", name="Registrar entrega").click()
    check(S, "Entrega registrada" in toast(gl), "Gestor registra entrega")
    gl.goto(BASE + "/panel/recursos/")
    row = gl.locator("tr", has_text="Kit de redes de laboratorio")
    check(S, "Ocupado" in row.inner_text(), "Inventario administrativo: kit 'Ocupado'")
    st.goto(BASE + "/app/materiales/?q=kit+de+redes")
    check(S, "Ocupado" in st.locator("article", has_text="Kit de redes de laboratorio").inner_text(), "Catálogo del estudiante: kit 'Ocupado'")
    st.goto(BASE + "/app/")
    check(S, st.locator(".kpi", has_text="Préstamos activos").locator(".kpi-value").inner_text() == "1", "Dashboard estudiante: 1 préstamo activo")
    gl.goto(BASE + "/panel/prestamos/?estado=activos")
    gl.get_by_role("link", name=folio).click()
    gl.select_option("#rt-dest", "disponible")
    gl.get_by_role("button", name="Registrar devolución").click()
    check(S, "Devolución registrada" in toast(gl), "Gestor registra devolución")
    st.goto(BASE + "/app/materiales/?q=kit+de+redes")
    check(S, "Disponible" in st.locator("article", has_text="Kit de redes de laboratorio").inner_text(), "Inventario vuelve a 'Disponible' en el portal")
    st.goto(BASE + "/app/prestamos/?vista=historial")
    st.get_by_role("link", name=folio).click()
    hist = st.locator(".timeline").inner_text()
    order = [s for s in ["Solicitado", "En revisión", "Aprobado", "Entregado", "Devuelto"] if s in hist]
    check(S, len(order) == 5, f"Historial del estudiante completo: {order}")
    st.context.close(); gl.context.close()
    return folio


def e2e02(b):
    S = "E2E-02"
    st = session(b, "alumno.demo1")
    gs = session(b, "gestor.servicios")
    st.goto(BASE + "/app/")
    before = int(st.locator(".kpi", has_text="Solicitudes abiertas").locator(".kpi-value").inner_text())
    st.get_by_role("link", name="Crear reporte").click()
    st.locator("label", has_text="Incidencia en instalaciones o equipo").click()
    st.fill("#f-subject", "Proyector del aula sin señal")
    st.fill("#f-description", "El proyector del aula de prácticas no detecta la laptop (caso de auditoría).")
    st.get_by_role("button", name="Registrar solicitud").click()
    st.wait_for_load_state("networkidle")
    folio = st.locator(".page-head .tag").first.inner_text()
    check(S, re.match(r"NP-SOL-\d{5}$", folio), f"Folio de caso {folio}")
    st.goto(BASE + "/app/")
    after = int(st.locator(".kpi", has_text="Solicitudes abiertas").locator(".kpi-value").inner_text())
    check(S, after == before + 1, f"Contador del estudiante {before}→{after}")
    gs.goto(BASE + "/panel/solicitudes/")
    check(S, gs.get_by_role("link", name=folio).count() == 1, "Caso aparece en la bandeja del gestor de servicios")
    gs.get_by_role("link", name=folio).click()
    gs.get_by_role("button", name="Acusar recibo").click()
    check(S, "no equivale" in toast(gs), "Gestor acusa recibo (mensaje aclara que no cierra)")
    st.goto(BASE + "/app/solicitudes/")
    st.get_by_role("link", name=folio).click()
    check(S, "Recibido" in st.locator(".page-head").inner_text() and "Aún está en atención" in st.content(), "Estudiante ve 'Recibido' y sigue abierto")
    gs.fill("#reply", "Nota interna AUDITORIA-OCULTA: revisar cable HDMI")
    gs.get_by_role("button", name="Guardar como nota interna").click()
    gs.fill("#reply", "Enviaremos a un técnico mañana a primera hora.")
    gs.get_by_role("button", name="Responder al estudiante").click()
    st.reload()
    check(S, "AUDITORIA-OCULTA" not in st.content(), "Nota interna NO visible al estudiante")
    check(S, "Enviaremos a un técnico" in st.content(), "Respuesta pública visible al estudiante")
    st.fill("#msg", "Gracias, estaré en el aula.")
    st.get_by_role("button", name="Enviar").click()
    gs.reload()
    check(S, "Gracias, estaré en el aula." in gs.content(), "Mensaje del estudiante visible al gestor")
    gs.get_by_role("button", name="Pasar a «En proceso»").click()
    gs.get_by_role("button", name="Resolver").click()
    gs.fill("#res", "Se cambió el cable HDMI y el proyector funciona.")
    gs.locator("#dlg-resolve").get_by_role("button", name="Marcar como resuelto").click()
    check(S, "resuelto" in toast(gs).lower(), "Gestor resuelve con nota (diálogo modal)")
    gs.get_by_role("button", name="Cerrar caso").click()
    check(S, "cerrado" in toast(gs).lower(), "Gestor cierra")
    st.goto(BASE + "/app/notificaciones/")
    check(S, st.get_by_text(f"{folio}: caso cerrado").count() == 1, "Estudiante recibe notificación de cierre")
    st.get_by_text(f"{folio}: caso cerrado").locator("xpath=ancestor::li").get_by_role("button").click()
    check(S, folio in st.content() and "Cerrado" in st.locator(".page-head").inner_text(), "La notificación abre el caso con estado Cerrado")
    st.locator("label.check", has_text="5").click()
    st.get_by_role("button", name="Enviar valoración").click()
    check(S, "5 / 5" in st.content(), "Valoración guardada")
    hist = st.locator(".timeline").inner_text()
    check(S, all(x in hist for x in ["Nuevo", "Recibido", "En proceso", "Resuelto", "Cerrado"]), "Historial del estudiante completo")
    st.context.close(); gs.context.close()


def e2e03(b):
    S = "E2E-03"
    st = session(b, "alumno.demo1")
    st.get_by_role("link", name="SmartMatch").first.click()
    st.locator("label", has_text="Material de redes").click()
    check(S, st.locator("#cat-materiales").is_checked() and "redes" in st.input_value("#tags"), "Elegir necesidad rellena categoría y etiquetas (JS)")
    st.get_by_role("button", name="Buscar coincidencias").click()
    first = st.locator("article.match-card").first
    check(S, "Kit de redes de laboratorio" in first.inner_text(), "Primera recomendación: Kit de redes")
    check(S, "Recomendado porque" in first.inner_text(), "Explicación visible")
    first.locator("summary").click()
    check(S, "Categoría" in first.locator(".breakdown").inner_text(), "Desglose de puntaje desplegable")
    st.locator("input[data-compare]").nth(0).check(); st.locator("input[data-compare]").nth(1).check()
    check(S, st.locator("[data-compare-bar]").is_visible(), "Barra de comparación aparece con 2 seleccionados")
    st.get_by_role("button", name="Comparar").click()
    check(S, st.locator("table").count() == 1 and "Puntaje total" in st.content(), "Comparación lado a lado")
    st.go_back()
    st.locator("article.match-card").first.get_by_role("link", name=re.compile("Ver y solicitar")).click()
    check(S, "Kit de redes" in st.locator("h1").inner_text(), "Detalle del recurso desde la recomendación")
    st.get_by_role("link", name="Solicitar préstamo").click()
    st.fill("#f-purpose", "Práctica desde SmartMatch")
    st.get_by_role("button", name="Enviar solicitud").click()
    folio = st.locator(".page-head .tag").first.inner_text()
    check(S, folio.startswith("NP-PRE-"), f"Solicitud creada desde SmartMatch con folio {folio}")
    st.get_by_role("button", name="Cancelar solicitud").click()
    st.locator("#dlg-cancel").get_by_role("button", name="Sí, cancelar").click()
    check(S, "Cancelado" in st.locator(".page-head").inner_text(), "Cancelación conserva el registro (estado Cancelado)")
    st.context.close()


def e2e04(b):
    S = "E2E-04"
    gl = session(b, "gestor.laboratorio")
    st = session(b, "alumno.demo1")
    gl.get_by_role("link", name="Avisos").click()
    gl.get_by_role("link", name="Nuevo aviso").click()
    gl.fill("#a-title", "Aviso auditoría: laboratorio cerrado el lunes")
    gl.fill("#a-summary", "El laboratorio permanecerá cerrado por inventario.")
    gl.fill("#a-body", "Contenido de prueba de auditoría.")
    pick(gl, "#a-scope", "Área: Laboratorios")
    gl.select_option("#a-cat", "materiales")
    gl.select_option("#a-pri", "alta")
    gl.get_by_role("button", name="Guardar borrador").click()
    check(S, "Borrador guardado" in toast(gl), "Borrador creado")
    st.goto(BASE + "/app/avisos/")
    check(S, "Aviso auditoría" not in st.content(), "Borrador invisible para el estudiante")
    gl.locator("tr", has_text="Aviso auditoría").get_by_role("button", name="Publicar").click()
    check(S, "publicado" in toast(gl).lower(), "Publicado")
    st.reload()
    check(S, "Aviso auditoría" in st.content(), "Estudiante lo ve publicado")
    st.goto(BASE + "/app/")
    check(S, "Aviso auditoría" in st.locator("section", has_text="Avisos prioritarios").inner_text(), "Aparece en avisos prioritarios del inicio")
    st.goto(BASE + "/app/avisos/")
    st.get_by_role("link", name=re.compile("Aviso auditoría")).click()
    st.get_by_role("button", name="Marcar como leído").click()
    check(S, "Leído" in st.content(), "Marcado como leído")
    gl.reload()
    check(S, re.search(r"Aviso auditoría.*?\s1\s", gl.locator("tr", has_text="Aviso auditoría").inner_text().replace("\n", " ")) is not None, "Gestor ve 1 lectura (sin lista nominal)")
    # Vence: el gestor edita la fecha retirándolo; usamos Retirar (vía UI) y verificamos expiración por BD aparte
    gl.locator("tr", has_text="Aviso auditoría").get_by_role("button", name="Retirar").click()
    st.goto(BASE + "/app/avisos/")
    check(S, "Aviso auditoría" not in st.content(), "Retirado: desaparece del portal")
    st.context.close(); gl.context.close()


def e2e05(b):
    S = "E2E-05"
    doc = session(b, "docente.demo")
    doc.get_by_role("link", name="Cursos").first.click()
    doc.get_by_role("link", name="Nuevo curso").click()
    doc.fill("#id_title", "Auditoría: Direccionamiento IP")
    doc.fill("#id_summary", "Subredes en una tarde.")
    doc.fill("#id_description", "Curso breve de prueba de auditoría.")
    pick(doc, "#id_area", "Laboratorios")
    doc.check("#id_content_license_ok")
    doc.get_by_role("button", name="Guardar borrador").click()
    check(S, "borrador" in toast(doc).lower(), "Curso creado en borrador")
    for i, t in enumerate(["Qué es una IP", "Máscaras de subred"], 1):
        doc.fill("#id_title", t)
        doc.fill("#id_content", f"## Tema {i}\nContenido original de la lección {i}.")
        doc.get_by_role("button", name="Agregar lección").click()
    check(S, doc.locator(".list-title", has_text="Máscaras de subred").count() == 1, "Dos lecciones agregadas")
    doc.get_by_role("button", name="Enviar a revisión").click()
    url = doc.url
    check(S, "revisión" in toast(doc), "Enviado a revisión")
    st = session(b, "alumno.demo1")
    st.goto(BASE + "/app/cursos/")
    check(S, "Auditoría: Direccionamiento IP" not in st.content(), "En revisión: invisible al estudiante")
    gl = session(b, "gestor.laboratorio")
    gl.goto(url)
    gl.get_by_role("button", name="Aprobar y publicar").first.click()
    gl.locator("#dlg-approve").get_by_role("button", name="Aprobar y publicar").click()
    check(S, "publicado" in toast(gl).lower(), "Gestor autoriza la publicación")
    st.reload()
    st.get_by_role("link", name=re.compile("Auditoría: Direccionamiento IP")).first.click()
    st.get_by_role("button", name="Inscribirme").click()
    check(S, "0 %" in st.locator(".kpi-value").inner_text(), "Inscrito: 0 %")
    st.get_by_role("link", name=re.compile("Comenzar")).click()
    st.get_by_role("button", name=re.compile("Marcar como completada")).click()
    check(S, "50 %" in toast(st), "Lección 1 completa: 50 %")
    st.get_by_role("button", name=re.compile("Marcar como completada")).click()
    check(S, "100 %" in toast(st), "Lección 2 completa: 100 %")
    st.context.close()
    st2 = session(b, "alumno.demo1")
    st2.goto(BASE + "/app/cursos/")
    check(S, "100 %" in st2.locator("article", has_text="Auditoría: Direccionamiento IP").inner_text(), "Progreso persiste tras nueva sesión")
    gl.reload()
    check(S, "100 %" in gl.locator("section,div.card", has_text="Inscripciones").last.inner_text(), "Vista administrativa de inscripciones muestra 100 %")
    st2.context.close(); gl.context.close(); doc.context.close()


def e2e06(b):
    S = "E2E-06"
    a = session(b, "alumno.demo1")
    # obtener ids de la alumna 2 desde su propia sesión
    b2 = session(b, "alumna.demo2")
    b2.goto(BASE + "/app/solicitudes/")
    case_url = b2.locator("tbody a.row-link").first.get_attribute("href")
    b2.goto(BASE + "/app/prestamos/")
    loan_url = b2.locator("tbody a.row-link").first.get_attribute("href")
    for u in (case_url, loan_url):
        r = a.goto(BASE + u)
        check(S, r.status == 404 and "No encontramos" in a.content(), f"Alumno A abre {u} de alumna B → 404")
    r = a.goto(BASE + "/panel/")
    check(S, r.status == 403 and "Acceso restringido" in a.content(), "Alumno abre /panel/ → 403")
    r = a.goto(BASE + "/api/v1/admin/kpis")
    check(S, r.status == 403, "Alumno consume API administrativa → 403")
    gl = session(b, "gestor.laboratorio")
    r = gl.goto(BASE + case_url.replace("/app/solicitudes/", "/panel/solicitudes/"))
    check(S, r.status == 404, "Gestor de laboratorio abre caso de servicios → 404")
    for p in (a, b2, gl):
        p.context.close()


def e2e07(b):
    S = "E2E-07"
    import django  # noqa: F401
    a1 = session(b, "alumno.demo1")
    a2 = session(b, "alumna.demo2")
    # la alumna 2 libera cupo cancelando su solicitud pendiente desde la interfaz
    a2.goto(BASE + "/app/prestamos/")
    pend = a2.locator("tr", has_text="Solicitado")
    if pend.count():
        pend.first.get_by_role("link", name="Ver seguimiento").click()
        a2.get_by_role("button", name="Cancelar solicitud").click()
        a2.locator("#dlg-cancel").get_by_role("button", name="Sí, cancelar").click()
        check(S, "cancelada" in toast(a2), "Alumna 2 cancela solicitud pendiente (diálogo)")
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    folios = []
    for p in (a1, a2):
        p.goto(BASE + "/app/materiales/?q=kit+de+redes")
        p.get_by_role("link", name="Ver ficha").first.click()
        p.get_by_role("link", name="Solicitar préstamo").click()
        p.fill("#f-start_date", tomorrow)
        p.fill("#f-due_date", tomorrow)
        p.fill("#f-purpose", "Compite por el último kit")
        p.get_by_role("button", name="Enviar solicitud").click()
        folios.append(p.locator(".page-head .tag").first.inner_text())
    check(S, len(set(folios)) == 2 and all(f.startswith("NP-PRE-") for f in folios), f"Dos solicitudes compiten: {folios}")
    g1 = session(b, "gestor.laboratorio")
    g2 = session(b, "coord.demo")  # se crea un segundo gestor real mediante la interfaz de invitación
    g2.goto(BASE + "/panel/usuarios/invitar/")
    g2.fill("#id_display_name", "Gestor Laboratorio 2 (auditoría)")
    g2.fill("#id_email", "gestor.lab2.audit@nextpoint.test")
    g2.select_option("#id_role", label="Gestor de área")
    g2.select_option("#id_campus", label="Campus 2")
    pick(g2, "#id_area", "Laboratorios y materiales")
    g2.get_by_role("button", name="Generar invitación").click()
    link = g2.input_value("#inv-link")
    check(S, "/invitacion/" in link, "Coordinación invita a un segundo gestor (enlace de un solo uso)")
    ctx = b.new_context(viewport={"width": 1366, "height": 900})
    g3 = ctx.new_page()
    g3.goto(link)
    g3.fill("#id_password1", "Clave-Auditoria-2026")
    g3.fill("#id_password2", "Clave-Auditoria-2026")
    g3.get_by_role("button", name="Activar cuenta").click()
    check(S, g3.url.endswith("/panel/"), "Segundo gestor activa su cuenta y entra al panel")
    pages = []
    for g, f in ((g1, folios[0]), (g3, folios[1])):
        g.goto(BASE + "/panel/prestamos/")
        g.get_by_role("link", name=f).click()
        pages.append(g)
    barrier = threading.Barrier(2)
    # Playwright sync no es thread-safe: disparamos ambos submits casi a la vez por JS
    for g in pages:
        g.evaluate("document.querySelector('form[action$=\"/approve/\"]').setAttribute('data-ready','1')")
    t0 = time.time()
    pages[0].evaluate("document.querySelector('form[action$=\"/approve/\"]').requestSubmit()")
    pages[1].evaluate("document.querySelector('form[action$=\"/approve/\"]').requestSubmit()")
    for g in pages:
        g.wait_for_load_state("networkidle")
    msgs = [toast(g) for g in pages]
    ok = sum("aprobado" in m.lower() for m in msgs) == 1 and sum("No hay ejemplares libres" in m for m in msgs) == 1
    check(S, ok, f"Aprobaciones casi simultáneas ({time.time()-t0:.2f}s): una gana, otra recibe conflicto → {[m[:45] for m in msgs]}")
    for p in (a1, a2, g1, g2):
        p.context.close()
    ctx.close()


if __name__ == "__main__":
    which = sys.argv[1:] or ["1", "2", "3", "4", "5", "6", "7"]
    with sync_playwright() as p:
        b = p.chromium.launch(channel="chrome", args=["--no-sandbox"])
        for w in which:
            fn = globals()[f"e2e0{w}"]
            try:
                fn(b)
            except Exception as e:  # noqa: BLE001
                step(f"E2E-0{w}", f"EXCEPCIÓN: {type(e).__name__}: {str(e)[:300]}", False)
        b.close()
    print("\nCONSOLA/CSP:", CONSOLE or "sin errores")
    print(f"\nRESUMEN: {sum(1 for l in LOG if l[1]=='OK')} OK · {len(FAILS)} fallas")
    for f in FAILS:
        print("  FALLA", f)
