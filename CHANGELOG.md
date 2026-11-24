# Changelog

## 1.0.0 — Phase 4: backups, training mode, offline install, hardening
- Automatic backups (daily, and after each closed watch) plus manual backups, a full .zip backup (database and PDFs) and copy to a USB folder.
- Restore from a saved backup or an uploaded file, after typing RESTORE to confirm. The current database is backed up first and every file is integrity-checked.
- Training mode with synthetic data in a separate folder and a TRAINING MODE banner.
- Offline wheel bundle script for installing on a ship PC without internet.
- Production web server (waitress), single-instance start, `/health`, a rotating log file and friendly error pages.
- Accessibility pass: skip link, page landmarks, a live save status and high-contrast lamps.

## 0.3.0 — Phase 3: reports
- Totals for the last completed watch, the day, the ISO week and the month, each showing the dates covered and any gaps.
- Compressor hours with operating and loading kept separate, service-air totals shown both the workbook way and for all machines, fuel, fresh water and cleaning cycles.
- Interval detail page and CSV exports.

## 0.2.0 — Phase 2: close, records, PDF, LAN
- Review & close with the officer and closure time; locked records with a frozen snapshot.
- Versioned corrections that keep the original; history search.
- A4 PDF on closing, with repeated table headings, missing readings marked and a correction banner.
- Opt-in, PIN-protected tablet access over the LAN.

## 0.1.0 — Phase 1: core watch entry
- Watch board with an explicit ship date and watch; entry screen built from the field registry, with autosaved drafts.
- Counter differences across midnight and month-end, gaps, rollover and meter replacement, and opening balances.
- Missing, zero and unavailable kept distinct; M4 total; the 4-hour fresh-water schedule stores each reading once.

## Phase 0 — design and data map
- Field registry and data model from the workbook; clickable mockups.
