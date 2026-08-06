import os
import time
import json
import logging
import threading
from flask import Flask, render_template, request, jsonify, Response, stream_with_context
from hachi_agent import process_agent_request, process_voice_request
from hachi_speech import speak, speak_quick, listen_voice_input, interrupt_speech

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
    Pauses when voice overlay is open (_voice_mode_active).
    Uses non-blocking mic acquire so it never fights the main listener.
    """
    from hachi_speech import listen_for_wakeword
    logging.info("Wakeword listener thread started.")
    time.sleep(3.0)   # Brief delay on startup so Flask/PyWebView start 100% cleanly
    while True:
        try:
            if _voice_mode_active.is_set():
                time.sleep(0.5)
                continue
            if listen_for_wakeword():
                logging.info("Wake word 'Hachi' detected!")
                _wakeword_detected.set()
            time.sleep(0.8)   # Breath between poll cycles to keep PyAudio driver clear
        except Exception as e:
            logging.debug(f"Wakeword loop error: {e}")
            time.sleep(1.5)



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
    """Text chat: LLM response with async TTS.
    Pass voice_mode=true to skip server TTS (browser handles it).
    """
    try:
        data = request.json or {}
        user_msg    = data.get("message", "").strip()
        current_mode = data.get("mode", "default")
        voice_mode   = data.get("voice_mode", False)  # True = browser owns TTS
        if not user_msg:
            return jsonify({"response": "", "tools": []})

        agent_response, executed_tools = process_agent_request(user_msg, current_mode)
        # Skip server TTS when browser is handling speech (avoids double audio)
        if not voice_mode:
            threading.Thread(target=speak, args=(agent_response,), daemon=True).start()
        return jsonify({"response": agent_response, "tools": executed_tools})
    except Exception as e:
        logging.error(f"api_chat error: {e}")
        return jsonify({"response": "Something went wrong.", "tools": []}), 500

@app.route("/api/stream_chat", methods=["POST"])
def api_stream_chat():
    """
    SSE streaming endpoint for voice mode.
    Streams LLM tokens as 'data: {json}\\n\\n' events.
    No server-side TTS — browser handles speaking.
    Frontend starts speaking the FIRST sentence while model is still generating.
    """
    data     = request.json or {}
    user_msg = data.get("message", "").strip()
    mode     = data.get("mode", "default")

    if not user_msg:
        return Response(
            "data: " + json.dumps({"done": True, "full": "", "tools": []}) + "\n\n",
            mimetype="text/event-stream"
        )

    def generate():
        try:
            from hachi_agent import process_agent_request_stream
            for event in process_agent_request_stream(user_msg, mode):
                yield "data: " + json.dumps(event) + "\n\n"
        except GeneratorExit:
            pass
        except Exception as e:
            logging.error(f"api_stream_chat error: {e}")
            yield "data: " + json.dumps({"done": True, "full": "Stream error.", "tools": [], "error": True}) + "\n\n"

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-store",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        }
    )


@app.route("/api/voice_listen_only", methods=["POST"])
def api_voice_listen_only():
    """
    Voice step 1 (server-side): STT only.
    Blocks until the user speaks (pause_threshold=1.5 s, phrase_limit=45 s).
    Frontend shows 'Listening…' while this is pending.
    """
    try:
        user_text = listen_voice_input()
        return jsonify({"user_text": user_text or ""})
    except Exception as e:
        logging.error(f"voice_listen_only error: {e}")
        return jsonify({"user_text": "", "error": str(e)}), 500


@app.route("/api/voice_request", methods=["POST"])
def api_voice_request():
    """
    Voice step 2: DeepSeek understands intent → Qwen executes tools → edge-tts speaks.
    Blocks until LLM response AND audio playback are both done, then returns.
    Frontend shows 'Thinking…' while pending; TTS has already played on return.
    """
    try:
        data         = request.json or {}
        user_text    = data.get("user_text", "").strip()
        current_mode = data.get("mode", "default")
        if not user_text:
            return jsonify({"response": "", "tools": []})

        # ── Instant acknowledgment (offline SAPI, ~200 ms) ─────────────────
        # User hears Hachi respond IMMEDIATELY while DeepSeek API is called.
        speak_quick(user_text)

        # ── DeepSeek intent → Qwen tools → edge-tts (2-5 s, runs after ack) ─
        agent_response, executed_tools = process_voice_request(user_text, current_mode)
        speak(agent_response)   # SYNCHRONOUS — blocks until TTS fully plays
        return jsonify({"response": agent_response, "tools": executed_tools})
    except Exception as e:
        logging.error(f"voice_request error: {e}")
        return jsonify({"response": "", "tools": [], "error": str(e)}), 500


@app.route("/api/interrupt_speech", methods=["POST"])
def api_interrupt_speech():
    """Immediately kill TTS playback (called by frontend stop button)."""
    try:
        interrupt_speech()
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


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


@app.route("/api/fetch_url", methods=["POST"])
def api_fetch_url():
    """
    Directly fetch a URL and return extracted text content.
    Allows the frontend to retrieve webpage content without going through the LLM.
    """
    try:
        from hachi_tools import fetch_url
        data = request.json or {}
        url = data.get("url", "").strip()
        if not url:
            return jsonify({"content": "", "error": "No URL provided"}), 400
        content = fetch_url(url)
        return jsonify({"content": content})
    except Exception as e:
        logging.error(f"api_fetch_url error: {e}")
        return jsonify({"content": "", "error": str(e)}), 500


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
