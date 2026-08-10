"""Opt-in global push-to-talk dictation for Windows desktop text fields."""

import json
import logging
import os
import tempfile
import threading
import wave


_service = None
_service_lock = threading.Lock()


def _config() -> dict:
    defaults = {"global_dictation_hotkey": "ctrl+alt+space"}
    try:
        with open(os.path.join(os.path.dirname(__file__), "config.json"), "r", encoding="utf-8") as handle:
            loaded = json.load(handle)
        if isinstance(loaded, dict):
            defaults.update({key: loaded[key] for key in defaults if key in loaded})
    except (OSError, ValueError):
        pass
    return defaults


class DictationService:
    def __init__(self, hotkey: str):
        self.hotkey = hotkey
        self._listener = None
        self._recording = False
        self._frames = []
        self._audio = None
        self._stream = None
        self._lock = threading.Lock()
        self._pressed = set()

    @staticmethod
    def _key_name(key) -> str:
        text = str(key).lower()
        if text in {"key.ctrl", "key.ctrl_l", "key.ctrl_r"}: return "ctrl"
        if text in {"key.alt", "key.alt_l", "key.alt_r", "key.alt_gr"}: return "alt"
        if text == "key.space": return "space"
        return text.strip("'")

    def _wanted_keys(self) -> set[str]:
        return {item.strip().lower().replace("<", "").replace(">", "") for item in self.hotkey.split("+") if item.strip()}

    def start(self) -> str:
        try:
            from pynput import keyboard
        except ImportError:
            return "Global dictation needs pynput. Run: pip install -r requirements.txt"
        self._listener = keyboard.Listener(on_press=self._on_press, on_release=self._on_release)
        self._listener.daemon = True
        self._listener.start()
        return f"Global dictation is on. Hold {self.hotkey.upper()}, speak, then release to paste into the active text field."

    def stop(self) -> str:
        with self._lock:
            if self._recording:
                self._stop_recording()
        if self._listener:
            self._listener.stop()
        return "Global dictation is off."

    def _on_press(self, key):
        self._pressed.add(self._key_name(key))
        if not self._recording and self._wanted_keys().issubset(self._pressed):
            self._start_recording()

    def _on_release(self, key):
        self._pressed.discard(self._key_name(key))
        if self._recording and not self._wanted_keys().issubset(self._pressed):
            self._stop_recording()

    def _start_recording(self) -> None:
        try:
            import pyaudio
            self._audio = pyaudio.PyAudio()
            self._stream = self._audio.open(format=pyaudio.paInt16, channels=1, rate=16000, input=True, frames_per_buffer=1024)
            self._frames = []
            self._recording = True
            threading.Thread(target=self._read_frames, daemon=True).start()
        except Exception as exc:
            logging.warning("Global dictation could not start microphone: %s", exc)
            self._cleanup_audio()

    def _read_frames(self) -> None:
        while self._recording and self._stream:
            try:
                self._frames.append(self._stream.read(1024, exception_on_overflow=False))
            except Exception:
                break

    def _stop_recording(self) -> None:
        if not self._recording:
            return
        self._recording = False
        stream, audio, frames = self._stream, self._audio, list(self._frames)
        self._stream = self._audio = None
        try:
            if stream: stream.stop_stream(); stream.close()
            if audio: audio.terminate()
        except Exception:
            pass
        if frames:
            threading.Thread(target=self._transcribe_and_paste, args=(frames,), daemon=True).start()

    def _cleanup_audio(self) -> None:
        try:
            if self._stream: self._stream.close()
            if self._audio: self._audio.terminate()
        except Exception:
            pass
        self._stream = self._audio = None
        self._recording = False

    def _transcribe_and_paste(self, frames: list[bytes]) -> None:
        path = os.path.join(tempfile.gettempdir(), "hachi_dictation.wav")
        try:
            with wave.open(path, "wb") as handle:
                handle.setnchannels(1); handle.setsampwidth(2); handle.setframerate(16000); handle.writeframes(b"".join(frames))
            from hachi_whisper import transcribe_audio_file
            text = transcribe_audio_file(path)
            if not text:
                return
            import pyperclip
            import pyautogui
            pyperclip.copy(text)
            pyautogui.hotkey("ctrl", "v")
        except Exception as exc:
            logging.warning("Global dictation failed: %s", exc)
        finally:
            try: os.remove(path)
            except OSError: pass


def set_global_dictation(enabled: bool) -> str:
    global _service
    with _service_lock:
        if enabled:
            if _service is not None:
                return "Global dictation is already on."
            _service = DictationService(str(_config()["global_dictation_hotkey"]))
            result = _service.start()
            if result.startswith("Global dictation needs"):
                _service = None
            return result
        if _service is None:
            return "Global dictation is already off."
        result = _service.stop(); _service = None
        return result
