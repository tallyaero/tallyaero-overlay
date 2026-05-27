"""
TallyAero EM Diagram — desktop launcher.

Wraps app.py for the PyInstaller bundle:

  1. Picks a free localhost port at startup so the user never has to know
     the port number and we never collide with another Dash app on 8051.
  2. Starts the Dash server in a background thread.
  3. Waits for `/` to respond (proxy for "Dash is ready").
  4. Opens the user's default browser to http://127.0.0.1:<port>.
  5. Keeps the foreground process alive until interrupted; clean shutdown
     on Ctrl+C or signal.

The bundled .app / .exe runs this file, not app.py directly. Development
still runs `python app.py 8051` as before.
"""

from __future__ import annotations

import logging
import os
import signal
import socket
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

# Honor PyInstaller's _MEIPASS for bundled resources. When we're not bundled
# (running from source) it just resolves to the project root.
if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
    BUNDLE_DIR = Path(sys._MEIPASS)
    os.chdir(BUNDLE_DIR)
else:
    BUNDLE_DIR = Path(__file__).resolve().parent

LOG = logging.getLogger("tallyaero.launcher")
logging.basicConfig(
    level=os.environ.get("TALLYAERO_LOG", "INFO"),
    format="%(asctime)s %(levelname)-7s %(name)s — %(message)s",
)


def pick_free_port() -> int:
    """Ask the OS for an unused localhost port. Bind to port 0 → the kernel
    assigns one; we read it back, close the probe socket, and reuse the
    number. There's a microsecond race where another process could grab
    that port between close and Dash bind, but on a desktop machine that's
    not a real concern."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_for_server(url: str, timeout_s: float = 30.0) -> bool:
    """Poll the URL until it returns 200 or `timeout_s` elapses."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1) as r:
                if r.status == 200:
                    return True
        except Exception:
            pass
        time.sleep(0.25)
    return False


def main() -> None:
    port = pick_free_port()
    url = f"http://127.0.0.1:{port}/"

    LOG.info("TallyAero EM Diagram starting on %s", url)

    # Import after _MEIPASS is configured so the app reads bundled resources.
    from app import server as flask_app

    def run_server():
        # Use werkzeug's serving directly so we can run it in a thread without
        # the reloader/debugger that `app.run_server` enables.
        from werkzeug.serving import make_server
        srv = make_server("127.0.0.1", port, flask_app, threaded=True)
        srv.serve_forever()

    server_thread = threading.Thread(target=run_server, daemon=True, name="dash-server")
    server_thread.start()

    if wait_for_server(url):
        LOG.info("Dash is ready, opening browser")
        webbrowser.open(url, new=2, autoraise=True)
    else:
        LOG.error("Dash did not respond on %s within 30s — opening browser anyway", url)
        webbrowser.open(url, new=2, autoraise=True)

    # Block on a signal so the .app stays open until the user quits.
    stop_event = threading.Event()

    def _handle_sig(_signum, _frame):
        LOG.info("Shutdown signal received")
        stop_event.set()

    signal.signal(signal.SIGINT,  _handle_sig)
    signal.signal(signal.SIGTERM, _handle_sig)

    try:
        while not stop_event.is_set():
            stop_event.wait(timeout=1.0)
    except KeyboardInterrupt:
        pass

    LOG.info("TallyAero EM Diagram exiting")


if __name__ == "__main__":
    main()
