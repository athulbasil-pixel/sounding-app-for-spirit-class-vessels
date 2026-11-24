"""Phase 2: review & close, records, versions/corrections, history, PDF, LAN PIN gate."""
from __future__ import annotations

import ipaddress
import socket
from datetime import date, datetime, timedelta
from pathlib import Path

from flask import (abort, current_app, flash, redirect, render_template, request, send_file, session,
                   url_for)
from werkzeug.security import check_password_hash, generate_password_hash

from . import logic
from .db import get_db
from .pdf import build_pdf, pdf_filename
from .registry import WATCH_LABELS, WATCHES
from .views import bp, layout_json, reg, vessel_name


# ---------------------------------------------------------------- LAN mode (opt-in, tablets)

def _is_local(addr: str | None) -> bool:
    try:
        return ipaddress.ip_address(addr or "").is_loopback
    except ValueError:
        return False


def lan_addresses() -> list[str]:
    ips = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if not ip.startswith("127."):
                ips.add(ip)
    except OSError:
        pass
    return sorted(ips)


def _pin_hash():
    r = get_db().execute("SELECT value FROM meta WHERE key='lan_pin_hash'").fetchone()
    return r["value"] if r and r["value"] else None


@bp.before_app_request
def lan_gate():
    if _is_local(request.remote_addr):
        return None
    if not current_app.config.get("LAN_MODE"):
        abort(403)                                     # never serve other machines unless LAN mode is on
    if request.endpoint in ("watchlog.unlock", "static") or session.get("lan_ok"):
        return None
    return redirect(url_for("watchlog.unlock", next=request.path))


@bp.route("/unlock", methods=["GET", "POST"])
def unlock():
    h = _pin_hash()
    if request.method == "POST":
        if h and check_password_hash(h, request.form.get("pin", "")):
            session["lan_ok"] = True
            session.permanent = True
            nxt = request.args.get("next") or "/"
            return redirect(nxt if nxt.startswith("/") and not nxt.startswith("//") else "/")
        flash("Wrong PIN.")
    return render_template("unlock.html", pin_set=bool(h))


def set_lan_pin(pin: str | None) -> None:
    conn = get_db()
    if not pin:
        conn.execute("DELETE FROM meta WHERE key='lan_pin_hash'")
        return
    if not (pin.isdigit() and 4 <= len(pin) <= 12):
        raise logic.ReadingError("PIN must be 4–12 digits")
    conn.execute("INSERT INTO meta(key,value) VALUES('lan_pin_hash',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                 (generate_password_hash(pin),))


# ---------------------------------------------------------------- review & close

def _now_local() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def _default_closure(ship_date: str, watch: str) -> str:
    """Suggest the scheduled end of the watch (ship time); the officer can change it."""
    end = {"w1": "06:00", "w2": "12:00", "w3": "18:00", "w4": "00:00"}[watch]
    d = date.fromisoformat(ship_date) + (timedelta(days=1) if watch == "w4" else timedelta())
    return f"{d.isoformat()} {end}"


@bp.get("/watch/<ship_date>/<watch>/review")
def review(ship_date, watch):
    try:
        ship_date, watch = logic.check_date(ship_date), logic.check_watch(watch)
    except logic.ReadingError:
        abort(404)
    conn = get_db()
    log = logic.editing_log(conn, ship_date, watch)
    if log is None:
        return redirect(url_for("watchlog.day", ship_date=ship_date))
    if log["status"] != "draft":
        return redirect(url_for("watchlog.record", log_id=log["id"]))
    st = logic.log_state(conn, reg(), ship_date, watch, log)
    r = reg()
    def label(i):
        f = r.fields[i["field"]]
        return f.label + (f" @ {i['slot']}" if i["slot"] != "watch" else "")
    visible = [i for i in st["items"] if not i["hidden"] and not i["linked"]]
    review_items = [dict(i, label=label(i)) for i in visible if i["diff_status"] == "review"]
    missing = [dict(i, label=label(i)) for i in visible if i["state"] == "missing"]
    unavailable = [dict(i, label=label(i)) for i in visible if i["state"] == "unavailable"]
    incomplete = [dict(i, label=label(i)) for i in visible if i["state"] == "entered" and i["diff_status"] in ("incomplete", "no_previous")]
    return render_template("review.html", ship_date=ship_date, watch=watch, log=log, st=st,
                           review_items=review_items, missing=missing, unavailable=unavailable,
                           incomplete=incomplete, problems=logic.close_check(st),
                           officers=logic.officers(conn), closure_default=_default_closure(ship_date, watch),
                           day=date.fromisoformat(ship_date))


def _store_pdf(conn, log) -> Path:
    data_dir = Path(current_app.config["DATA_DIR"])
    st = logic.record_state(conn, reg(), log)
    name = pdf_filename(dict(log))
    rel = Path("pdfs") / log["ship_date"][:4] / log["ship_date"][5:7] / name
    sha = build_pdf(st, reg(), vessel_name(), data_dir / rel, logic.versions(conn, log["ship_date"], log["watch"]))
    conn.execute("DELETE FROM pdf_file WHERE log_id=?", (log["id"],))
    conn.execute("INSERT INTO pdf_file(log_id, filename, rel_path, sha256) VALUES (?,?,?,?)",
                 (log["id"], name, str(rel).replace("\\", "/"), sha))
    return data_dir / rel


@bp.post("/watch/<ship_date>/<watch>/close")
def close(ship_date, watch):
    conn = get_db()
    f = request.form
    officer = f.get("officer_new", "").strip() or f.get("officer", "").strip()
    try:
        conn.execute("BEGIN IMMEDIATE")
        log = logic.close_log(conn, reg(), ship_date, watch, officer, f.get("closed_at", ""),
                              f.get("remarks"), f.get("confirm_missing") == "1")
        conn.execute("COMMIT")
    except logic.ReadingError as e:
        conn.execute("ROLLBACK")
        flash(f"Not closed: {e}")
        return redirect(url_for("watchlog.review", ship_date=ship_date, watch=watch))
    try:
        _store_pdf(conn, log)
        flash("Watch closed. PDF generated.")
    except Exception as e:                      # the record is closed even if PDF fails; it can be regenerated
        current_app.logger.exception("PDF generation failed")
        flash(f"Watch closed, but the PDF could not be generated ({e}). Use 'Regenerate PDF'.")
    return redirect(url_for("watchlog.record", log_id=log["id"]))


# ---------------------------------------------------------------- records, versions, corrections

@bp.get("/record/<int:log_id>")
def record(log_id):
    conn = get_db()
    log = logic.log_by_id(conn, log_id)
    if log is None:
        abort(404)
    st = logic.record_state(conn, reg(), log)
    vers = logic.versions(conn, log["ship_date"], log["watch"])
    eff = logic.current_log(conn, log["ship_date"], log["watch"])
    draft = conn.execute("SELECT id, version FROM watch_log WHERE ship_date=? AND watch=? AND status='draft'",
                         (log["ship_date"], log["watch"])).fetchone()
    pdf = conn.execute("SELECT * FROM pdf_file WHERE log_id=? ORDER BY id DESC LIMIT 1", (log_id,)).fetchone()
    return render_template("record.html", log=log, st=st, versions=vers, effective_id=eff["id"] if eff else None,
                           draft=draft, pdf=pdf, layout=layout_json(), day=date.fromisoformat(log["ship_date"]))


@bp.post("/watch/<ship_date>/<watch>/correct")
def correct(ship_date, watch):
    conn = get_db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        logic.start_correction(conn, ship_date, watch, request.form.get("reason", ""))
        conn.execute("COMMIT")
    except logic.ReadingError as e:
        conn.execute("ROLLBACK")
        flash(f"Correction not started: {e}")
        eff = logic.current_log(conn, ship_date, watch)
        return redirect(url_for("watchlog.record", log_id=eff["id"]) if eff else url_for("watchlog.home"))
    flash("Correction draft started. The closed original is kept unchanged.")
    return redirect(url_for("watchlog.entry", ship_date=ship_date, watch=watch))


@bp.post("/watch/<ship_date>/<watch>/discard")
def discard(ship_date, watch):
    conn = get_db()
    try:
        logic.cancel_correction(conn, ship_date, watch)
    except logic.ReadingError as e:
        flash(str(e))
    eff = logic.current_log(conn, ship_date, watch)
    flash("Correction draft discarded.")
    return redirect(url_for("watchlog.record", log_id=eff["id"]))


@bp.get("/pdf/<int:log_id>")
def pdf(log_id):
    conn = get_db()
    log = logic.log_by_id(conn, log_id)
    if log is None or log["status"] != "closed":
        abort(404)
    row = conn.execute("SELECT * FROM pdf_file WHERE log_id=? ORDER BY id DESC LIMIT 1", (log_id,)).fetchone()
    path = Path(current_app.config["DATA_DIR"]) / row["rel_path"] if row else None
    if path is None or not path.exists():
        path = _store_pdf(conn, log)
        row = conn.execute("SELECT * FROM pdf_file WHERE log_id=? ORDER BY id DESC LIMIT 1", (log_id,)).fetchone()
    return send_file(path, mimetype="application/pdf", as_attachment=request.args.get("download") == "1",
                     download_name=row["filename"], max_age=0)


@bp.post("/pdf/<int:log_id>/regenerate")
def regenerate_pdf(log_id):
    conn = get_db()
    log = logic.log_by_id(conn, log_id)
    if log is None or log["status"] != "closed":
        abort(404)
    _store_pdf(conn, log)
    flash("PDF regenerated from the saved record.")
    return redirect(url_for("watchlog.record", log_id=log_id))


# ---------------------------------------------------------------- history

@bp.get("/history")
def history_page():
    conn = get_db()
    today, _ = logic.suggested_ship_date(conn)
    d_to = request.args.get("to") or today
    d_from = request.args.get("from") or (date.fromisoformat(d_to) - timedelta(days=13)).isoformat()
    watch = request.args.get("watch") or None
    status = request.args.get("status") or None
    try:
        rows = logic.history(conn, reg(), d_from, d_to, watch if watch in WATCHES else None, status)
    except logic.ReadingError as e:
        flash(str(e))
        rows = []
    return render_template("history.html", rows=rows, d_from=d_from, d_to=d_to, watch=watch, status=status)
