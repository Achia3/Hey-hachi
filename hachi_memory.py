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

    if any(w in lower for w in ("safe code", "safe password", "code to the safe", "code of the safe", "safe passcode")):
        return "security", "safe code"
    if any(w in lower for w in ("secret code", "my secret code", "secret pin")):
        return "security", "secret code"
    if any(w in lower for w in ("password", "pin code", "pin number", "passcode", "credentials", "pin")):
        return "security", "credentials"
    if "secret" in lower:
        return "identity", "secret"
    if "allergic" in lower or "allergy" in lower:
        return "health", "allergies"

    patterns = [
        ("preference", r"^i\s+(?:prefer|like|love|dislike|hate)\s+(.+)$"),
        ("preference", r"^my\s+fav(?:orite|ourite)?\s+([^.!?]{1,40}?)\s+is\s+(.+)$"),
        ("identity", r"^my\s+([^.!?]{1,40}?)\s+is\s+(.+)$"),
        ("profile", r"^i\s+(?:am|live|work|study|m)\s+(.+)$"),
    ]
    for category, pattern in patterns:
        match = re.match(pattern, clean, flags=re.IGNORECASE)
        if match:
            subject = match.group(1)
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
        all_active = conn.execute(
            "SELECT * FROM memories WHERE user_id=? AND agent_id=? AND status='active' ORDER BY id DESC",
            (user_id, agent_id),
        ).fetchall()

        superseded_ids = []
        clean_tokens = _tokens(f"{category} {subject} {clean}")

        for row in all_active:
            row_norm = _normalize(row["content"])
            if row_norm == normalized_content:
                conn.execute("UPDATE memories SET updated_at=? WHERE id=?", (now, row["id"]))
                conn.commit()
                return {"status": "duplicate", "id": row["id"], "content": row["content"]}

            row_cat = row["category"] or ""
            row_subj = row["subject"] or ""
            row_tokens = _tokens(f"{row_cat} {row_subj} {row['content']}")

            # Supersede matching subject or entity specifically
            is_same_subject = (
                (row_cat == category and row_subj == subject) or
                (subject in ("secret code", "secret") and row_subj in ("secret code", "secret")) or
                (subject in ("safe code", "safe password") and row_subj in ("safe code", "safe password", "safe 4555 password", "safe passcode")) or
                (subject == row_subj and subject not in ("general", "fact")) or
                (len(clean_tokens & row_tokens) >= 2 and any(k in (clean_tokens & row_tokens) for k in ("secret", "safe", "birthday", "address", "food", "color", "favorite", "favourite", "name")))
            )

            if is_same_subject:
                superseded_ids.append(row["id"])

        primary_superseded = superseded_ids[0] if superseded_ids else None

        cursor = conn.execute(
            "INSERT INTO memories (user_id,agent_id,category,subject,content,embedding,confidence,source,status,supersedes_id,created_at,updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (user_id, agent_id, category, subject, clean, vector, max(0.0, min(float(confidence), 1.0)), source,
             "active", primary_superseded, now, now),
        )
        new_id = cursor.lastrowid
        for s_id in superseded_ids:
            conn.execute("UPDATE memories SET status='superseded', updated_at=? WHERE id=?", (now, s_id))
        conn.commit()

    return {"status": "saved", "id": new_id, "supersedes_id": primary_superseded, "content": clean}


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
    query_lower = (query or "").lower()

    query_has_safe = "safe" in query_lower
    query_has_secret = "secret" in query_lower and not query_has_safe

    with closing(get_connection()) as conn:
        rows = conn.execute(
            "SELECT * FROM memories WHERE user_id=? AND agent_id=? AND status='active' ORDER BY updated_at DESC LIMIT 500",
            (user_id, agent_id),
        ).fetchall()
    results = []
    for row in rows:
        row_content_lower = (row["content"] or "").lower()
        row_subj_lower = (row["subject"] or "").lower()

        # Entity disambiguation
        if query_has_safe and "safe" not in row_content_lower and "safe" not in row_subj_lower:
            continue
        if query_has_secret and "secret" not in row_content_lower and "secret" not in row_subj_lower:
            continue

        try:
            vector = json.loads(row["embedding"] or "[]")
        except Exception:
            vector = []
        semantic = _cosine(query_vector, vector) if vector else 0.0
        memory_tokens = _tokens(f"{row['subject']} {row['content']}")
        lexical = len(query_tokens & memory_tokens) / max(1, len(query_tokens))
        score = 0.50 * semantic + 0.50 * lexical
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

    lower = text.lower().strip(" .?!'\"")

    # 1. "change that to 112233 its my new safe code" / "change that to 112233 as my new secret code"
    m = re.match(r"^(?:change|update|set|switch|replace)\s+(?:that|it)\s+to\s+([0-9a-zA-Z _'-]+?)(?:\s+(?:it's|its|as)\s+(?:my\s+)?(?:new\s+)?([^.,!?]+))?[.?!]?$", lower)
    if m:
        val = m.group(1).strip(" .?!'\"")
        declared_item = (m.group(2) or "").strip(" .?!'\"")
        item = declared_item or "value"
        if "safe" in item:
            fact = f"The safe code is {val}"
            return save_memory(fact, category="security", subject="safe code", source="explicit_user_request")
        elif "secret" in item:
            fact = f"My secret code is {val}"
            return save_memory(fact, category="security", subject="secret code", source="explicit_user_request")
        elif any(w in item for w in ("code", "password", "pin", "key", "passcode")):
            fact = f"My {item} is {val}"
            return save_memory(fact, category="security", subject=item, source="explicit_user_request")
        else:
            with closing(get_connection()) as conn:
                recent = conn.execute("SELECT category, subject, content FROM memories WHERE status='active' ORDER BY updated_at DESC LIMIT 1").fetchone()
                if recent:
                    subj = recent["subject"]
                    cat = recent["category"]
                    fact = f"My {subj} is {val}" if not recent["content"].lower().startswith("the ") else f"The {subj} is {val}"
                    return save_memory(fact, category=cat, subject=subj, source="explicit_user_request")
            fact = f"My {item} is {val}" if item != "value" else f"Value is {val}"
            return save_memory(fact, source="explicit_user_request")

    # 2. "change my safe code to 112233" / "update my password to secret123" / "set my pin to 4321"
    m = re.match(r"^(?:change|update|set|switch|replace)\s+(?:my\s+|the\s+)?([^.,!?]+?)\s+to\s+([0-9a-zA-Z _'-]+?)[.?!]?$", lower)
    if m:
        item = m.group(1).strip(" .?!'\"")
        val = m.group(2).strip(" .?!'\"")
        if "safe" in item:
            fact = f"The safe code is {val}"
            return save_memory(fact, category="security", subject="safe code", source="explicit_user_request")
        elif "secret" in item:
            fact = f"My secret code is {val}"
            return save_memory(fact, category="security", subject="secret code", source="explicit_user_request")
        elif any(w in item for w in ("code", "password", "pin", "key", "passcode")):
            fact = f"My {item} is {val}"
            return save_memory(fact, category="security", subject=item, source="explicit_user_request")
        else:
            fact = f"My {item} is {val}"
            return save_memory(fact, subject=item, source="explicit_user_request")

    # 3. "new safe code is 112233" / "my new password is xyz" / "its my new safe code: 112233"
    m = re.match(r"^(?:my\s+)?(?:new\s+)?([^.,!?]+?)\s+(?:is|its|it's|:|=)\s*(.+)$", lower)
    if m and any(k in lower for k in ("safe code", "secret code", "new safe code", "new secret code", "passcode", "password", "pin", "secret")):
        item = m.group(1).strip(" .?!'\"")
        val = m.group(2).strip(" .?!'\"")
        if "safe" in item:
            fact = f"The safe code is {val}"
            return save_memory(fact, category="security", subject="safe code", source="explicit_user_request")
        elif "secret" in item:
            fact = f"My secret code is {val}"
            return save_memory(fact, category="security", subject="secret code", source="explicit_user_request")
        elif any(w in item for w in ("code", "password", "pin", "key", "passcode")):
            fact = f"My {item} is {val}"
            return save_memory(fact, category="security", subject=item, source="explicit_user_request")

    # 4. "i have a secret code its 45688" / "i have a code its 1234" / "i got a password its xyz"
    m = re.match(r"^(?:i have|i got)\s+(?:a\s+)?(secret\s+code|safe\s+code|safe\s+password|code|password|pin|key|secret)\s+(?:is|its|it's|:|=)\s*(.+)$", lower)
    if m:
        item = m.group(1).strip()
        val = m.group(2).strip(" .?!'\"")
        if val:
            fact = f"My {item} is {val}"
            cat, subj = ("security", item) if "code" in item or "password" in item or "pin" in item else ("identity", "secret")
            return save_memory(fact, category=cat, subject=subj, source="explicit_user_request")

    # 5. "my secret code is 45688" / "my safe code is 1234" / "my password is xyz" / "my pin is 9988"
    m = re.match(r"^my\s+(secret\s+code|safe\s+code|safe\s+password|code|password|pin|key|secret)\s+(?:is|its|it's|:|=)\s*(.+)$", lower)
    if m:
        item = m.group(1).strip()
        val = m.group(2).strip(" .?!'\"")
        if val:
            fact = f"My {item} is {val}"
            cat, subj = ("security", item) if "code" in item or "password" in item or "pin" in item else ("identity", "secret")
            return save_memory(fact, category=cat, subject=subj, source="explicit_user_request")

    # 6. "the code of/to the safe is 4555" / "the password for X is Y"
    m = re.match(r"^the\s+(code|password|pin|key|passcode)\s+(?:to|for|of)\s+(?:the\s+)?([^.,!?]+?)\s+(?:is|its|it's|:|=)\s*(.+)$", lower)
    if m:
        kind = m.group(1).strip()
        target = m.group(2).strip()
        val = m.group(3).strip(" .?!'\"")
        if val:
            fact = f"The {kind} to the {target} is {val}"
            subj = f"{target} {kind}".strip()
            return save_memory(fact, category="security", subject=subj, source="explicit_user_request")

    # 7. "please remember that X" / "remember this: X" / "keep in mind that X" / "tandaan mo na X"
    m = re.match(r"^(?:please\s+)?(?:remember|keep in mind|memorize|take note|note down|note that|never forget|don't forget|tandaan mo|wag mo kalimutan)(?:\s+(?:that|this|the following|na|ito))?[:\s]+(.{3,})$", text, flags=re.IGNORECASE)
    if m:
        fact = m.group(1).strip(" .?!'\"")
        if len(fact) >= 3:
            return save_memory(fact, source="explicit_user_request")

    # 8. "ima tell you the code of the safe its 4555" / "im gonna tell you a secret its X"
    m = re.match(r"^(?:ima|im gonna|let me|i will|i want to)\s+tell\s+you\s+(?:something|a secret|my [^.,!?]+|the [^.,!?]+)?\s*[:,-]?\s*(?:it's\s+that|its\s+that|that|is|its|it's)?\s*(.{3,})$", text, flags=re.IGNORECASE)
    if m:
        fact = m.group(1).strip(" .?!'\"")
        if len(fact) >= 3:
            return save_memory(fact, source="explicit_user_request")

    # 9. General identity & preferences: "my favorite food is pizza", "my birthday is Aug 21", "my dog name is Max"
    m = re.match(r"^my\s+([a-zA-Z0-9 _'-]{2,35})\s+(?:is|its|it's|=)\s*([^.,!?]+)$", text, flags=re.IGNORECASE)
    if m:
        field = m.group(1).strip()
        val = m.group(2).strip(" .?!'\"")
        if not any(neg in field.lower() for neg in ("screen", "system", "pc", "laptop", "battery", "window", "wifi", "internet", "browser")):
            fact = f"My {field} is {val}"
            return save_memory(fact, category="identity", subject=field, source="explicit_user_request")

    # 10. Preferences: "i like X", "i prefer X", "i love X", "i live in X"
    m = re.match(r"^i\s+(prefer|like|love|hate|dislike|live in|work at|study at)\s+([^.,!?]+)$", text, flags=re.IGNORECASE)
    if m:
        rel = m.group(1).strip()
        val = m.group(2).strip(" .?!'\"")
        fact = f"I {rel} {val}"
        return save_memory(fact, category="preference" if "live" not in rel and "work" not in rel else "profile", subject=rel, source="explicit_user_request")

    # 11. Tagalog: "ang password ko ay 1234"
    m = re.match(r"^(?:ang\s+)?(password|code|secret|pin)\s+(?:ko|ng safe)\s+ay\s+(.+)$", lower)
    if m:
        kind = m.group(1).strip()
        val = m.group(2).strip(" .?!'\"")
        fact = f"My {kind} is {val}"
        return save_memory(fact, category="security", subject=kind, source="explicit_user_request")

    return None
