"""Responsive: desbordamiento horizontal y elementos fuera de pantalla en 390 / 820 / 1366 px,
más prueba del menú en móvil y tableta. Usa las URLs reales descubiertas por el rastreo."""
import json
import os
import re

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8000"
PW = os.environ["NEXTPOINT_DEMO_PASSWORD"]
rep = json.load(open("/home/claude/audit/crawl_report.json"))
ROLES = ["anon", "alumno.demo1", "gestor.laboratorio", "gestor.servicios", "coord.demo", "admin.demo", "docente.demo"]
JS = """() => {
  const vw = document.documentElement.clientWidth;
  const off = [];
  document.querySelectorAll('body *').forEach(el => {
    const r = el.getBoundingClientRect(); const cs = getComputedStyle(el);
    if (r.width && r.right > vw + 1 && cs.position !== 'fixed' && !el.closest('.table-wrap') && !el.closest('dialog') && !el.closest('.stepper') && !el.closest('.sidebar') && !el.closest('.toasts'))
      off.push((el.tagName + '.' + (el.className.baseVal ?? el.className)).slice(0,60) + ' ' + Math.round(r.right));
  });
  return {sw: document.documentElement.scrollWidth, vw, off: off.slice(0,4)};
}"""
issues, checked = [], 0
with sync_playwright() as p:
    b = p.chromium.launch(channel="chrome", args=["--no-sandbox"])
    for who in ROLES:
        urls = sorted(set(rep[who]["urls"]))
        # una muestra por patrón de ruta (ids distintos = misma plantilla)
        seen, sample = set(), []
        for u in urls:
            k = re.sub(r"\d+", "N", u.split("?")[0])
            if k not in seen:
                seen.add(k); sample.append(u)
        for width in (390, 820, 1366):
            ctx = b.new_context(viewport={"width": width, "height": 860})
            pg = ctx.new_page()
            if who != "anon":
                pg.goto(BASE + "/acceso/"); pg.fill("#id_email", f"{who}@nextpoint.test"); pg.fill("#id_password", PW)
                pg.get_by_role("button", name="Entrar").click(); pg.wait_for_load_state("networkidle")
            for u in sample:
                pg.goto(BASE + u); checked += 1
                m = pg.evaluate(JS)
                if m["sw"] > m["vw"] + 1 or m["off"]:
                    issues.append(f"{width}px {who} {u}: scrollWidth={m['sw']} vw={m['vw']} {m['off']}")
            # menú de navegación en móvil/tableta
            if who != "anon" and width < 1024:
                pg.goto(BASE + ("/app/" if who.startswith("alumno") else "/panel/"))
                side_visible = pg.locator("#sidebar").evaluate("e => e.getBoundingClientRect().right > 0")
                pg.locator(".topbar [data-nav-toggle]").click()
                pg.wait_for_timeout(350)
                opened = pg.locator("#sidebar").evaluate("e => e.getBoundingClientRect().left >= 0")
                link = pg.locator("#sidebar .nav a").nth(1)
                target = link.get_attribute("href")
                link.click(); pg.wait_for_load_state("networkidle")
                if side_visible or not opened or not pg.url.endswith(target):
                    issues.append(f"{width}px {who}: menú lateral (oculto={not side_visible}, abre={opened}, navega={pg.url.endswith(target)})")
                if who.startswith("alumno") and width == 390:
                    bn = pg.locator(".bottom-nav")
                    if not bn.is_visible():
                        issues.append("390px estudiante: falta navegación inferior")
                    pg.locator(".bottom-nav a", has_text="Más").click(); pg.wait_for_timeout(350)
                    if not pg.locator("#sidebar").evaluate("e => e.getBoundingClientRect().left >= 0"):
                        issues.append("390px: 'Más' no abre el menú")
            ctx.close()
    b.close()
print(f"{checked} vistas revisadas")
for i in issues:
    print("HALLAZGO", i)
print(f"{len(issues)} hallazgos")
