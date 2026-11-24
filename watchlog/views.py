from __future__ import annotations

import secrets
from datetime import date, timedelta

from flask import (Blueprint, abort, current_app, flash, jsonify, redirect, render_template, request,
                   session, url_for)

from . import __version__, logic
from .db import get_db
from .registry import WATCH_LABELS, WATCHES, load_registry

bp = Blueprint("watchlog", __name__)


# ---------------------------------------------------------------- helpers

def reg():
    return load_registry()


def csrf_token() -> str:
    if "csrf" not in session:
        session["csrf"] = secrets.token_hex(16)
    return session["csrf"]


@bp.app_context_processor
def inject():
    return {"csrf_token": csrf_token, "WATCH_LABELS": WATCH_LABELS, "WATCHES": WATCHES,
            "app_version": __version__, "vessel_name": vessel_name(),
            "demo_mode": current_app.config.get("DEMO", False)}


@bp.app_template_filter("num")
def num_filter(v):
    """1234567.5 -> '1 234 567.5' (thin grouping, no float noise)."""
    if v is None or v == "":
        return ""
    try:
        x = round(float(v), 6)
    except (TypeError, ValueError):
        return v
    if x.is_integer():
        return f"{int(x):,}".replace(",", " ")
    i, d = f"{x}".split(".")
    return f"{int(i):,}".replace(",", " ") + "." + d


def vessel_name() -> str:
    r = get_db().execute("SELECT value FROM meta WHERE key='vessel_name'").fetchone()
    return r["value"] if r and r["value"] else "Vessel name not set"


@bp.before_request
def protect():
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return
    if request.path.startswith("/api/"):
        # custom header cannot be sent cross-site without a CORS preflight we never grant
        if request.headers.get("X-Watchlog") != "1":
            abort(403)
    elif request.form.get("csrf") != session.get("csrf"):
        abort(403)


def layout_json():
    r = reg()
    out = []
    for s in r.sections:
        out.append({
            "id": s.id, "title": s.title, "tag": s.tag, "fw": s.is_fw_schedule,
            "groups": s.groups,
            "fields": [{"id": f.id, "label": f.label, "kind": f.kind, "unit": f.unit,
                        "unit_status": f.unit_status, "group": f.group, "diff_unit": f.diff_unit,
                        "derived_label": f.derived_label} for f in s.fields],
        })
    fw_labels = {f: r.fields[f].label.split(" — ")[0].replace(" counter", "") for f in r.fw_fields}
    return {"sections": out, "fw_fields": r.fw_fields, "fw_labels": fw_labels, "slots": r.slots,
            "fields": {f.id: {"label": f.label, "unit": f.unit, "kind": f.kind, "diff_unit": f.diff_unit,
                              "unit_status": f.unit_status} for f in r.fields.values()}}


def api_error(msg, code=400):
    return jsonify({"error": msg}), code


# ---------------------------------------------------------------- pages

@bp.get("/")
def home():
    d, _why = logic.suggested_ship_date(get_db())
    return redirect(url_for("watchlog.day", ship_date=d))


@bp.get("/day/<ship_date>")
def day(ship_date):
    try:
        ship_date = logic.check_date(ship_date)
    except logic.ReadingError:
        abort(404)
    conn = get_db()
    d = date.fromisoformat(ship_date)
    suggested, why = logic.suggested_ship_date(conn)
    return render_template("board.html", ship_date=ship_date, day=d,
                           prev_day=(d - timedelta(days=1)).isoformat(), next_day=(d + timedelta(days=1)).isoformat(),
                           watches=logic.day_overview(conn, ship_date), suggested=suggested, suggested_why=why,
                           has_logs=logic.earliest_log(conn) is not None)


@bp.post("/day")
def pick_day():
    try:
        d = logic.check_date(request.form.get("ship_date", ""))
    except logic.ReadingError:
        flash("Choose a valid ship date.")
        return redirect(url_for("watchlog.home"))
    return redirect(url_for("watchlog.day", ship_date=d))


@bp.post("/watch/<ship_date>/<watch>/start")
def start_watch(ship_date, watch):
    try:
        logic.get_or_create_log(get_db(), ship_date, watch)   # never duplicates (UNIQUE + INSERT OR IGNORE)
    except logic.ReadingError:
        abort(404)
    return redirect(url_for("watchlog.entry", ship_date=ship_date, watch=watch))


@bp.get("/watch/<ship_date>/<watch>")
def entry(ship_date, watch):
    try:
        ship_date, watch = logic.check_date(ship_date), logic.check_watch(watch)
    except logic.ReadingError:
        abort(404)
    conn = get_db()
    log = logic.editing_log(conn, ship_date, watch)
    if log is None:
        return redirect(url_for("watchlog.day", ship_date=ship_date))
    if log["status"] == "closed":
        return redirect(url_for("watchlog.record", log_id=log["id"]))
    return render_template("entry.html", ship_date=ship_date, watch=watch, day=date.fromisoformat(ship_date),
                           watches=logic.day_overview(conn, ship_date), layout=layout_json(), log=log)


# ---------------------------------------------------------------- API

@bp.get("/api/watch/<ship_date>/<watch>")
def api_state(ship_date, watch):
    try:
        return jsonify(logic.log_state(get_db(), reg(), ship_date, watch))
    except logic.ReadingError as e:
        return api_error(str(e))


@bp.put("/api/watch/<ship_date>/<watch>/reading")
def api_reading(ship_date, watch):
    body = request.get_json(silent=True) or {}
    conn = get_db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        logic.save_reading(conn, reg(), ship_date, watch, body.get("field", ""), body.get("slot", "watch"),
                           body.get("raw"), body.get("status", "entered"), body.get("reason"))
        conn.execute("COMMIT")
    except logic.ReadingError as e:
        conn.execute("ROLLBACK")
        return api_error(str(e))
    return jsonify(logic.log_state(conn, reg(), ship_date, watch))


@bp.put("/api/watch/<ship_date>/<watch>/remarks")
def api_remarks(ship_date, watch):
    body = request.get_json(silent=True) or {}
    try:
        logic.save_remarks(get_db(), ship_date, watch, str(body.get("remarks", ""))[:4000])
    except logic.ReadingError as e:
        return api_error(str(e))
    return jsonify({"ok": True, "saved_at": logic.editing_log(get_db(), ship_date, watch)["saved_at"]})


@bp.route("/api/watch/<ship_date>/<watch>/event", methods=["POST", "DELETE"])
def api_event(ship_date, watch):
    body = request.get_json(silent=True) or {}
    conn = get_db()
    r = reg()
    fid, series, point = body.get("field", ""), body.get("series", "6h"), body.get("point", watch)
    if fid not in r.fields or series not in ("6h", "4h") or point not in logic.series_points(series):
        return api_error("Unknown reading")
    log = logic.editing_log(conn, ship_date, watch)
    if log is None or log["status"] != "draft":
        return api_error("Watch not editable")
    try:
        if request.method == "DELETE":
            logic.clear_point_event(conn, fid, series, ship_date, point)
        else:
            val = body.get("value")
            val = logic.parse_reading(val)[0] if val not in (None, "") else None
            logic.set_point_event(conn, fid, series, ship_date, point, body.get("kind"), val, body.get("reason"))
    except logic.ReadingError as e:
        return api_error(str(e))
    return jsonify(logic.log_state(conn, r, ship_date, watch))


# ---------------------------------------------------------------- settings

@bp.route("/settings", methods=["GET", "POST"])
def settings():
    conn = get_db()
    r = reg()
    if request.method == "POST":
        action = request.form.get("action")
        try:
            if action == "vessel":
                conn.execute("INSERT INTO meta(key,value) VALUES('vessel_name',?) "
                             "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                             (request.form.get("vessel_name", "").strip()[:120],))
                flash("Vessel name saved.")
            elif action == "opening":
                n = 0
                for f in r.fields.values():
                    if not f.is_counter:
                        continue
                    for series in ("6h", "4h") if f.id in r.fw_fields else ("6h",):
                        key = f"ob__{f.id}__{series}"
                        if key in request.form:
                            v = logic.parse_reading(request.form[key])[0]
                            logic.set_opening_balance(conn, f.id, series, v)
                            n += 1
                flash("Opening balances saved.")
            elif action == "officer_add":
                logic.get_or_create_officer(conn, request.form.get("name", ""), request.form.get("rank") or None)
                flash("Officer added.")
            elif action == "officer_toggle":
                conn.execute("UPDATE officer SET active = 1 - active WHERE id=?", (int(request.form.get("id", 0)),))
                flash("Officer list updated.")
            elif action == "lan_pin":
                if request.remote_addr not in ("127.0.0.1", "::1"):
                    abort(403)                      # PIN can only be changed at the ECR PC itself
                from .records import set_lan_pin
                set_lan_pin(request.form.get("pin", "").strip() or None)
                flash("Tablet PIN saved." if request.form.get("pin") else "Tablet PIN removed.")
            elif action == "field":
                fid = request.form.get("field_id", "")
                if fid not in r.fields:
                    abort(400)
                eff = logic.check_date(request.form.get("effective_from", ""))
                logic.set_not_in_use(conn, fid, eff, request.form.get("not_in_use") == "1")
                lim = request.form.get("rollover_limit", "").strip()
                if r.fields[fid].is_counter:
                    logic.set_rollover_limit(conn, fid, logic.parse_reading(lim)[0] if lim else None)
                flash(f"Saved settings for {r.fields[fid].label}.")
        except logic.ReadingError as e:
            flash(f"Not saved: {e}")
        return redirect(url_for("watchlog.settings") + (f"#{request.form.get('field_id')}" if action == "field" else ""))

    today_suggest, _ = logic.suggested_ship_date(conn)
    rows = []
    for s in r.sections:
        for f in s.fields:
            st = conn.execute("SELECT effective_from, not_in_use FROM field_state WHERE field_id=? "
                              "ORDER BY effective_from DESC LIMIT 1", (f.id,)).fetchone()
            lim = conn.execute("SELECT rollover_limit FROM field_setting WHERE field_id=?", (f.id,)).fetchone()
            rows.append({"section": s.id, "field": f,
                         "not_in_use": bool(st and st["not_in_use"]),
                         "effective_from": st["effective_from"] if st else None,
                         "rollover_limit": lim["rollover_limit"] if lim and lim["rollover_limit"] else None,
                         "ob6": logic.opening_balance(conn, f.id, "6h"),
                         "ob4": logic.opening_balance(conn, f.id, "4h") if f.id in r.fw_fields else None,
                         "fw": f.id in r.fw_fields})
    from .records import lan_addresses
    pin_set = conn.execute("SELECT 1 FROM meta WHERE key='lan_pin_hash'").fetchone() is not None
    return render_template("settings.html", rows=rows, suggest_date=today_suggest,
                           officers=logic.officers(conn, active_only=False), pin_set=pin_set,
                           lan_mode=current_app.config.get("LAN_MODE"), lan_ips=lan_addresses(),
                           port=request.host.rsplit(":", 1)[-1] if ":" in request.host else "5080",
                           data_dir=current_app.config["DATA_DIR"],
                           vessel=conn.execute("SELECT value FROM meta WHERE key='vessel_name'").fetchone())
