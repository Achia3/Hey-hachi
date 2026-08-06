import os
import asyncio
import tempfile
import subprocess
import threading
import json
import logging
import re
import time
import random
import speech_recognition as sr
from typing import Optional

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

# ---------------------------------------------------------------------------
# Locks & shared state
# ---------------------------------------------------------------------------
_mic_lock    = threading.Lock()    # Exclusive microphone access
speech_lock  = threading.Lock()    # Exclusive TTS playback

# Interruptible TTS process reference
_tts_proc: Optional[subprocess.Popen] = None
_tts_proc_lock = threading.Lock()

# Ambient noise calibration cache (refresh every 30 s)
_noise_threshold:      float = 400.0
_noise_calibrated_at:  float = 0.0
_RECALIBRATE_SECS:     float = 30.0

# Words that can be spoken to stop Hachi mid-sentence
STOP_WORDS = {
    # English
    "stop", "quiet", "shh", "shhh", "pause", "cancel", "enough",
    "ok stop", "please stop", "be quiet", "shut up",
    # Tagalog / Filipino
    "tama", "tama na", "hinto", "tigil", "tumahimik",
    "sandali", "pakitigil", "sige na",
}

TAGALOG_WORDS = {
    "ako", "ikaw", "opo", "kasi", "naman", "salamat", "kamusta",
    "ano", "bakit", "sige", "talaga", "nga", "hindi", "oo",
    "paalam", "po", "yung", "yun", "ba", "na", "si", "ang",
    "mag", "mga", "sa", "ng", "ay", "ito", "iyan", "siya",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Short bilingual acknowledgments played INSTANTLY (offline SAPI) while DeepSeek thinks
_ACKS_EN = [
    "Hmm, let me think...",
    "Sure, one sec.",
    "Got it.",
    "Let me check that.",
    "On it.",
]
_ACKS_TL = [
    "Sige, sandali lang.",
    "Hmm, tignan ko.",
    "Oo sige, sandali.",
    "Konting sandali.",
    "Sige po.",
]


def clean_speech_text(text: str) -> str:
    """Strip markdown, think-blocks, and code blocks before TTS."""
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    text = re.sub(r"\[DO:[^\]]*\]", "", text)      # Remove action tags
    text = re.sub(r"```[\s\S]*?```", "", text)      # Remove code blocks
    text = re.sub(r"[*#_`~|>]", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def generate_tts_audio(text: str) -> Optional[str]:
    """
    Generate Edge TTS audio for text and return the temp file path.
    Returns None if generation fails. Caller is responsible for cleanup.
    Used by the /api/voice_stream endpoint for parallel TTS pipeline.
    """
    clean = clean_speech_text(text)
    if not clean:
        return None

    if not HAS_EDGE_TTS:
        return None

    try:
        voice = _pick_voice(clean)
        tmp = os.path.join(
            tempfile.gettempdir(),
            f"hachi_tts_{os.getpid()}_{threading.get_ident()}_{int(time.time()*1000)}.mp3",
        )
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(_generate_edge_tts_file(clean, voice, tmp))
        finally:
            loop.close()

        if os.path.exists(tmp) and os.path.getsize(tmp) > 500:
            return tmp
        return None
    except Exception as e:
        logging.warning(f"generate_tts_audio failed: {e}")
        return None


async def _generate_edge_tts_file(text: str, voice: str, out_path: str):
    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(out_path)


def _pick_voice(text: str) -> str:
    lower_words = set(text.lower().split())
    return DEFAULT_TAGALOG_VOICE if lower_words & TAGALOG_WORDS else DEFAULT_ENGLISH_VOICE


def _play_mp3_interruptible(path: str):
    """
    Play MP3 via WMPlayer COM using Popen (not run) so we can kill it.
    Simultaneously starts a background mic-listener for stop words.
    """
    global _tts_proc

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

    with _tts_proc_lock:
        _tts_proc = subprocess.Popen(
            ["powershell", "-NoProfile", "-NonInteractive", "-c", ps],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    try:
        _tts_proc.wait(timeout=40)
    except subprocess.TimeoutExpired:
        interrupt_speech()
    except Exception:
        pass

    with _tts_proc_lock:
        _tts_proc = None



def _speak_sapi(text: str):
    """Fallback: Windows SAPI — 100% offline, no extra dependencies."""
    safe = text.replace("'", "''")[:600]
    ps = (
        f"Add-Type -AssemblyName System.speech; "
        f"$t = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
        f"$t.Rate = 1; "
        f"$t.Speak('{safe}')"
    )
    try:
        proc = subprocess.Popen(
            ["powershell", "-NoProfile", "-NonInteractive", "-c", ps],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        with _tts_proc_lock:
            global _tts_proc
            _tts_proc = proc

        proc.wait(timeout=35)
    except subprocess.TimeoutExpired:
        interrupt_speech()
    except Exception as e:
        logging.error(f"SAPI error: {e}")
    finally:
        with _tts_proc_lock:
            _tts_proc = None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def interrupt_speech():
    """Kill current TTS immediately — callable from any thread."""
    global _tts_proc
    with _tts_proc_lock:
        if _tts_proc and _tts_proc.poll() is None:
            try:
                _tts_proc.kill()
                logging.info("TTS interrupted.")
            except Exception:
                pass
            _tts_proc = None


def speak_quick(user_text: str = ""):
    """
    Instant offline acknowledgment via Windows SAPI (~200 ms, no internet needed).
    Call this immediately after STT returns, BEFORE calling DeepSeek/tools,
    so the user hears Hachi respond right away instead of waiting 2-4 seconds.

    Detects whether user spoke Tagalog and picks a matching ack phrase.
    Uses speech_lock so it won't overlap with a concurrent speak() call.
    """
    with speech_lock:
        words = set(user_text.lower().split()) if user_text else set()
        is_tagalog = bool(words & TAGALOG_WORDS)
        phrase = random.choice(_ACKS_TL if is_tagalog else _ACKS_EN)

        safe = phrase.replace("'", "''")
        ps = (
            f"Add-Type -AssemblyName System.speech; "
            f"$t = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
            f"$t.Rate = 2; "     # Slightly faster rate for brief ack
            f"$t.Speak('{safe}')"
        )
        try:
            subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-c", ps],
                timeout=6,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            logging.info(f"speak_quick: '{phrase}'")
        except Exception as e:
            logging.debug(f"speak_quick error: {e}")


def speak(text: str):
    """
    Synthesize speech and play it.
    BLOCKS until audio finishes (or is interrupted via interrupt_speech()).
    """
    with speech_lock:
        clean = clean_speech_text(text)
        if not clean:
            return


        logging.info(f"TTS speaking: {clean[:80]}…")

        # Primary: edge-tts neural voices (requires internet)
        if HAS_EDGE_TTS:
            try:
                tmp = os.path.join(
                    tempfile.gettempdir(),
                    f"hachi_{os.getpid()}_{threading.get_ident()}.mp3",
                )
                voice = _pick_voice(clean)

                loop = asyncio.new_event_loop()
                try:
                    loop.run_until_complete(_generate_edge_tts_file(clean, voice, tmp))
                finally:
                    loop.close()

                if os.path.exists(tmp) and os.path.getsize(tmp) > 500:
                    _play_mp3_interruptible(tmp)
                    try:
                        os.remove(tmp)
                    except OSError:
                        pass
                    return
            except Exception as e:
                logging.warning(f"edge-tts failed ({e}), using SAPI fallback.")

        # Fallback: Windows SAPI (offline)
        _speak_sapi(clean)


def listen_voice_input() -> str:
    """
    Listen to mic and return recognized text (empty string if nothing heard).

    Improvements vs previous version:
    - Calibration cache: ambient noise measured only once per 30 s, not every call
    - pause_threshold = 1.5 s: waits through "uhms" and natural pauses
    - phrase_time_limit = 45 s: allows long sentences
    - Tries fil-PH first, then en-US (best Tagalog/Taglish coverage)
    - BLOCKING acquire (timeout 8 s): waits for wakeword listener to finish its cycle
    """
    global _noise_threshold, _noise_calibrated_at

    acquired = _mic_lock.acquire(timeout=8)
    if not acquired:
        logging.warning("listen_voice_input: could not acquire mic within 8 s.")
        return ""

    try:
        r = sr.Recognizer()
        r.pause_threshold         = 1.5   # Wait 1.5 s of silence before phrase ends
        r.non_speaking_duration   = 0.4
        r.phrase_threshold        = 0.1
        r.dynamic_energy_threshold = False  # We manage threshold manually

        with sr.Microphone() as source:
            now = time.time()
            if _noise_threshold < 100 or (now - _noise_calibrated_at) >= _RECALIBRATE_SECS:
                logging.info("Calibrating ambient noise (0.5 s)…")
                r.energy_threshold = 400
                r.adjust_for_ambient_noise(source, duration=0.5)
                _noise_threshold     = r.energy_threshold
                _noise_calibrated_at = time.time()
                logging.info(f"Noise threshold: {_noise_threshold:.0f}")
            else:
                r.energy_threshold = _noise_threshold
                logging.info(f"Cached threshold: {_noise_threshold:.0f}")

            logging.info("Listening (pause=1.5 s, max=45 s)…")
            audio = r.listen(source, timeout=10, phrase_time_limit=45)

        # --- Language detection: fil-PH → en-US ---
        for lang in ("fil-PH", "en-US"):
            try:
                text = r.recognize_google(audio, language=lang)
                if text:
                    logging.info(f"Recognized ({lang}): {text}")
                    return text
            except sr.UnknownValueError:
                continue
            except sr.RequestError as re_err:
                logging.error(f"Google STT request error ({lang}): {re_err}")
                break

        logging.info("Speech not understood in either language.")
        return ""

    except sr.WaitTimeoutError:
        logging.info("No speech detected within timeout.")
        return ""
    except Exception as e:
        logging.error(f"listen_voice_input error: {e}")
        return ""
    finally:
        _mic_lock.release()


def listen_for_wakeword() -> bool:
    """
    Quick listen (~3 s) for the phrase 'Hey Hachi'.
    NON-BLOCKING mic acquire — returns False immediately if mic is busy.
    """
    acquired = _mic_lock.acquire(blocking=False)
    if not acquired:
        return False

    try:
        r = sr.Recognizer()
        r.dynamic_energy_threshold = True
        r.energy_threshold = 500
        r.pause_threshold  = 0.6

        with sr.Microphone() as source:
            r.adjust_for_ambient_noise(source, duration=0.3)
            audio = r.listen(source, timeout=3, phrase_time_limit=2)

        text = r.recognize_google(audio, language="en-US").lower()
        logging.info(f"Wakeword check: '{text}'")
        return "hachi" in text

    except Exception:
        return False
    finally:
        _mic_lock.release()
