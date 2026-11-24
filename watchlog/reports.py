"""Phase 3: period totals (last completed watch, day, week, month) with coverage and gaps.

Totals are the sum of *valid* watch differences (the same rules as the entry
screen: compute_point). Intervals that cannot be calculated are listed as gaps
and the total is flagged incomplete — never zero-filled.
"""
from __future__ import annotations

import calendar
from dataclasses import dataclass, field
from datetime import date, timedelta

from . import logic
from .registry import WATCH_LABELS, WATCHES, Registry

PERIODS = ("watch", "day", "week", "month")
PERIOD_LABELS = {"watch": "Last completed watch", "day": "Day", "week": "Week", "month": "Month"}
WATCH_START = {"w1": "0000", "w2": "0600", "w3": "1200", "w4": "1800"}
WATCH_END = {"w1": "0600", "w2": "1200", "w3": "1800", "w4": "2400"}

# report groups -> registry sections
GROUPS = [
    ("compressors", "Compressor running hours", ("H", "J")),
    ("fuel", "Fuel consumption", ("A",)),
    ("fresh_water", "Fresh-water production", ("B",)),
    ("cycles", "Cleaning cycles", ("D", "F", "K")),
]

# combined rows: (id, label, unit, group, parts)
COMPOSITES = [
    ("sa_workbook_operating", "Service air — daily total as workbook (Aft + Fwd) · operating", "h", "compressors",
     ("sa_aft_operating_h", "sa_fwd_operating_h")),
    ("sa_workbook_loading", "Service air — daily total as workbook (Aft + Fwd) · loading", "h", "compressors",
     ("sa_aft_loading_h", "sa_fwd_loading_h")),
    ("sa_all_operating", "Service air — all machines (Aft + Fwd + Osmosis) · operating", "h", "compressors",
     ("sa_aft_operating_h", "sa_fwd_operating_h", "sa_osmosis_operating_h")),
    ("sa_all_loading", "Service air — all machines (Aft + Fwd + Osmosis) · loading", "h", "compressors",
     ("sa_aft_loading_h", "sa_fwd_loading_h", "sa_osmosis_loading_h")),
    ("start_air_total", "Starting air — total (No. 1 + 2 + 3)", "h", "compressors",
     ("start_air_1_h", "start_air_2_h", "start_air_3_h")),
    ("fw_total", "Total production (Aft LOC + Fwd LOC + RO)", "m³", "fresh_water",
     ("aft_evap_loc_counter", "fwd_evap_loc_counter", "ro_ecr_counter")),
]


@dataclass
class Period:
    kind: str
    points: list[tuple[str, str]]           # (ship_date, watch) intervals included
    start: date | None
    end: date | None
    note: str = ""

    @property
    def covered(self) -> str:
        if not self.points:
            return "no records"
        (d0, w0), (d1, w1) = self.points[0], self.points[-1]
        a = date.fromisoformat(d0).strftime("%d %b %Y")
        b = date.fromisoformat(d1).strftime("%d %b %Y")
        return f"{a} {WATCH_START[w0]} → {b} {WATCH_END[w1]}"


@dataclass
class Total:
    value: float = 0
    valid: int = 0
    expected: int = 0
    gaps: list[dict] = field(default_factory=list)

    @property
    def complete(self) -> bool:
        return self.expected > 0 and not self.gaps

    def as_dict(self) -> dict:
        return {"value": logic._r(self.value) if self.valid else None, "valid": self.valid,
                "expected": self.expected, "complete": self.complete, "gaps": self.gaps}


# ---------------------------------------------------------------- periods

def _key(d: str, w: str) -> tuple[str, int]:
    return d, WATCHES.index(w)


def _bounds(conn) -> tuple[tuple[str, int], tuple[str, int]] | None:
    first = conn.execute("SELECT ship_date, watch FROM watch_log ORDER BY ship_date, watch LIMIT 1").fetchone()
    last = conn.execute("SELECT ship_date, watch FROM watch_log ORDER BY ship_date DESC, watch DESC LIMIT 1").fetchone()
    if not first:
        return None
    return _key(first["ship_date"], first["watch"]), _key(last["ship_date"], last["watch"])


def _points(d0: date, d1: date, bounds) -> list[tuple[str, str]]:
    """All watch intervals between d0..d1, clipped to the recorded range
    (intervals before the first record or after the latest one are not 'gaps')."""
    if bounds is None:
        return []
    lo, hi = bounds
    out, d = [], d0
    while d <= d1:
        for w in WATCHES:
            k = _key(d.isoformat(), w)
            if lo <= k <= hi:
                out.append((d.isoformat(), w))
        d += timedelta(days=1)
    return out


def last_completed_watch(conn, ref: date):
    return conn.execute("SELECT ship_date, watch FROM watch_log WHERE status='closed' AND ship_date<=? "
                        "ORDER BY ship_date DESC, watch DESC LIMIT 1", (ref.isoformat(),)).fetchone()


def make_period(conn, kind: str, ref: date) -> Period:
    b = _bounds(conn)
    if kind == "watch":
        r = last_completed_watch(conn, ref)
        if not r:
            return Period(kind, [], None, None, "no closed watch yet")
        d = date.fromisoformat(r["ship_date"])
        return Period(kind, [(r["ship_date"], r["watch"])], d, d,
                      f"{d.strftime('%d %b')} {WATCH_LABELS[r['watch']]}")
    if kind == "day":
        d0 = d1 = ref
        note = ref.strftime("%a %d %b %Y")
    elif kind == "week":
        d0 = ref - timedelta(days=ref.weekday())               # ISO week, Monday..Sunday
        d1 = d0 + timedelta(days=6)
        note = f"ISO week {ref.isocalendar()[1]} · {d0.strftime('%d %b')}–{d1.strftime('%d %b %Y')}"
    elif kind == "month":
        d0 = ref.replace(day=1)
        d1 = ref.replace(day=calendar.monthrange(ref.year, ref.month)[1])
        note = ref.strftime("%B %Y")
    else:
        raise logic.ReadingError("Unknown period")
    return Period(kind, _points(d0, d1, b), d0, d1, note)


# ---------------------------------------------------------------- totals

def field_total(conn, reg: Registry, field_id: str, period: Period, with_intervals=False) -> tuple[Total, list]:
    fld = reg.fields[field_id]
    t, rows = Total(), []
    earliest = logic.earliest_log(conn)
    for d, w in period.points:
        if logic.not_in_use(conn, field_id, d):
            continue
        c = logic.compute_point(conn, fld, "6h", d, w, earliest)
        t.expected += 1
        if c["diff_status"] == "ok":
            t.value += c["diff"]
            t.valid += 1
        else:
            reason = {"incomplete": "reading missing" if c["state"] != "entered" else "previous reading missing",
                      "review": "meter went backwards (unconfirmed)",
                      "no_previous": "no previous reading / opening balance"}.get(c["diff_status"], c["diff_status"])
            if c["state"] == "unavailable":
                reason = f"unavailable: {c.get('reason') or ''}"
            if c["state"] == "no_log":
                reason = "watch not logged"
            t.gaps.append({"ship_date": d, "watch": w, "reason": reason})
        if with_intervals:
            rows.append({"ship_date": d, "watch": w, **{k: c.get(k) for k in
                         ("state", "prev", "value", "raw", "diff", "diff_status", "diff_note", "prev_note", "reason")}})
    return t, rows


def composite_total(parts: list[Total]) -> Total:
    t = Total()
    for p in parts:
        t.value += p.value
        t.valid += p.valid
        t.expected += p.expected
        t.gaps.extend(p.gaps)
    return t


def report(conn, reg: Registry, ref: date) -> dict:
    with logic.read_cache():
        periods = {k: make_period(conn, k, ref) for k in PERIODS}
        groups = []
        cache: dict[tuple[str, str], Total] = {}
        for gid, title, secs in GROUPS:
            rows = []
            for sec in reg.sections:
                if sec.id not in secs:
                    continue
                for f in sec.fields:
                    if not f.is_counter:
                        continue
                    cells = {}
                    for k, p in periods.items():
                        t, _ = field_total(conn, reg, f.id, p)
                        cache[(f.id, k)] = t
                        cells[k] = t.as_dict()
                    rows.append({"id": f.id, "label": f.label, "unit": f.diff_unit, "section": sec.id,
                                 "group": f.group, "composite": False, "cells": cells})
            for cid, label, unit, g, parts in COMPOSITES:
                if g != gid:
                    continue
                cells = {k: composite_total([cache[(pid, k)] for pid in parts]).as_dict() for k in periods}
                rows.append({"id": cid, "label": label, "unit": unit, "section": None, "group": None,
                             "composite": True, "parts": parts, "cells": cells})
            groups.append({"id": gid, "title": title, "rows": rows})
    return {
        "ref": ref.isoformat(),
        "periods": {k: {"label": PERIOD_LABELS[k], "note": p.note, "covered": p.covered,
                        "intervals": len(p.points), "start": p.start.isoformat() if p.start else None,
                        "end": p.end.isoformat() if p.end else None} for k, p in periods.items()},
        "groups": groups,
    }


def intervals(conn, reg: Registry, d0: date, d1: date, field_ids: list[str] | None = None) -> list[dict]:
    """Every watch interval for every counter field in a date range (for detail views / CSV)."""
    with logic.read_cache():
        p = Period("range", _points(d0, d1, _bounds(conn)), d0, d1)
        out = []
        for f in reg.fields.values():
            if not f.is_counter or (field_ids and f.id not in field_ids):
                continue
            _, rows = field_total(conn, reg, f.id, p, with_intervals=True)
            for r in rows:
                out.append({"field": f.id, "label": f.label, "unit": f.diff_unit, **r})
    out.sort(key=lambda r: (r["ship_date"], r["watch"], r["field"]))
    return out
