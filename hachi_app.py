#!/usr/bin/env python3
"""
Hachi - Agentic AI Voice Assistant
Desktop Application Launcher using PyWebView
"""
import os
# Disable autoplay restrictions for Edge WebView2 on Windows
os.environ["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"] = "--autoplay-policy=no-user-gesture-required"
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
from hachi_db import init_db


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

    # Start background wakeword listener ('Hey Hachi')
    start_wakeword_listener()

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
    try:
        webview.create_window(
            title='Hachi — Agentic Voice Assistant',
            url=f'http://127.0.0.1:{FLASK_PORT}',
            width=1240,
            height=820,
            min_size=(700, 500),
            background_color='#0f172a',
            js_api=None
        )
        webview.start(debug=False)
    except Exception as e:
        logging.error(f"Error starting desktop window: {e}")
        print(f"❌ Desktop Window Error: {e}")
        print(f"Falling back to running Flask web server on http://127.0.0.1:{FLASK_PORT}")
        # Keep process alive so the user can use the web interface
        flask_thread.join()


if __name__ == '__main__':
    main()
