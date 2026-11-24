"""Watch-log rules and calculations. Pure functions over an sqlite3 connection.

Nothing here imports Flask so it can be unit-tested directly.
"""
from __future__ import annotations

import json
import re
import sqlite3
import functools
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from .db import DEFAULT_ROLLOVER
from .registry import FW_SLOT_STORAGE, FW_SLOTS, WATCH_LABELS, WATCHES, Field, Registry

# ---------------------------------------------------------------- parsing

_NUM_RE = re.compile(r"^\s*(-?\d[\d ]*(?:[.,]\d+)?)\s*([+~-])?\s*$")


class ReadingError(ValueError):
    pass


def parse_reading(raw: str | None) -> tuple[float | None, str | None]:
    """'1 204' -> 1204.0, '74+' -> (74.0, '+'), '0' -> 0.0, '' -> None (missing)."""
    if raw is None or str(raw).strip() == "":
        return None, None
    m = _NUM_RE.match(str(raw).replace(" ", " "))
    if not m:
        raise ReadingError(f"Not a number: {raw!r}")
    num = m.group(1).replace(" ", "").replace(",", ".")
    return float(num), m.group(2)


def now_iso() -> str:
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def check_date(d: str) -> str:
    try:
        return date.fromisoformat(d).isoformat()
    except (TypeError, ValueError) as exc:
        raise ReadingError(f"Bad ship date: {d!r}") from exc


def check_watch(w: str) -> str:
    if w not in WATCHES:
        raise ReadingError(f"Bad watch: {w!r}")
    return w


# ---------------------------------------------------------------- points

def series_points(series: str) -> list[str]:
    return WATCHES if series == "6h" else FW_SLOTS


def prev_point(series: str, ship_date: str, point: str) -> tuple[str, str]:
    pts = series_points(series)
    i = pts.index(point)
    if i > 0:
        return ship_date, pts[i - 1]
    d = date.fromisoformat(ship_date) - timedelta(days=1)   # crosses midnight & month-end
    return d.isoformat(), pts[-1]


def storage_of(series: str, point: str) -> tuple[str, str]:
    """(watch holding the reading, slot key)."""
    return (point, "watch") if series == "6h" else FW_SLOT_STORAGE[point]


def _watch_key(ship_date: str, watch: str) -> tuple[str, int]:
    return ship_date, WATCHES.index(watch)


# ---------------------------------------------------------------- logs

def current_log(conn: sqlite3.Connection, ship_date: str, watch: str):
    """The *effective* record: latest closed version; else the original draft.

    A correction draft (version > 1) is not effective until it is closed, so
    other watches keep carrying forward from the closed record meanwhile.
    """
    r = conn.execute("SELECT * FROM watch_log WHERE ship_date=? AND watch=? AND status='closed' "
                     "ORDER BY version DESC LIMIT 1", (ship_date, watch)).fetchone()
    if r:
        return r
    return conn.execute("SELECT * FROM watch_log WHERE ship_date=? AND watch=? AND version=1",
                        (ship_date, watch)).fetchone()


def editing_log(conn: sqlite3.Connection, ship_date: str, watch: str):
    """The draft being edited (original or correction) — else the effective record."""
    r = conn.execute("SELECT * FROM watch_log WHERE ship_date=? AND watch=? AND status='draft' "
                     "ORDER BY version DESC LIMIT 1", (ship_date, watch)).fetchone()
    return r or current_log(conn, ship_date, watch)


def log_by_id(conn, log_id: int):
    return conn.execute("SELECT * FROM watch_log WHERE id=?", (log_id,)).fetchone()


def get_or_create_log(conn: sqlite3.Connection, ship_date: str, watch: str):
    ship_date, watch = check_date(ship_date), check_watch(watch)
    conn.execute("INSERT OR IGNORE INTO watch_log(ship_date, watch, version, status) VALUES (?,?,1,'draft')",
                 (ship_date, watch))
    return editing_log(conn, ship_date, watch)


def earliest_log(conn: sqlite3.Connection) -> tuple[str, int] | None:
    rows = conn.execute("SELECT ship_date, watch FROM watch_log ORDER BY ship_date, watch LIMIT 1").fetchone()
    return _watch_key(rows["ship_date"], rows["watch"]) if rows else None


def suggested_ship_date(conn: sqlite3.Connection) -> tuple[str, str]:
    """Never silently trust the PC clock: prefer the open draft, then the latest log."""
    r = conn.execute("SELECT ship_date FROM watch_log WHERE status='draft' ORDER BY ship_date DESC, watch DESC LIMIT 1").fetchone()
    if r:
        return r["ship_date"], "open draft"
    r = conn.execute("SELECT ship_date FROM watch_log ORDER BY ship_date DESC LIMIT 1").fetchone()
    if r:
        return r["ship_date"], "latest log"
    return date.today().isoformat(), "PC date — confirm ship date"


# ---------------------------------------------------------------- settings

def not_in_use(conn: sqlite3.Connection, field_id: str, ship_date: str) -> bool:
    r = conn.execute("SELECT not_in_use FROM field_state WHERE field_id=? AND effective_from<=? "
                     "ORDER BY effective_from DESC LIMIT 1", (field_id, ship_date)).fetchone()
    return bool(r and r["not_in_use"])


def set_not_in_use(conn, field_id: str, effective_from: str, flag: bool) -> None:
    conn.execute("INSERT INTO field_state(field_id, effective_from, not_in_use) VALUES (?,?,?) "
                 "ON CONFLICT(field_id, effective_from) DO UPDATE SET not_in_use=excluded.not_in_use",
                 (field_id, check_date(effective_from), int(flag)))


def rollover_limit(conn, field_id: str) -> float:
    r = conn.execute("SELECT rollover_limit FROM field_setting WHERE field_id=?", (field_id,)).fetchone()
    return float(r["rollover_limit"]) if r and r["rollover_limit"] else float(DEFAULT_ROLLOVER)


def set_rollover_limit(conn, field_id: str, limit: float | None) -> None:
    conn.execute("INSERT INTO field_setting(field_id, rollover_limit) VALUES (?,?) "
                 "ON CONFLICT(field_id) DO UPDATE SET rollover_limit=excluded.rollover_limit", (field_id, limit))


def opening_balance(conn, field_id: str, series: str) -> float | None:
    r = conn.execute("SELECT value FROM counter_event WHERE kind='opening_balance' AND field_id=? AND series=?",
                     (field_id, series)).fetchone()
    return r["value"] if r else None


def set_opening_balance(conn, field_id: str, series: str, value: float | None) -> None:
    conn.execute("DELETE FROM counter_event WHERE kind='opening_balance' AND field_id=? AND series=?",
                 (field_id, series))
    if value is not None:
        conn.execute("INSERT INTO counter_event(field_id, series, kind, value) VALUES (?,?,'opening_balance',?)",
                     (field_id, series, value))


def point_event(conn, field_id: str, series: str, ship_date: str, point: str):
    return conn.execute("SELECT * FROM counter_event WHERE kind<>'opening_balance' AND field_id=? AND series=? "
                        "AND ship_date=? AND point=?", (field_id, series, ship_date, point)).fetchone()


def set_point_event(conn, field_id, series, ship_date, point, kind, value=None, reason=None) -> None:
    if kind not in ("rollover", "meter_replaced"):
        raise ReadingError("Unknown event")
    if kind == "meter_replaced" and value is None:
        raise ReadingError("Meter replaced needs the new meter's opening value")
    clear_point_event(conn, field_id, series, ship_date, point)
    conn.execute("INSERT INTO counter_event(field_id, series, ship_date, point, kind, value, reason) "
                 "VALUES (?,?,?,?,?,?,?)", (field_id, series, ship_date, point, kind, value, reason))


def clear_point_event(conn, field_id, series, ship_date, point) -> None:
    conn.execute("DELETE FROM counter_event WHERE kind<>'opening_balance' AND field_id=? AND series=? "
                 "AND ship_date=? AND point=?", (field_id, series, ship_date, point))


# ---------------------------------------------------------------- readings

@dataclass
class PointValue:
    state: str                 # entered | missing | unavailable | no_log | before_records | not_in_use
    value: float | None = None
    raw: str | None = None
    qualifier: str | None = None
    reason: str | None = None
    ship_date: str | None = None
    point: str | None = None


# While computing a correction draft, its own (date, watch) must read from the draft,
# while every other watch reads from the effective records.
_LOG_OVERRIDE: ContextVar[dict] = ContextVar("_LOG_OVERRIDE", default={})


def reading_at(conn, field_id: str, series: str, ship_date: str, point: str, _earliest=None) -> PointValue:
    watch, slot = storage_of(series, point)
    log = _LOG_OVERRIDE.get().get((ship_date, watch)) or current_log(conn, ship_date, watch)
    if log is None:
        earliest = _earliest if _earliest is not None else earliest_log(conn)
        if earliest is None or _watch_key(ship_date, watch) < earliest:
            return PointValue("before_records", ship_date=ship_date, point=point)
        return PointValue("no_log", ship_date=ship_date, point=point)
    if not_in_use(conn, field_id, ship_date):
        return PointValue("not_in_use", ship_date=ship_date, point=point)
    r = _reading_row(conn, log["id"], field_id, slot)
    if r is None or r["status"] == "missing":
        return PointValue("missing", ship_date=ship_date, point=point)
    return PointValue(r["status"], value=r["value_num"], raw=r["raw_text"], qualifier=r["qualifier"],
                      reason=r["unavailable_reason"], ship_date=ship_date, point=point)


def last_valid_before(conn, field_id, series, ship_date, point, max_steps=4 * 31) -> PointValue | None:
    earliest = earliest_log(conn)
    d, p = ship_date, point
    for _ in range(max_steps):
        d, p = prev_point(series, d, p)
        pv = reading_at(conn, field_id, series, d, p, earliest)
        if pv.state == "entered":
            return pv
        if pv.state == "before_records":
            return None
    return None


def _r(x: float) -> float:
    x = round(x, 6)
    return int(x) if float(x).is_integer() else x


def compute_point(conn, fld: Field, series: str, ship_date: str, point: str, earliest=None) -> dict:
    """Current reading, previous reading and difference for one point."""
    cur = reading_at(conn, fld.id, series, ship_date, point, earliest)
    out = {"field": fld.id, "series": series, "point": point,
           "state": cur.state, "value": cur.value, "raw": cur.raw, "qualifier": cur.qualifier,
           "reason": cur.reason, "prev": None, "prev_note": None, "diff": None,
           "diff_status": "none", "event": None}
    pd, pp = prev_point(series, ship_date, point)
    prev = reading_at(conn, fld.id, series, pd, pp, earliest)

    if prev.state == "entered":
        out["prev"] = prev.value
    elif prev.state in ("before_records", "not_in_use"):
        ob = opening_balance(conn, fld.id, series) if fld.is_counter else None
        if ob is not None:
            out["prev"], out["prev_note"] = ob, "opening balance"
        else:
            out["prev_note"] = "no previous"
    else:
        lv = last_valid_before(conn, fld.id, series, ship_date, point)
        out["prev_note"] = "gap — previous reading missing"
        if lv:
            out["prev_last_valid"] = {"value": lv.value, "ship_date": lv.ship_date, "point": lv.point}

    if not fld.is_counter:
        return out

    ev = point_event(conn, fld.id, series, ship_date, point)
    if ev:
        out["event"] = {"kind": ev["kind"], "value": ev["value"], "reason": ev["reason"]}

    if cur.state != "entered":
        out["diff_status"] = "incomplete"
        return out
    if out["prev"] is None:
        out["diff_status"] = "no_previous" if prev.state in ("before_records", "not_in_use") else "incomplete"
        return out

    c, p = cur.value, out["prev"]
    if ev and ev["kind"] == "meter_replaced":
        out["diff"], out["diff_status"] = _r(c - ev["value"]), "ok"
        out["diff_note"] = "meter replaced"
    elif c < p:
        if ev and ev["kind"] == "rollover":
            limit = rollover_limit(conn, fld.id)
            out["diff"], out["diff_status"] = _r(limit - p + c), "ok"
            out["diff_note"] = f"rollover at {int(limit):,}".replace(",", " ")
        else:
            out["diff"], out["diff_status"] = _r(c - p), "review"
    else:
        out["diff"], out["diff_status"] = _r(c - p), "ok"
    return out


# ---------------------------------------------------------------- log state

def _lamp(item: dict) -> str:
    if item.get("hidden"):
        return "off"
    st, ds = item["state"], item["diff_status"]
    if ds == "review":
        return "red"
    if st == "unavailable":
        return "amber"
    if st != "entered":
        return "grey"
    if ds in ("incomplete", "no_previous"):
        return "amber"
    return "green"


def log_state(conn, reg: Registry, ship_date: str, watch: str, log=None) -> dict:
    """Live computed state of one watch record (default: the one being edited)."""
    ship_date, watch = check_date(ship_date), check_watch(watch)
    if log is None:
        log = editing_log(conn, ship_date, watch)
    token = _LOG_OVERRIDE.set({(ship_date, watch): log} if log is not None else {})
    try:
        return _log_state(conn, reg, ship_date, watch, log)
    finally:
        _LOG_OVERRIDE.reset(token)


def _log_state(conn, reg, ship_date, watch, log) -> dict:
    earliest = earliest_log(conn)
    items = []
    for it in reg.entry_items(watch):
        fld = reg.fields[it["field"]]
        point = watch if it["series"] == "6h" else it["slot"]
        c = compute_point(conn, fld, it["series"], ship_date, point, earliest)
        c.update(section=it["section"], slot=it["slot"], linked=it["linked"],
                 key=f'{fld.id}@{it["slot"]}', hidden=not_in_use(conn, fld.id, ship_date))
        c["lamp"] = _lamp(c)
        items.append(c)

    by_key = {i["key"]: i for i in items}
    sections = []
    totals = {"entered": 0, "missing": 0, "review": 0, "unavailable": 0, "count": 0}
    for sec in reg.sections:
        s = {"entered": 0, "missing": 0, "review": 0, "unavailable": 0, "count": 0}
        for i in items:
            if i["section"] != sec.id or i["linked"] or i["hidden"]:
                continue
            s["count"] += 1
            if i["diff_status"] == "review":
                s["review"] += 1
            elif i["state"] == "entered":
                s["entered"] += 1
            elif i["state"] == "unavailable":
                s["unavailable"] += 1
            else:
                s["missing"] += 1
        for k in totals:
            totals[k] += s[k]
        lamp = ("red" if s["review"] else "green" if s["missing"] == 0 and s["count"] else
                "grey" if s["entered"] + s["unavailable"] == 0 else "amber")
        sections.append({"id": sec.id, "lamp": lamp, **s})

    # calculated values
    calcs = {}
    m4 = [by_key.get(f"m4_{n}@watch") for n in (1, 2, 3)]
    if all(x and x["state"] == "entered" for x in m4):
        calcs["m4_total"] = {"value": _r(sum(x["value"] for x in m4)), "status": "ok"}
    else:
        calcs["m4_total"] = {"value": None, "status": "incomplete"}
    fw_parts = [by_key.get(f"{f}@watch") for f in ("aft_evap_loc_counter", "fwd_evap_loc_counter", "ro_ecr_counter")]
    fw_parts = [p for p in fw_parts if p and not p["hidden"]]
    if fw_parts and all(p["diff_status"] == "ok" for p in fw_parts):
        calcs["fw_total_production"] = {"value": _r(sum(p["diff"] for p in fw_parts)), "status": "ok", "unit": "m³"}
    else:
        calcs["fw_total_production"] = {"value": None, "status": "incomplete", "unit": "m³"}

    return {
        "ship_date": ship_date, "watch": watch,
        "log": _log_public(log),
        "items": items, "sections": sections, "totals": totals, "calcs": calcs,
    }


def _log_public(log) -> dict | None:
    if log is None:
        return None
    d = dict(log)
    d.pop("snapshot_json", None)
    return d


def record_state(conn, reg: Registry, log) -> dict:
    """What a record shows: the frozen snapshot for closed versions, live state for drafts."""
    if log["status"] == "closed" and log["snapshot_json"]:
        st = json.loads(log["snapshot_json"])
        st["log"] = _log_public(log)
        st["frozen"] = True
        return st
    st = log_state(conn, reg, log["ship_date"], log["watch"], log)
    st["frozen"] = False
    return st


# ---------------------------------------------------------------- writes

def _valid_slots(reg: Registry, watch: str) -> dict[tuple[str, str], dict]:
    return {(i["field"], i["slot"]): i for i in reg.entry_items(watch) if not i["linked"]}


def _draft_or_error(conn, ship_date, watch):
    log = editing_log(conn, check_date(ship_date), check_watch(watch))
    if log is None:
        raise ReadingError("Watch not started")
    if log["status"] != "draft":
        raise ReadingError("Watch is closed — start a correction to change it")
    return log


def save_reading(conn, reg: Registry, ship_date: str, watch: str, field_id: str, slot: str,
                 raw: str | None, status: str = "entered", reason: str | None = None) -> None:
    log = _draft_or_error(conn, ship_date, watch)
    if (field_id, slot) not in _valid_slots(reg, watch):
        raise ReadingError(f"{field_id}@{slot} is not entered in this watch")

    if status == "unavailable":
        if not (reason and reason.strip()):
            raise ReadingError("Give a reason for an unavailable reading")
        value, qual, raw_text, reason = None, None, None, reason.strip()[:200]
    elif status == "entered":
        value, qual = parse_reading(raw)
        raw_text = None if value is None else str(raw).strip()
        if value is None:
            status = "missing"
        reason = None
    else:
        raise ReadingError("Bad status")

    if status == "missing":
        conn.execute("DELETE FROM reading WHERE log_id=? AND field_id=? AND slot=?", (log["id"], field_id, slot))
    else:
        conn.execute(
            "INSERT INTO reading(log_id, field_id, slot, value_num, qualifier, raw_text, status, unavailable_reason, entered_at) "
            "VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(log_id, field_id, slot) DO UPDATE SET "
            "value_num=excluded.value_num, qualifier=excluded.qualifier, raw_text=excluded.raw_text, "
            "status=excluded.status, unavailable_reason=excluded.unavailable_reason, entered_at=excluded.entered_at",
            (log["id"], field_id, slot, value, qual, raw_text, status, reason, now_iso()))
    conn.execute("UPDATE watch_log SET saved_at=? WHERE id=?", (now_iso(), log["id"]))


def save_remarks(conn, ship_date, watch, remarks: str) -> None:
    log = _draft_or_error(conn, ship_date, watch)
    conn.execute("UPDATE watch_log SET remarks=?, saved_at=? WHERE id=?", (remarks, now_iso(), log["id"]))


# ---------------------------------------------------------------- officers / close / correct

def officers(conn, active_only=True) -> list:
    q = "SELECT * FROM officer" + (" WHERE active=1" if active_only else "") + " ORDER BY display_name"
    return conn.execute(q).fetchall()


def get_or_create_officer(conn, name: str, rank: str | None = None) -> int:
    name = " ".join((name or "").split())[:80]
    if not name:
        raise ReadingError("Enter the responsible officer")
    r = conn.execute("SELECT id FROM officer WHERE display_name=? COLLATE NOCASE", (name,)).fetchone()
    if r:
        conn.execute("UPDATE officer SET active=1 WHERE id=?", (r["id"],))
        return r["id"]
    return conn.execute("INSERT INTO officer(display_name, rank) VALUES (?,?)", (name, rank)).lastrowid


def parse_ship_time(s: str) -> str:
    s = (s or "").strip().replace(" ", "T")
    for fmt in ("%Y-%m-%dT%H:%M", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%dT%H:%M")
        except ValueError:
            pass
    raise ReadingError("Enter the closure time as YYYY-MM-DD HH:MM")


def close_check(st: dict) -> list[str]:
    """Reasons the watch cannot be closed yet (empty list = may close)."""
    problems = []
    if st["totals"]["review"]:
        problems.append(f'{st["totals"]["review"]} reading(s) flagged for review must be resolved '
                        "(confirm rollover / meter replaced, re-enter, or mark unavailable)")
    return problems


def close_log(conn, reg: Registry, ship_date: str, watch: str, officer_name: str, closed_at: str,
              remarks: str | None = None, confirm_missing: bool = False):
    """Close the draft: record officer + closure time, freeze a snapshot. Returns the closed log row."""
    log = _draft_or_error(conn, ship_date, watch)
    closed_at = parse_ship_time(closed_at)
    if remarks is not None:
        conn.execute("UPDATE watch_log SET remarks=? WHERE id=?", (remarks[:4000], log["id"]))
    st = log_state(conn, reg, ship_date, watch, log_by_id(conn, log["id"]))
    problems = close_check(st)
    if problems:
        raise ReadingError("; ".join(problems))
    if st["totals"]["missing"] and not confirm_missing:
        raise ReadingError(f'{st["totals"]["missing"]} reading(s) are missing — tick the confirmation to close anyway')
    oid = get_or_create_officer(conn, officer_name)
    name = conn.execute("SELECT display_name FROM officer WHERE id=?", (oid,)).fetchone()["display_name"]
    conn.execute("UPDATE watch_log SET status='closed', officer_id=?, officer_name=?, closed_at=?, "
                 "closed_recorded_at=?, missing_confirmed=? WHERE id=?",
                 (oid, name, closed_at, now_iso(), int(bool(st["totals"]["missing"])), log["id"]))
    closed = log_by_id(conn, log["id"])
    st = log_state(conn, reg, ship_date, watch, closed)
    conn.execute("UPDATE watch_log SET snapshot_json=? WHERE id=?", (json.dumps(st), log["id"]))
    return log_by_id(conn, log["id"])


def start_correction(conn, ship_date: str, watch: str, reason: str):
    """Copy the closed record into a new draft version. The closed original is never modified."""
    reason = " ".join((reason or "").split())[:300]
    if not reason:
        raise ReadingError("Give the reason for the correction")
    if conn.execute("SELECT 1 FROM watch_log WHERE ship_date=? AND watch=? AND status='draft'",
                    (ship_date, watch)).fetchone():
        raise ReadingError("A draft already exists for this watch")
    base = current_log(conn, ship_date, watch)
    if base is None or base["status"] != "closed":
        raise ReadingError("Only a closed watch can be corrected")
    new_id = conn.execute(
        "INSERT INTO watch_log(ship_date, watch, status, version, supersedes_id, correction_reason, "
        "correction_created_at, remarks, saved_at) VALUES (?,?,'draft',?,?,?,?,?,?)",
        (ship_date, watch, base["version"] + 1, base["id"], reason, now_iso(), base["remarks"], now_iso())).lastrowid
    conn.execute("INSERT INTO reading(log_id, field_id, slot, value_num, qualifier, raw_text, status, "
                 "unavailable_reason, entered_at) SELECT ?, field_id, slot, value_num, qualifier, raw_text, "
                 "status, unavailable_reason, entered_at FROM reading WHERE log_id=?", (new_id, base["id"]))
    return log_by_id(conn, new_id)


def cancel_correction(conn, ship_date: str, watch: str) -> None:
    log = editing_log(conn, ship_date, watch)
    if log is None or log["status"] != "draft" or log["version"] < 2:
        raise ReadingError("No correction draft to discard")
    conn.execute("DELETE FROM watch_log WHERE id=?", (log["id"],))


def versions(conn, ship_date: str, watch: str) -> list:
    return conn.execute("SELECT id, version, status, closed_at, officer_name, correction_reason, "
                        "correction_created_at, closed_recorded_at FROM watch_log WHERE ship_date=? AND watch=? "
                        "ORDER BY version", (ship_date, watch)).fetchall()


# ---------------------------------------------------------------- overviews

def day_overview(conn, ship_date: str) -> list[dict]:
    out = []
    for w in WATCHES:
        log = current_log(conn, ship_date, w)
        if log is None:
            out.append({"watch": w, "status": "not_started"})
            continue
        ed = editing_log(conn, ship_date, w)
        n = conn.execute("SELECT COUNT(*) c FROM reading WHERE log_id=? AND status<>'missing'", (log["id"],)).fetchone()["c"]
        out.append({"watch": w, "status": log["status"], "saved_at": log["saved_at"], "log_id": log["id"],
                    "closed_at": log["closed_at"], "officer": log["officer_name"], "version": log["version"],
                    "correcting": ed["id"] != log["id"], "readings": n})
    return out


def history(conn, reg: Registry, date_from: str, date_to: str, watch: str | None = None,
            status: str | None = None, limit: int = 500) -> list[dict]:
    q = "SELECT * FROM watch_log WHERE ship_date BETWEEN ? AND ?"
    args = [check_date(date_from), check_date(date_to)]
    if watch:
        q += " AND watch=?"
        args.append(check_watch(watch))
    q += " ORDER BY ship_date DESC, watch DESC, version DESC"
    out = []
    for r in conn.execute(q, args).fetchall():
        eff = current_log(conn, r["ship_date"], r["watch"])
        is_eff = eff is not None and eff["id"] == r["id"]
        is_corr_draft = r["status"] == "draft" and r["version"] > 1
        if not (is_eff or is_corr_draft):
            continue                       # superseded versions are reached from the record page
        if r["status"] == "closed" and r["snapshot_json"]:
            totals = json.loads(r["snapshot_json"])["totals"]
        else:
            totals = log_state(conn, reg, r["ship_date"], r["watch"], r)["totals"]
        if status == "closed" and r["status"] != "closed":
            continue
        if status == "draft" and r["status"] != "draft":
            continue
        if status == "corrected" and r["version"] < 2:
            continue
        if status == "missing" and not totals["missing"]:
            continue
        out.append({"id": r["id"], "ship_date": r["ship_date"], "watch": r["watch"], "status": r["status"],
                    "version": r["version"], "officer": r["officer_name"], "closed_at": r["closed_at"],
                    "missing": totals["missing"], "unavailable": totals["unavailable"], "review": totals["review"],
                    "correction_draft": is_corr_draft})
        if len(out) >= limit:
            break
    return out


# ---------------------------------------------------------------- read cache (reports)
#
# Period reports evaluate thousands of intervals. Inside `read_cache()` the
# lookup helpers below are memoised for the duration of one read-only request,
# so the same rules (compute_point) are reused without thousands of queries.

_MEMO: ContextVar[dict | None] = ContextVar("_MEMO", default=None)


def _memo(fn):
    @functools.wraps(fn)
    def wrapper(conn, *args):
        m = _MEMO.get()
        if m is None:
            return fn(conn, *args)
        key = (fn.__name__,) + args
        if key not in m:
            m[key] = fn(conn, *args)
        return m[key]
    return wrapper


def _reading_row(conn, log_id, field_id, slot):
    m = _MEMO.get()
    if m is None:
        return conn.execute("SELECT * FROM reading WHERE log_id=? AND field_id=? AND slot=?",
                            (log_id, field_id, slot)).fetchone()
    key = ("rows", log_id)
    if key not in m:
        m[key] = {(r["field_id"], r["slot"]): r for r in
                  conn.execute("SELECT * FROM reading WHERE log_id=?", (log_id,))}
    return m[key].get((field_id, slot))


@contextmanager
def read_cache():
    token = _MEMO.set({})
    try:
        yield
    finally:
        _MEMO.reset(token)


current_log = _memo(current_log)
earliest_log = _memo(earliest_log)
not_in_use = _memo(not_in_use)
rollover_limit = _memo(rollover_limit)
opening_balance = _memo(opening_balance)
point_event = _memo(point_event)
