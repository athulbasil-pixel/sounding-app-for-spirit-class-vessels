"""MarineSense Engine Room Watch Log — Spirit class."""
from __future__ import annotations

import os
import secrets
from pathlib import Path

from flask import Flask

from . import db

__version__ = "0.2.0-phase2"


def default_data_dir() -> Path:
    """Runtime data lives outside the repository (never committed)."""
    env = os.environ.get("WATCHLOG_DATA_DIR")
    if env:
        return Path(env)
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / ".local" / "share")
    return Path(base) / "MarineSense" / "WatchLog"


def create_app(data_dir: str | Path | None = None, testing: bool = False, lan: bool = False) -> Flask:
    data = Path(data_dir) if data_dir else default_data_dir()
    data.mkdir(parents=True, exist_ok=True)
    key_file = data / "secret.key"
    if not key_file.exists():
        key_file.write_text(secrets.token_hex(32), encoding="utf-8")

    app = Flask(__name__, static_folder="static", template_folder="templates")
    app.config.update(
        DATA_DIR=str(data),
        DATABASE=str(data / "watchlog.sqlite3"),
        SECRET_KEY=key_file.read_text(encoding="utf-8").strip(),
        TESTING=testing,
        JSON_SORT_KEYS=False,
        LAN_MODE=lan,
        SESSION_COOKIE_SAMESITE="Strict",
        SESSION_COOKIE_HTTPONLY=True,
    )
    db.init_db(app.config["DATABASE"])
    app.teardown_appcontext(db.close_db)

    from .views import bp
    from . import records  # noqa: F401  (registers Phase 2 routes on bp)
    app.register_blueprint(bp)
    return app
