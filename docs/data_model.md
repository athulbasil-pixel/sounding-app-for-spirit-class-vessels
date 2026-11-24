# Data model and calculation rules (Phase 0 draft)

This note covers the SQLite schema and calculation rules for the Spirit-class Engine Room Watch Log. All field ids come from [field_registry.yaml](field_registry.yaml). Section letters follow the build brief. Control air compressor 3 (brief section I) is merged into section H, and the registry has no section I.

## 1. What the workbook taught us

| Finding | Consequence for the app |
|---|---|
| Day N `Prev. Watch` and `BEGIN` rows link to Day N-1's 1800-2400 row | Previous reading = last **valid** reading for that field, whatever its date (handles midnight and month-end) |
| The Model sheet's BEGIN links point to an external file and show `#REF!`; daily TOTALs add `+#REF!+#REF!` | Reimplement the intent; never port workbook formulas literally |
| The April workbook has a "Day 31" sheet, and Day 1's date cell shows a 2022 date | The ship date is always chosen explicitly and stored on the log |
| The feeder DG 1-2-3 counter drops from near 1 000 000 to a small value overnight | Treat it as a `rollover` or `meter_replaced` event confirmed by the officer, not a negative consumption |
| Blank FW 4-hour slots produced large negative "production" values in Excel | Empty = missing, so the interval is incomplete and never computed against 0 |
| A sump reading was written with a qualifier (e.g. "NN+") | Store `value_num` plus `qualifier` and keep the raw text |
| Sounding rows sit one row higher on Day sheets than on Model | The registry records both layouts (only matters for a future import tool) |
| ECR counters for the evaporators, and the DAM. sump rows, were empty on sampled days | Keep these fields but allow "not in use" to be marked once, in Settings, so they don't nag every watch |

## 2. Tables

```
vessel_settings(id=1, vessel_name, timezone_note, theme_default, created_at)

officer(id, display_name, rank, active)                       -- synthetic in tests; real names stay in local DB only

watch_log(
  id PK,
  ship_date DATE NOT NULL,                                     -- explicit, never from Windows clock
  watch TEXT NOT NULL CHECK (watch IN ('w1','w2','w3','w4')),
  status TEXT NOT NULL CHECK (status IN ('draft','closed')),
  version INTEGER NOT NULL DEFAULT 1,                          -- 1 = original; >1 = correction
  supersedes_id INTEGER NULL REFERENCES watch_log(id),
  correction_reason TEXT NULL,
  remarks TEXT,
  officer_id INTEGER NULL REFERENCES officer(id),
  created_at, saved_at, closed_at,
  UNIQUE (ship_date, watch, version)
)
-- "current" log for a date+watch = highest version.
-- A closed row is never updated; a correction inserts version+1 copying readings.

reading(
  id PK,
  log_id INTEGER NOT NULL REFERENCES watch_log(id),
  field_id TEXT NOT NULL,                                      -- registry id
  slot TEXT NOT NULL DEFAULT 'watch',                          -- 'watch' or FW slot id s1..s6
  value_num REAL NULL,                                         -- NULL = missing
  qualifier TEXT NULL,                                         -- '+', '-', '~'
  raw_text TEXT NULL,                                          -- exactly what was typed
  status TEXT NOT NULL CHECK (status IN ('entered','missing','unavailable')),
  unavailable_reason TEXT NULL,
  entered_at,
  UNIQUE (log_id, field_id, slot)
)

counter_event(                                                 -- opening balances, rollovers, meter swaps
  id PK, field_id, ship_date, watch,
  kind TEXT CHECK (kind IN ('opening_balance','rollover','meter_replaced')),
  value REAL,                                                  -- opening/new-meter value, or rollover modulus
  reason TEXT, officer_id, created_at
)

pdf_file(id PK, log_id, path, sha256, created_at)              -- files live outside the repo
```

FW 4-hour slots `s3` and `s6` are **not stored**. They resolve to the `watch` reading of the same field in w2 and w4. Slots `s1`, `s2`, `s4` and `s5` are stored once, on the log of the watch that contains the reading time.

## 3. Calculation rules

**Ordering.** A reading's position is `(ship_date, watch_index, slot_time)`. The previous valid reading is the latest earlier reading with `status='entered'` in the **current version** of each log.

**Difference** for `counter`, `hours_counter` and `cycle_counter`:
```
if current missing/unavailable           -> INCOMPLETE
if previous valid reading is not the immediately preceding watch -> INCOMPLETE (gap), show span
if opening_balance event exists and no earlier reading -> diff vs opening balance
if current < previous:
    if rollover event for this interval  -> (modulus - previous) + current
    elif meter_replaced event            -> current - new_meter_opening
    else                                 -> REVIEW (flag; excluded from totals)
else                                     -> current - previous
```
Example: compressor `86631 -> 86635` gives `4 h`.

**Period totals** (last completed watch, day, ISO week, month) are the sum of the valid differences inside the period. Each total also returns `covered_from`, `covered_to`, `intervals_expected`, `intervals_valid` and a `gaps[]` list. A total with gaps is shown with an amber "incomplete" mark and is never silently zero-filled.

**Calculated values:**
- `m4_total` = `m4_1 + m4_2 + m4_3` only when all three are present (0 counts).
- `fw_total_production` = aft LOC + fwd LOC + RO production. It is incomplete if any part is incomplete.
- `sa_daily_*` and `start_air_daily_h`: workbook totals, kept for the PDF and the day view.

**Deferred** (raw data kept): DG running hours, sludge, and sounding-to-volume conversions.

## 4. Lifecycle

```
(new) -> draft --autosave--> draft --review & close (officer, time)--> closed
                                                                    \--correct (reason)--> draft vN+1 --> closed vN+1
```
- Only one draft may exist per (date, watch).
- Opening a date+watch that already exists resumes it; a duplicate is never created.
- Closing shows the missing list. Every missing field must be filled, marked unavailable with a reason, or acknowledged as missing.

## 5. Storage location

`%LOCALAPPDATA%\MarineSense\WatchLog\` holds `watchlog.sqlite3`, `pdfs\` and `backups\`. Nothing under the repo folder holds real data.
