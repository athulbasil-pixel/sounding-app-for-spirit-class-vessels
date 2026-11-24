# MarineSense Engine Room Watch Log — Spirit class

This app replaces the Excel engine-room watch and sounding workbook with an offline browser app built on Flask and SQLite.

**Version 1.0.0**: watch entry, close, history, corrections, PDF, reports, backups, training mode and tablet (LAN) mode. See [CHANGELOG.md](CHANGELOG.md).

## Install on another PC (no Python needed)

Send **`MarineSense_WatchLog_Setup_<version>.exe`**. It installs for the current Windows user, with no administrator rights, on Windows 10/11 64-bit.
- The Start menu gets shortcuts for normal use, **Training (sample data)**, **Tablet access (LAN)** and the **Reviewer guide**.
- The installer isn't code-signed yet, so Windows may show "Windows protected your PC". Click **More info → Run anyway**.
- Uninstalling removes the program but keeps the data folder.

To build it (needs Python 3.12 and Inno Setup 6), run `BUILD_INSTALLER_WINDOWS.bat`. The installer is written to `installer\Output\`, which is git-ignored.

**Reviewer feedback:** the yellow **✎ Feedback** button on every screen saves a note tagged with that screen. **Feedback → Export notes** saves one text file containing only notes, name and version, never readings. Notes from normal and training mode share one file.

## Start (Windows)

1. Install **Python 3.11 or newer** from python.org and tick *Add Python to PATH*.
2. Double-click **`START_WATCHLOG_WINDOWS.bat`**.
   - The first run creates `.venv` and installs Flask, PyYAML, fpdf2 and waitress. After an update that adds packages, it installs them automatically. This needs internet once, unless a `wheels\` folder with the packages sits next to the script.
   - After that the app starts offline and opens **http://127.0.0.1:5080/** in your browser.
3. Keep the black console window open while using the log. Close it, or press Ctrl+C, to stop.

To use tablets on the ship's network, see *Tablet access* below.

| Script | What it does |
|---|---|
| `START_WATCHLOG_WINDOWS.bat` | Normal use at the ECR PC |
| `START_WATCHLOG_LAN_WINDOWS.bat` | Same, plus PIN-protected access for tablets |
| `START_WATCHLOG_DEMO_WINDOWS.bat` | **Training mode** with synthetic data in a separate folder, on http://127.0.0.1:5081/ |
| `BUILD_OFFLINE_BUNDLE_WINDOWS.bat` | Downloads all packages into `wheels\` so a ship PC can install without internet |
| `TEST_WATCHLOG_WINDOWS.bat` | Runs the automated tests |

Double-clicking START again while the app is running just opens the browser; it never starts a second copy.

Your entries are saved in `%LOCALAPPDATA%\MarineSense\WatchLog\watchlog.sqlite3`. They survive closing the browser, closing the app and restarting the PC.

To run the tests, double-click `TEST_WATCHLOG_WINDOWS.bat`, or run `.venv\Scripts\python -m pytest`.

## What Phase 1 does

- **Watch board:** pick the ship date explicitly (never from the PC clock) and start or resume any of the four watches. The 1800–2400 watch is filed under the date it began. Each date and watch can have only one log.
- **Watch entry:** sections A–M follow the workbook. Each row shows the previous reading, an odometer-style input, the difference and a status lamp. Every field autosaves as a draft and shows the time it was saved.
  - Keys: **Enter** moves to the next field, **Shift+Enter** goes back, **Esc** undoes an unsaved edit, **Ctrl+S** saves, **Ctrl+J** jumps to a section.
- **Calculations:**
  - Differences come from consecutive valid readings, across midnight, month-end and year-end.
  - A missing reading makes the interval *incomplete*.
  - A counter that goes backwards is flagged *for review*. The officer confirms a **rollover** (using that meter's limit) or a **meter replacement**.
  - M4 TOTAL is calculated only when M4.1, M4.2 and M4.3 are all entered. An explicit 0 counts as a reading.
  - Fresh-water production per watch is shown as it is calculated.
- **Fresh-water 4-hour schedule:** the 0400, 0800, 1600 and 2000 readings are typed in the watch that contains them. The 1200 and 2400 values reuse the 6-hour readings, so each reading is stored once.
- **Unavailable readings** are recorded with a reason. Values with qualifiers such as `74+` keep the exact text typed.
- **Settings:** vessel name, opening balances for the first watch, a "not in use" switch per field (with the ship date it takes effect) and the rollover limit for each counter.

## What Phase 2 adds

- **Review & close:** lists readings flagged for review (these must be resolved first), missing readings, unavailable readings and incomplete intervals.
  - The officer picks or types their name and enters the closure time in ship time. The PC time is also recorded.
  - Closing with missing readings needs a ticked confirmation.
- **Locked records:** a closed watch is read-only, and a frozen copy of the full record is stored at closing.
- **Corrections:** a correction needs a reason and creates **version 2, 3, …**. The original closed version is never changed and stays viewable, marked *superseded*.
  - Until a correction is closed, other watches keep calculating from the closed original.
- **History:** search by date range, watch and status (closed, draft, corrected, has missing). Each record shows its readings, calculated values, remarks, officer and version history.
- **PDF on closing:** A4, named `YYYY-MM-DD_HHMM-HHMM_Watch_Log.pdf` (`_v2` for a correction), with table headings repeated across pages. Missing readings are shown in red and corrections get a banner.
  - From the record page you can open, download or print it. PDFs are stored under `%LOCALAPPDATA%\MarineSense\WatchLog\pdfs\`.

## What Phase 3 adds: Reports

- **Reports** in the top menu: pick a ship date to see totals for the **last completed watch**, that **day**, its **ISO week** (Monday–Sunday) and its **month**. Each column shows the dates it covers.
- **Compressor running hours** per machine. Operating and loading hours are kept separate.
  - Service-air totals are shown both ways: the workbook's Aft + Fwd, and all machines including the osmosis room.
  - Also included: control air compressor 3 and starting air No. 1–3, with a combined total.
- **Fuel consumption** (feeder modules and boilers), **fresh-water production** (Aft LOC, Fwd LOC, RO and total) and **cleaning cycles** (purifiers, filters, feeders and DG 1–6).
- **Gaps are never filled with zero.** A total with a missing, unavailable or unconfirmed interval is marked **incomplete**, with the gap count. Click a total to see each watch interval and the reason for each gap.
  - Watches before the first record or after the latest one count as not yet recorded, not as gaps.
- **CSV export:** totals for all periods, and every watch interval of the month (opens in Excel).

## What Phase 4 adds: backups, training and hardening

- **Backups** (Settings → Backups & restore):
  - Automatic backups run once a day on start and after every closed watch. The newest 60 automatic backups are kept; manual backups are never deleted.
  - **Backup now**, **Download full backup** (a .zip of the database and all PDFs), and **Copy to a folder** such as a USB drive.
- **Restore** from a saved backup or an uploaded file. You must type `RESTORE` to confirm.
  - The current database is saved as a *pre-restore* backup first, so a restore can be undone.
  - Files are checked for integrity before use.
  - Backups and restores only work on the ECR PC, never from a tablet.
- **Training mode:** a separate folder with 14 days of synthetic watches and a striped **TRAINING MODE** banner. It refuses to run on a folder that holds a real log.
- **Offline installation:** run `BUILD_OFFLINE_BUNDLE_WINDOWS.bat` on a PC with internet and the **same Python version** as the ship PC, then copy the whole folder, including `wheels\`, to the ship.
- **Hardening:**
  - A production web server (waitress) replaces Flask's development server.
  - A second start just opens the running app.
  - A `/health` check, a rotating log in `%LOCALAPPDATA%\MarineSense\WatchLog\logs\`, and friendly error pages.
- **Accessibility:** a skip-to-content link, page landmarks, a live "saved" status for screen readers, visible keyboard focus, reduced motion when the PC asks for it, and lamps that stay visible in high-contrast mode.

**Still deferred until confirmed onboard:** generator running hours, sludge generation and sounding-to-volume conversions. The raw readings are stored so they can be added later.

## Tablet access (LAN, opt-in)

1. On the ECR PC, open **Settings → Tablet access** and set a 4–12 digit PIN. The PIN can only be changed on the ECR PC itself.
2. Start the app with **`START_WATCHLOG_LAN_WINDOWS.bat`**. The console shows the address to open on the tablet, for example `http://192.168.x.x:5080/`.
3. If Windows asks about the firewall, allow Python on **private networks only**.

The connection is plain HTTP, so use it only on the ship's internal network. In normal mode (`START_WATCHLOG_WINDOWS.bat`) other machines are always refused.

## Repository layout

| Path | Contents |
|---|---|
| `watchlog/` | The Flask app: `logic.py` (rules and calculations), `records.py` (close, corrections, history, PDF and LAN), `reports.py` and `report_views.py` (period totals and CSV), `backup.py` and `backup_views.py` (backups and restore), `demo.py` (synthetic training data), `pdf.py`, `registry.py`, `db.py`, `views.py`, templates and static files |
| `docs/field_registry.yaml` | Every workbook field. The entry screen and calculations are built from this file |
| `docs/data_model.md` | Schema and calculation rules |
| `docs/WATCHLOG_BUILD_PROMPT.md` | Build brief, phase plan and approved design decisions |
| `mockups/` | Phase 0 static design mockups |
| `tests/` | pytest suite, using synthetic data only |

## Data privacy

This repository is public. `.gitignore` excludes real workbooks, watch records, crew names, generated PDFs and databases, and they must never be committed. All test and demo data is synthetic.
