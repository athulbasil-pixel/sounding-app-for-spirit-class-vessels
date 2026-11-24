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
  window.msToast = function (msg) {
    let el = document.querySelector(".toast");
    if (!el) { el = document.createElement("div"); el.className = "toast"; el.setAttribute("role", "status"); document.body.append(el); }
    el.textContent = msg; el.classList.add("show");
    clearTimeout(el._t); el._t = setTimeout(() => el.classList.remove("show"), 2600);
  };
})();
