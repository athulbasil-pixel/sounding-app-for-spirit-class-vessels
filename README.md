# MarineSense Engine Room Watch Log — Spirit class

This app replaces the Excel engine-room watch and sounding workbook with an offline browser app built on Flask and SQLite.

**Status: Phase 1, core watch entry.** Closing a watch, history, PDFs and LAN mode for tablets arrive in Phase 2. Reports arrive in Phase 3.

## Start (Windows)

1. Install **Python 3.11 or newer** from python.org and tick *Add Python to PATH*.
2. Double-click **`START_WATCHLOG_WINDOWS.bat`**.
   - The first run creates `.venv` and installs Flask and PyYAML. This needs internet once, unless a `wheels\` folder with the packages sits next to the script.
   - After that the app starts offline and opens **http://127.0.0.1:5080/** in your browser.
3. Keep the black console window open while using the log. Close it, or press Ctrl+C, to stop.

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

## Repository layout

| Path | Contents |
|---|---|
| `watchlog/` | The Flask app: `logic.py` (rules and calculations), `registry.py`, `db.py`, `views.py`, templates and static files |
| `docs/field_registry.yaml` | Every workbook field. The entry screen and calculations are built from this file |
| `docs/data_model.md` | Schema and calculation rules |
| `docs/WATCHLOG_BUILD_PROMPT.md` | Build brief, phase plan and approved design decisions |
| `mockups/` | Phase 0 static design mockups |
| `tests/` | pytest suite, using synthetic data only |

## Data privacy

This repository is public. `.gitignore` excludes real workbooks, watch records, crew names, generated PDFs and databases, and they must never be committed. All test and demo data is synthetic.
