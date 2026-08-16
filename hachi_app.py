#!/usr/bin/env python3
"""
Hachi - Agentic AI Voice Assistant
Desktop Application Launcher using PyWebView
"""
import os
import sys
import json
# Force UTF-8 output so emoji / non-ASCII chars don't crash the Windows terminal
if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass
if sys.stderr and hasattr(sys.stderr, 'reconfigure'):
    try:
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass
# Edge WebView2 browser flags:
#  - no-user-gesture-required   → allow audio autoplay (TTS)
#  - use-fake-ui-for-media-stream → auto-grant mic permission for localhost
os.environ["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"] = (
    "--autoplay-policy=no-user-gesture-required "
    "--use-fake-ui-for-media-stream"
)
import time
import socket
import logging
import threading
import webview

# Truncate log on startup to prevent unbounded growth (keep last 500 lines)
_log_path = os.path.join(os.path.dirname(__file__), "hachi.log")
try:
    if os.path.exists(_log_path) and os.path.getsize(_log_path) > 500_000:
        with open(_log_path, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()
        with open(_log_path, "w", encoding="utf-8") as f:
            f.writelines(lines[-500:])
except Exception:
    pass

logging.basicConfig(
    filename=_log_path,
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)

from hachi_web import app, FLASK_PORT, start_wakeword_listener
from hachi_web import start_tts_janitor
from hachi_db import init_db
from hachi_productivity import start_reminder_scheduler


def _wait_for_flask(host="127.0.0.1", port=FLASK_PORT, timeout=15):
    """
    Poll until Flask is accepting connections.
    Much more reliable than a fixed time.sleep() on slow machines.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.2)
    return False


def _wakeword_is_enabled() -> bool:
    """Read the optional wake-word setting without making startup fragile."""
    config_path = os.path.join(os.path.dirname(__file__), "config.json")
    try:
        with open(config_path, "r", encoding="utf-8") as config_file:
            return bool(json.load(config_file).get("wakeword_enabled", False))
    except (OSError, ValueError, TypeError):
        return False


class DesktopApi:
    """Native-window actions exposed only to Hachi's trusted local frontend."""

    def __init__(self):
        self._smart_home_window = None
        self._window_lock = threading.Lock()

    def _clear_smart_home_window(self):
        with self._window_lock:
            self._smart_home_window = None

    def open_smart_home(self):
        """Focus an existing simulator or create it as a separate native window."""
        with self._window_lock:
            existing = self._smart_home_window
            if existing is not None and not existing.events.closed.is_set():
                try:
                    existing.restore()
                    existing.show()
                    try:
                        existing.evaluate_js(
                            "window.hachiSmartHomeBegin && window.hachiSmartHomeBegin()"
                        )
                    except Exception:
                        # Focusing the already-open window is still useful if its
                        # page has not finished registering the animation hook.
                        pass
                    return {"opened": True, "reused": True}
                except Exception:
                    self._smart_home_window = None

            simulator = webview.create_window(
                title="Hachi — Smart Home Simulation",
                url=f"http://127.0.0.1:{FLASK_PORT}/smart-home?auto=1",
                width=1160,
                height=820,
                min_size=(820, 620),
                background_color="#f5f1e8",
                text_select=True,
            )
            if simulator is None:
                return {"opened": False, "error": "Could not create the simulator window."}
            simulator.events.closed += self._clear_smart_home_window
            self._smart_home_window = simulator
            return {"opened": True, "reused": False}


def run_flask():
    """Run Flask server in background thread. Errors are logged but won't crash the main thread."""
    try:
        logging.info("Starting Flask backend server...")
        app.run(
            host='127.0.0.1',
            port=FLASK_PORT,
            debug=False,
            use_reloader=False,
            threaded=True
        )
    except Exception as e:
        logging.error(f"Flask startup failed: {e}")
        print(f"❌ Flask error: {e}")


def main():
    """Main application entry point"""
    print("\n" + "="*60)
    print("  HACHI - Agentic AI Voice Assistant (Desktop App)")
    print("="*60)
    print("🎤 Initializing agent engine & SQLite memory...")

    # Initialize DB once at startup (not on every DB call)
    init_db()
    start_reminder_scheduler()

    # Browser voice mode has its own microphone path. Keep the old always-on
    # wake-word listener opt-in so it cannot contend for the microphone.
    start_tts_janitor()
    if _wakeword_is_enabled():
        start_wakeword_listener()
    else:
        logging.info("Wake-word listener is disabled by config.")

    print("🌐 Opening native desktop application window...")
    print("\nMake sure Ollama is running! (http://localhost:11434)")
    print("Close the window or press Ctrl+C to exit.\n")

    # Start Flask in background daemon thread
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()

    # Poll until Flask is ready instead of blindly sleeping
    logging.info("Waiting for Flask to be ready...")
    if not _wait_for_flask():
        logging.error("Flask did not start within timeout. Check hachi.log for details.")
        print("❌ Flask did not start in time. See hachi.log for details.")
        # Keep main thread alive so the user can see the error
        flask_thread.join()
        return

    logging.info("Flask is ready. Opening WebView window.")

    # Create and show native desktop window
    # storage_path: persist Edge WebView2 profile (mic permission, cookies)
    _storage = os.path.join(os.path.dirname(__file__), ".webview_profile")
    os.makedirs(_storage, exist_ok=True)
    try:
        desktop_api = DesktopApi()
        webview.create_window(
            title='Hachi — Agentic Voice Assistant',
            url=f'http://127.0.0.1:{FLASK_PORT}',
            width=1240,
            height=820,
            min_size=(700, 500),
            background_color='#0f172a',
            js_api=desktop_api
        )
        webview.start(
            debug=False,
            private_mode=False,     # allow Edge WebView2 to save mic permission
            storage_path=_storage,  # persistent profile dir
        )
    except Exception as e:
        logging.error(f"Error starting desktop window: {e}")
        print(f"❌ Desktop Window Error: {e}")
        print(f"Falling back to running Flask web server on http://127.0.0.1:{FLASK_PORT}")
        # Open the web UI in the default browser so the user isn't left staring at a dead terminal
        try:
            import webbrowser
            webbrowser.open(f"http://127.0.0.1:{FLASK_PORT}")
        except Exception as we:
            logging.error(f"Could not open browser: {we}")
        # Keep process alive so the user can use the web interface
        flask_thread.join()


if __name__ == '__main__':
    main()
