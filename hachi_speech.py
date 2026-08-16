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
OFFLINE_TTS_ONLY = True

if os.path.exists(_CONFIG_PATH):
    try:
        with open(_CONFIG_PATH, "r", encoding="utf-8") as _f:
            _cfg = json.load(_f)
            DEFAULT_TAGALOG_VOICE = _cfg.get("tagalog_voice", DEFAULT_TAGALOG_VOICE)
            DEFAULT_ENGLISH_VOICE = _cfg.get("english_voice", DEFAULT_ENGLISH_VOICE)
            OFFLINE_TTS_ONLY = bool(_cfg.get("offline_tts_only", OFFLINE_TTS_ONLY))
    except Exception:
        pass

# ---------------------------------------------------------------------------
# Locks & shared state
# ---------------------------------------------------------------------------
_mic_lock    = threading.Lock()    # Exclusive microphone access
speech_lock  = threading.Lock()    # Exclusive TTS playback
pyaudio_c_lock = threading.Lock()  # Global PortAudio C-library lock (prevents concurrent init/terminate segfaults)

# Set when the voice overlay is open (browser mic in use). The wakeword thread
# checks this so it never fights the browser for the audio device.
voice_mode_active = threading.Event()

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


def _generate_sapi_wav(text: str) -> Optional[str]:
    """Offline fallback: synthesize speech to a WAV file via Windows SAPI."""
    safe = text.replace("'", "''")[:500]
    tmp = os.path.join(
        tempfile.gettempdir(),
        f"hachi_sapi_{os.getpid()}_{threading.get_ident()}_{int(time.time()*1000)}.wav",
    )
    safe_path = tmp.replace("\\", "/")
    ps = (
        f"Add-Type -AssemblyName System.speech; "
        f"$t = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
        f"$f = $t.GetInstalledVoices() | Where-Object {{ $_.VoiceInfo.Gender -eq 'Female' }} | Select-Object -First 1; "
        f"if ($f) {{ $t.SelectVoice($f.VoiceInfo.Name) }}; "
        f"$t.Rate = 1; "
        f"$t.SetOutputToWaveFile('{safe_path}'); "
        f"$t.Speak('{safe}'); "
        f"$t.Dispose()"
    )
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-c", ps],
            timeout=12,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
        )
        if os.path.exists(tmp) and os.path.getsize(tmp) > 500:
            return tmp
    except Exception as e:
        logging.debug(f"SAPI wav fallback failed: {e}")
    return None


def generate_tts_audio(text: str) -> Optional[str]:
    """
    Generate TTS audio for text and return the temp file path.
    Primary: Edge TTS (MP3). Fallback: Windows SAPI (WAV).
    Returns None if generation fails. Caller is responsible for cleanup.
    Used by the /api/voice_stream endpoint for parallel TTS pipeline.
    """
    clean = clean_speech_text(text)
    if not clean:
        return None

    if HAS_EDGE_TTS and not OFFLINE_TTS_ONLY:
        try:
            voice = _pick_voice(clean)
            tmp = os.path.join(
                tempfile.gettempdir(),
                f"hachi_tts_{os.getpid()}_{threading.get_ident()}_{int(time.time()*1000)}.mp3",
            )
            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(asyncio.wait_for(_generate_edge_tts_file(clean, voice, tmp), timeout=8))
            finally:
                loop.close()

            if os.path.exists(tmp) and os.path.getsize(tmp) > 500:
                return tmp
        except Exception as e:
            logging.warning(f"generate_tts_audio edge-tts failed: {e}")

    # Offline / network-failure fallback
    wav = _generate_sapi_wav(clean)
    if wav:
        logging.info("generate_tts_audio: using SAPI WAV fallback")
    return wav


async def _generate_edge_tts_file(text: str, voice: str, out_path: str):
    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(out_path)


def _pick_voice(text: str) -> str:
    lower_words = set(text.lower().split())
    return DEFAULT_TAGALOG_VOICE if lower_words & TAGALOG_WORDS else DEFAULT_ENGLISH_VOICE


def _is_stop_phrase(text: str) -> bool:
    normalized = re.sub(r"[^a-z0-9\s']+", " ", (text or "").lower())
    normalized = re.sub(r"\s+", " ", normalized).strip()
    if not normalized or len(normalized.split()) > 5:
        return False
    if re.search(r"\b(?:don't|dont|do not|huwag)\s+(?:you\s+)?stop\b", normalized):
        return False
    return any(normalized in {word, f"hachi {word}", f"hey hachi {word}"} for word in STOP_WORDS)


def _monitor_stop_during_tts(done: threading.Event):
    """Fast native stop listener used only for non-browser TTS playback."""
    import speech_recognition as sr

    while not done.is_set() and not voice_mode_active.is_set():
        if not _mic_lock.acquire(blocking=False):
            done.wait(0.1)
            continue
        try:
            recognizer = sr.Recognizer()
            recognizer.dynamic_energy_threshold = True
            recognizer.pause_threshold = 0.35
            with pyaudio_c_lock:
                with sr.Microphone() as source:
                    try:
                        audio = recognizer.listen(source, timeout=0.6, phrase_time_limit=2.0)
                    except sr.WaitTimeoutError:
                        continue
            for language in ("en-PH", "fil-PH", "en-US"):
                try:
                    if _is_stop_phrase(recognizer.recognize_google(audio, language=language)):
                        interrupt_speech()
                        done.set()
                        return
                except (sr.UnknownValueError, sr.RequestError):
                    continue
        except Exception as exc:
            logging.debug("TTS stop monitor error: %s", exc)
        finally:
            _mic_lock.release()


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
        f"$maxIter = if ($m.currentMedia.duration) {{ [Math]::Min(300, [Math]::Ceiling($m.currentMedia.duration * 10) + 10) }} else {{ 300 }}; "
        f"while ($m.playState -ne 1 -and $m.playState -ne 8 -and $i -lt $maxIter) "
        f"{{ Start-Sleep -Milliseconds 100; $i++ }}; "
        f"$m.controls.stop()"
    )

    with _tts_proc_lock:
        _tts_proc = subprocess.Popen(
            ["powershell", "-NoProfile", "-NonInteractive", "-c", ps],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    monitor_done = threading.Event()
    if not voice_mode_active.is_set():
        threading.Thread(
            target=_monitor_stop_during_tts,
            args=(monitor_done,),
            daemon=True,
            name="TTSStopMonitor",
        ).start()

    try:
        _tts_proc.wait(timeout=40)
    except subprocess.TimeoutExpired:
        interrupt_speech()
    except Exception:
        pass
    finally:
        monitor_done.set()
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
    monitor_done = threading.Event()
    try:
        proc = subprocess.Popen(
            ["powershell", "-NoProfile", "-NonInteractive", "-c", ps],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        with _tts_proc_lock:
            global _tts_proc
            _tts_proc = proc

        if not voice_mode_active.is_set():
            threading.Thread(
                target=_monitor_stop_during_tts,
                args=(monitor_done,),
                daemon=True,
                name="SAPIStopMonitor",
            ).start()

        proc.wait(timeout=35)
    except subprocess.TimeoutExpired:
        interrupt_speech()
    except Exception as e:
        logging.error(f"SAPI error: {e}")
    finally:
        monitor_done.set()
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
    Fast local female neural acknowledgment (0ms latency, 100% female voice).
    Uses pre-rendered female neural audio files in static/audio/acks.
    """
    if not speech_lock.acquire(timeout=0.1):
        return
    try:
        words = set(user_text.lower().split()) if user_text else set()
        is_tagalog = bool(words & TAGALOG_WORDS)
        acks = ['ack_tl_1.mp3', 'ack_tl_2.mp3', 'ack_tl_3.mp3'] if is_tagalog else ['ack_en_1.mp3', 'ack_en_2.mp3', 'ack_en_3.mp3']
        chosen = random.choice(acks)
        ack_file = os.path.join(os.path.dirname(__file__), 'static', 'audio', 'acks', chosen)
        if os.path.exists(ack_file):
            logging.info(f"speak_quick playing local female ack: {chosen}")
            _play_mp3_interruptible(ack_file)
    except Exception as e:
        logging.debug(f"speak_quick error: {e}")
    finally:
        speech_lock.release()


def speak(text: str):
    """
    Synthesize speech and play it.
    BLOCKS until audio finishes (or is interrupted via interrupt_speech()).
    Generation runs OUTSIDE speech_lock so a network delay never blocks other TTS.
    """
    clean = clean_speech_text(text)
    if not clean:
        return

    logging.info(f"TTS speaking: {clean[:80]}…")

    tmp = None
    # Primary: edge-tts neural voices (requires internet) — generate outside the lock
    if HAS_EDGE_TTS and not OFFLINE_TTS_ONLY:
        try:
            tmp = os.path.join(
                tempfile.gettempdir(),
                f"hachi_{os.getpid()}_{threading.get_ident()}_{int(time.time()*1000)}.mp3",
            )
            voice = _pick_voice(clean)
            loop = asyncio.new_event_loop()
            try:
                # 10s timeout so a dropped network can't hang TTS forever
                loop.run_until_complete(asyncio.wait_for(_generate_edge_tts_file(clean, voice, tmp), timeout=10))
            finally:
                loop.close()
            if not (os.path.exists(tmp) and os.path.getsize(tmp) > 500):
                tmp = None
        except Exception as e:
            logging.warning(f"edge-tts failed ({e}), using SAPI fallback.")
            tmp = None

    # Playback is serialized — only one voice at a time
    with speech_lock:
        if tmp:
            try:
                _play_mp3_interruptible(tmp)
            finally:
                try:
                    os.remove(tmp)
                except OSError:
                    pass
            return
        # Fallback: Windows SAPI (offline)
        _speak_sapi(clean)


def listen_voice_input() -> str:
    """
    Listen to mic and return recognized text (empty string if nothing heard).

    Improvements vs previous version:
    - Calibration cache: ambient noise measured only once per 30 s, not every call
    - pause_threshold = 3.0 s: waits through "uhms" and natural pauses
    - phrase_time_limit = 60 s: allows long commands without an unbounded mic hold
    - Tries fil-PH first, then en-US (best Tagalog/Taglish coverage)
    - BLOCKING acquire (timeout 8 s): waits for wakeword listener to finish its cycle
    """
    import speech_recognition as sr

    global _noise_threshold, _noise_calibrated_at

    acquired = _mic_lock.acquire(timeout=8)
    if not acquired:
        logging.warning("listen_voice_input: could not acquire mic within 8 s.")
        return ""

    try:
        r = sr.Recognizer()
        r.pause_threshold         = 3.0   # Preserve natural long-form thought pauses
        r.non_speaking_duration   = 0.4
        r.phrase_threshold        = 0.1
        r.dynamic_energy_threshold = False  # We manage threshold manually

        with pyaudio_c_lock:
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

                logging.info("Listening (pause=3.0 s, max=60 s)…")
                audio = r.listen(source, timeout=10, phrase_time_limit=60)

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
                continue

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
    Quick listen (~2 s) for the phrase 'Hey Hachi'.
    NON-BLOCKING mic acquire — returns False immediately if mic is busy or if
    the voice overlay is open (browser owns the mic). Recognizes English then
    Tagalog so Tagalog speakers can wake it too.
    """
    import speech_recognition as sr

    if voice_mode_active.is_set():
        return False
    acquired = _mic_lock.acquire(blocking=False)
    if not acquired:
        return False

    try:
        r = sr.Recognizer()
        r.dynamic_energy_threshold = True
        r.energy_threshold = 500
        r.pause_threshold  = 0.6

        with pyaudio_c_lock:
            with sr.Microphone() as source:
                r.adjust_for_ambient_noise(source, duration=0.15)
                audio = r.listen(source, timeout=2, phrase_time_limit=2)

        text = ""
        for lang in ("en-US", "fil-PH"):
            try:
                text = r.recognize_google(audio, language=lang).lower()
                if text:
                    break
            except Exception:
                continue
        logging.info(f"Wakeword check: '{text}'")
        return "hachi" in text

    except Exception:
        return False
    finally:
        _mic_lock.release()
