/* WebCore – Bedienlogik des Dashboards (ohne Abhängigkeiten).
   Reiter, Chip-Mehrfachauswahl, Speicherleiste, Bestätigungsdialog, Tabellenfilter,
   Toasts, Nur-Ansicht- und Bedienen-Modus. Alles progressiv: ohne JS funktionieren die Seiten weiter. */
(function () {
  "use strict";
  var content = document.getElementById("wc-content");
  var body = document.body;
  var READONLY = body.getAttribute("data-readonly") === "1";
  // Stufe „Bedienen“: nur Tagesgeschäft-Formulare (form/action-Wert in data-operate-forms oder
  // Formular mit data-wc-operate) bleiben benutzbar – der Server prüft trotzdem jeden POST.
  var OPERATE = !READONLY && body.getAttribute("data-operate") === "1";
  var OP_FORMS = (body.getAttribute("data-operate-forms") || "").split(",")
    .map(function (x) { return x.trim(); }).filter(Boolean);

  function $$(sel, root) { return Array.prototype.slice.call((root || document).querySelectorAll(sel)); }
  function el(tag, cls, text) { var e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; }
  function store(key, val) { try { if (val === undefined) return sessionStorage.getItem(key); sessionStorage.setItem(key, val); } catch (e) { return null; } }

  /* ---------------------------------------------------------------- Toasts */
  function toast(text, err) {
    var box = document.getElementById("toasts"); if (!box || !text) return;
    var t = el("div", "toast-x" + (err ? " err" : ""));
    var i = el("i", "bi " + (err ? "bi-exclamation-octagon" : "bi-check2-circle"));
    var s = el("span", null, text);
    var b = el("button"); b.type = "button"; b.setAttribute("aria-label", "Schließen"); b.innerHTML = "&times;";
    b.onclick = function () { t.remove(); };
    t.appendChild(i); t.appendChild(s); t.appendChild(b); box.appendChild(t);
    setTimeout(function () { t.classList.add("hide"); setTimeout(function () { t.remove(); }, 400); }, err ? 9000 : 5000);
  }
  window.wcToast = toast;
  (function () {
    var p = new URLSearchParams(location.search), ok = p.get("ok"), er = p.get("err");
    var BAD = /(nicht gefunden|fehlgeschlagen|ungültig|fehler|keine |abgelehnt|nicht erlaubt|bitte |darfst du nicht)/i;
    if (!ok && !er) return;
    var msg = ok === "1" ? "Gespeichert." : (er === "1" ? "Eingabe ungültig – bitte prüfen." : (er || ok));
    toast(msg, !!er || BAD.test(msg));
    $$('#wc-content [class*="-flash"]').forEach(function (e) { e.style.display = "none"; });
    p.delete("ok"); p.delete("err");
    var qs = p.toString();
    history.replaceState(null, "", location.pathname + (qs ? "?" + qs : "") + location.hash);
  })();

  /* --------------------------------------------------------- Nutzer-Menü */
  document.addEventListener("click", function (e) {
    $$("details.um[open]").forEach(function (d) { if (!d.contains(e.target)) d.removeAttribute("open"); });
  });

  /* ---------------------------------------------------------- Nur-Ansicht */
  if (READONLY && content) {
    $$("form", content).forEach(function (f) {
      if ((f.getAttribute("method") || "get").toLowerCase() !== "post") return;
      f.setAttribute("data-wc-locked", "1");
      $$("input,select,textarea,button", f).forEach(function (x) { if (x.type !== "hidden") x.disabled = true; });
      f.addEventListener("submit", function (e) { e.preventDefault(); toast("Nur Ansicht – dir fehlt die Berechtigung zum Bearbeiten.", true); });
    });
  }

  /* -------------------------------------------------------------- Bedienen */
  function isSubmit(x) { return (x.tagName === "BUTTON" && (x.type || "submit") === "submit") || (x.tagName === "INPUT" && (x.type === "submit" || x.type === "image")); }
  function opAllowed(v) { return OP_FORMS.indexOf(v) > -1; }
  function opLockForm(f) {
    f.setAttribute("data-wc-locked", "1");
    Array.prototype.forEach.call(f.elements, function (x) { if (x.type !== "hidden") x.disabled = true; });
    f.addEventListener("submit", function (e) { e.preventDefault(); toast("Dafür brauchst du das Recht Bearbeiten.", true); });
  }
  if (OPERATE && content) {
    $$("form", content).forEach(function (f) {
      if ((f.getAttribute("method") || "get").toLowerCase() !== "post") return;
      if (f.hasAttribute("data-wc-operate")) return;
      var els = Array.prototype.slice.call(f.elements);
      var key = els.some(function (x) { return x.name === "form" && x.value; }) ? "form" : "action";
      var fixed = els.filter(function (x) { return x.name === key && !isSubmit(x) && x.value; });
      var btns = els.filter(function (x) { return x.name === key && isSubmit(x); });
      if (fixed.length) {
        // Formular-Typ steht fest (verstecktes Feld): ganz frei oder ganz gesperrt.
        if (!fixed.every(function (x) { return opAllowed(x.value); })) return opLockForm(f);
        btns.forEach(function (b) { if (!opAllowed(b.value)) { b.disabled = true; b.setAttribute("data-wc-op-locked", "1"); } });
        return;
      }
      // Aktion kommt vom geklickten Button: nur erlaubte Buttons aktiv lassen.
      var ok = btns.filter(function (b) { return opAllowed(b.value); });
      if (!ok.length) return opLockForm(f);
      els.forEach(function (x) {
        if (isSubmit(x) && ok.indexOf(x) === -1) { x.disabled = true; x.setAttribute("data-wc-op-locked", "1"); }
      });
    });
  }

  /* ---------------------------------------------------------------- Reiter */
  function initTabs() {
    if (!content) return;
    var tabs = $$(".wc-tab", content).filter(function (t) { return t.getAttribute("data-hidden") !== "1"; });
    if (tabs.length < 2) return;
    var bar = el("div", "wc-tabbar"); bar.setRole = null; bar.setAttribute("role", "tablist");
    var key = "wc-tab:" + location.pathname;
    var buttons = {};
    tabs.forEach(function (t) {
      var b = el("button"); b.type = "button"; b.setAttribute("role", "tab");
      var ic = t.getAttribute("data-icon"); if (ic) b.appendChild(el("i", "bi " + ic));
      b.appendChild(el("span", null, t.getAttribute("data-title") || t.getAttribute("data-tab")));
      var cnt = t.getAttribute("data-count"); if (cnt !== null && cnt !== "") b.appendChild(el("span", "wc-tab-count", cnt));
      b.addEventListener("click", function () { activate(t.getAttribute("data-tab"), true); });
      buttons[t.getAttribute("data-tab")] = b; bar.appendChild(b);
    });
    tabs[0].parentNode.insertBefore(bar, tabs[0]);
    content.classList.add("wc-tabs-ready");
    function activate(name, user) {
      var found = false;
      tabs.forEach(function (t) {
        var on = t.getAttribute("data-tab") === name; t.classList.toggle("active", on);
        buttons[t.getAttribute("data-tab")].classList.toggle("active", on);
        buttons[t.getAttribute("data-tab")].setAttribute("aria-selected", on ? "true" : "false");
        if (on) found = true;
      });
      if (!found) return activate(tabs[0].getAttribute("data-tab"), user);
      store(key, name);
      // Aktiven Reiter in der (auf dem Handy scrollbaren) Leiste sichtbar halten
      var btn = buttons[name], bar = btn && btn.parentNode;
      if (bar && bar.scrollWidth > bar.clientWidth) bar.scrollLeft = btn.offsetLeft - (bar.clientWidth - btn.offsetWidth) / 2;
      if (user) history.replaceState(null, "", location.pathname + location.search + "#" + name);
      document.dispatchEvent(new CustomEvent("wc:tab", { detail: name }));
    }
    window.wcActivateTab = activate;
    // Sprung-Buttons (ui.goto): <button data-wc-goto="reiter">
    document.addEventListener("click", function (e) {
      var g = e.target.closest ? e.target.closest("[data-wc-goto]") : null;
      if (!g) return;
      e.preventDefault();
      activate(g.getAttribute("data-wc-goto"), true);
      var bar = document.querySelector(".wc-tabbar"); if (bar) window.scrollTo({ top: Math.max(0, bar.getBoundingClientRect().top + window.scrollY - 90), behavior: "smooth" });
    });
    var q = new URLSearchParams(location.search).get("tab");
    var start = (location.hash || "").replace(/^#(tab-)?/, "") || q || store(key) || tabs[0].getAttribute("data-tab");
    activate(start, false);
    // Pflichtfeld in verstecktem Reiter -> Reiter öffnen, damit der Browser es zeigen kann
    content.addEventListener("invalid", function (e) {
      var t = e.target.closest && e.target.closest(".wc-tab");
      if (t && !t.classList.contains("active")) activate(t.getAttribute("data-tab"), true);
    }, true);
  }

  /* ------------------------------------------------ Chip-Mehrfachauswahl */
  function enhanceMulti(sel) {
    if (sel.getAttribute("data-native") === "1" || sel.getAttribute("data-wc-ms")) return;
    sel.setAttribute("data-wc-ms", "1");
    var wrap = el("div", "wc-ms"), box = el("div", "wc-ms-box"), input = el("input", "wc-ms-input"), list = el("div", "wc-ms-list");
    input.type = "text"; input.autocomplete = "off";
    input.placeholder = sel.getAttribute("data-placeholder") || "Auswählen oder tippen …";
    wrap.appendChild(box); wrap.appendChild(list);
    sel.parentNode.insertBefore(wrap, sel); wrap.appendChild(sel); sel.style.display = "none";
    var hl = -1;
    function opts() { return Array.prototype.slice.call(sel.options); }
    function dot(o) { var d = el("span", "dot"); var c = o.getAttribute("data-color"); if (c) d.style.background = c; return d; }
    function renderChips() {
      box.innerHTML = "";
      opts().filter(function (o) { return o.selected; }).forEach(function (o) {
        var c = el("span", "wc-chip"); c.appendChild(dot(o)); c.appendChild(el("span", null, o.textContent));
        if (!sel.disabled) {
          var x = el("button"); x.type = "button"; x.innerHTML = "&times;"; x.setAttribute("aria-label", "Entfernen");
          x.addEventListener("click", function (e) { e.stopPropagation(); o.selected = false; changed(); });
          c.appendChild(x);
        }
        box.appendChild(c);
      });
      if (!sel.disabled) box.appendChild(input);
      else if (!box.children.length) box.appendChild(el("span", "wc-help", "— keine —"));
      wrap.classList.toggle("disabled", sel.disabled);
    }
    function renderList() {
      list.innerHTML = ""; var q = input.value.trim().toLowerCase(); var shown = 0;
      opts().forEach(function (o, i) {
        if (q && o.textContent.toLowerCase().indexOf(q) === -1) return;
        var r = el("div", "wc-ms-opt" + (o.selected ? " sel" : "") + (shown === hl ? " hl" : ""));
        r.appendChild(dot(o)); r.appendChild(el("span", null, o.textContent));
        r.addEventListener("mousedown", function (e) { e.preventDefault(); o.selected = !o.selected; input.value = ""; changed(); renderList(); });
        list.appendChild(r); shown++;
      });
      if (!shown) list.appendChild(el("div", "wc-ms-none", "Keine Treffer"));
    }
    function changed() { renderChips(); sel.dispatchEvent(new Event("change", { bubbles: true })); if (wrap.classList.contains("open")) input.focus(); }
    box.addEventListener("click", function () { if (sel.disabled) return; wrap.classList.add("open", "focus"); renderList(); input.focus(); });
    input.addEventListener("focus", function () { wrap.classList.add("open", "focus"); renderList(); });
    input.addEventListener("blur", function () { setTimeout(function () { wrap.classList.remove("open", "focus"); input.value = ""; hl = -1; }, 120); });
    input.addEventListener("input", function () { hl = 0; renderList(); });
    input.addEventListener("keydown", function (e) {
      var rows = $$(".wc-ms-opt", list);
      if (e.key === "ArrowDown") { hl = Math.min(hl + 1, rows.length - 1); renderList(); e.preventDefault(); }
      else if (e.key === "ArrowUp") { hl = Math.max(hl - 1, 0); renderList(); e.preventDefault(); }
      else if (e.key === "Enter") { e.preventDefault(); var r = rows[Math.max(hl, 0)]; if (r) r.dispatchEvent(new MouseEvent("mousedown")); }
      else if (e.key === "Backspace" && !input.value) { var s = opts().filter(function (o) { return o.selected; }); if (s.length) { s[s.length - 1].selected = false; changed(); } }
      else if (e.key === "Escape") { input.blur(); }
    });
    sel.addEventListener("wc:sync", renderChips);
    renderChips();
  }

  /* ------------------------------------------------------- Speicherleiste */
  var savebar = null, dirtyForm = null, submitting = false;
  function serialize(f) {
    var parts = [];
    $$("input,select,textarea", f).forEach(function (x) {
      if (!x.name || x.type === "hidden" || x.type === "submit") return;
      if (x.type === "checkbox" || x.type === "radio") parts.push(x.name + "=" + x.checked);
      else if (x.type === "file") parts.push(x.name + "=" + (x.files ? x.files.length : 0));
      else if (x.tagName === "SELECT" && x.multiple) parts.push(x.name + "=" + Array.prototype.map.call(x.selectedOptions, function (o) { return o.value; }).join(","));
      else parts.push(x.name + "=" + x.value);
    });
    return parts.join("&");
  }
  function ensureBar() {
    if (savebar) return savebar;
    savebar = el("div", "wc-savebar");
    savebar.innerHTML = "<i class='bi bi-exclamation-circle'></i><div class='txt'><strong>Ungespeicherte Änderungen</strong><small>Speichere, bevor du die Seite verlässt.</small></div>";
    var reset = el("button", "btn-ghost btn-sm"); reset.type = "button"; reset.innerHTML = "<i class='bi bi-arrow-counterclockwise'></i><span>Verwerfen</span>";
    var save = el("button", "btn-accent btn-sm"); save.type = "button"; save.innerHTML = "<i class='bi bi-check2'></i><span>Speichern</span>";
    reset.addEventListener("click", function () {
      if (!dirtyForm) return; dirtyForm.reset();
      $$("select[data-wc-ms]", dirtyForm).forEach(function (s) { s.dispatchEvent(new Event("wc:sync")); });
      check(dirtyForm);
    });
    save.addEventListener("click", function () { if (dirtyForm) { if (dirtyForm.requestSubmit) dirtyForm.requestSubmit(); else dirtyForm.submit(); } });
    savebar.appendChild(reset); savebar.appendChild(save); document.body.appendChild(savebar);
    return savebar;
  }
  function check(f) {
    var dirty = serialize(f) !== f._wcInitial;
    f._wcDirty = dirty;
    if (dirty) { dirtyForm = f; ensureBar().classList.add("show"); body.classList.add("wc-has-savebar"); }
    else if (dirtyForm === f) {
      var other = $$("form[data-wc-savebar]").filter(function (x) { return x._wcDirty; })[0];
      dirtyForm = other || null;
      if (!other && savebar) { savebar.classList.remove("show"); body.classList.remove("wc-has-savebar"); }
    }
  }
  function initSavebars() {
    if (READONLY) return;
    $$("form[data-wc-savebar]:not([data-wc-locked])").forEach(function (f) {
      f._wcInitial = serialize(f);
      f.addEventListener("input", function () { check(f); });
      f.addEventListener("change", function () { check(f); });
      f.addEventListener("submit", function () { submitting = true; });
    });
    window.addEventListener("beforeunload", function (e) {
      if (submitting) return;
      if ($$("form[data-wc-savebar]").some(function (f) { return f._wcDirty; })) { e.preventDefault(); e.returnValue = ""; }
    });
  }

  /* ------------------------------------------------ Bestätigungsdialog */
  function confirmBox(text, onYes) {
    var bg = el("div", "wc-modal-bg"), m = el("div", "wc-modal");
    m.setAttribute("role", "dialog"); m.setAttribute("aria-modal", "true");
    var h = el("h4"); h.innerHTML = "<i class='bi bi-exclamation-triangle'></i>"; h.appendChild(el("span", null, "Bist du sicher?"));
    var p = el("p", null, text);
    var act = el("div", "wc-form-actions");
    var no = el("button", "btn-ghost"); no.type = "button"; no.textContent = "Abbrechen";
    var yes = el("button", "btn-danger"); yes.type = "button"; yes.textContent = "Ja, fortfahren";
    act.appendChild(no); act.appendChild(yes); m.appendChild(h); m.appendChild(p); m.appendChild(act); bg.appendChild(m);
    function close() { bg.remove(); document.removeEventListener("keydown", key); }
    function key(e) { if (e.key === "Escape") close(); }
    no.addEventListener("click", close); bg.addEventListener("click", function (e) { if (e.target === bg) close(); });
    yes.addEventListener("click", function () { close(); onYes(); });
    document.addEventListener("keydown", key); document.body.appendChild(bg); yes.focus();
  }
  document.addEventListener("click", function (e) {
    var btn = e.target.closest && e.target.closest("button[data-confirm]");
    if (!btn || btn._wcConfirmed || btn.disabled) return;
    e.preventDefault();
    confirmBox(btn.getAttribute("data-confirm"), function () {
      btn._wcConfirmed = true;
      var f = btn.form; if (f) { f._wcConfirmed = true; if (f.requestSubmit) f.requestSubmit(btn); else f.submit(); }
      setTimeout(function () { btn._wcConfirmed = false; }, 500);
    });
  }, true);
  document.addEventListener("submit", function (e) {
    var f = e.target;
    if (!f.getAttribute || !f.getAttribute("data-confirm") || f._wcConfirmed) { if (f) f._wcConfirmed = false; return; }
    e.preventDefault();
    confirmBox(f.getAttribute("data-confirm"), function () { f._wcConfirmed = true; submitting = true; f.submit(); });
  }, true);

  /* -------------------------------------------------- Tabellenfilter */
  $$("input[data-wc-filter]").forEach(function (inp) {
    var table = document.querySelector(inp.getAttribute("data-wc-filter")); if (!table) return;
    inp.addEventListener("input", function () {
      var q = inp.value.trim().toLowerCase();
      $$("tbody tr", table).forEach(function (r) {
        if (r.classList.contains("wc-empty-row")) return;
        r.style.display = !q || r.textContent.toLowerCase().indexOf(q) > -1 ? "" : "none";
      });
    });
  });

  /* ---------------------------------------------------------------- Start */
  initTabs();
  if (content) $$("select[multiple]", content).forEach(enhanceMulti);
  // Tabellen: Spaltennamen je Zelle merken → auf dem Handy als Karten mit Beschriftung darstellen
  $$("table.wc-table").forEach(function (tb) {
    var heads = $$("thead th", tb).map(function (th) { return th.textContent.trim(); });
    $$("tbody tr", tb).forEach(function (tr) {
      $$(":scope > td", tr).forEach(function (td, i) { if (!td.hasAttribute("data-label") && heads[i]) td.setAttribute("data-label", heads[i]); });
    });
  });
  initSavebars();
})();
