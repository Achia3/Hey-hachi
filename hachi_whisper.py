"""Official OpenAI Whisper speech-to-text integration for Hachi.

The browser records each user turn directly, then this module transcribes it
with the official ``openai-whisper`` package and its original model weights.
It intentionally does not use Faster-Whisper/CTranslate2.
"""

import json
import logging
import os
import threading
import time
from typing import Optional


_whisper_model = None
_model_lock = threading.Lock()


def _voice_model_name() -> str:
    """Read the multilingual OpenAI Whisper model selected in config.json."""
    config_path = os.path.join(os.path.dirname(__file__), "config.json")
    try:
        with open(config_path, "r", encoding="utf-8") as config_file:
            return str(json.load(config_file).get("voice_transcription_model", "small"))
    except Exception:
        return "small"


def _ensure_ffmpeg() -> Optional[str]:
    """Expose imageio-ffmpeg's bundled executable to official Whisper.

    OpenAI Whisper invokes the ``ffmpeg`` command to decode WebM/Opus browser
    recordings. This makes that work on a fresh Windows installation without a
    separate system-wide ffmpeg setup.
    """
    try:
        import imageio_ffmpeg
        executable = imageio_ffmpeg.get_ffmpeg_exe()
        executable_dir = os.path.dirname(executable)
        path_entries = os.environ.get("PATH", "").split(os.pathsep)
        if executable_dir not in path_entries:
            os.environ["PATH"] = executable_dir + os.pathsep + os.environ.get("PATH", "")
        return executable
    except Exception as exc:
        logging.warning("Bundled ffmpeg setup failed: %s", exc)
        return None


def _configure_whisper_ffmpeg(executable: Optional[str]) -> None:
    """Make official Whisper use imageio-ffmpeg's versioned Windows binary."""
    if not executable:
        return
    try:
        import whisper.audio
        original_run = whisper.audio.run

        def run_with_bundled_ffmpeg(command, *args, **kwargs):
            if isinstance(command, (list, tuple)) and command and command[0] == "ffmpeg":
                command = list(command)
                command[0] = executable
            return original_run(command, *args, **kwargs)

        whisper.audio.run = run_with_bundled_ffmpeg
    except Exception as exc:
        logging.warning("Could not configure official Whisper decoder: %s", exc)


def get_whisper_model():
    """Load the official OpenAI Whisper model once per Hachi process."""
    global _whisper_model
    with _model_lock:
        if _whisper_model is not None:
            return _whisper_model
        try:
            ffmpeg_executable = _ensure_ffmpeg()
            import whisper
            _configure_whisper_ffmpeg(ffmpeg_executable)
            model_name = _voice_model_name()
            logging.info("Loading official OpenAI Whisper model (%s, CPU)...", model_name)
            started = time.time()
            _whisper_model = whisper.load_model(model_name, device="cpu")
            logging.info("Official OpenAI Whisper model loaded in %.2fs", time.time() - started)
        except Exception as exc:
            logging.exception("Failed to load official OpenAI Whisper model: %s", exc)
            _whisper_model = None
    return _whisper_model


def transcribe_audio_file(audio_path: str, language: Optional[str] = None) -> str:
    """Transcribe WAV, MP3, OGG, or WebM audio using official OpenAI Whisper."""
    if not os.path.exists(audio_path) or os.path.getsize(audio_path) < 100:
        return ""
    model = get_whisper_model()
    if model is None:
        return ""

    try:
        started = time.time()
        result = model.transcribe(
            audio_path,
            language=language,
            task="transcribe",
            fp16=False,
            verbose=False,
            condition_on_previous_text=False,
            initial_prompt=(
                "This is a conversational voice assistant. The speaker may mix "
                "English, Filipino, and Tagalog in one sentence."
            ),
        )
        text = str(result.get("text", "")).strip()
        if text:
            logging.info(
                "[OpenAI Whisper] Transcribed in %.2fs (lang=%s): %r",
                time.time() - started,
                result.get("language", "unknown"),
                text[:180],
            )
        return text
    except Exception as exc:
        logging.exception("OpenAI Whisper transcription failed: %s", exc)
        return ""
