"""Phase 4 routes: backups (ECR PC only), health check, error pages."""
from __future__ import annotations

from datetime import datetime

from flask import abort, current_app, flash, redirect, render_template, request, send_file, url_for

from . import backup
from .db import get_db
from .records import _is_local
from .views import bp


def _local_only():
    if not _is_local(request.remote_addr):
        abort(403)                            # backups and restores only at the ECR PC


def _paths():
    return current_app.config["DATA_DIR"], current_app.config["DATABASE"]


@bp.get("/backups")
def backups_page():
    _local_only()
    data_dir, _ = _paths()
    return render_template("backups.html", backups=backup.list_backups(data_dir), data_dir=data_dir,
                           keep=backup.KEEP_AUTO)


@bp.post("/backups/new")
def backup_now():
    _local_only()
    try:
        p = backup.make_backup(*_paths(), reason="manual")
        flash(f"Backup saved: {p.name}")
    except backup.BackupError as e:
        flash(f"Backup failed: {e}")
    return redirect(url_for("watchlog.backups_page"))


@bp.get("/backups/full.zip")
def backup_zip():
    _local_only()
    buf = backup.full_zip(*_paths())
    name = f"WatchLog_full_backup_{datetime.now():%Y%m%d-%H%M}.zip"
    return send_file(buf, mimetype="application/zip", as_attachment=True, download_name=name)


@bp.get("/backups/file/<name>")
def backup_download(name):
    _local_only()
    try:
        p = backup.backup_path(_paths()[0], name)
    except backup.BackupError:
        abort(404)
    return send_file(p, as_attachment=True, download_name=name)


@bp.post("/backups/copy")
def backup_copy():
    _local_only()
    try:
        dest = backup.copy_latest_to(_paths()[0], request.form.get("folder", ""))
        flash(f"Copied to {dest}")
    except (backup.BackupError, OSError) as e:
        flash(f"Not copied: {e}")
    return redirect(url_for("watchlog.backups_page"))


def _confirmed() -> bool:
    return request.form.get("confirm", "").strip().upper() == "RESTORE"


@bp.post("/backups/restore")
def backup_restore():
    _local_only()
    if not _confirmed():
        flash("Not restored: type RESTORE to confirm.")
        return redirect(url_for("watchlog.backups_page"))
    data_dir, db_path = _paths()
    _close_request_db()
    try:
        if request.form.get("name"):
            safety, info = backup.restore(data_dir, db_path, backup.backup_path(data_dir, request.form["name"]))
        else:
            f = request.files.get("file")
            if not f or not f.filename:
                raise backup.BackupError("Choose a backup file")
            safety, info = backup.restore_upload(data_dir, db_path, f.stream)
    except backup.BackupError as e:
        flash(f"Not restored: {e}")
        return redirect(url_for("watchlog.backups_page"))
    flash(f"Restored ({info['logs']} watch logs, {info['first'] or '—'} to {info['last'] or '—'}). "
          f"The previous database was saved first as {safety.name}.")
    return redirect(url_for("watchlog.backups_page"))


def _close_request_db():
    from flask import g
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


@bp.get("/health")
def health():
    conn = get_db()
    ok = conn.execute("PRAGMA quick_check").fetchone()[0] == "ok"
    return {"ok": ok, "version": current_app.config.get("VERSION")}, (200 if ok else 500)


@bp.app_errorhandler(404)
def not_found(e):
    return render_template("error.html", code=404, title="Page not found",
                           message="That page does not exist. Use the Watch board to find a watch."), 404


@bp.app_errorhandler(403)
def forbidden(e):
    return render_template("error.html", code=403, title="Not allowed here",
                           message="This action is only available on the ECR PC running the Watch Log, "
                                   "or the request was not sent from the app itself."), 403


@bp.app_errorhandler(500)
def server_error(e):
    current_app.logger.exception("Unhandled error")
    return render_template("error.html", code=500, title="Something went wrong",
                           message="The error was written to the log file. Your saved entries are safe; "
                                   "go back and try again."), 500
