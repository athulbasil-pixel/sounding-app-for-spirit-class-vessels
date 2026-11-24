// Watch entry screen: renders sections from the registry layout, autosaves each reading,
// and re-renders calculated state returned by the server (server is the source of truth).
(function () {
  "use strict";
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => [...r.querySelectorAll(s)];
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const fmt = (v) => {
    if (v === null || v === undefined || v === "") return "";
    if (typeof v !== "number") return String(v);
    const [i, d] = String(Math.abs(Math.round(v * 1e6) / 1e6)).split(".");
    return (v < 0 ? "-" : "") + i.replace(/\B(?=(\d{3})+(?!\d))/g, " ") + (d ? "." + d : "");
  };
  const WL = { w1: "0000–0600", w2: "0600–1200", w3: "1200–1800", w4: "1800–2400" };
  const SLOT_AT = { s1: "0400", s2: "0800", s3: "1200", s4: "1600", s5: "2000", s6: "2400" };

  let LAYOUT, STATE, DATE, WATCH, editable = true;
  const pending = new Map();   // key -> timer
  const saved = new Map();     // key -> last saved raw text

  document.addEventListener("DOMContentLoaded", async () => {
    LAYOUT = JSON.parse($("#layout").textContent);
    const ctx = $(".context");
    DATE = ctx.dataset.date; WATCH = ctx.dataset.watch;
    const st = await api("GET");
    if (!st) return;
    build(st);
    render(st);
    bind();
    const first = $("input.odo:not([readonly])");
    if (first) first.focus();
  });

  async function api(method, path = "", body) {
    try {
      const r = await fetch(`/api/watch/${DATE}/${WATCH}${path}`, {
        method, headers: { "Content-Type": "application/json", "X-Watchlog": "1" },
        body: body ? JSON.stringify(body) : undefined,
      });
      const j = await r.json();
      if (!r.ok) { window.msToast(j.error || "Not saved"); return null; }
      return j;
    } catch (e) {
      window.msToast("App not reachable — is the Watch Log window still running?");
      return null;
    }
  }

  // ------------------------------------------------------------ build
  function unitHTML(f) {
    return f.unit ? `<span class="unit">${esc(f.unit)}</span>`
      : `<span class="unit unconf" title="Unit not stated in the workbook — confirm onboard">unit unconfirmed</span>`;
  }

  function rowHTML(item, f, label, sub) {
    const k = esc(item.key);
    const linked = item.linked;
    const input = linked
      ? `<div class="odo linked-odo" data-linked="${k}" aria-label="${esc(label)} (same as 6-hour reading)"></div>`
      : `<input class="odo" data-key="${k}" inputmode="decimal" autocomplete="off" spellcheck="false"
           placeholder="______" aria-label="${esc(label)} current reading">`;
    const html = `
      <div class="lbl" data-row="${k}">${esc(label)}${sub ? `<small>${sub}</small>` : ""}</div>${unitHTML(f)}
      <div class="prev" data-prev="${k}"></div>${input}
      <div class="tape" data-tape="${k}"></div>
      <span class="lamp grey" data-lamp="${k}"></span>
      ${linked ? "<span></span>" : `<button type="button" class="more" data-more="${k}" title="Mark unavailable" aria-label="More for ${esc(label)}" tabindex="-1">⋯</button>`}`;
    // tag every grid cell of this row so the whole row can be hidden when "not in use"
    const tpl = document.createElement("template");
    tpl.innerHTML = html;
    [...tpl.content.children].forEach(el => el.setAttribute("data-rowkey", item.key));
    return [...tpl.content.children].map(el => el.outerHTML).join("") +
      `<div class="flag-note" data-flag="${k}" hidden></div>`;
  }

  function build(st) {
    const secWrap = $(".sections"), rail = $(".rail ol");
    const items = st.items;
    LAYOUT.sections.forEach((s, i) => {
      let rows = "";
      if (s.fw) {
        const bySlot = {};
        items.filter(it => it.section === s.id).forEach(it => (bySlot[it.slot] ||= []).push(it));
        const slots = Object.keys(bySlot);
        if (!slots.length) rows = `<div class="subgroup">No 4-hour reading falls in this watch.</div>`;
        slots.forEach(slot => {
          const slotDef = LAYOUT.slots.find(x => x.id === slot);
          const linked = bySlot[slot][0].linked;
          rows += `<div class="subgroup">Slot ${esc(slotDef.label.replace("-", "–"))} · reading at ${SLOT_AT[slot]}${linked ? " — same reading as section B, stored once" : ""}</div>`;
          bySlot[slot].forEach(it => {
            const f = LAYOUT.fields[it.field];
            rows += rowHTML(it, f, LAYOUT.fw_labels[it.field] || f.label,
              linked ? `<span class="linked">↺ ${WL[WATCH].slice(-4)} reading in B</span>` : `prev = ${SLOT_AT[prevSlot(slot)]} reading`);
          });
        });
      } else {
        let lastGroup = null;
        s.fields.forEach(f => {
          if (f.group && f.group !== lastGroup) { rows += `<div class="subgroup">${esc(s.groups[f.group] || f.group)}</div>`; lastGroup = f.group; }
          const it = items.find(x => x.key === `${f.id}@watch`);
          rows += rowHTML(it, f, f.label, f.derived_label ? `Counter → ${esc(f.derived_label.toLowerCase())} (${esc(f.diff_unit)})` : "");
        });
      }
      const calc = s.id === "M" ? `<div class="calc-row">M4 TOTAL = M4.1 + M4.2 + M4.3 <b data-calc="m4_total"></b></div>`
        : s.id === "B" ? `<div class="calc-row">Total production (Aft LOC + Fwd LOC + RO) this watch <b data-calc="fw_total_production"></b></div>` : "";
      const plate = document.createElement("section");
      plate.className = "plate" + (i === 0 ? " on" : "");
      plate.id = "sec-" + s.id;
      plate.innerHTML = `
        <div class="plate-head"><span class="lamp grey" data-seclamp="${s.id}"></span>
          <h2>${s.id} · ${esc(s.title)}</h2><span class="tag">${esc(s.tag)}</span>
          <span class="right" data-seccount="${s.id}"></span></div>
        <div class="rows">
          <div class="hdr">Equipment</div><div class="hdr">Unit</div><div class="hdr" style="text-align:right">Previous</div>
          <div class="hdr" style="text-align:right">Current</div><div class="hdr" style="text-align:right">Difference</div><div class="hdr"></div><div class="hdr"></div>
          ${rows}${calc}
        </div>
        <div class="pager" style="margin-top:16px">
          <button type="button" class="btn" data-go="${i - 1}" ${i === 0 ? "disabled" : ""}>‹ Previous section</button>
          <button type="button" class="btn primary" data-go="${i + 1}" ${i === LAYOUT.sections.length - 1 ? "disabled" : ""}>Next section ›</button>
        </div>`;
      secWrap.append(plate);
      const li = document.createElement("li");
      li.innerHTML = `<a href="#sec-${s.id}" data-sec="${i}"><span class="lamp grey" data-raillamp="${s.id}"></span><span class="k">${s.id}</span>${esc(s.title)}<span class="cnt" data-railcnt="${s.id}"></span></a>`;
      rail.append(li);
    });
    const rem = document.createElement("section");
    rem.className = "plate"; rem.id = "sec-remarks";
    rem.innerHTML = `<div class="plate-head"><h2>Remarks</h2></div>
      <textarea class="remarks" data-remarks rows="3" maxlength="4000" placeholder="Watch remarks (optional)"></textarea>`;
    secWrap.append(rem);
    $(".rail a").classList.add("active");

    // fill inputs from state
    st.items.forEach(it => {
      const el = inputFor(it.key);
      if (!el) return;
      const v = it.state === "entered" ? (it.raw ?? fmtRaw(it.value)) : "";
      el.value = v; saved.set(it.key, v);
    });
    $("[data-remarks]").value = (st.log && st.log.remarks) || "";
  }

  function prevSlot(s) { const a = ["s1", "s2", "s3", "s4", "s5", "s6"]; return a[(a.indexOf(s) + 5) % 6]; }
  function fmtRaw(v) { return v === null || v === undefined ? "" : String(v); }
  function inputFor(key) { return $(`input.odo[data-key="${CSS.escape(key)}"]`); }

  // ------------------------------------------------------------ render state
  function render(st) {
    STATE = st;
    const log = st.log || {};
    editable = log.status === "draft";
    $("[data-status]").textContent = (log.status || "").toUpperCase();
    $("[data-status-lamp]").className = "lamp " + (log.status === "closed" ? "green" : "amber");
    $("[data-saved]").textContent = log.saved_at ? "draft saved " + log.saved_at.slice(11, 16) : "nothing saved yet";

    st.items.forEach(it => {
      const k = CSS.escape(it.key);
      const f = LAYOUT.fields[it.field];
      // hidden (not in use)
      $$(`[data-rowkey="${k}"]`).forEach(el => el.classList.toggle("not-in-use", !!it.hidden));
      if (it.hidden) { $(`[data-flag="${k}"]`).hidden = true; return; }
      // previous
      const prev = $(`[data-prev="${k}"]`);
      if (it.prev !== null && it.prev !== undefined) {
        prev.innerHTML = esc(fmt(it.prev)) + (it.prev_note ? `<small>${esc(it.prev_note.toUpperCase())}</small>` : "");
        prev.title = it.prev_note || "Previous reading";
      } else if (it.prev_last_valid) {
        const lv = it.prev_last_valid;
        prev.innerHTML = `<span class="gapv">${esc(fmt(lv.value))}</span><small>GAP · LAST ${esc(lv.ship_date.slice(5))} ${esc(lv.point)}</small>`;
        prev.title = "Previous reading is missing — last valid reading shown";
      } else {
        const note = (it.prev_note || "").startsWith("gap") ? "not recorded" : (it.prev_note || "no previous");
        prev.innerHTML = `—<small>${esc(note.toUpperCase())}</small>`;
        prev.title = (it.prev_note || "").startsWith("gap") ? "No reading in the previous watch" : "No earlier reading or opening balance";
      }
      // current
      const input = $(`input.odo[data-key="${k}"]`);
      if (input) {
        const unavailable = it.state === "unavailable";
        input.classList.toggle("unavailable", unavailable);
        input.readOnly = !editable || unavailable;
        if (unavailable) input.value = "Unavailable: " + (it.reason || "");
        else if (document.activeElement !== input && !pending.has(it.key)) {
          const v = it.state === "entered" ? (it.raw ?? fmtRaw(it.value)) : "";
          input.value = v; saved.set(it.key, v);
        }
      }
      const linked = $(`[data-linked="${k}"]`);
      if (linked) {
        linked.textContent = it.state === "entered" ? fmt(it.value) : "awaiting B";
        linked.classList.toggle("awaiting", it.state !== "entered");
      }
      // tape
      const tape = $(`[data-tape="${k}"]`);
      const isCounter = ["counter", "hours_counter", "cycle_counter"].includes(f.kind);
      let t = "", cls = "none";
      if (it.state === "unavailable") { t = "unavailable"; cls = "incomplete"; }
      else if (it.state !== "entered") { t = "—"; cls = "none"; }
      else if (!isCounter) { t = "recorded"; cls = "none"; }
      else if (it.diff_status === "ok") { t = `+${fmt(it.diff)} ${f.diff_unit}`; cls = ""; if (it.diff_note) t += " ↻"; }
      else if (it.diff_status === "review") { t = `▼ ${fmt(it.diff)}`; cls = "review"; }
      else if (it.diff_status === "no_previous") { t = "no previous"; cls = "incomplete"; }
      else { t = "incomplete"; cls = "incomplete"; }
      tape.textContent = t; tape.className = "tape " + cls;
      tape.title = it.diff_note || (cls === "incomplete" ? "Difference cannot be calculated for this interval" : "");
      $(`[data-lamp="${k}"]`).className = "lamp " + it.lamp;
      // flag / event note
      const flag = $(`[data-flag="${k}"]`);
      if (it.diff_status === "review") {
        flag.hidden = false; flag.className = "flag-note";
        flag.innerHTML = `<span class="lamp red"></span>
          <span><b>Counter went backwards</b> (${esc(fmt(it.prev))} → ${esc(fmt(it.value))}). Excluded from totals until confirmed.</span>
          ${editable ? `<button type="button" class="btn" data-ev="rollover" data-k="${esc(it.key)}">Rollover</button>
          <button type="button" class="btn" data-ev="meter" data-k="${esc(it.key)}">Meter replaced…</button>
          <button type="button" class="btn ghost" data-ev="reenter" data-k="${esc(it.key)}">Re-enter</button>` : ""}`;
      } else if (it.event) {
        flag.hidden = false; flag.className = "flag-note ok";
        const what = it.event.kind === "rollover" ? `Rollover confirmed (${esc(it.diff_note || "")})`
          : `Meter replaced — new meter opened at ${esc(fmt(it.event.value))}`;
        flag.innerHTML = `<span class="lamp green"></span><span>${what}${it.event.reason ? " · " + esc(it.event.reason) : ""}</span>
          ${editable ? `<button type="button" class="btn ghost" data-ev="undo" data-k="${esc(it.key)}">Undo</button>` : ""}`;
      } else flag.hidden = true;
      const more = $(`[data-more="${k}"]`);
      if (more) { more.disabled = !editable; more.textContent = it.state === "unavailable" ? "↺" : "⋯";
        more.title = it.state === "unavailable" ? "Clear 'unavailable'" : "Mark unavailable"; }
    });

    st.sections.forEach(s => {
      const lamp = s.count ? s.lamp : "off";
      $(`[data-seclamp="${s.id}"]`).className = "lamp " + lamp;
      $(`[data-raillamp="${s.id}"]`).className = "lamp " + lamp;
      $(`[data-railcnt="${s.id}"]`).textContent = s.count ? `${s.entered + s.unavailable + s.review}/${s.count}` : "–";
      const parts = [];
      if (s.missing) parts.push(`${s.missing} missing`);
      if (s.unavailable) parts.push(`${s.unavailable} unavailable`);
      if (s.review) parts.push(`${s.review} for review`);
      parts.push(`${s.entered + s.unavailable + s.review}/${s.count} done`);
      $(`[data-seccount="${s.id}"]`).textContent = parts.join(" · ");
    });
    for (const [id, c] of Object.entries(st.calcs)) {
      const el = $(`[data-calc="${id}"]`);
      if (!el) continue;
      if (c.status === "ok") { el.textContent = fmt(c.value) + (c.unit ? " " + c.unit : ""); el.className = ""; }
      else { el.textContent = "INCOMPLETE"; el.className = "calc-incomplete"; }
    }
    const t = st.totals;
    $("[data-stat-done]").textContent = `${t.entered}/${t.count}`;
    $("[data-stat-missing]").textContent = t.missing;
    $("[data-stat-unavail]").textContent = t.unavailable;
    $("[data-stat-review]").textContent = t.review;
    $("[data-remarks]").readOnly = !editable;
    if (!editable) $("[data-saved]").textContent = "closed " + (log.closed_at || "").slice(0, 16).replace("T", " ");
  }

  // ------------------------------------------------------------ saving
  function itemByKey(key) { return STATE.items.find(i => i.key === key); }

  function queueSave(input, delay = 700) {
    const key = input.dataset.key;
    clearTimeout(pending.get(key));
    pending.set(key, setTimeout(() => flush(key), delay));
    $("[data-saved]").textContent = "saving…";
  }

  async function flush(key) {
    clearTimeout(pending.get(key));
    const input = inputFor(key);
    if (!input || input.readOnly) { pending.delete(key); return; }
    const raw = input.value.trim();
    if (raw === saved.get(key)) { pending.delete(key); render(STATE); return; }
    const it = itemByKey(key);
    const st = await api("PUT", "/reading", { field: it.field, slot: it.slot, raw, status: "entered" });
    pending.delete(key);
    if (st) { saved.set(key, raw); input.classList.remove("bad"); render(st); }
    else input.classList.add("bad");
  }

  async function flushAll() { await Promise.all([...pending.keys()].map(flush)); }

  // ------------------------------------------------------------ interactions
  function bind() {
    const secWrap = $(".sections");
    secWrap.addEventListener("input", (e) => {
      if (e.target.matches("input.odo")) queueSave(e.target);
      if (e.target.matches("[data-remarks]")) {
        clearTimeout(bind._rt);
        bind._rt = setTimeout(async () => {
          const r = await api("PUT", "/remarks", { remarks: e.target.value });
          if (r) $("[data-saved]").textContent = "draft saved " + r.saved_at.slice(11, 16);
        }, 800);
      }
    });
    secWrap.addEventListener("focusout", (e) => { if (e.target.matches("input.odo") && pending.has(e.target.dataset.key)) flush(e.target.dataset.key); });
    secWrap.addEventListener("focusin", (e) => { if (e.target.matches("input.odo")) { e.target.select(); showSectionOf(e.target); } });

    const inputs = () => $$("input.odo:not([readonly])").filter(el => !el.classList.contains("not-in-use"));
    document.addEventListener("keydown", (e) => {
      const list = inputs();
      const idx = list.indexOf(document.activeElement);
      if (e.key === "Enter" && idx >= 0) {
        e.preventDefault();
        if (pending.has(list[idx].dataset.key)) flush(list[idx].dataset.key);
        const next = list[idx + (e.shiftKey ? -1 : 1)];
        if (next) { showSectionOf(next); next.focus(); }
      } else if (e.key === "Escape" && idx >= 0) {
        const key = list[idx].dataset.key;
        clearTimeout(pending.get(key)); pending.delete(key);
        list[idx].value = saved.get(key) ?? ""; list[idx].classList.remove("bad"); render(STATE);
      } else if (e.ctrlKey && e.key.toLowerCase() === "s") {
        e.preventDefault(); flushAll().then(() => window.msToast("Draft saved"));
      } else if (e.ctrlKey && e.key.toLowerCase() === "j") {
        e.preventDefault(); openJump();
      }
    });
    window.addEventListener("beforeunload", (e) => { if (pending.size) { flushAll(); e.preventDefault(); } });

    // unavailable / events
    document.addEventListener("click", async (e) => {
      const more = e.target.closest("[data-more]");
      if (more && editable) {
        const it = itemByKey(more.dataset.more);
        if (it.state === "unavailable") {
          const st = await api("PUT", "/reading", { field: it.field, slot: it.slot, raw: "", status: "entered" });
          if (st) { saved.set(it.key, ""); render(st); const inp = inputFor(it.key); inp.value = ""; inp.focus(); }
        } else openUnavailable(it);
        return;
      }
      const ev = e.target.closest("[data-ev]");
      if (ev) {
        const it = itemByKey(ev.dataset.k);
        const body = { field: it.field, series: it.series, point: it.point };
        if (ev.dataset.ev === "rollover") {
          const st = await api("POST", "/event", { ...body, kind: "rollover" }); if (st) render(st);
        } else if (ev.dataset.ev === "undo") {
          const st = await api("DELETE", "/event", body); if (st) render(st);
        } else if (ev.dataset.ev === "meter") openMeter(it, body);
        else if (ev.dataset.ev === "reenter") { const inp = inputFor(it.key); inp.focus(); inp.select(); }
      }
      const a = e.target.closest("[data-sec]"); if (a) { e.preventDefault(); goSection(+a.dataset.sec); }
      const g = e.target.closest("[data-go]"); if (g) goSection(+g.dataset.go);
    });

    $("[data-open-jump]").addEventListener("click", openJump);
    const rv = $("[data-review]");
    if (rv) rv.addEventListener("click", async (e) => { e.preventDefault(); await flushAll(); location.href = rv.href; });
    const dlg = $("#jump");
    dlg.addEventListener("click", (e) => {
      const b = e.target.closest("[data-jump]");
      if (!b) { if (e.target === dlg) dlg.close(); return; }
      dlg.close(); goSection(+b.dataset.jump);
    });
  }

  function openUnavailable(it) {
    const dlg = $("#unavail"), f = LAYOUT.fields[it.field];
    $("[data-unavail-label]", dlg).textContent = f.label + (it.slot !== "watch" ? ` (slot ${it.slot})` : "");
    const reason = $("input[name=reason]", dlg); reason.value = "";
    $$("[data-reason]", dlg).forEach(b => b.onclick = () => { reason.value = b.dataset.reason; reason.focus(); });
    dlg.onclose = async () => {
      if (dlg.returnValue !== "ok") return;
      if (!reason.value.trim()) { window.msToast("A reason is required"); return; }
      const st = await api("PUT", "/reading", { field: it.field, slot: it.slot, status: "unavailable", reason: reason.value.trim() });
      if (st) { saved.set(it.key, ""); render(st); }
    };
    dlg.returnValue = ""; dlg.showModal(); reason.focus();
  }

  function openMeter(it, body) {
    const dlg = $("#meter");
    $("[data-meter-label]", dlg).textContent = `${LAYOUT.fields[it.field].label}: current reading ${fmt(it.value)}. ` +
      `Enter the reading of the new meter when it was fitted; this watch's difference is counted from there.`;
    const v = $("input[name=value]", dlg), r = $("input[name=reason]", dlg); v.value = "0"; r.value = "";
    dlg.onclose = async () => {
      if (dlg.returnValue !== "ok") return;
      const st = await api("POST", "/event", { ...body, kind: "meter_replaced", value: v.value, reason: r.value });
      if (st) render(st);
    };
    dlg.returnValue = ""; dlg.showModal(); v.select();
  }

  function openJump() {
    const dlg = $("#jump");
    $("ol", dlg).innerHTML = LAYOUT.sections.map((s, i) =>
      `<li><button type="button" data-jump="${i}"><span class="${$(`[data-raillamp="${s.id}"]`).className}"></span><b>${s.id}</b> ${esc(s.title)}</button></li>`).join("");
    dlg.showModal(); $("button", dlg).focus();
  }

  function goSection(i) {
    const plates = $$(".sections > .plate:not(#sec-remarks)");
    if (i < 0 || i >= plates.length) return;
    plates.forEach((p, k) => p.classList.toggle("on", k === i));
    $$(".rail a").forEach((a, k) => a.classList.toggle("active", k === i));
    plates[i].scrollIntoView({ behavior: "smooth", block: "start" });
    const first = $$("input.odo:not([readonly])", plates[i]).find(el => !el.classList.contains("not-in-use"));
    if (first) setTimeout(() => first.focus({ preventScroll: true }), 250);
  }
  function showSectionOf(el) {
    const plate = el.closest(".plate");
    const plates = $$(".sections > .plate:not(#sec-remarks)");
    const i = plates.indexOf(plate);
    if (i < 0) return;
    plates.forEach((p, k) => p.classList.toggle("on", k === i));
    $$(".rail a").forEach((a, k) => a.classList.toggle("active", k === i));
  }
})();
