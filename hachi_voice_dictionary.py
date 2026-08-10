"""Local custom vocabulary used to improve Hachi speech transcription."""

import json
import os
import re
import threading


_PATH = os.path.join(os.path.dirname(__file__), "hachi_voice_dictionary.json")
_LOCK = threading.Lock()


def get_voice_terms(limit: int = 120) -> list[str]:
    try:
        with open(_PATH, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        terms = data.get("terms", []) if isinstance(data, dict) else []
    except (OSError, ValueError, TypeError):
        terms = []
    cleaned = []
    for term in terms if isinstance(terms, list) else []:
        value = re.sub(r"\s+", " ", str(term or "")).strip()[:80]
        if value and value.lower() not in {item.lower() for item in cleaned}:
            cleaned.append(value)
    return cleaned[:max(1, min(int(limit), 200))]


def add_voice_term(term: str) -> str:
    value = re.sub(r"\s+", " ", str(term or "")).strip()[:80]
    if not value:
        return "Please provide a word or phrase for the voice dictionary."
    with _LOCK:
        terms = get_voice_terms(200)
        if any(item.lower() == value.lower() for item in terms):
            return f"'{value}' is already in Hachi's voice dictionary."
        terms.append(value)
        with open(_PATH, "w", encoding="utf-8") as handle:
            json.dump({"terms": terms}, handle, ensure_ascii=False, indent=2)
    return f"Added '{value}' to Hachi's voice dictionary."


def transcription_prompt() -> str:
    terms = get_voice_terms()
    dictionary = ", ".join(terms)
    suffix = f" Important names and terms: {dictionary}." if dictionary else ""
    return (
        "This is a conversational voice assistant. The speaker may mix English, "
        "Filipino, and Tagalog in one sentence." + suffix
    )
