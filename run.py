"""Start the MarineSense Watch Log on http://127.0.0.1:5080 and open the browser."""
from __future__ import annotations

import argparse
import threading
import webbrowser

from watchlog import create_app, default_data_dir


def main() -> None:
    ap = argparse.ArgumentParser(description="MarineSense Engine Room Watch Log")
    ap.add_argument("--port", type=int, default=5080)
    ap.add_argument("--data-dir", default=None, help=r"folder for the database (default: %%LOCALAPPDATA%%\MarineSense\WatchLog)")
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--lan", action="store_true",
                    help="also accept tablets on the ship's network (PIN required; set it in Settings first)")
    args = ap.parse_args()

    app = create_app(args.data_dir, lan=args.lan)
    url = f"http://127.0.0.1:{args.port}/"
    print(f"\n  MarineSense Watch Log running at {url}")
    print(f"  Data folder: {args.data_dir or default_data_dir()}")
    print("  Keep this window open while using the log. Press Ctrl+C to stop.\n")
    if not args.no_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    host = "127.0.0.1"
    if args.lan:
        from watchlog.records import lan_addresses
        host = "0.0.0.0"
        print("  LAN MODE ON - tablets on the ship's network can connect with the PIN:")
        for ip in lan_addresses() or ["(no network address found)"]:
            print(f"     http://{ip}:{args.port}/")
        print()
    app.run(host=host, port=args.port, debug=False, threaded=True, use_reloader=False)


if __name__ == "__main__":
    main()
