"""Rastreo exhaustivo por rol: sigue todos los enlaces internos (GET), registra formularios y botones.

Detecta: respuestas 4xx/5xx inesperadas, enlaces vacíos o "#", formularios sin action válida,
botones fuera de formulario sin comportamiento (data-*), y destinos de formularios POST inexistentes.
"""
import json
import os
import re
import sys
from collections import deque
from html.parser import HTMLParser
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse

import requests

BASE = "http://127.0.0.1:8000"
PW = os.environ["NEXTPOINT_DEMO_PASSWORD"]
ROLES = [None, "alumno.demo1", "alumna.demo2", "gestor.laboratorio", "gestor.servicios", "docente.demo", "coord.demo", "admin.demo"]
SKIP = ("/salir/", "/static/", "/panel/informes/exportar/")  # exportar se prueba aparte (descarga)


class Page(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links, self.forms, self.buttons, self.issues = [], [], [], []
        self.form_stack = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "a":
            href = a.get("href")
            if href is None or href.strip() in ("", "#"):
                if "data-nav-toggle" not in a and "data-confirm-dialog" not in a:
                    self.issues.append(f"enlace sin destino: {a}")
            else:
                self.links.append(href)
        elif tag == "form":
            f = {"method": (a.get("method") or "get").lower(), "action": a.get("action"), "inputs": [], "submits": []}
            self.forms.append(f)
            self.form_stack.append(f)
        elif tag in ("input", "select", "textarea") and self.form_stack:
            self.form_stack[-1]["inputs"].append(a.get("name"))
        elif tag == "button":
            inside = bool(self.form_stack)
            btype = a.get("type", "submit")
            behaviour = any(k.startswith("data-") for k in a) or a.get("formaction")
            if inside and btype == "submit" and a.get("formaction"):
                self.form_stack[-1]["submits"].append(a["formaction"])
            if not inside and not behaviour:
                self.issues.append(f"botón sin comportamiento: {a}")
            if inside and btype == "button" and not behaviour:
                self.issues.append(f"botón type=button sin comportamiento: {a}")

    def handle_endtag(self, tag):
        if tag == "form" and self.form_stack:
            self.form_stack.pop()


def login(who):
    s = requests.Session()
    if who is None:
        return s
    r = s.get(BASE + "/acceso/")
    token = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', r.text).group(1)
    r = s.post(BASE + "/acceso/", data={"csrfmiddlewaretoken": token, "email": f"{who}@nextpoint.test", "password": PW},
               headers={"Referer": BASE + "/acceso/"}, allow_redirects=False)
    assert r.status_code == 302, (who, r.status_code)
    return s


def norm(url):
    p = urlparse(url)
    q = [(k, v) for k, v in parse_qsl(p.query) if k != "page"]
    return p.path + ("?" + urlencode(sorted(q)) if q else "")


def crawl(who, limit=600):
    s = login(who)
    starts = ["/", "/acerca/", "/ayuda/", "/acceso/", "/recuperar/"] if who is None else ["/inicio/"]
    seen, queue = set(), deque(starts)
    results, issues, posts = [], [], set()
    path_variants = {}
    while queue and len(seen) < limit:
        url = queue.popleft()
        key = norm(url)
        if key in seen:
            continue
        # limitar variantes de query por ruta
        path = urlparse(url).path
        path_variants[path] = path_variants.get(path, 0) + 1
        if path_variants[path] > 12:
            continue
        seen.add(key)
        r = s.get(BASE + url, allow_redirects=False)
        results.append((r.status_code, url))
        if r.status_code >= 500:
            issues.append(f"{r.status_code} en {url}")
        if r.status_code in (301, 302):
            loc = r.headers.get("Location", "")
            if loc.startswith("/") and not loc.startswith("/acceso/"):
                queue.append(loc)
            continue
        if "text/html" not in r.headers.get("Content-Type", ""):
            continue
        p = Page()
        p.feed(r.text)
        for i in p.issues:
            issues.append(f"{url}: {i}")
        for f in p.forms:
            action = f["action"] if f["action"] not in (None, "") else url
            if f["method"] == "post":
                if "csrfmiddlewaretoken" not in f["inputs"]:
                    issues.append(f"{url}: formulario POST sin CSRF -> {action}")
                posts.add(urljoin(url, action).split("?")[0])
                for fa in f["submits"]:
                    posts.add(urljoin(url, fa))
            else:
                if f["action"] and not f["action"].startswith("/") and not f["action"].startswith("?"):
                    issues.append(f"{url}: GET form con action externa {f['action']}")
        for href in p.links:
            full = urljoin(url, href)
            pu = urlparse(full)
            if pu.netloc and pu.netloc != "127.0.0.1:8000":
                continue  # enlaces externos (fuente de avisos)
            if href.startswith("#"):
                continue
            target = pu.path + ("?" + pu.query if pu.query else "")
            if not any(target.startswith(x) for x in SKIP):
                queue.append(target)
    # comprobar que cada destino POST existe (un GET debe dar 405/403/404 controlado, nunca 500)
    for action in sorted(posts):
        r = s.get(BASE + action, allow_redirects=False)
        if r.status_code >= 500:
            issues.append(f"POST destino {action} responde {r.status_code} a GET")
    return results, issues, sorted(posts)


if __name__ == "__main__":
    roles = ROLES if len(sys.argv) == 1 else [None if a == "anon" else a for a in sys.argv[1:]]
    report = {}
    for who in roles:
        results, issues, posts = crawl(who)
        codes = {}
        for c, _ in results:
            codes[c] = codes.get(c, 0) + 1
        bad = [(c, u) for c, u in results if c not in (200, 301, 302)]
        report[who or "anon"] = {"pages": len(results), "codes": codes, "non200": bad, "issues": issues, "post_endpoints": len(posts), "posts": posts, "urls": [u for c, u in results if c == 200]}
        print(f"== {who or 'anon'}: {len(results)} URLs {codes} · {len(posts)} destinos POST · {len(issues)} hallazgos")
        for c, u in bad:
            print(f"   {c} {u}")
        for i in issues[:40]:
            print("   !", i)
    json.dump(report, open("/home/claude/audit/crawl_report.json", "w"), ensure_ascii=False, indent=1)
