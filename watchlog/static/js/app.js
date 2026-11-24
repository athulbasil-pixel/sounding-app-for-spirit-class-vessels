// Shared: theme rocker (Night default) and toast messages.
(function () {
  "use strict";
  function syncRocker() {
    const t = document.documentElement.dataset.theme;
    document.querySelectorAll("[data-theme-btn]").forEach(b => b.setAttribute("aria-pressed", String(b.dataset.themeBtn === t)));
  }
  document.addEventListener("DOMContentLoaded", syncRocker);
  document.addEventListener("click", (e) => {
    const b = e.target.closest("[data-theme-btn]");
    if (!b) return;
    document.documentElement.dataset.theme = b.dataset.themeBtn;
    localStorage.setItem("ms-theme", b.dataset.themeBtn);
    syncRocker();
  });
  // reviewer feedback dialog (bottom-left button on every screen)
  document.addEventListener("click", (e) => {
    if (!e.target.closest("[data-fb-open]")) return;
    const dlg = document.getElementById("fb-dialog");
    if (!dlg) return;
    dlg.querySelector("[data-fb-where]").textContent = "Screen: " + document.title.replace(" · MarineSense", "");
    const ta = dlg.querySelector("textarea"); ta.value = "";
    dlg.onclose = async () => {
      if (dlg.returnValue !== "ok" || !ta.value.trim()) return;
      try {
        const r = await fetch("/api/feedback", { method: "POST",
          headers: { "Content-Type": "application/json", "X-Watchlog": "1" },
          body: JSON.stringify({ page: location.pathname + location.search, page_title: document.title.replace(" · MarineSense", ""),
                                 category: dlg.querySelector("select").value, text: ta.value }) });
        const j = await r.json();
        window.msToast(r.ok ? `Note saved (${j.count} in total)` : (j.error || "Not saved"));
      } catch (err) { window.msToast("Not saved — is the Watch Log still running?"); }
    };
    dlg.returnValue = ""; dlg.showModal(); ta.focus();
  });

  window.msToast = function (msg) {
    let el = document.querySelector(".toast");
    if (!el) { el = document.createElement("div"); el.className = "toast"; el.setAttribute("role", "status"); document.body.append(el); }
    el.textContent = msg; el.classList.add("show");
    clearTimeout(el._t); el._t = setTimeout(() => el.classList.remove("show"), 2600);
  };
})();
