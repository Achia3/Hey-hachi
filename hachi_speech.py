import os
import asyncio
import tempfile
import threading
import json
import logging
import re
import speech_recognition as sr

# Check edge-tts availability
try:
    import edge_tts
    HAS_EDGE_TTS = True
except ImportError:
    HAS_EDGE_TTS = False

try:
    import pyttsx3
    pyttsx3_engine = pyttsx3.init()
    pyttsx3_engine.setProperty("rate", 155)
except Exception:
    pyttsx3_engine = None

# Load voice config from config.json
_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.json")
DEFAULT_TAGALOG_VOICE = "fil-PH-AngeloNeural"
DEFAULT_ENGLISH_VOICE = "en-US-AvaNeural"

if os.path.exists(_CONFIG_PATH):
    try:
        with open(_CONFIG_PATH, "r") as _f:
            _cfg = json.load(_f)
            DEFAULT_TAGALOG_VOICE = _cfg.get("tagalog_voice", DEFAULT_TAGALOG_VOICE)
            DEFAULT_ENGLISH_VOICE = _cfg.get("english_voice", DEFAULT_ENGLISH_VOICE)
    except Exception as _e:
        logging.warning(f"Could not load voice config: {_e}")

# Microphone access lock (prevents concurrent mic opens)
_mic_lock = threading.Lock()

# Speech output lock (ensures only one TTS audio plays at a time)
speech_lock = threading.Lock()


def clean_speech_text(text: str) -> str:
    """Remove markdown tags, thinking tags, or emojis before TTS."""
    text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL)
    text = re.sub(r'[*#_`~]', '', text)
    return text.strip()


async def _edge_tts_speak_async(text: str, voice: str, output_file: str):
    """Generate audio file via edge-tts."""
    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(output_file)


def speak(text: str, voice: str = DEFAULT_TAGALOG_VOICE):
    """
    Synthesize and play speech.
    Uses high quality edge-tts if available, else falls back to pyttsx3.
    The speech_lock ensures concurrent speak() calls are serialized,
    preventing audio overlap.
    """
    with speech_lock:
        clean_text = clean_speech_text(text)
        if not clean_text:
            return

        logging.info(f"Speaking response: {clean_text[:80]}...")

        if HAS_EDGE_TTS:
            try:
                temp_dir = tempfile.gettempdir()
                # Use a unique filename per thread to avoid race condition on the file
                audio_path = os.path.join(temp_dir, f"hachi_tts_{threading.get_ident()}.mp3")

                # Detect language context (if Tagalog words present, use Tagalog voice)
                lower = clean_text.lower()
                if any(w in lower for w in ["ako", "ikaw", "opo", "kasi", "naman", "salamat", "kamusta", "ano", "bakit"]):
                    chosen_voice = DEFAULT_TAGALOG_VOICE
                else:
                    chosen_voice = DEFAULT_ENGLISH_VOICE

                # asyncio.run creates a new event loop; safe inside a daemon thread
                asyncio.run(_edge_tts_speak_async(clean_text, chosen_voice, audio_path))

                # Play mp3 via Windows MediaPlayer COM object (blocks until done)
                ps_cmd = (
                    f'powershell -c "$player = New-Object -ComObject WMPlayer.OCX; '
                    f"$player.URL = '{audio_path}'; "
                    f"$player.controls.play(); "
                    f"while ($player.playState -ne 1) {{ Start-Sleep -Milliseconds 100 }}\""
                )
                os.system(ps_cmd)

                # Cleanup temp file
                try:
                    os.remove(audio_path)
                except OSError:
                    pass
                return
            except Exception as e:
                logging.warning(f"edge-tts failed ({e}), falling back to pyttsx3.")

        # Fallback to local pyttsx3 engine
        if pyttsx3_engine:
            try:
                pyttsx3_engine.say(clean_text)
                pyttsx3_engine.runAndWait()
            except Exception as err:
                logging.error(f"pyttsx3 error: {err}")


def listen_voice_input(energy_threshold: int = 4000) -> str:
    """
    Listen to microphone input and convert to text.
    Uses _mic_lock to prevent concurrent microphone access from parallel HTTP requests.
    """
    if not _mic_lock.acquire(blocking=False):
        logging.warning("Microphone already in use, dropping concurrent listen request.")
        return ""

    try:
        recognizer = sr.Recognizer()
        recognizer.energy_threshold = energy_threshold
        recognizer.dynamic_energy_threshold = True

        with sr.Microphone() as source:
            logging.info("Listening for user voice...")
            recognizer.adjust_for_ambient_noise(source, duration=0.8)
            audio = recognizer.listen(source, timeout=8, phrase_time_limit=12)

            # Try Filipino/Tagalog first, then English fallback
            try:
                text = recognizer.recognize_google(audio, language="fil-PH")
                logging.info(f"Speech recognized (fil-PH): {text}")
            except sr.UnknownValueError:
                logging.info("fil-PH recognition yielded no result, retrying in en-US...")
                text = recognizer.recognize_google(audio, language="en-US")
                logging.info(f"Speech recognized (en-US): {text}")

            return text

    except sr.WaitTimeoutError:
        return ""
    except sr.UnknownValueError:
        return ""
    except Exception as e:
        logging.error(f"Speech recognition error: {e}")
        return ""
    finally:
        _mic_lock.release()
