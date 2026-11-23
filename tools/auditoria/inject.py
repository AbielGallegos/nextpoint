"""Inyección: XSS almacenado en todos los campos libres que se muestran, e inyección de fórmulas en CSV."""
import os
import re
import sys
import uuid

import requests

BASE = "http://127.0.0.1:8000"
PW = os.environ["NEXTPOINT_DEMO_PASSWORD"]
XSS = '<script>alert("np")</script><img src=x onerror=alert(1)>'
FORMULA = '=HYPERLINK("http://evil.example","clic")'
F, OK = [], []


def res(c, m):
    (OK if c else F).append(m)
    print(("OK    " if c else "HALLAZGO ") + m)


def login(who):
    s = requests.Session()
    r = s.get(BASE + "/acceso/")
    t = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', r.text).group(1)
    s.post(BASE + "/acceso/", data={"csrfmiddlewaretoken": t, "email": f"{who}@nextpoint.test", "password": PW}, headers={"Referer": BASE})
    return s


def post(s, path, data, files=None):
    data["csrfmiddlewaretoken"] = s.cookies.get("csrftoken")
    return s.post(BASE + path, data=data, files=files, headers={"Referer": BASE + path})


def unsafe(html):
    return "<script>alert(\"np\")</script>" in html or "<img src=x onerror" in html


st, gl, gs, coord = login("alumno.demo1"), login("gestor.laboratorio"), login("gestor.servicios"), login("coord.demo")
# Caso con asunto/descripción maliciosos
r = st.get(BASE + "/app/solicitudes/nueva/")
cat = re.search(r'name="category" id="cat-(\d+)"', r.text).group(1)
r = post(st, "/app/solicitudes/nueva/", {"category": cat, "subject": FORMULA + " " + XSS, "description": XSS + " descripción larga", "priority": "normal",
                                         "idempotency_key": str(uuid.uuid4())})
case_url = r.url
res(not unsafe(st.get(case_url).text), "XSS en asunto/descripción del caso (portal) escapado")
pid = re.search(r"/(\d+)/$", case_url).group(1)
res(not unsafe(gs.get(f"{BASE}/panel/solicitudes/{pid}/").text), "XSS en caso (panel) escapado")
res(not unsafe(gs.get(f"{BASE}/panel/solicitudes/").text), "XSS en bandeja escapado")
post(gs, f"/panel/solicitudes/{pid}/reply/", {"body": XSS})
res(not unsafe(st.get(case_url).text), "XSS en respuesta del gestor escapado")
# Recurso con nombre de fórmula y XSS
r = gl.get(BASE + "/panel/recursos/nuevo/")
catid = re.search(r'id="id_category"[^>]*>.*?<option value="(\d+)"', r.text, re.S).group(1)
area = re.search(r'id="id_area"[^>]*>.*?<option value="(\d+)"', r.text, re.S).group(1)
r = post(gl, "/panel/recursos/nuevo/", {"name": FORMULA, "code": "XSS-" + uuid.uuid4().hex[:4], "category": catid, "area": area, "description": XSS, "status": "borrador", "tags_text": XSS})
res(not unsafe(r.text) and not unsafe(gl.get(r.url).text), "XSS en recurso (panel) escapado")
# Aviso
r = gl.get(BASE + "/panel/avisos/nuevo/")
scope = re.search(r'<option value="(area:\d+)"', r.text).group(1)
post(gl, "/panel/avisos/nuevo/", {"title": "Aviso XSS " + XSS, "summary": XSS + " resumen", "body": XSS + " cuerpo", "scope": scope, "category": "general", "priority": "normal", "audience": "estudiantes"})
lst = gl.get(BASE + "/panel/avisos/").text
aid = re.findall(r"/panel/avisos/(\d+)/publicar/", lst)[0]
post(gl, f"/panel/avisos/{aid}/publicar/", {})
res(not unsafe(st.get(f"{BASE}/app/avisos/{aid}/").text) and not unsafe(st.get(BASE + "/app/").text), "XSS en aviso (detalle e inicio) escapado")
# Exportación CSV: inyección de fórmulas
csv = coord.get(BASE + "/panel/informes/exportar/?tipo=solicitudes").text
lines = [l for l in csv.splitlines() if "HYPERLINK" in l]
res(not any(re.search(r'(^|,)"?=', l) for l in lines), "CSV de solicitudes neutraliza fórmulas en celdas")
# Notificación con destino externo inyectado (no debe redirigir afuera)
print(f"\n{len(OK)} OK · {len(F)} hallazgos")
