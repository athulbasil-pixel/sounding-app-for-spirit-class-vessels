"""MarineSense Engine Room Watch Log — Spirit class."""
from __future__ import annotations

import logging
import os
import secrets
from logging.handlers import RotatingFileHandler
from pathlib import Path

from flask import Flask

from . import db

__version__ = "1.0.1"


def default_data_dir() -> Path:
    """Runtime data lives outside the repository (never committed)."""
    env = os.environ.get("WATCHLOG_DATA_DIR")
    if env:
        return Path(env)
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / ".local" / "share")
    return Path(base) / "MarineSense" / "WatchLog"


def _setup_logging(app: Flask, data: Path) -> None:
    logs = data / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    h = RotatingFileHandler(logs / "watchlog.log", maxBytes=1_000_000, backupCount=5, encoding="utf-8")
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    h.setLevel(logging.INFO)
    app.logger.addHandler(h)
    app.logger.setLevel(logging.INFO)


def create_app(data_dir: str | Path | None = None, testing: bool = False, lan: bool = False,
               feedback_db: str | Path | None = None) -> Flask:
    data = Path(data_dir) if data_dir else default_data_dir()
    data.mkdir(parents=True, exist_ok=True)
    key_file = data / "secret.key"
    if not key_file.exists():
        key_file.write_text(secrets.token_hex(32), encoding="utf-8")

    app = Flask(__name__, static_folder="static", template_folder="templates")
    app.config.update(
        DATA_DIR=str(data),
        DATABASE=str(data / "watchlog.sqlite3"),
        # reviewer notes: one shared file, so notes from normal and training mode end up together
        FEEDBACK_DB=str(feedback_db or data / "feedback.sqlite3"),
        SECRET_KEY=key_file.read_text(encoding="utf-8").strip(),
        TESTING=testing,
        JSON_SORT_KEYS=False,
        LAN_MODE=lan,
        VERSION=__version__,
        DEMO=(data / "DEMO_DATA_ONLY.txt").exists(),
        SESSION_COOKIE_SAMESITE="Strict",
        SESSION_COOKIE_HTTPONLY=True,
        MAX_CONTENT_LENGTH=200 * 1024 * 1024,     # largest accepted restore upload
    )
    if not testing:
        _setup_logging(app, data)
    db.init_db(app.config["DATABASE"])
    app.teardown_appcontext(db.close_db)

    from .views import bp
    from . import records  # noqa: F401  (registers Phase 2 routes on bp)
    from . import report_views  # noqa: F401  (Phase 3 routes)
    from . import backup_views  # noqa: F401  (Phase 4 routes)
    from . import feedback  # noqa: F401  (reviewer notes)
    app.register_blueprint(bp)

    if not testing:
        from . import backup
        try:
            p = backup.daily_backup_if_due(data, app.config["DATABASE"])
            if p:
                app.logger.info("daily backup %s", p.name)
        except Exception:                          # never block start-up on a backup problem
            app.logger.exception("daily backup failed")
    app.logger.info("Watch Log %s started (data=%s, lan=%s)", __version__, data, lan)
    return app
