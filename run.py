"""Start the MarineSense Watch Log on http://127.0.0.1:5080 and open the browser."""
from __future__ import annotations

import argparse
import json
import socket
import sys
import threading
import urllib.request
import webbrowser

from watchlog import __version__, create_app, default_data_dir


def already_running(port: int) -> bool:
    """True if a Watch Log is already answering on this port (second double-click)."""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1.5) as r:
            return "version" in json.loads(r.read().decode("utf-8"))
    except Exception:
        return False


def port_busy(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


def main() -> None:
    ap = argparse.ArgumentParser(description="MarineSense Engine Room Watch Log")
    ap.add_argument("--port", type=int, default=None, help="default 5080 (5081 in --demo)")
    ap.add_argument("--data-dir", default=None, help=r"folder for the database (default: %%LOCALAPPDATA%%\MarineSense\WatchLog)")
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--lan", action="store_true",
                    help="also accept tablets on the ship's network (PIN required; set it in Settings first)")
    ap.add_argument("--demo", action="store_true",
                    help="training mode: separate folder with SYNTHETIC data; the real log is not touched")
    args = ap.parse_args()
    if args.port is None:
        args.port = 5081 if args.demo else 5080
    if args.demo:
        from datetime import date, timedelta
        from watchlog import demo
        from pathlib import Path
        args.data_dir = args.data_dir or str(default_data_dir().parent / "WatchLog-DEMO")
        if (Path(args.data_dir) / "watchlog.sqlite3").exists() and not demo.is_demo_dir(args.data_dir):
            sys.exit("  Refusing: that folder holds a real Watch Log. Training mode needs its own folder.")
        demo.mark_demo_dir(args.data_dir)
        r = demo.generate(args.data_dir, date.today() - timedelta(days=13))
        if not r.get("skipped"):
            print(f"  Created synthetic training data: {r['watches']} watches, {r['from']} to {r['to']}")

    url = f"http://127.0.0.1:{args.port}/"
    if already_running(args.port):
        print(f"\n  The Watch Log is already running at {url} - opening it.\n")
        if not args.no_browser:
            webbrowser.open(url)
        return
    if port_busy(args.port):
        print(f"\n  Port {args.port} is used by another program. Close it, or start with --port 5085.\n")
        sys.exit(1)

    app = create_app(args.data_dir, lan=args.lan)
    print(f"\n  MarineSense Watch Log {__version__} running at {url}")
    print(f"  Data folder: {args.data_dir or default_data_dir()}")
    print("  Keep this window open while using the log. Close it (or press Ctrl+C) to stop.\n")
    host = "127.0.0.1"
    if args.lan:
        from watchlog.records import lan_addresses
        host = "0.0.0.0"
        print("  LAN MODE ON - tablets on the ship's network can connect with the PIN:")
        for ip in lan_addresses() or ["(no network address found)"]:
            print(f"     http://{ip}:{args.port}/")
        print()
    if not args.no_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    try:
        from waitress import serve                 # production WSGI server (pure Python)
        serve(app, host=host, port=args.port, threads=8, ident="WatchLog")
    except ImportError:                            # fallback if waitress is not installed yet
        app.run(host=host, port=args.port, debug=False, threaded=True, use_reloader=False)


if __name__ == "__main__":
    main()
