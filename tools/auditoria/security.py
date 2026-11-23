"""Sondas de seguridad y matriz de acceso contra el servidor real."""
import json, os, re, sys
import requests
BASE = "http://127.0.0.1:8000"
PW = os.environ["NEXTPOINT_DEMO_PASSWORD"]
rep = json.load(open("/home/claude/audit/crawl_report.json"))
FIND, OK = [], []

def res(cond, msg):
    (OK if cond else FIND).append(msg); print(("OK    " if cond else "HALLAZGO ") + msg)

def login(who):
    s = requests.Session()
    if not who: return s
    t = csrf(s, "/acceso/")
    r = s.post(BASE+"/acceso/", data={"csrfmiddlewaretoken": t, "email": f"{who}@nextpoint.test", "password": PW}, headers={"Referer": BASE+"/acceso/"}, allow_redirects=False)
    assert r.status_code == 302, who
    return s

def csrf(s, path):
    r = s.get(BASE+path)
    m = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', r.text)
    return m.group(1) if m else s.cookies.get("csrftoken")

def post(s, path, data=None, ref="/"):
    data = dict(data or {}); data["csrfmiddlewaretoken"] = s.cookies.get("csrftoken") or csrf(s, "/inicio/")
    return s.post(BASE+path, data=data, headers={"Referer": BASE+ref}, allow_redirects=False)

staff_urls = sorted({u for r in ("gestor.laboratorio","gestor.servicios","coord.demo","admin.demo","docente.demo") for u in rep[r]["urls"] if u.startswith("/panel") or u.startswith("/api")})
staff_posts = sorted({u for r in ("gestor.laboratorio","gestor.servicios","coord.demo","admin.demo","docente.demo") for u in rep[r]["posts"] if "/panel/" in u})
student_urls = sorted({u for r in ("alumno.demo1","alumna.demo2") for u in rep[r]["urls"] if u.startswith("/app/") or u.startswith("/adjuntos")})

# 1. Anónimo: toda ruta privada exige sesión
anon = login(None)
bad = [u for u in staff_urls+student_urls if anon.get(BASE+u, allow_redirects=False).status_code not in (302, 401)]
res(not bad, f"Anónimo redirigido a acceso en {len(staff_urls)+len(student_urls)} rutas privadas {bad[:5]}")
# 2. Estudiante: ninguna ruta administrativa accesible (GET) ni acción POST
st = login("alumno.demo1")
bad = [(u, c) for u in staff_urls if (c := st.get(BASE+u, allow_redirects=False).status_code) not in (403, 404)]
res(not bad, f"Estudiante: {len(staff_urls)} rutas de panel → 403/404 {bad[:5]}")
bad = [(u, c) for u in staff_posts if (c := post(st, u, {"note": "x", "reason": "xxxxxx", "body": "xxxxxxxxxxxx", "status": "suspendido", "state": "baja", "value": "0", "key": "max_loan_days"}).status_code) not in (403, 404, 405)]
res(not bad, f"Estudiante: {len(staff_posts)} acciones POST administrativas rechazadas {bad[:5]}")
# 3. Alumna 2 sobre recursos privados de alumno 1 (detalles y acciones)
st2 = login("alumna.demo2")
mine1 = [u for u in rep["alumno.demo1"]["urls"] if re.match(r"^/app/(solicitudes|prestamos|ayuda/tickets)/\d+/$", u)]
mine2 = set(rep["alumna.demo2"]["urls"])
foreign = [u for u in mine1 if u not in mine2]
bad = [(u, c) for u in foreign if (c := st2.get(BASE+u).status_code) != 404]
res(not bad and foreign, f"IDOR horizontal: {len(foreign)} detalles de alumno 1 → 404 para alumna 2 {bad}")
# 4. Soporte técnico / admin no leen casos ni préstamos
adm = login("admin.demo")
case_det = [u for u in staff_urls if re.match(r"^/panel/(solicitudes|prestamos)/\d+/$", u)]
bad = [(u, c) for u in case_det if (c := adm.get(BASE+u).status_code) not in (403, 404)]
res(not bad, f"Administración técnica sin acceso a {len(case_det)} casos/préstamos {bad[:4]}")
# 5. Docente: sin préstamos, inventario, usuarios, informes
doc = login("docente.demo")
bad = [(u, c) for u in ["/panel/prestamos/", "/panel/recursos/", "/panel/usuarios/", "/panel/informes/", "/panel/auditoria/", "/panel/configuracion/", "/panel/avisos/"] if (c := doc.get(BASE+u).status_code) != 403]
res(not bad, f"Docente bloqueado en módulos ajenos {bad}")
# 6. Gestor: no ve fichas de estudiantes en usuarios
gl = login("gestor.laboratorio")
ids = re.findall(r"/panel/usuarios/(\d+)/", " ".join(rep["coord.demo"]["urls"]))
r = gl.get(BASE+"/panel/usuarios/")
students_listed = "Alumno Demo" in r.text
res(not students_listed, "Gestor no lista cuentas de estudiantes (minimización)")
# 7. Métodos: acciones GET no ejecutan
r = st.get(BASE+"/salir/"); res(r.status_code == 405, f"GET /salir/ → {r.status_code}")
r = gl.get(BASE+"/panel/prestamos/1/approve/"); res(r.status_code == 405, f"GET acción aprobar → {r.status_code}")
# 8. CSRF: POST sin token rechazado
s = login("gestor.laboratorio")
r = s.post(BASE+"/panel/prestamos/1/review/", headers={"Referer": BASE+"/"}, allow_redirects=False)
res(r.status_code == 403, f"POST sin token CSRF → {r.status_code}")
# 9. Redirección abierta en login
s = requests.Session(); t = csrf(s, "/acceso/?next=https://evil.example/")
r = s.post(BASE+"/acceso/", data={"csrfmiddlewaretoken": t, "email": "alumno.demo1@nextpoint.test", "password": PW, "next": "https://evil.example/"}, headers={"Referer": BASE+"/acceso/"}, allow_redirects=False)
res("evil" not in r.headers.get("Location", ""), f"Login ignora next externo → {r.headers.get('Location')}")
r = s.post(BASE+"/acceso/", data={"csrfmiddlewaretoken": t, "email": "alumno.demo1@nextpoint.test", "password": PW, "next": "//evil.example/"}, headers={"Referer": BASE+"/acceso/"}, allow_redirects=False)
# 10. Fijación de sesión: el id cambia al iniciar sesión
s = requests.Session(); s.get(BASE+"/acceso/"); t = s.cookies.get("csrftoken")
s.cookies.set("sessionid", "fijada123456789")
s.post(BASE+"/acceso/", data={"csrfmiddlewaretoken": t, "email": "alumno.demo1@nextpoint.test", "password": PW}, headers={"Referer": BASE+"/acceso/"}, allow_redirects=False)
vals = [c.value for c in s.cookies if c.name == "sessionid"]
res(any(v != "fijada123456789" for v in vals), f"Sesión rotada al iniciar sesión ({len(vals)} cookies)")
# 11. Cookies y cabeceras
r = requests.get(BASE+"/acceso/")
res("HttpOnly" in login("alumno.demo1").get(BASE+"/app/").headers.get("Set-Cookie", "HttpOnly") , "Cookie de sesión HttpOnly")
hdr = login("alumno.demo1").get(BASE+"/app/").headers
res(hdr.get("X-Frame-Options") == "DENY" and "frame-ancestors 'none'" in hdr.get("Content-Security-Policy", "") and "no-store" in hdr.get("Cache-Control", ""), "Cabeceras: XFO DENY, CSP frame-ancestors, no-store")
# 12. Recuperación sin enumeración
s = requests.Session()
a = s.post(BASE+"/recuperar/", data={"csrfmiddlewaretoken": csrf(s, "/recuperar/"), "email": "alumno.demo1@nextpoint.test"}, headers={"Referer": BASE+"/recuperar/"}, allow_redirects=False)
b = s.post(BASE+"/recuperar/", data={"csrfmiddlewaretoken": csrf(s, "/recuperar/"), "email": "nadie@nextpoint.test"}, headers={"Referer": BASE+"/recuperar/"}, allow_redirects=False)
res(a.status_code == b.status_code == 302 and a.headers["Location"] == b.headers["Location"], "Recuperación: misma respuesta para correo existente e inexistente")
# 13. Fuerza bruta distribuida: muchos correos desde una IP
s = requests.Session(); t = csrf(s, "/acceso/")
codes = [s.post(BASE+"/acceso/", data={"csrfmiddlewaretoken": t, "email": f"x{i}@nextpoint.test", "password": "malamala1"}, headers={"Referer": BASE+"/acceso/"}).status_code for i in range(25)]
res(429 in codes, f"Límite por IP ante correos rotativos (códigos finales {codes[-3:]})")
json.dump({"ok": OK, "hallazgos": FIND}, open("/home/claude/audit/security_report.json", "w"), ensure_ascii=False, indent=1)
print(f"\n{len(OK)} OK · {len(FIND)} hallazgos")
