#!/usr/bin/env python3
"""
Hachi - AI Voice Assistant
Desktop Application Launcher using PyWebView
"""
import webview
import threading
import time
import logging
from hachi_web import app

# Configure logging
logging.basicConfig(
    filename="hachi.log",
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)

def run_flask():
    """Run Flask server in background thread"""
    logging.info("Starting Flask server...")
    app.run(
        host='127.0.0.1',
        port=5000,
        debug=False,
        use_reloader=False,
        threaded=True
    )

def main():
    """Main application entry point"""
    print("\n" + "="*60)
    print("  HACHI - AI Voice Assistant (Desktop App)")
    print("="*60)
    print("🎤 Initializing voice assistant...")
    print("🌐 Opening desktop application window...")
    print("\nMake sure Ollama is running! (http://localhost:11434)")
    print("Close the window or press Ctrl+C to exit.\n")
    
    # Start Flask in background thread
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    
    # Give Flask time to start
    time.sleep(2)
    
    # Create and show native desktop window
    try:
        webview.create_window(
            title='Hachi — AI Voice Assistant',
            url='http://127.0.0.1:5000',
            width=1200,
            height=800,
            min_size=(600, 400),
            background_color='#12141c',
            js_api=None
        )
        webview.start(debug=False)
    except Exception as e:
        logging.error(f"Error starting application: {e}")
        print(f"❌ Error: {e}")

if __name__ == '__main__':
    main()
