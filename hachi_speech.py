import os
import asyncio
import tempfile
import subprocess
import threading
import json
import logging
import re
import speech_recognition as sr

try:
    import edge_tts
    HAS_EDGE_TTS = True
except ImportError:
    HAS_EDGE_TTS = False

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.json")
DEFAULT_TAGALOG_VOICE = "fil-PH-AngeloNeural"
DEFAULT_ENGLISH_VOICE = "en-US-AvaNeural"

if os.path.exists(_CONFIG_PATH):
    try:
        with open(_CONFIG_PATH, "r", encoding="utf-8") as _f:
            _cfg = json.load(_f)
            DEFAULT_TAGALOG_VOICE = _cfg.get("tagalog_voice", DEFAULT_TAGALOG_VOICE)
            DEFAULT_ENGLISH_VOICE = _cfg.get("english_voice", DEFAULT_ENGLISH_VOICE)
    except Exception:
        pass

# Locks
_mic_lock = threading.Lock()
speech_lock = threading.Lock()

TAGALOG_WORDS = {
    "ako", "ikaw", "opo", "kasi", "naman", "salamat", "kamusta",
    "ano", "bakit", "sige", "talaga", "nga", "hindi", "oo",
    "paalam", "po", "yung", "yun", "ba", "na", "si", "ang"
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def clean_speech_text(text: str) -> str:
    """Strip markdown, think-blocks, code fences, and extra whitespace before TTS."""
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    # Remove code fences
    text = re.sub(r"```[\s\S]*?```", "", text)
    text = re.sub(r"`[^`]+`", "", text)
    # Remove markdown formatting chars
    text = re.sub(r"[*#_~|>]", "", text)
    # Remove leading list characters (-, *, 1.)
    text = re.sub(r"^\s*[-*•]\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\s*\d+\.\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


async def _generate_edge_tts_file(text: str, voice: str, out_path: str):
    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(out_path)


def _play_mp3_wmp(path: str):
    """
    Play an MP3 via WMPlayer COM object in PowerShell.
    Blocks until playback finishes (or 35 s timeout).
    """
    safe = path.replace("\\", "/")
    ps = (
        f"$m = New-Object -ComObject WMPlayer.OCX.7; "
        f"$m.URL = '{safe}'; "
        f"$m.controls.play(); "
        f"$i = 0; "
        f"while ($m.playState -ne 1 -and $i -lt 300) "
        f"{{ Start-Sleep -Milliseconds 100; $i++ }}; "
        f"$m.controls.stop()"
    )
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-c", ps],
            timeout=35,
            capture_output=True,
        )
    except subprocess.TimeoutExpired:
        logging.warning("WMPlayer playback timed out (35 s).")
    except Exception as e:
        logging.error(f"WMPlayer error: {e}")


def _speak_sapi(text: str):
    """
    Fallback TTS using Windows built-in SAPI via PowerShell.
    Works 100% offline on any Windows 10/11 machine.
    """
    safe = text.replace("'", "''")[:500]   # escape single-quotes for PS
    ps = (
        f"Add-Type -AssemblyName System.speech; "
        f"$t = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
        f"$t.Rate = 1; "
        f"$t.Speak('{safe}')"
    )
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-c", ps],
            timeout=30,
            capture_output=True,
        )
    except subprocess.TimeoutExpired:
        logging.warning("SAPI TTS timed out.")
    except Exception as e:
        logging.error(f"SAPI error: {e}")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def speak(text: str):
    """
    Synthesize speech and play it.
    Always BLOCKS until audio finishes — do NOT call from the main Flask thread
    when you want to keep the response non-blocking (use threading.Thread instead).
    For voice-mode endpoints, call directly so the HTTP response is not sent
    until speaking is done.
    """
    with speech_lock:
        clean = clean_speech_text(text)
        if not clean:
            return

        logging.info(f"TTS: {clean[:80]}…")

        # --- Primary: edge-tts (neural voices, requires internet) ---
        if HAS_EDGE_TTS:
            try:
                tmp = os.path.join(
                    tempfile.gettempdir(),
                    f"hachi_{os.getpid()}_{threading.get_ident()}.mp3",
                )
                lower_words = set(clean.lower().split())
                voice = (
                    DEFAULT_TAGALOG_VOICE
                    if lower_words & TAGALOG_WORDS
                    else DEFAULT_ENGLISH_VOICE
                )

                # Create a fresh event loop — safe to call from any thread
                loop = asyncio.new_event_loop()
                try:
                    loop.run_until_complete(
                        _generate_edge_tts_file(clean, voice, tmp)
                    )
                finally:
                    loop.close()

                if os.path.exists(tmp) and os.path.getsize(tmp) > 500:
                    _play_mp3_wmp(tmp)
                    try:
                        os.remove(tmp)
                    except OSError:
                        pass
                    return
            except Exception as e:
                logging.warning(f"edge-tts failed ({e}), using SAPI fallback.")

        # --- Fallback: Windows SAPI (offline, always available) ---
        _speak_sapi(clean)


def listen_voice_input() -> str:
    """
    Listen to the microphone and return the recognized text (may be empty).

    Uses _mic_lock with a BLOCKING acquire (timeout=15 s) so this function
    properly waits if the wakeword listener is currently using the mic,
    rather than returning '' immediately.
    """
    logging.info("listen_voice_input: attempting to acquire mic lock…")
    acquired = _mic_lock.acquire(timeout=15)
    if not acquired:
        logging.warning("listen_voice_input: Could NOT acquire mic lock within 15 s — mic is busy with wakeword listener.")
        return ""

    logging.info("listen_voice_input: mic lock acquired.")
    try:
        r = sr.Recognizer()
        r.dynamic_energy_threshold = True
        r.energy_threshold = 300        # More sensitive (was 400)
        r.pause_threshold = 1.2         # Wait longer for user to finish speaking
        r.non_speaking_duration = 0.6   # How long of silence before cutting off

        with sr.Microphone() as source:
            logging.info("listen_voice_input: adjusting for ambient noise (0.8 s)…")
            r.adjust_for_ambient_noise(source, duration=0.8)
            logging.info(f"listen_voice_input: energy threshold after calibration = {r.energy_threshold:.1f}. Listening (timeout=10 s)…")
            try:
                audio = r.listen(source, timeout=10, phrase_time_limit=15)
                logging.info("listen_voice_input: audio captured, sending to STT…")
            except sr.WaitTimeoutError:
                logging.info("listen_voice_input: no speech detected within 10 s timeout.")
                return ""

        # Try Tagalog/Filipino first, fall back to English
        for lang in ("fil-PH", "en-US"):
            try:
                text = r.recognize_google(audio, language=lang)
                if text:
                    logging.info(f"listen_voice_input: recognized ({lang}): '{text}'")
                    return text
            except sr.UnknownValueError:
                logging.info(f"listen_voice_input: speech not understood in {lang}.")
            except sr.RequestError as e:
                logging.error(f"listen_voice_input: Google STT request error ({lang}): {e}")

        logging.info("listen_voice_input: speech not understood in any language.")
        return ""

    except Exception as e:
        logging.error(f"listen_voice_input: unexpected error: {e}")
        return ""
    finally:
        _mic_lock.release()
        logging.info("listen_voice_input: mic lock released.")


def listen_for_wakeword() -> bool:
    """
    Quick non-blocking listen for 'Hey Hachi'.
    Skips expensive ambient noise adjustment on every loop to keep PyAudio responsive
    and prevent audio driver contention when opening voice mode.
    """
    acquired = _mic_lock.acquire(blocking=False)
    if not acquired:
        return False

    try:
        r = sr.Recognizer()
        r.energy_threshold = 350
        r.pause_threshold = 0.5

        with sr.Microphone() as source:
            try:
                audio = r.listen(source, timeout=1.2, phrase_time_limit=1.8)
            except sr.WaitTimeoutError:
                return False

        # Check raw frame count / silence before calling network API
        raw_data = audio.get_raw_data()
        if not raw_data or len(raw_data) < 800:
            return False

        text = r.recognize_google(audio, language="en-US").lower()
        logging.info(f"Wakeword check: '{text}'")
        return "hachi" in text or "hey hachi" in text

    except Exception:
        return False
    finally:
        _mic_lock.release()

