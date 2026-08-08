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
    clean = re.sub(r"^(?:please\s+)?remember(?:\s+that)?\s+", "", content.strip(), flags=re.IGNORECASE)
    if re.match(r"^i(?:'m| am)\s+allergic\s+to\s+.+$", clean, flags=re.IGNORECASE):
        return "health", "allergies"
    patterns = [
        ("preference", r"^i\s+(?:prefer|like|love)\s+(.+)$"),
        ("identity", r"^my\s+([^.!?]{1,40}?)\s+is\s+(.+)$"),
        ("profile", r"^i\s+(?:am|live|work|study)\s+(.+)$"),
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
    """Store only explicit memory requests; ordinary chat remains an audit log."""
    text = (user_text or "").strip()
    match = re.match(r"^(?:hachi[, ]+)?(?:please\s+)?remember(?:\s+that)?\s+(.{3,})$", text, flags=re.IGNORECASE)
    if not match:
        return None
    return save_memory(match.group(1), source="explicit_user_request")
