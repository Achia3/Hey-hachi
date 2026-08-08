"""Request-scoped runtime primitives shared by web, agent, and tools.

The registry is intentionally process-local: Hachi currently runs as one desktop
process.  A turn owns one cancellation Event and a small idempotency cache so a
provider failover cannot repeat an already-completed side effect.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import logging
import threading
import time
import uuid
from typing import Any, Callable


class TurnCancelled(RuntimeError):
    """Raised at cooperative cancellation checkpoints."""


@dataclass
class TurnContext:
    turn_id: str
    cancel_event: threading.Event = field(default_factory=threading.Event)
    created_at: float = field(default_factory=time.time)
    completed_actions: dict[str, Any] = field(default_factory=dict)
    lock: threading.Lock = field(default_factory=threading.Lock)

    @property
    def cancelled(self) -> bool:
        return self.cancel_event.is_set()

    def checkpoint(self) -> None:
        if self.cancelled:
            raise TurnCancelled(f"Turn {self.turn_id} was cancelled")

    @staticmethod
    def action_key(tool_name: str, arguments: dict, call_id: str = "") -> str:
        canonical = json.dumps(arguments or {}, sort_keys=True, ensure_ascii=False, default=str)
        digest = hashlib.sha256(f"{tool_name}\0{canonical}".encode("utf-8")).hexdigest()[:20]
        # Arguments, rather than provider-generated call IDs, are the stable
        # identity across a Qwen -> DeepSeek failover.
        return f"args:{digest}"

    def run_action(
        self,
        tool_name: str,
        arguments: dict,
        action: Callable[[], Any],
        *,
        call_id: str = "",
    ) -> tuple[Any, bool]:
        """Execute once per turn/call ID. Returns (result, reused)."""
        self.checkpoint()
        key = self.action_key(tool_name, arguments, call_id)
        with self.lock:
            if key in self.completed_actions:
                return self.completed_actions[key], True
        result = action()
        with self.lock:
            self.completed_actions[key] = result
        self.checkpoint()
        return result, False


_turns: dict[str, TurnContext] = {}
_turns_lock = threading.Lock()
_TURN_TTL_SECONDS = 15 * 60


def _clean_old_turns(now: float) -> None:
    stale = [key for key, ctx in _turns.items() if now - ctx.created_at > _TURN_TTL_SECONDS]
    for key in stale:
        _turns.pop(key, None)


def create_turn(turn_id: str | None = None) -> TurnContext:
    clean_id = (turn_id or "").strip() or str(uuid.uuid4())
    now = time.time()
    with _turns_lock:
        _clean_old_turns(now)
        existing = _turns.get(clean_id)
        if existing is not None:
            return existing
        ctx = TurnContext(turn_id=clean_id)
        _turns[clean_id] = ctx
        return ctx


def get_turn(turn_id: str | None) -> TurnContext | None:
    if not turn_id:
        return None
    with _turns_lock:
        return _turns.get(str(turn_id))


def cancel_turn(turn_id: str | None) -> bool:
    ctx = get_turn(turn_id)
    if ctx is None:
        return False
    ctx.cancel_event.set()
    logging.info("[turn=%s] cancellation requested", ctx.turn_id)
    return True


def finish_turn(turn_id: str | None) -> None:
    if not turn_id:
        return
    with _turns_lock:
        _turns.pop(str(turn_id), None)


def classify_provider_error(error: BaseException) -> str:
    """Small shared failure taxonomy used to make fallback decisions observable."""
    text = str(error).lower()
    status = getattr(getattr(error, "response", None), "status_code", None)
    if status in (401, 403) or "authentication" in text or "api key" in text:
        return "authentication"
    if status == 429 or "rate limit" in text or "quota" in text:
        return "rate_limited"
    if status == 413 or "context length" in text or "context window" in text:
        return "context_exceeded"
    if status in (404, 422) and ("model" in text or "unsupported" in text):
        return "model_unavailable"
    if status and status >= 500:
        return "provider_outage"
    if "timeout" in text or isinstance(error, TimeoutError):
        return "timeout"
    if "connection" in text or "unavailable" in text:
        return "provider_outage"
    if "json" in text or "parse" in text or "invalid response" in text:
        return "invalid_response"
    return "unknown"


def should_failover(kind: str) -> bool:
    return kind in {
        "rate_limited",
        "model_unavailable",
        "provider_outage",
        "timeout",
        "invalid_response",
        "context_exceeded",
        "unknown",
    }
