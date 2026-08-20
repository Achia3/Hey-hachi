"""Curated durable memory with scoped hybrid retrieval and safe supersession."""

from __future__ import annotations

from contextlib import closing
from datetime import datetime
import hashlib
import json
import math
import re
from typing import Iterable

from hachi_db import get_connection, init_db


_STOP = {
    "a", "an", "and", "are", "as", "at", "be", "for", "from", "i", "in", "is",
    "it", "my", "of", "on", "or", "that", "the", "this", "to", "was", "with", "you",
}


def _normalize(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]+", " ", (value or "").lower())).strip()


def _tokens(value: str) -> set[str]:
    return {token for token in _normalize(value).split() if len(token) > 1 and token not in _STOP}


def _hashed_embedding(value: str, dimensions: int = 256) -> list[float]:
    """Dependency-free feature embedding using words and character trigrams."""
    normalized = f"  {_normalize(value)}  "
    features: list[str] = list(_tokens(value))
    features.extend(normalized[index:index + 3] for index in range(max(0, len(normalized) - 2)))
    vector = [0.0] * dimensions
    for feature in features:
        digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest()
        number = int.from_bytes(digest, "little")
        vector[number % dimensions] += -1.0 if number & 1 else 1.0
    norm = math.sqrt(sum(item * item for item in vector)) or 1.0
    return [item / norm for item in vector]


def _cosine(left: Iterable[float], right: Iterable[float]) -> float:
    return sum(a * b for a, b in zip(left, right))


def _infer_category_subject(content: str) -> tuple[str, str]:
    clean = re.sub(r"^(?:please\s+)?remember(?:\s+that|\s+this)?\s+", "", content.strip(), flags=re.IGNORECASE)
    clean = re.sub(r"[.,!?]+$", "", clean).strip()
    lower = clean.lower()
    if "secret" in lower:
        return "identity", "secret"
    if any(w in lower for w in ("code", "password", "pin", "safe", "credentials", "key")):
        return "security", "credentials"
    if "allergic" in lower or "allergy" in lower:
        return "health", "allergies"
    patterns = [
        ("preference", r"^i\s+(?:prefer|like|love|dislike|hate)\s+(.+)$"),
        ("identity", r"^my\s+([^.!?]{1,40}?)\s+is\s+(.+)$"),
        ("profile", r"^i\s+(?:am|live|work|study|m)\s+(.+)$"),
    ]
    for category, pattern in patterns:
        match = re.match(pattern, clean, flags=re.IGNORECASE)
        if match:
            subject = match.group(1) if category == "identity" else "user"
            return category, _normalize(subject)[:80] or "user"
    tokens = list(_tokens(clean))
    return "fact", " ".join(tokens[:5])[:80] or "general"


def save_memory(
    content: str,
    *,
    category: str = "",
    subject: str = "",
    user_id: str = "local",
    agent_id: str = "hachi",
    confidence: float = 1.0,
    source: str = "explicit",
) -> dict:
    init_db()
    clean = re.sub(r"\s+", " ", (content or "")).strip()
    if len(clean) < 3:
        return {"status": "rejected", "reason": "memory_too_short"}
    inferred_category, inferred_subject = _infer_category_subject(clean)
    category = _normalize(category) or inferred_category
    subject = _normalize(subject) or inferred_subject
    normalized_content = _normalize(clean)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    vector = json.dumps(_hashed_embedding(clean), separators=(",", ":"))

    with closing(get_connection()) as conn:
        rows = conn.execute(
            "SELECT * FROM memories WHERE user_id=? AND agent_id=? AND category=? AND subject=? "
            "AND status='active' ORDER BY id DESC",
            (user_id, agent_id, category, subject),
        ).fetchall()
        for row in rows:
            if _normalize(row["content"]) == normalized_content:
                conn.execute("UPDATE memories SET updated_at=? WHERE id=?", (now, row["id"]))
                conn.commit()
                return {"status": "duplicate", "id": row["id"], "content": row["content"]}

        superseded_id = rows[0]["id"] if rows else None
        cursor = conn.execute(
            "INSERT INTO memories (user_id,agent_id,category,subject,content,embedding,confidence,source,status,supersedes_id,created_at,updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (user_id, agent_id, category, subject, clean, vector, max(0.0, min(float(confidence), 1.0)), source,
             "active", superseded_id, now, now),
        )
        new_id = cursor.lastrowid
        if superseded_id:
            conn.execute("UPDATE memories SET status='superseded', updated_at=? WHERE id=?", (now, superseded_id))
        conn.commit()
    return {"status": "saved", "id": new_id, "supersedes_id": superseded_id, "content": clean}


def search_memories(
    query: str,
    *,
    limit: int = 5,
    user_id: str = "local",
    agent_id: str = "hachi",
    min_score: float = 0.12,
) -> list[dict]:
    init_db()
    query_vector = _hashed_embedding(query)
    query_tokens = _tokens(query)
    with closing(get_connection()) as conn:
        rows = conn.execute(
            "SELECT * FROM memories WHERE user_id=? AND agent_id=? AND status='active' ORDER BY updated_at DESC LIMIT 500",
            (user_id, agent_id),
        ).fetchall()
    results = []
    for row in rows:
        try:
            vector = json.loads(row["embedding"] or "[]")
        except Exception:
            vector = []
        semantic = _cosine(query_vector, vector) if vector else 0.0
        memory_tokens = _tokens(f"{row['subject']} {row['content']}")
        lexical = len(query_tokens & memory_tokens) / max(1, len(query_tokens))
        score = 0.65 * semantic + 0.35 * lexical
        if score >= min_score:
            results.append({
                "id": row["id"], "category": row["category"], "subject": row["subject"],
                "content": row["content"], "confidence": row["confidence"], "source": row["source"],
                "score": round(score, 4), "updated_at": row["updated_at"],
            })
    results.sort(key=lambda item: (item["score"], item["updated_at"]), reverse=True)
    return results[:max(1, min(int(limit), 20))]


def format_memory_search(query: str, limit: int = 5) -> str:
    rows = search_memories(query, limit=limit)
    if not rows:
        return "No durable memories matched that query."
    return "\n".join(
        f"[{row['category']}/{row['subject']}; confidence={row['confidence']:.2f}; score={row['score']:.2f}] {row['content']}"
        for row in rows
    )


def capture_explicit_memory(user_text: str) -> dict | None:
    """Store explicit user memory requests with flexible natural phrasing."""
    text = (user_text or "").strip()
    if not text:
        return None

    # 1. "no just remember this the code is 4555" / "please remember that X" / "remember this: X"
    m = re.search(r"\b(?:remember|keep in mind|memorize)\b(?:\s+(?:that|this))?[:\s]+(.{3,})$", text, flags=re.IGNORECASE)
    if m:
        fact = m.group(1).strip(" .?!'\"")
        if len(fact) >= 3:
            return save_memory(fact, source="explicit_user_request")

    # 2. "make sure you remember this / that" / "don't forget that X"
    m = re.search(r"\b(?:make\s+sure\s+you\s+remember|don't\s+forget|note\s+that)(?:\s+that|\s+this)?[:\s]+(.{3,})$", text, flags=re.IGNORECASE)
    if m:
        fact = m.group(1).strip(" .?!'\"")
        if len(fact) >= 3:
            return save_memory(fact, source="explicit_user_request")

    # 3. "ima tell you the code of the safe its 4555" / "im gonna tell you something its that X"
    m = re.search(r"\b(?:ima|im gonna|let me|i will|i want to)\s+tell\s+you\s+(?:something|a secret|the\s+[^.,!?]+)?\s*[:,-]?\s*(?:it's\s+that|its\s+that|that|is)?\s*(.+?)(?:[,\s]+(?:make\s+sure\s+you\s+remember(?:\s+this)?|remember\s+this|don't\s+forget|keep\s+this\s+in\s+mind))?[.!?]*$", text, flags=re.IGNORECASE)
    if m:
        fact = m.group(1).strip(" .?!'\"")
        if len(fact) >= 3:
            return save_memory(fact, source="explicit_user_request")

    # 4. "the code of/to the safe is 4555" / "the password for X is Y" when mentioning code/password/secret
    if re.search(r"\b(?:code|password|pin|secret|safe)\b", text, flags=re.IGNORECASE):
        m = re.search(r"\b(the\s+(?:code|password|pin)\s+(?:of|for|to)\s+(?:the\s+)?[^.,!?]+\s+(?:is|its|it's)\s+[^.,!?]+)", text, flags=re.IGNORECASE)
        if m:
            return save_memory(m.group(1).strip(), category="security", subject="credentials", source="explicit_user_request")
        m = re.search(r"\b(the\s+code\s+is\s+[^.,!?]+)", text, flags=re.IGNORECASE)
        if m:
            return save_memory(m.group(1).strip(), category="security", subject="credentials", source="explicit_user_request")

    # 5. "my secret is X" / "im secretly X" when remember context is present
    if re.search(r"\b(?:remember|save|note|keep|secret)\b", text, flags=re.IGNORECASE):
        m = re.search(r"\b(i(?:'m| am) secretly [^.,!?]+|my secret is [^.,!?]+)", text, flags=re.IGNORECASE)
        if m:
            return save_memory(m.group(1).strip(), category="identity", subject="secret", source="explicit_user_request")

    return None
