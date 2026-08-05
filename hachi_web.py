import os
import time
import logging
import threading
from flask import Flask, render_template, request, jsonify
from hachi_agent import process_agent_request
from hachi_speech import speak, listen_voice_input

app = Flask(__name__)
FLASK_PORT = 5000

# ---------------------------------------------------------------------------
# Wakeword state
# ---------------------------------------------------------------------------
_voice_mode_active = threading.Event()   # set when overlay is open
_wakeword_detected = threading.Event()   # set when "Hey Hachi" heard
_wakeword_started = False


def _wakeword_loop():
    """
    Background thread: continuously polls the mic for 'Hey Hachi'.
    Automatically pauses when the voice overlay is open (_voice_mode_active).
    Uses non-blocking mic acquire so it never fights the main listener.
    """
    from hachi_speech import listen_for_wakeword
    logging.info("Wakeword listener thread started.")
    while True:
        try:
            if _voice_mode_active.is_set():
                time.sleep(0.5)
                continue
            if listen_for_wakeword():
                logging.info("Wake word 'Hachi' detected!")
                _wakeword_detected.set()
            time.sleep(0.3)   # short breath between poll cycles
        except Exception as e:
            logging.debug(f"Wakeword loop error: {e}")
            time.sleep(1)


def start_wakeword_listener():
    global _wakeword_started
    if not _wakeword_started:
        _wakeword_started = True
        t = threading.Thread(
            target=_wakeword_loop, daemon=True, name="WakewordListener"
        )
        t.start()


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/chat", methods=["POST"])
def api_chat():
    """Text chat: LLM response with async TTS (does NOT block HTTP response)."""
    try:
        data = request.json or {}
        user_msg = data.get("message", "").strip()
        current_mode = data.get("mode", "default")
        if not user_msg:
            return jsonify({"response": "", "tools": []})

        agent_response, executed_tools = process_agent_request(user_msg, current_mode)
        # Fire-and-forget TTS for text chat mode
        threading.Thread(target=speak, args=(agent_response,), daemon=True).start()
        return jsonify({"response": agent_response, "tools": executed_tools})
    except Exception as e:
        logging.error(f"api_chat error: {e}")
        return jsonify({"response": "Something went wrong.", "tools": []}), 500


@app.route("/api/voice_listen_only", methods=["POST"])
def api_voice_listen_only():
    """
    Voice step 1: STT only.
    Blocks until the user speaks (up to ~9 s) and returns recognized text.
    Frontend shows 'Listening…' while this is pending.
    """
    try:
        user_text = listen_voice_input()
        return jsonify({"user_text": user_text or ""})
    except Exception as e:
        logging.error(f"voice_listen_only error: {e}")
        return jsonify({"user_text": "", "error": str(e)}), 500


@app.route("/api/voice_chat", methods=["POST"])
def api_voice_chat():
    """
    Voice step 2: LLM + synchronous TTS.
    Blocks until Ollama finishes AND audio playback finishes,
    then returns. Frontend shows 'Thinking…' while this is pending,
    and the voice already played by the time the response arrives.
    """
    try:
        data = request.json or {}
        user_text = data.get("user_text", "").strip()
        current_mode = data.get("mode", "default")
        if not user_text:
            return jsonify({"response": "", "tools": []})

        agent_response, executed_tools = process_agent_request(user_text, current_mode)
        speak(agent_response)   # SYNCHRONOUS — blocks until audio done
        return jsonify({"response": agent_response, "tools": executed_tools})
    except Exception as e:
        logging.error(f"voice_chat error: {e}")
        return jsonify({"response": "", "tools": [], "error": str(e)}), 500


@app.route("/api/wakeword_status", methods=["GET"])
def api_wakeword_status():
    """Polling endpoint: returns {detected: true} once if wakeword was heard."""
    if _wakeword_detected.is_set():
        _wakeword_detected.clear()
        return jsonify({"detected": True})
    return jsonify({"detected": False})


@app.route("/api/voice_mode", methods=["POST"])
def api_voice_mode():
    """Let the frontend tell the backend when the voice overlay is open/closed."""
    data = request.json or {}
    if data.get("active", False):
        _voice_mode_active.set()
    else:
        _voice_mode_active.clear()
    return jsonify({"ok": True})


if __name__ == "__main__":
    start_wakeword_listener()
    app.run(
        host="127.0.0.1",
        port=FLASK_PORT,
        debug=False,
        use_reloader=False,
        threaded=True,
    )
