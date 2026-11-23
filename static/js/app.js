/* NextPoint — interacciones ligeras. Sin dependencias; la app funciona también sin JS
   (los formularios envían y el servidor valida). */
(function () {
  "use strict";

  // Menú lateral en tableta/móvil
  document.querySelectorAll("[data-nav-toggle]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var open = document.body.classList.toggle("nav-open");
      btn.setAttribute("aria-expanded", open ? "true" : "false");
    });
  });
  document.querySelectorAll("[data-nav-close]").forEach(function (el) {
    el.addEventListener("click", function () { document.body.classList.remove("nav-open"); });
  });
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape") {
      document.body.classList.remove("nav-open");
      document.querySelectorAll("details.user-menu[open]").forEach(function (d) { d.removeAttribute("open"); });
    }
  });
  document.addEventListener("click", function (e) {
    document.querySelectorAll("details.user-menu[open]").forEach(function (d) { if (!d.contains(e.target)) d.removeAttribute("open"); });
  });

  // Evitar doble envío: deshabilita el botón tras enviar (el servidor también es idempotente)
  document.querySelectorAll("form").forEach(function (form) {
    form.addEventListener("submit", function (e) {
      if (form.dataset.submitted === "1") { e.preventDefault(); return; }
      form.dataset.submitted = "1";
      var btn = e.submitter || form.querySelector("[type=submit]");
      if (btn && form.method.toLowerCase() === "post") {
        btn.classList.add("is-busy");
        btn.setAttribute("aria-busy", "true");
        if (btn.dataset.busyLabel) btn.textContent = btn.dataset.busyLabel;
      }
      setTimeout(function () { form.dataset.submitted = ""; if (btn) { btn.classList.remove("is-busy"); btn.removeAttribute("aria-busy"); } }, 6000);
    });
  });

  // Confirmación de acciones sensibles con <dialog> accesible
  document.querySelectorAll("[data-confirm-dialog]").forEach(function (trigger) {
    var dialog = document.getElementById(trigger.dataset.confirmDialog);
    if (!dialog) return;
    trigger.addEventListener("click", function (e) {
      e.preventDefault();
      if (typeof dialog.showModal === "function") { dialog.showModal(); var f = dialog.querySelector("textarea, input:not([type=hidden]), select, button"); if (f) f.focus(); }
    });
    dialog.querySelectorAll("[data-close]").forEach(function (b) { b.addEventListener("click", function () { dialog.close(); }); });
  });

  // Toasts: se ocultan solos (los de error permanecen)
  document.querySelectorAll(".toast[data-autohide]").forEach(function (t) {
    setTimeout(function () { t.style.transition = "opacity .3s"; t.style.opacity = "0"; setTimeout(function () { t.remove(); }, 350); }, 6000);
  });
  document.querySelectorAll("[data-dismiss]").forEach(function (b) { b.addEventListener("click", function () { b.closest(".toast").remove(); }); });

  // SmartMatch: selección para comparar (máx. 3)
  var picks = document.querySelectorAll("input[data-compare]");
  var bar = document.querySelector("[data-compare-bar]");
  function syncCompare() {
    var checked = Array.prototype.filter.call(picks, function (p) { return p.checked; });
    picks.forEach(function (p) { p.disabled = !p.checked && checked.length >= 3; });
    if (bar) {
      bar.hidden = checked.length < 2;
      var c = bar.querySelector("[data-compare-count]"); if (c) c.textContent = checked.length;
    }
  }
  picks.forEach(function (p) { p.addEventListener("change", syncCompare); });
  syncCompare();

  // Selector de necesidad: rellena categoría y etiquetas sugeridas
  document.querySelectorAll("input[name=need]").forEach(function (radio) {
    radio.addEventListener("change", function () {
      var cat = document.querySelector("[name=category][value='" + radio.dataset.category + "']");
      if (cat) cat.checked = true;
      var tags = document.querySelector("[name=tags]");
      if (tags && radio.dataset.tags !== undefined) tags.value = radio.dataset.tags;
    });
  });

  // Contador de caracteres
  document.querySelectorAll("textarea[maxlength][data-counter]").forEach(function (ta) {
    var out = document.getElementById(ta.dataset.counter);
    function upd() { if (out) out.textContent = ta.value.length + " / " + ta.getAttribute("maxlength"); }
    ta.addEventListener("input", upd); upd();
  });

  // Cuentas demo en la pantalla de acceso: solo rellena el correo
  document.querySelectorAll("[data-fill-email]").forEach(function (b) {
    b.addEventListener("click", function () {
      var input = document.getElementById("id_email");
      if (input) { input.value = b.dataset.fillEmail; var pw = document.getElementById("id_password"); if (pw) pw.focus(); }
    });
  });

  // Enfocar resumen de errores para lectores de pantalla
  var summary = document.querySelector(".error-summary");
  if (summary) { summary.setAttribute("tabindex", "-1"); summary.focus(); }
})();
