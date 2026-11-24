"""Reviewer feedback: notes tagged with the screen they were written on, exported as one text file."""
from __future__ import annotations

import platform
from datetime import datetime

from flask import Response, abort, current_app, flash, jsonify, redirect, render_template, request, url_for

from . import __version__
import sqlite3
from pathlib import Path

from flask import g

from .views import bp, vessel_name

FEEDBACK_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS feedback (
    id INTEGER PRIMARY KEY,
    page TEXT,
    page_title TEXT,
    category TEXT NOT NULL DEFAULT 'suggestion',
    text TEXT NOT NULL,
    mode TEXT,                               -- 'normal' or 'training'
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now','localtime')),
    updated_at TEXT
);
"""


def get_db():
    """Connection to the shared feedback file (separate from the watch-log database)."""
    if "fb_db" not in g:
        path = Path(current_app.config["FEEDBACK_DB"])
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(path), isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.executescript(FEEDBACK_SCHEMA)
        g.fb_db = conn
    return g.fb_db


@bp.teardown_app_request
def _close_fb(_exc=None):
    conn = g.pop("fb_db", None)
    if conn is not None:
        conn.close()


def _mode() -> str:
    return "training" if current_app.config.get("DEMO") else "normal"

CATEGORIES = {
    "suggestion": "Suggestion",
    "problem": "Problem / bug",
    "missing": "Missing field or equipment",
    "wording": "Wording / units",
    "question": "Question",
    "good": "Works well",
}


def _reviewer() -> str:
    r = get_db().execute("SELECT value FROM meta WHERE key='reviewer_name'").fetchone()
    return r["value"] if r and r["value"] else ""


def _clean(s: str | None, n: int) -> str:
    return (s or "").replace("\r\n", "\n").strip()[:n]


@bp.post("/api/feedback")
def api_feedback_add():
    body = request.get_json(silent=True) or {}
    text = _clean(body.get("text"), 4000)
    if not text:
        return jsonify({"error": "Write a note first"}), 400
    cat = body.get("category") if body.get("category") in CATEGORIES else "suggestion"
    conn = get_db()
    conn.execute("INSERT INTO feedback(page, page_title, category, text, mode) VALUES (?,?,?,?,?)",
                 (_clean(body.get("page"), 300), _clean(body.get("page_title"), 200), cat, text, _mode()))
    n = conn.execute("SELECT COUNT(*) FROM feedback").fetchone()[0]
    return jsonify({"ok": True, "count": n})


@bp.route("/feedback", methods=["GET", "POST"])
def feedback_page():
    conn = get_db()
    if request.method == "POST":
        action = request.form.get("action")
        if action == "reviewer":
            conn.execute("INSERT INTO meta(key,value) VALUES('reviewer_name',?) "
                         "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                         (_clean(request.form.get("reviewer"), 80),))
            flash("Name saved.")
        elif action == "add":
            text = _clean(request.form.get("text"), 4000)
            if text:
                cat = request.form.get("category") if request.form.get("category") in CATEGORIES else "suggestion"
                conn.execute("INSERT INTO feedback(page, page_title, category, text, mode) VALUES (?,?,?,?,?)",
                             ("/feedback", "General", cat, text, _mode()))
                flash("Note added.")
        elif action == "edit":
            fid = int(request.form.get("id", 0))
            text = _clean(request.form.get("text"), 4000)
            cat = request.form.get("category") if request.form.get("category") in CATEGORIES else "suggestion"
            if text:
                conn.execute("UPDATE feedback SET text=?, category=?, updated_at=strftime('%Y-%m-%dT%H:%M:%S','now','localtime') "
                             "WHERE id=?", (text, cat, fid))
                flash("Note updated.")
        elif action == "delete":
            conn.execute("DELETE FROM feedback WHERE id=?", (int(request.form.get("id", 0)),))
            flash("Note deleted.")
        else:
            abort(400)
        return redirect(url_for("watchlog.feedback_page"))
    notes = conn.execute("SELECT * FROM feedback ORDER BY id DESC").fetchall()
    return render_template("feedback.html", notes=notes, categories=CATEGORIES, reviewer=_reviewer())


@bp.get("/feedback/export.txt")
def feedback_export():
    conn = get_db()
    notes = conn.execute("SELECT * FROM feedback ORDER BY id").fetchall()
    now = datetime.now()
    lines = [
        "MarineSense Engine Room Watch Log - reviewer feedback",
        "=" * 56,
        f"Exported:  {now:%Y-%m-%d %H:%M}",
        f"Reviewer:  {_reviewer() or '(name not set)'}",
        f"Vessel:    {vessel_name()}",
        f"App:       {__version__}",
        f"Windows:   {platform.platform()}",
        f"Notes:     {len(notes)}",
        "",
    ]
    for i, n in enumerate(notes, 1):
        when = n["created_at"].replace("T", " ")[:16]
        mode = " [training]" if n["mode"] == "training" else ""
        lines.append(f"[{i}] {CATEGORIES.get(n['category'], n['category'])} - {n['page_title'] or ''} ({n['page'] or ''}){mode} - {when}")
        lines.extend("    " + ln for ln in n["text"].split("\n"))
        lines.append("")
    if not notes:
        lines.append("(no notes yet)")
    body = "\r\n".join(lines) + "\r\n"
    name = f"WatchLog_feedback_{now:%Y%m%d-%H%M}.txt"
    return Response("﻿" + body, mimetype="text/plain; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})
