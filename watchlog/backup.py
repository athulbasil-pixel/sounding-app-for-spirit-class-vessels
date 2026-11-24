"""Backups: consistent SQLite snapshots (online backup API), restore, full zip.

Backups live in <data>/backups. Automatic backups (daily on start, and after
every watch closure) are pruned to the newest KEEP_AUTO; manual and
pre-restore backups are never pruned automatically.
"""
from __future__ import annotations

import io
import re
import shutil
import sqlite3
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

from . import db

KEEP_AUTO = 60
AUTO_REASONS = {"daily", "close"}
NAME_RE = re.compile(r"^watchlog_(\d{8}-\d{6})(?:-\d+)?_([a-z-]+)\.sqlite3$")


class BackupError(Exception):
    pass


def backups_dir(data_dir: str | Path) -> Path:
    p = Path(data_dir) / "backups"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _snapshot(src_path: str | Path, dest: Path) -> None:
    src = sqlite3.connect(str(src_path))
    dst = sqlite3.connect(str(dest))
    try:
        src.backup(dst)
        dst.execute("PRAGMA journal_mode=DELETE")   # self-contained single file (no -wal/-shm beside it)
    finally:
        dst.close()
        src.close()


def check_db_file(path: str | Path) -> dict:
    """Raise BackupError unless `path` is a healthy Watch Log database."""
    p = Path(path)
    if not p.exists() or p.stat().st_size < 100:
        raise BackupError("File is empty or missing")
    with open(p, "rb") as fh:
        if fh.read(16) != b"SQLite format 3\x00":
            raise BackupError("Not a SQLite database file")
    conn = sqlite3.connect(f"file:{p.as_posix()}?mode=ro", uri=True)
    try:
        if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise BackupError("Database integrity check failed")
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        missing = {"watch_log", "reading", "meta"} - tables
        if missing:
            raise BackupError(f"Not a Watch Log database (missing {', '.join(sorted(missing))})")
        logs = conn.execute("SELECT COUNT(*) FROM watch_log").fetchone()[0]
        span = conn.execute("SELECT MIN(ship_date), MAX(ship_date) FROM watch_log").fetchone()
        return {"logs": logs, "first": span[0], "last": span[1]}
    except sqlite3.DatabaseError as e:
        raise BackupError(f"Unreadable database: {e}") from e
    finally:
        conn.close()


def make_backup(data_dir: str | Path, db_path: str | Path, reason: str = "manual") -> Path:
    if not re.fullmatch(r"[a-z-]+", reason):
        raise BackupError("bad reason")
    d = backups_dir(data_dir)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    dest = d / f"watchlog_{stamp}_{reason}.sqlite3"
    n = 1
    while dest.exists():                     # two backups in the same second
        dest = d / f"watchlog_{stamp}-{n}_{reason}.sqlite3"
        n += 1
    tmp = dest.with_suffix(".part")
    _snapshot(db_path, tmp)
    check_db_file(tmp)
    tmp.replace(dest)
    for stray in d.glob("*.part*"):                 # leftovers from an interrupted backup
        stray.unlink(missing_ok=True)
    prune(data_dir)
    return dest


def list_backups(data_dir: str | Path) -> list[dict]:
    out = []
    for p in backups_dir(data_dir).glob("watchlog_*.sqlite3"):
        m = NAME_RE.match(p.name)
        if not m:
            continue
        st = p.stat()
        out.append({"name": p.name, "reason": m.group(2), "size": st.st_size,
                    "created": datetime.strptime(m.group(1), "%Y%m%d-%H%M%S")})
    out.sort(key=lambda b: (b["created"], b["name"]), reverse=True)
    return out


def prune(data_dir: str | Path, keep: int = KEEP_AUTO) -> None:
    auto = [b for b in list_backups(data_dir) if b["reason"] in AUTO_REASONS]
    for b in auto[keep:]:
        (backups_dir(data_dir) / b["name"]).unlink(missing_ok=True)


def backup_path(data_dir: str | Path, name: str) -> Path:
    if not NAME_RE.match(name or ""):
        raise BackupError("Unknown backup")
    p = backups_dir(data_dir) / name
    if not p.exists():
        raise BackupError("Backup not found")
    return p


def daily_backup_if_due(data_dir: str | Path, db_path: str | Path) -> Path | None:
    today = datetime.now().date()
    if any(b["created"].date() == today and b["reason"] in AUTO_REASONS for b in list_backups(data_dir)):
        return None
    if not Path(db_path).exists():
        return None
    return make_backup(data_dir, db_path, "daily")


def restore(data_dir: str | Path, db_path: str | Path, source: str | Path) -> tuple[Path, dict]:
    """Replace the live database with `source`. The current database is backed up first."""
    info = check_db_file(source)
    safety = make_backup(data_dir, db_path, "pre-restore")
    src = sqlite3.connect(f"file:{Path(source).as_posix()}?mode=ro", uri=True)
    dst = sqlite3.connect(str(db_path), timeout=10)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    db.init_db(db_path)                      # bring an older backup up to the current schema
    return safety, info


def restore_upload(data_dir, db_path, fileobj) -> tuple[Path, dict]:
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td) / "upload.sqlite3"
        with open(tmp, "wb") as fh:
            shutil.copyfileobj(fileobj, fh, length=1 << 20)
        return restore(data_dir, db_path, tmp)


def full_zip(data_dir: str | Path, db_path: str | Path) -> io.BytesIO:
    """Database snapshot + all generated PDFs, for copying off the PC."""
    buf = io.BytesIO()
    with tempfile.TemporaryDirectory() as td:
        snap = Path(td) / "watchlog.sqlite3"
        _snapshot(db_path, snap)
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            z.write(snap, "watchlog.sqlite3")
            pdfs = Path(data_dir) / "pdfs"
            if pdfs.exists():
                for p in sorted(pdfs.rglob("*.pdf")):
                    z.write(p, p.relative_to(data_dir).as_posix())
            z.writestr("README.txt", "MarineSense Watch Log full backup.\r\n"
                       "To restore: Settings > Backups > Restore from file, and choose watchlog.sqlite3.\r\n"
                       "PDFs are copies of the closed watch records.\r\n")
    buf.seek(0)
    return buf


def copy_latest_to(data_dir: str | Path, target_dir: str) -> Path:
    t = Path(target_dir.strip().strip('"'))
    if not t.is_absolute() or not t.exists() or not t.is_dir():
        raise BackupError("Folder not found — plug in the USB drive and enter its folder, e.g. E:\\")
    latest = list_backups(data_dir)
    if not latest:
        raise BackupError("No backup yet — press Backup now first")
    dest = t / latest[0]["name"]
    shutil.copy2(backups_dir(data_dir) / latest[0]["name"], dest)
    return dest
