import os
import time
import json
import uuid
import logging
import threading
import tempfile
from flask import Flask, render_template, request, jsonify, Response, stream_with_context, send_file
from hachi_agent import process_agent_request
from hachi_speech import speak, interrupt_speech, generate_tts_audio

app = Flask(__name__)
FLASK_PORT = 5000

# ---------------------------------------------------------------------------
# TTS audio cache for parallel voice pipeline
# ---------------------------------------------------------------------------
_tts_cache = {}          # {audio_id: {"path": str, "created": float}}
_tts_cache_lock = threading.Lock()

def _cleanup_tts_cache(max_age=60):
    """Remove TTS audio files older than max_age seconds."""
    now = time.time()
    with _tts_cache_lock:
        expired = [k for k, v in _tts_cache.items() if now - v["created"] > max_age]
        for k in expired:
            try:
                os.remove(_tts_cache[k]["path"])
            except OSError:
                pass
            del _tts_cache[k]

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
    SSE streaming endpoint for text chat mode.
    Streams LLM tokens as 'data: {json}\\n\\n' events.
    No server-side TTS — browser handles speaking.
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


@app.route("/api/voice_stream", methods=["POST"])
def api_voice_stream():
    """
    Parallel voice pipeline: streams LLM tokens + pre-generated TTS audio.
    
    SSE event types:
      {"type":"token", "text":"..."} — individual LLM token for display
      {"type":"audio", "id":"uuid", "sentence":"..."} — TTS audio ready to play
      {"type":"done", "full":"...", "tools":[...]} — stream complete
    
    A background TTS worker runs in parallel with LLM generation.
    """
    data     = request.json or {}
    user_msg = data.get("message", "").strip()
    mode     = data.get("mode", "default")

    if not user_msg:
        return Response(
            "data: " + json.dumps({"type": "done", "full": "", "tools": []}) + "\n\n",
            mimetype="text/event-stream"
        )

    def generate():
        _cleanup_tts_cache()

        # Shared state between main thread and TTS worker
        sentence_queue = []        # sentences waiting for TTS
        audio_events = []          # completed audio events ready to send
        tts_done = threading.Event()
        llm_done = threading.Event()
        queue_lock = threading.Lock()
        audio_lock = threading.Lock()

        def tts_worker():
            """Background thread: picks sentences from queue, generates TTS audio."""
            while True:
                sentence = None
                with queue_lock:
                    if sentence_queue:
                        sentence = sentence_queue.pop(0)

                if sentence:
                    audio_path = generate_tts_audio(sentence)
                    if audio_path:
                        audio_id = str(uuid.uuid4())[:8]
                        with _tts_cache_lock:
                            _tts_cache[audio_id] = {"path": audio_path, "created": time.time()}
                        with audio_lock:
                            audio_events.append({"type": "audio", "id": audio_id, "sentence": sentence})
                elif llm_done.is_set():
                    # No more sentences and LLM is done
                    break
                else:
                    time.sleep(0.02)  # Brief sleep while waiting for sentences
            tts_done.set()

        # Start TTS worker thread
        worker = threading.Thread(target=tts_worker, daemon=True)
        worker.start()

        try:
            from hachi_agent import process_agent_request_stream

            token_buffer = ""
            full_text = ""
            tools_list = []

            for event in process_agent_request_stream(user_msg, mode):
                # Yield token events immediately
                if not event.get("done") and event.get("token"):
                    token = event["token"]
                    token_buffer += token
                    yield "data: " + json.dumps({"type": "token", "text": token}) + "\n\n"

                    # Eager sentence detection: match text ending with . ! ? or \n (no space needed)
                    import re
                    m = re.search(r'([^.!?\n]+[.!?\n])', token_buffer)
                    if m:
                        sentence = m.group(1).strip()
                        # Avoid splitting short abbreviations like "Mr.", "U.S.", or decimals like "3.14"
                        if len(sentence) > 3 and not (sentence[-1] == '.' and sentence[:-1].isdigit()):
                            with queue_lock:
                                sentence_queue.append(sentence)
                            token_buffer = token_buffer[m.end():]

                if event.get("done"):
                    full_text = event.get("full", "")
                    tools_list = event.get("tools", [])
                    # Queue remaining buffer as final sentence
                    if token_buffer.strip() and len(token_buffer.strip()) > 3:
                        with queue_lock:
                            sentence_queue.append(token_buffer.strip())
                    break

                # Flush any ready audio events immediately during token streaming
                with audio_lock:
                    for ae in audio_events:
                        yield "data: " + json.dumps(ae) + "\n\n"
                    audio_events.clear()

            # Signal LLM is done
            llm_done.set()

            # Wait for TTS worker to finish remaining sentences, yielding audio events as they become ready
            start_wait = time.time()
            while not tts_done.is_set() and (time.time() - start_wait < 15):
                with audio_lock:
                    events_to_send = list(audio_events)
                    audio_events.clear()
                for ae in events_to_send:
                    yield "data: " + json.dumps(ae) + "\n\n"
                time.sleep(0.05)

            # One final flush of any remaining audio events
            with audio_lock:
                events_to_send = list(audio_events)
                audio_events.clear()
            for ae in events_to_send:
                yield "data: " + json.dumps(ae) + "\n\n"

            yield "data: " + json.dumps({"type": "done", "full": full_text, "tools": tools_list}) + "\n\n"

        except GeneratorExit:
            llm_done.set()
        except Exception as e:
            llm_done.set()
            logging.error(f"api_voice_stream error: {e}")
            yield "data: " + json.dumps({"type": "done", "full": "Stream error.", "tools": [], "error": True}) + "\n\n"

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-store",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        }
    )


@app.route("/api/tts_audio/<audio_id>", methods=["GET"])
def api_tts_audio(audio_id):
    """Serve a pre-generated TTS audio file by ID."""
    with _tts_cache_lock:
        entry = _tts_cache.get(audio_id)
    if not entry or not os.path.exists(entry["path"]):
        return jsonify({"error": "Audio not found"}), 404
    return send_file(entry["path"], mimetype="audio/mpeg")


@app.route("/api/interrupt_speech", methods=["POST"])
def api_interrupt_speech():
    """Immediately kill TTS playback (called by frontend stop button)."""
    try:
        interrupt_speech()
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


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
