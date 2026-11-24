// MarineSense Watch Log — Phase 0 clickable mockup (no backend, synthetic data)
(function () {
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => [...r.querySelectorAll(s)];
  const fmt = (v) => (v === null || v === undefined || v === "") ? "" :
    (typeof v === "number" ? v.toLocaleString("en-GB", { maximumFractionDigits: 2 }).replace(/,/g, " ") : String(v));
  const num = (s) => {
    if (s === null || s === undefined) return null;
    const t = String(s).replace(/\s/g, "").replace(/[+~-]$/, "");
    if (t === "") return null;
    const n = Number(t);
    return Number.isFinite(n) ? n : null;
  };

  // ---------- theme ----------
  const theme = localStorage.getItem("ms-theme") || "night";
  document.documentElement.dataset.theme = theme;

  function brandbar(page) {
    const nav = [["index.html", "Watch board", "board"], ["entry.html", "Watch entry", "entry"],
                 ["history.html", "History", "history"], ["#", "Reports", "reports"], ["#", "Settings", "settings"]];
    const t = document.documentElement.dataset.theme;
    return `
      <img class="logo" src="../watchlog/static/brand/marinesense-logo.png" alt="MarineSense">
      <div class="app-title"><b>Engine Room Watch Log</b><span>Spirit class · Phase 0 mockup</span></div>
      <nav>${nav.map(([h, l, k]) => `<a href="${h}" ${k === page ? 'aria-current="page"' : ""} ${h === "#" ? 'title="Phase 3/4" style="opacity:.5"' : ""}>${l}</a>`).join("")}</nav>
      <span class="spacer"></span>
      <span class="vessel">${MOCK.vessel}</span>
      <div class="rocker" role="group" aria-label="Theme">
        <button data-theme-btn="night" aria-pressed="${t === "night"}">NIGHT</button>
        <button data-theme-btn="day" aria-pressed="${t === "day"}">DAY</button>
      </div>`;
  }

  function toast(msg) {
    let el = $(".toast");
    if (!el) { el = document.createElement("div"); el.className = "toast"; document.body.append(el); }
    el.textContent = msg; el.classList.add("show");
    clearTimeout(el._t); el._t = setTimeout(() => el.classList.remove("show"), 1800);
  }
  window.msToast = toast;

  document.addEventListener("DOMContentLoaded", () => {
    const page = document.body.dataset.page;
    const bar = $(".brandbar");
    if (bar) bar.innerHTML = brandbar(page);
    document.addEventListener("click", (e) => {
      const b = e.target.closest("[data-theme-btn]");
      if (!b) return;
      document.documentElement.dataset.theme = b.dataset.themeBtn;
      localStorage.setItem("ms-theme", b.dataset.themeBtn);
      $$("[data-theme-btn]").forEach(x => x.setAttribute("aria-pressed", x === b));
    });
    if (page === "entry") initEntry();
  });

  // ---------- entry page ----------
  function evalField(f, raw) {
    // returns {lamp, tape, tapeClass, flag}
    if (f.unavailable) return { lamp: "amber", tape: "unavailable", tapeClass: "incomplete" };
    const v = num(raw);
    const isCounter = ["counter", "cycle", "hours"].includes(f.kind);
    if (v === null) return { lamp: "grey", tape: isCounter ? "incomplete" : "missing", tapeClass: "incomplete", missing: true };
    if (!isCounter) {
      return { lamp: "green", tape: f.unit === null ? "raw kept" : "level", tapeClass: "none" };
    }
    if (f.prev === null) return { lamp: "amber", tape: "no previous", tapeClass: "incomplete" };
    const d = v - f.prev;
    if (d < 0) return { lamp: "red", tape: `▼ ${fmt(d)}`, tapeClass: "review", review: true };
    const unit = f.kind === "hours" ? "h" : f.kind === "cycle" ? "cyc" : f.unit;
    return { lamp: "green", tape: `+${fmt(Math.round(d * 100) / 100)} ${unit}` , tapeClass: "" };
  }

  function rowHTML(f) {
    if (f.group) return `<div class="subgroup">${f.group}</div>`;
    const unit = f.unit ? `<span class="unit">${f.unit}</span>` : `<span class="unit unconf" title="Unit not stated in workbook — confirm onboard">unit unconfirmed</span>`;
    const prev = f.prev === null ? `<div class="prev">—<small>NO PREVIOUS</small></div>`
      : `<div class="prev" title="Previous valid reading">${fmt(f.prev)}</div>`;
    let input;
    if (f.linked) {
      input = `<div class="odo mono" data-linked="${f.linked}" style="opacity:.8" aria-label="${f.label} (linked)"></div>`;
    } else if (f.unavailable) {
      input = `<input class="odo unavailable" data-id="${f.id}" value="Unavailable: ${f.unavailable}" readonly>`;
    } else {
      input = `<input class="odo" data-id="${f.id}" inputmode="decimal" autocomplete="off" placeholder="______"
        aria-label="${f.label} current reading" value="${f.cur === null || f.cur === undefined ? "" : String(f.cur)}">`;
    }
    const linkedTag = f.linked ? `<small><span class="linked">↺ same as 1200 reading in B</span></small>` : (f.sub ? `<small>${f.sub}</small>` : "");
    return `
      <div class="lbl">${f.label}${linkedTag}</div>${unit}${prev}${input}
      <div class="tape" data-tape="${f.id}"></div>
      <span class="lamp grey" data-lamp="${f.id}"></span>
      <button class="more" title="Mark unavailable / add note" aria-label="More for ${f.label}" tabindex="-1">⋯</button>
      <div class="flag-note" data-flag="${f.id}" hidden>
        <span class="lamp red"></span>
        <span><b>Counter went backwards</b> (${fmt(f.prev)} → <span data-flagval></span>). Excluded from totals until confirmed.</span>
        <button class="btn">Rollover (modulus 1 000 000)</button>
        <button class="btn">Meter replaced…</button>
        <button class="btn ghost">Re-enter</button>
      </div>`;
  }

  function initEntry() {
    const secWrap = $(".sections"), rail = $(".rail ol");
    MOCK.sections.forEach((s, i) => {
      const plate = document.createElement("section");
      plate.className = "plate" + (i === 0 ? " on" : "");
      plate.id = "sec-" + s.id;
      plate.innerHTML = `
        <div class="plate-head"><span class="lamp grey" data-seclamp="${s.id}"></span>
          <h2>${s.id} · ${s.title}</h2><span class="tag">${s.tag}</span>
          <span class="right" data-seccount="${s.id}"></span></div>
        <div class="rows">
          <div class="hdr">Equipment</div><div class="hdr">Unit</div><div class="hdr" style="text-align:right">Previous</div>
          <div class="hdr" style="text-align:right">Current</div><div class="hdr" style="text-align:right">Difference</div><div class="hdr"></div><div class="hdr"></div>
          ${s.fields.map(rowHTML).join("")}
          ${s.calc === "m4_total" ? `<div class="calc-row">M4 TOTAL = M4.1 + M4.2 + M4.3 <b data-calc="m4"></b></div>` : ""}
          ${s.calc === "fw_total" ? `<div class="calc-row">Total production (Aft LOC + Fwd LOC + RO) <b data-calc="fw"></b></div>` : ""}
        </div>
        <div class="pager" style="margin-top:16px">
          <button class="btn" data-go="${i - 1}" ${i === 0 ? "disabled" : ""}>‹ Previous section</button>
          <button class="btn primary" data-go="${i + 1}">${i === MOCK.sections.length - 1 ? "Review & close ›" : "Next section ›"}</button>
        </div>`;
      secWrap.append(plate);
      const li = document.createElement("li");
      li.innerHTML = `<a href="#sec-${s.id}" data-sec="${i}"><span class="lamp grey" data-raillamp="${s.id}"></span><span class="k">${s.id}</span>${s.title}<span class="cnt" data-railcnt="${s.id}"></span></a>`;
      rail.append(li);
    });

    const inputs = () => $$("input.odo:not([readonly])");
    const fieldById = {};
    MOCK.sections.forEach(s => s.fields.forEach(f => { if (f.id) fieldById[f.id] = { f, s }; }));

    function refresh() {
      let missing = 0, review = 0, done = 0, total = 0;
      const vals = {};
      $$("input.odo").forEach(el => { vals[el.dataset.id] = el.value; });
      MOCK.sections.forEach(s => {
        let sm = 0, sr = 0, sd = 0, st = 0;
        s.fields.forEach(f => {
          if (!f.id) return;
          let raw = vals[f.id];
          if (f.linked) {
            raw = vals[f.linked];
            const box = $(`[data-linked="${f.linked}"]`, $("#sec-" + s.id));
            $$(`[data-linked="${f.linked}"]`).forEach(b => b.textContent = raw ? fmt(num(raw)) : "awaiting B");
          }
          const r = evalField(f, raw);
          const tape = $(`[data-tape="${CSS.escape(f.id)}"]`);
          tape.textContent = r.tape; tape.className = "tape " + r.tapeClass;
          $(`[data-lamp="${CSS.escape(f.id)}"]`).className = "lamp " + r.lamp;
          const flag = $(`[data-flag="${CSS.escape(f.id)}"]`);
          if (flag) { flag.hidden = !r.review; if (r.review) $("[data-flagval]", flag).textContent = fmt(num(raw)); }
          if (f.linked) return;
          st++; total++;
          if (r.missing) { sm++; missing++; } else if (r.review) { sr++; review++; } else { sd++; done++; }
        });
        const lamp = sr ? "red" : sm ? (sd ? "amber" : "grey") : "green";
        $(`[data-seclamp="${s.id}"]`).className = "lamp " + lamp;
        $(`[data-raillamp="${s.id}"]`).className = "lamp " + lamp;
        $(`[data-railcnt="${s.id}"]`).textContent = `${sd + sr}/${st}`;
        $(`[data-seccount="${s.id}"]`).textContent = `${sm ? sm + " missing · " : ""}${sr ? sr + " for review · " : ""}${sd + sr}/${st} entered`;
      });
      // calculated values
      const m4 = ["m4_1", "m4_2", "m4_3"].map(k => num(vals[k]));
      const m4el = $('[data-calc="m4"]');
      if (m4.some(v => v === null)) { m4el.textContent = "INCOMPLETE"; m4el.style.color = "var(--lamp-amber)"; }
      else { m4el.textContent = fmt(Math.round(m4.reduce((a, b) => a + b, 0) * 100) / 100); m4el.style.color = ""; }
      const fwParts = ["aft_evap_loc_counter", "fwd_evap_loc_counter", "ro_ecr_counter"].map(k => {
        const v = num(vals[k]); const p = fieldById[k].f.prev; return (v === null || p === null || v < p) ? null : v - p; });
      const fwel = $('[data-calc="fw"]');
      if (fwParts.some(v => v === null)) { fwel.textContent = "INCOMPLETE"; fwel.style.color = "var(--lamp-amber)"; }
      else { fwel.textContent = fwParts.reduce((a, b) => a + b, 0) + " m³"; fwel.style.color = ""; }

      $("[data-stat-missing]").textContent = missing;
      $("[data-stat-review]").textContent = review;
      $("[data-stat-done]").textContent = `${done + review}/${total}`;
    }

    // live update + "autosave" indicator
    let saveTimer;
    secWrap.addEventListener("input", () => {
      refresh();
      $("[data-saved]").textContent = "saving…";
      clearTimeout(saveTimer);
      saveTimer = setTimeout(() => {
        const t = new Date(); $("[data-saved]").textContent = "draft saved " + t.toTimeString().slice(0, 5);
      }, 700);
    });

    // keyboard: Enter = next field, Shift+Enter = previous, Esc = clear, Ctrl+S save, Ctrl+J jump
    document.addEventListener("keydown", (e) => {
      const list = inputs();
      const idx = list.indexOf(document.activeElement);
      if (e.key === "Enter" && idx >= 0) {
        e.preventDefault();
        const next = list[idx + (e.shiftKey ? -1 : 1)];
        if (next) { showSectionOf(next); next.focus(); next.select(); }
      } else if (e.key === "Escape" && idx >= 0) {
        list[idx].value = ""; refresh();
      } else if (e.ctrlKey && e.key.toLowerCase() === "s") {
        e.preventDefault(); toast("Draft saved"); $("[data-saved]").textContent = "draft saved " + new Date().toTimeString().slice(0, 5);
      } else if (e.ctrlKey && e.key.toLowerCase() === "j") {
        e.preventDefault(); openJump();
      }
    });
    secWrap.addEventListener("focusin", (e) => { if (e.target.matches("input.odo")) e.target.select(); });

    // jump dialog
    const dlg = $("#jump");
    function openJump() {
      $("ol", dlg).innerHTML = MOCK.sections.map((s, i) =>
        `<li><button data-jump="${i}"><span class="${$(`[data-raillamp="${s.id}"]`).className}"></span><b>${s.id}</b> ${s.title}</button></li>`).join("");
      dlg.showModal(); $("button", dlg).focus();
    }
    dlg.addEventListener("click", (e) => {
      const b = e.target.closest("[data-jump]"); if (!b) { if (e.target === dlg) dlg.close(); return; }
      dlg.close(); goSection(+b.dataset.jump);
    });
    $("[data-open-jump]").addEventListener("click", openJump);

    // section navigation (rail + tablet pager)
    function goSection(i) {
      const plates = $$(".sections > .plate");
      if (i >= plates.length) { location.href = "review.html"; return; }
      if (i < 0) return;
      plates.forEach((p, k) => p.classList.toggle("on", k === i));
      $$(".rail a").forEach((a, k) => a.classList.toggle("active", k === i));
      plates[i].scrollIntoView({ behavior: "smooth", block: "start" });
      const first = $("input.odo:not([readonly])", plates[i]); if (first) setTimeout(() => first.focus({ preventScroll: true }), 250);
    }
    function showSectionOf(el) {
      const plate = el.closest(".plate"); const plates = $$(".sections > .plate");
      const i = plates.indexOf(plate);
      if (!plate.classList.contains("on")) { plates.forEach((p, k) => p.classList.toggle("on", k === i)); }
      $$(".rail a").forEach((a, k) => a.classList.toggle("active", k === i));
    }
    document.addEventListener("click", (e) => {
      const a = e.target.closest("[data-sec]"); if (a) { e.preventDefault(); goSection(+a.dataset.sec); }
      const g = e.target.closest("[data-go]"); if (g) goSection(+g.dataset.go);
    });
    $(".rail a").classList.add("active");
    refresh();
  }
})();
