import os
import time
import re
import json
import uuid
import logging
import threading
import tempfile
from queue import Queue
from flask import Flask, render_template, request, jsonify, Response, stream_with_context, send_file
from hachi_agent import process_agent_request, get_llm_debug
from hachi_speech import speak, speak_quick, interrupt_speech, generate_tts_audio

app = Flask(__name__)
FLASK_PORT = 5000

# Abbreviations that should NOT be treated as a sentence boundary in TTS
_ABBREVIATIONS = {
    "prof", "dr", "mr", "mrs", "ms", "sr", "jr", "st", "approx",
    "incl", "vs", "etc", "dept", "univ", "est", "govt", "corp",
    "inc", "ltd", "co", "min", "max", "temp", "vol", "pg", "fig",
    "jan", "feb", "mar", "apr", "jun", "jul", "aug", "sep",
    "oct", "nov", "dec", "a.m", "p.m", "u.s", "u.k", "e.g", "i.e",
}


def _is_false_boundary(buffer: str, abs_end: int, segment: str) -> bool:
    """True if the matched punctuation is NOT a real sentence boundary.
    Handles decimals ("3.14", "v1.2.3") and abbreviations ("Dr.", "e.g.")."""
    # Decimal point: period immediately followed by a digit
    if abs_end < len(buffer) and buffer[abs_end].isdigit():
        return True
    # Abbreviation word ("Dr.", "Prof.", "e.g", "i.e")
    last_word = re.split(r'\s', segment.rstrip('.!?\n'))[-1].lower().rstrip('.')
    if last_word in _ABBREVIATIONS:
        return True
    # "e.g." / "i.e." style: single letter + period + letter + period
    if re.search(r'\b[a-z]\.$', segment) and abs_end < len(buffer) and re.match(r'[a-z]\.', buffer[abs_end:]):
        return True
    return False


def _pop_sentence(token_buffer: str):
    """Pop the first complete sentence from the buffer, skipping abbreviations and
    decimal numbers. Returns (sentence_or_None, remaining_buffer)."""
    search_pos = 0
    while True:
        m = re.search(r'([^.!?\n]+[.!?\n])', token_buffer[search_pos:])
        if not m:
            return None, token_buffer
        abs_end = search_pos + m.end()
        # Inspect the FULL segment from the buffer start so the prefix is kept.
        # "Hello Dr. Smith." → last word "Smith" (not an abbreviation) → whole thing
        segment = token_buffer[:abs_end].strip()
        if len(segment) <= 1:
            # Just a lone punctuation mark — consume and keep scanning
            token_buffer = token_buffer[abs_end:]
            search_pos = 0
            continue
        if _is_false_boundary(token_buffer, abs_end, segment):
            # Skip past this punctuation, keeping the prefix for the next match
            search_pos = abs_end
            continue
        return segment, token_buffer[abs_end:]


# ---------------------------------------------------------------------------
# Single speak worker — drops stale queued speech so rapid messages never
# play old replies after the current one (fixes thread backlog).
# ---------------------------------------------------------------------------
_speak_cond = threading.Condition()
_latest_speak = None
_speak_worker_started = False


def _speak_worker():
    global _latest_speak
    while True:
        with _speak_cond:
            while _latest_speak is None:
                _speak_cond.wait()
            text = _latest_speak
            _latest_speak = None
        try:
            speak(text)
        except Exception as e:
            logging.error(f"speak worker error: {e}")


def _ensure_speak_worker():
    global _speak_worker_started
    # Guard with the cond lock so two concurrent api_chat calls can't both spawn a
    # worker (which would double-speak).
    with _speak_cond:
        if not _speak_worker_started:
            _speak_worker_started = True
            threading.Thread(target=_speak_worker, daemon=True, name="SpeakWorker").start()


def _request_speak(text: str):
    """Queue speech; only the latest pending text is spoken."""
    if not text:
        return
    _ensure_speak_worker()
    with _speak_cond:
        global _latest_speak
        _latest_speak = text
        _speak_cond.notify()

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


_tts_janitor_started = False


def _tts_janitor():
    """Background thread: periodically purge stale TTS cache + orphaned temp files
    (covers interrupt/crash leaks that _cleanup_tts_cache misses)."""
    while True:
        time.sleep(30)
        try:
            _cleanup_tts_cache()
            tmpdir = tempfile.gettempdir()
            cutoff = time.time() - 60
            # Don't delete files still referenced by the active cache (a slow client
            # on a long reply could 404 on audio the janitor already removed).
            with _tts_cache_lock:
                cached_paths = {v.get("path") for v in _tts_cache.values()}
            for f in os.listdir(tmpdir):
                if f.startswith("hachi_") and f.endswith(".mp3"):
                    p = os.path.join(tmpdir, f)
                    if p in cached_paths:
                        continue
                    try:
                        if os.path.getmtime(p) < cutoff:
                            os.remove(p)
                    except OSError:
                        pass
        except Exception as e:
            logging.debug(f"tts janitor error: {e}")


def start_tts_janitor():
    global _tts_janitor_started
    if not _tts_janitor_started:
        _tts_janitor_started = True
        threading.Thread(target=_tts_janitor, daemon=True, name="TTSJanitor").start()

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
    time.sleep(1.0)   # Brief delay on startup so Flask/PyWebView start cleanly
    while True:
        try:
            if _voice_mode_active.is_set():
                time.sleep(0.5)
                continue
            if listen_for_wakeword():
                logging.info("Wake word 'Hachi' detected!")
                _wakeword_detected.set()
            time.sleep(0.3)   # Breath between poll cycles to keep PyAudio driver clear
        except Exception as e:
            logging.debug(f"Wakeword loop error: {e}")
            time.sleep(1.5)



def start_wakeword_listener():
    global _wakeword_started
    if not _wakeword_started:
        _wakeword_started = True
        start_tts_janitor()
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
            return jsonify({"response": "", "tools": [], "engine": "none", "pomo": None})

        agent_response, executed_tools, engine, pomo = process_agent_request(user_msg, current_mode)
        # Skip server TTS when browser is handling speech (avoids double audio)
        if not voice_mode:
            _request_speak(agent_response)
        return jsonify({"response": agent_response, "tools": executed_tools, "engine": engine, "pomo": pomo})
    except Exception as e:
        logging.error(f"api_chat error: {e}")
        return jsonify({"response": "Something went wrong.", "tools": [], "engine": "none", "pomo": None}), 500


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
            "data: " + json.dumps({"done": True, "full": "", "tools": [], "engine": "none", "pomo": None}) + "\n\n",
            mimetype="text/event-stream"
        )

    def generate():
        try:
            from hachi_agent import process_agent_request_stream
            for event in process_agent_request_stream(user_msg, mode, voice_mode=False):
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
            "data: " + json.dumps({"type": "done", "full": "", "tools": [], "engine": "none", "pomo": None}) + "\n\n",
            mimetype="text/event-stream"
        )

    def generate():
        _cleanup_tts_cache()

        # Fix 4: instant spoken acknowledgment ("Sige, sandali lang.") while the
        # LLM thinks — the user hears a reply within ~200ms instead of silence.
        try:
            threading.Thread(target=speak_quick, args=(user_msg,), daemon=True).start()
        except Exception:
            pass

        # Shared state between main thread and TTS worker
        sentence_queue = Queue()   # blocking queue (worker never busy-waits)
        audio_events = []          # completed audio events ready to send
        tts_done = threading.Event()
        llm_done = threading.Event()
        audio_lock = threading.Lock()

        def tts_worker():
            """Background thread: blocks on the queue, generates TTS audio per sentence."""
            while True:
                sentence = sentence_queue.get()
                if sentence is None:   # sentinel: LLM finished
                    break
                audio_path = generate_tts_audio(sentence)
                if audio_path:
                    audio_id = str(uuid.uuid4())[:8]
                    with _tts_cache_lock:
                        _tts_cache[audio_id] = {"path": audio_path, "created": time.time()}
                    with audio_lock:
                        audio_events.append({"type": "audio", "id": audio_id, "sentence": sentence})
            tts_done.set()

        # Start TTS worker thread
        worker = threading.Thread(target=tts_worker, daemon=True)
        worker.start()

        def flush_audio():
            """Snapshot audio events under lock, return them for yielding OUTSIDE the lock."""
            events_to_send = []
            with audio_lock:
                if audio_events:
                    events_to_send = list(audio_events)
                    audio_events.clear()
            return events_to_send

        try:
            from hachi_agent import process_agent_request_stream

            token_buffer = ""
            full_text = ""
            tools_list = []
            engine = "qwen"
            pomo = None

            for event in process_agent_request_stream(user_msg, mode, voice_mode=True):
                # Yield token events immediately
                if not event.get("done") and event.get("token"):
                    token = event["token"]
                    token_buffer += token
                    yield "data: " + json.dumps({"type": "token", "text": token}) + "\n\n"

                    # Eager sentence detection (handles abbreviations, advances past rejects)
                    sentence, token_buffer = _pop_sentence(token_buffer)
                    if not sentence and len(token_buffer.split()) >= 15:
                        # Fix 6: provisional flush — emit the buffered words even
                        # without a period so the FIRST audio starts sooner.
                        sentence = token_buffer.strip()
                        token_buffer = ""
                    if sentence:
                        sentence_queue.put(sentence)

                if event.get("done"):
                    full_text = event.get("full", "")
                    tools_list = event.get("tools", [])
                    engine = event.get("engine", "qwen")
                    pomo = event.get("pomo")
                    # Queue remaining buffer as final sentence
                    if token_buffer.strip() and len(token_buffer.strip()) > 3:
                        sentence_queue.put(token_buffer.strip())
                    token_buffer = ""
                    break

                # Flush any ready audio events immediately during token streaming
                for ae in flush_audio():
                    yield "data: " + json.dumps(ae) + "\n\n"

            # Signal LLM is done → worker drains remaining sentences, then exits
            llm_done.set()
            sentence_queue.put(None)

            # Fix 5: don't gate `done` behind ALL tail-sentence TTS. Give the worker
            # a bounded window to flush remaining audio, then end the turn. generate_tts_audio
            # has its own 10s per-sentence cap, so tts_done always sets within budget.
            tail_deadline = time.time() + 5.0
            while not tts_done.is_set() and time.time() < tail_deadline:
                for ae in flush_audio():
                    yield "data: " + json.dumps(ae) + "\n\n"
                time.sleep(0.05)

            # One final flush of any remaining audio events
            for ae in flush_audio():
                yield "data: " + json.dumps(ae) + "\n\n"

            yield "data: " + json.dumps({"type": "done", "full": full_text, "tools": tools_list, "engine": engine, "pomo": pomo}) + "\n\n"

        except GeneratorExit:
            llm_done.set()
            sentence_queue.put(None)
        except Exception as e:
            llm_done.set()
            sentence_queue.put(None)
            logging.error(f"api_voice_stream error: {e}")
            yield "data: " + json.dumps({"type": "done", "full": "Stream error.", "tools": [], "error": True, "engine": "none", "pomo": None}) + "\n\n"

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
    from hachi_speech import voice_mode_active
    data = request.json or {}
    if data.get("active", False):
        _voice_mode_active.set()
        voice_mode_active.set()
        # Fix 7: settle so an in-flight pyaudio wakeword listen finishes and
        # releases the device before the browser mic grabs it.
        time.sleep(0.3)
    else:
        _voice_mode_active.clear()
        voice_mode_active.clear()
    return jsonify({"ok": True})


@app.route("/api/mic_status", methods=["GET"])
def api_mic_status():
    """Report whether a microphone is detected and which one. Lets the user know
    if the program can see their mic (fixes 'it can't hear my mic' confusion)."""
    try:
        import pyaudio
        pa = pyaudio.PyAudio()
        try:
            mics = []
            for i in range(pa.get_device_count()):
                info = pa.get_device_info_by_index(i)
                if info.get("maxInputChannels", 0) > 0:
                    mics.append({
                        "index": i,
                        "name": info.get("name", f"Microphone {i}"),
                        "channels": info.get("maxInputChannels", 0),
                        "sample_rate": info.get("defaultSampleRate", 0),
                    })
            return jsonify({"ok": True, "mics": mics, "detected": len(mics) > 0})
        finally:
            pa.terminate()
    except Exception as e:
        logging.warning(f"mic_status error: {e}")
        return jsonify({"ok": False, "mics": [], "detected": False, "error": str(e)})


@app.route("/api/llm_debug", methods=["GET"])
def api_llm_debug():
    """Return recent LLM raw outputs and parsed tool_calls for debugging."""
    try:
        limit = int(request.args.get("limit", 50))
    except Exception:
        limit = 50
    try:
        entries = get_llm_debug(limit=limit)
        return jsonify({"ok": True, "entries": entries})
    except Exception as e:
        logging.error(f"api_llm_debug error: {e}")
        return jsonify({"ok": False, "error": str(e)}), 500


if __name__ == "__main__":
    start_wakeword_listener()
    app.run(
        host="127.0.0.1",
        port=FLASK_PORT,
        debug=False,
        use_reloader=False,
        threaded=True,
    )
