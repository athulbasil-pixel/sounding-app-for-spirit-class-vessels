# MarineSense Engine Room Watch Log (Spirit class): build brief

> A phased brief for Claude Code. Do Phase 0 first and stop for design approval.
> Then run each later phase as its own request, using the "Phase N prompt" at the end.

---

## 1. Context

Spirit-class engine rooms record watch readings in an Excel workbook: one `Day N` sheet per day, copied from a `Model` template. Build an offline browser app to replace it. The app is a MarineSense product and must look like one. Use the MarineSense logo and the ergonomic skeuomorphic style of earlier MarineSense tools (ShipSim ECR/OWS panels).

Source workbook, to be **read in place only**: the monthly workbook (e.g. `4 - April 2023.xlsx`), kept **outside** the repo

The repository is **public**. The workbook, real readings, crew names, generated PDFs and the local database must never be committed. Tests and demos use synthetic data only.

### Decisions already made
- **Repository:** this repository, a public GitHub repo with no commits yet.
  Real workbooks and Excel lock files may sit in the working folder. **The first commit must be a `.gitignore` that excludes them. Never `git add .` before that.** Better still, keep workbooks outside the repo folder.
- **Default theme:** Night/ECR dark, with a Day toggle.
- **Skeuomorphism:** moderate. Panel plates, odometer-style counter inputs and indicator lamps, with flat, fast-reading text and no heavy textures.
- **Devices:** both the ECR desktop PC (keyboard-first, wide layout) and a tablet on rounds (touch, one section per screen). The layout must be responsive.
  Because a tablet cannot reach `127.0.0.1` on the ECR PC, v1 stays localhost. An opt-in **LAN mode** (bind to the ECR PC's IP, with a simple PIN) is moved up to Phase 2.

## 2. What the workbook contains (verified; re-check before coding)

Sheets `Day 1` … `Day 31` plus `Model`. Day 31 exists even though April has 30 days, so the app must not infer calendar dates from sheet names. The date cell `B2` on Day 1 holds 20 Nov 2022, a stale template date. **The ship date must be entered explicitly. Do not derive it from sheet names, sheet dates or the Windows clock.**

Day-to-day carry-forward:
- `Prev. Watch` (column F) on Day N is Day N-1's `1800-2400` value (column J).
- Each `BEGIN` row on Day N is Day N-1's `1800-2400` TOTAL row.
- Model's own BEGIN links point to an external workbook (`[1]DAY1!…`) and resolve to `#REF!`. Several TOTAL formulas add `+#REF!+#REF!`. **Do not copy the totals formulas literally. Reimplement the intent.**

Sections, in the workbook's order. Inputs are raw readings; everything marked *calc* is derived.

| # | Section | Inputs per watch | Calculated |
|---|---|---|---|
| A | Fuel counters | Feeder module DG 1-2-3 counter; feeder module DG 4-5-6 counter; Aft boiler HFO counter; Fwd boiler HFO counter | Consumption (Ltr) per watch, daily total |
| B | Fresh-water counters | Aft evaporator LOC and ECR counters; Fwd evaporator LOC and ECR counters; Reverse osmosis ECR counter | Production (m³) per watch and day; total production = Aft + Fwd + RO |
| C | Fresh-water 4-hour schedule | Aft evap, Fwd evap and RO counters at 0400, 0800, 1600 and 2000. **The 1200 and 2400 values reuse the 6-hour watch readings.** Store each reading once. | Production per 4-hour slot |
| D | Aft cleaning cycles | HFO purifier 1, HFO purifier 2, HFO filtration 1, feeder module DG 1-2-3 (TOTAL counts) | PARTIAL per watch, daily total |
| E | Aft tank levels (m³) | HFO service, HFO settling and DO service tanks, ECR and LOCAL level each | none (raw only for now) |
| F | Fwd cleaning cycles | HFO purifier 3, HFO purifier 4, HFO filtrator 2, feeder module DG 4-5-6 | PARTIAL, daily total |
| G | Fwd tank levels (m³) | Same as E, forward | none |
| H | Service air compressors | Aft, Forward, Osmosis room: **operating hours and loading hours separately** | Watch, day, week and month hours |
| I | Control air compressor 3 | Operating hours only | Same as H |
| J | Starting air compressors | No. 1, 2, 3: running-hour totals | Same as H |
| K | DG 1–6 cleaning cycles | TOTAL count per DG | PARTIAL per watch, daily total (**cycle counts, not hours**) |
| L | DG lube-oil sump tanks | DG 1–6: LOC. and DAM. reading per watch | none (raw only) |
| M | Sounding table | M4.1, M4.2, M4.3, M5 (cm), M8 (cm), GS, AFT LT, FWD LT, AFT HT, FWD HT | M4 TOTAL = M4.1+M4.2+M4.3 |

Each section has an Engine Officer signature or initials field.

Units: use only those the workbook states (Ltr, m³, m3, cm, hours, cycles). Where none is stated (M4.x, GS, LT and HT, DG sump LOC and DAM), show "unit unconfirmed" and keep the raw value.

**Real-data pitfall found:** the feeder DG 1-2-3 counter drops from near 1 000 000 to a small value between consecutive days. That is a counter rollover or meter reset. The app must flag it and let the officer mark it as *rollover (modulus N)* or *meter replaced (new opening value)*. It must not report a negative consumption.

Before coding, produce `docs/field_registry.yaml`. List every field with its id, section, label, unit (or "unconfirmed"), kind (`counter`, `cycle_counter`, `hours_counter`, `level`, `sounding`), watch schedule (6h or 4h) and the workbook cell it came from. All app screens, calculations and PDFs are driven from this registry.

## 3. Domain rules

- **Watches:** 0000–0600, 0600–1200, 1200–1800, 1800–2400. The 1800–2400 watch belongs to the date it began. FW 4-hour slots are a separate schedule linked to the same ship date.
- **One log per (ship date, watch)**, enforced by a database unique constraint.
- **Lifecycle:** Draft → Closed → Corrected (vN). Drafts autosave and show "saved hh:mm". Closing requires an officer name and closure time, and shows a review of missing entries. A correction creates a new version with a reason and time. The original closed record is never overwritten.
- **Missing vs zero:** an empty field is *missing*. An explicit `0` is a valid reading. A field may be marked *unavailable* with a reason.
- **Counter differences:** current minus previous *valid* reading, chained across watches, midnight and month-end. The first ever watch takes a manually entered opening balance. A missing reading makes the affected interval *incomplete*, not zero. A reading lower than the previous one is flagged *for review*.
- **Period totals** (day, week, month, last completed watch): sum valid watch differences. Show the dates covered and flag any gaps.
- **M4 total** is calculated only when all three components are present.
- **Deferred:** DG running hours, sludge, tank-volume conversions. Keep the raw soundings so they can be added later.

## 4. Platform

- Python 3.11+, Flask, SQLite (WAL mode), Jinja templates and vanilla JS. All fonts, icons and CSS are bundled locally, with no CDN, so the app works fully offline after install.
- PDFs come from a pure-Python library (e.g. ReportLab) with no system dependencies.
- Data lives in `%LOCALAPPDATA%\MarineSense\WatchLog\` (database, PDFs, backups) and is never stored in the repo. A `.gitignore` excludes `*.xlsx`, `*.sqlite*`, `*.db`, `pdfs/`, `instance/` and `.env`.
- Windows: `START_WATCHLOG_WINDOWS.bat` creates a venv on first run, installs from `requirements.txt` (or a bundled `wheels/` folder for offline install), starts on `http://127.0.0.1:5080` and opens the browser. Also provide `TEST_WATCHLOG_WINDOWS.bat`.
- Localhost only in Phase 1. Opt-in LAN mode for tablets arrives in Phase 2.

## 5. Interface design (to agree in Phase 0)

Brand: the MarineSense waveform logo (white "Marine", yellow "Sense" and a pulse line on navy). Bundle it as `static/brand/marinesense-logo.png`; supply an SVG trace later if available.

Style: ergonomic skeuomorphism in the spirit of ShipSim's ECR panels. It should feel like a physical log board and instrument panel, while staying clean enough for fast data entry.
- Section cards as **panel plates** with subtle bevels, engraved-style labels and screw-corner details kept minimal.
- Counter inputs styled as **mechanical odometer windows** (monospace digits, right-aligned). The previous reading sits beside each input in a recessed plate, and the live difference appears as a small "tape" readout.
- Status shown as **indicator lamps**: green = complete, amber = incomplete or unavailable, red = for review (backwards meter, rollover), grey = not started.
- Two themes, **defaulting to Night / ECR**: Night / ECR (dark graphite, the ShipSim palette `#202124 / #2a2c2f / #35373b`, cyan, green, amber, red, to protect night vision) and **Day** (light navy and white). There is a manual toggle and no auto-switching from the clock.
- Large hit targets (≥ 44 px), readable at arm's length on an ECR PC, usable with gloves on a touch screen.
- **Keyboard first:** Tab and Enter move to the next field in workbook order, Shift+Enter goes back, Esc clears, Ctrl+S saves the draft, and a hotkey opens "jump to section". Numeric `inputmode` on all readings.

Screens:
1. **Home / Watch board.** Ship date picker plus four watch tiles with status lamps. "Resume draft" and "Open current watch" buttons.
2. **Watch entry.** A sticky left rail lists sections A–M with lamps. The main area shows the section plates. A sticky footer shows the saved time, missing count and Review and Close.
3. **Review & close.** Missing and flagged list with jump links, an "unavailable + reason" action, officer name and closure time.
4. **History.** Search by date range and watch. The record view shows inputs, calculations, remarks, officer and versions.
5. **Reports.** Compressor hours (watch, day, week, month), fuel consumption and FW production, with coverage dates and gap flags.
6. **Settings.** Vessel name, opening balances, officer list, theme, backup and export.

## 6. Acceptance checks (synthetic data)

- Enter two consecutive watches, close one, restart the app, reopen it and generate the PDF.
- Compressor readings 86631 then 86635 give 4 h.
- A missing M4 component leaves M4 TOTAL incomplete. An explicit 0 counts as a reading.
- Carry-forward works across midnight (1800–2400 → next day 0000–0600) and month-end (30 Apr → 1 May).
- A backwards counter is flagged. A confirmed rollover gives a correct positive difference.
- The PDF is named `YYYY-MM-DD_HHMM-HHMM_Watch_Log.pdf`, is A4, repeats table headers across pages, marks missing readings, and carries a "Correction vN" banner when corrected.
- `git status` and `git check-ignore` prove the workbook, database, PDFs and real names are excluded.

---

## Phase plan

| Phase | Scope | Exit criterion |
|---|---|---|
| **0 – Design & data map** | Read the workbook, write `field_registry.yaml` and a data-model note, build **static clickable mockups** (Home, Entry, Review, History) in both themes with the logo. No backend. | User approves the look and field map |
| **1 – Core watch entry** | Flask app, SQLite schema, start script, watch board, entry screen driven by the registry, autosave drafts, unique date+watch, opening balances, counter diffs with midnight and month carry-forward, missing/zero/unavailable, M4 total, backwards and rollover flags | Acceptance checks 1–4 pass; user tries it in a browser |
| **2 – Close, history, PDF, LAN** | Review & close, officer and closure time, immutable versions and corrections, history search and detail, A4 PDF, opt-in LAN mode for tablets | PDF and correction checks pass |
| **3 – Reports** | Compressor hours by period (operating and loading kept separate), fuel consumption and FW production totals, coverage and gap flags, CSV export | Period totals match a hand-calculated synthetic month |
| **4 – Hardening** | Backup and restore, offline wheel bundle, optional synthetic-data import tool, accessibility pass; later the deferred conversions once confirmed onboard | Release v1.0 |

### Phase 0 prompt
> Read `WATCHLOG_BUILD_PROMPT.md`. Do Phase 0 only. Inspect the workbook in place (Model plus at least Day 1 and Day 2, including the cross-sheet formulas) and produce `docs/field_registry.yaml` and `docs/data_model.md`. Build static HTML/CSS mockups of the Home, Watch entry, Review & close and History screens, in Night and Day themes, with the MarineSense logo and the skeuomorphic style described in section 5. Use synthetic numbers only. Start a local preview, then stop and list the design decisions you need me to confirm.

### Phase 1–4 prompt (repeat per phase)
> Read `WATCHLOG_BUILD_PROMPT.md` and the approved Phase 0 artefacts. Implement Phase N only. Write tests for every rule in section 3 that this phase touches, run them, launch the app locally and tell me the address, the start command and what to try. Confirm that no real data is tracked by Git.
