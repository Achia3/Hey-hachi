import os
import time
import threading
import ollama
import requests
import json
import logging
import re
from datetime import datetime
from typing import Optional
from hachi_tools import AVAILABLE_TOOLS, execute_tool_call, fetch_url, search_web
from hachi_db import add_message, search_history, get_recent_messages

def split_into_subrequests(user_input: str) -> list[str]:
    """Heuristic splitter: break a user input containing multiple commands
    into smaller sub-requests. Conservative: splits when connector words
    (also/then/and/oh) precede an imperative/wh-word like open, launch,
    check, search, what, who, when.
    """
    if not user_input or not user_input.strip():
        return []
    s = user_input.strip()
    # Normalize newlines to spaces for matching
    normalized = re.sub(r"[\r\n]+", " ", s)
    # Find split points where a connector is followed by a verb/wh-word
    parts = []
    last = 0
    for m in re.finditer(r"\b(?:also|then|and|oh|also,|oh,|also:)\b\s+(open|launch|close|check|what|who|when|search|find|look|tell|show|open|launch|close)\b", normalized, flags=re.IGNORECASE):
        start = m.start()
        # keep previous segment
        seg = normalized[last:start].strip()
        if seg:
            parts.append(seg)
        last = start
    tail = normalized[last:].strip()
    if parts and tail:
        parts.append(tail)

    # Aggressive fallback (configurable): if conservative split didn't find
    # anything but the input contains multiple imperative verbs, optionally
    # split on common separators.
    if not parts and MULTI_SPLIT_AGGRESSIVE:
        aggressive_splits = re.split(r"(?:\band\b|\bthen\b|;|\.|\n)", normalized, flags=re.IGNORECASE)
        cand = [p.strip() for p in aggressive_splits if p.strip()]
        verb_re = re.compile(r"^(open|launch|close|check|what|who|when|search|find|look|tell|show|start|stop|please)\b", re.IGNORECASE)
        good = [c for c in cand if verb_re.search(c) or (len(c.split()) < 8 and any(v in c.lower() for v in ['open','launch','search','check','close','start','stop','what','who','when']))]
        if len(good) >= 2:
            logging.info(f"split_into_subrequests: aggressive split into {len(good)} parts")
            log_llm_event("splitter", user_input, [{"parts": good}])
            return good

    # If we didn't split, return original as single element
    return parts if parts else [s]

# Load .env for API keys (not committed to git).
# Try python-dotenv first, then a manual parser fallback so the key works even
# if the package isn't installed.
_ENV_PATH = os.path.join(os.path.dirname(__file__), ".env")
try:
    from dotenv import load_dotenv
    load_dotenv(_ENV_PATH)
except ImportError:
    try:
        if os.path.exists(_ENV_PATH):
            with open(_ENV_PATH, "r", encoding="utf-8") as _ef:
                for _line in _ef:
                    _line = _line.strip()
                    if _line and not _line.startswith("#") and "=" in _line:
                        _k, _v = _line.split("=", 1)
                        os.environ.setdefault(_k.strip(), _v.strip())
    except Exception:
        pass

def get_current_time_context() -> str:
    """Dynamically generate current system date/time context for the LLM."""
    now = datetime.now()
    return f"\n\nCURRENT DATE & TIME: {now.strftime('%A, %B %d, %Y, %I:%M %p')}"

# logging is configured by hachi_app.py (only one basicConfig call)

# Load configuration
CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.json")
MODEL_NAME = "qwen2.5:3b"
USE_DEEPSEEK = True
DEEPSEEK_API_KEY = ""
DEEPSEEK_MODEL = "deepseek-v4-flash"
DEEPSEEK_URL = "https://api.deepseek.com/chat/completions"

if os.path.exists(CONFIG_PATH):
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg = json.load(f)
            MODEL_NAME = cfg.get("model_name", "qwen2.5:3b")
            USE_DEEPSEEK = cfg.get("use_deepseek", True)
            DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "").strip() or cfg.get("deepseek_api_key", "").strip()
            DEEPSEEK_MODEL = cfg.get("deepseek_model", "deepseek-v4-flash")
    except Exception as e:
        logging.warning(f"Could not load config.json: {e}. Using defaults.")

# Multi-command splitter aggressiveness toggle (can be set in config.json)
MULTI_SPLIT_AGGRESSIVE = False
try:
    MULTI_SPLIT_AGGRESSIVE = bool(cfg.get("aggressive_split", False))
except Exception:
    MULTI_SPLIT_AGGRESSIVE = False

# In-memory LLM debug log (most recent N entries). Each entry: {ts, source, raw, parsed}
from collections import deque
_LLM_DEBUG_LOG_MAX = 80
_llm_debug_log = deque(maxlen=_LLM_DEBUG_LOG_MAX)

def log_llm_event(source: str, raw: str, parsed: list | None = None):
    try:
        _llm_debug_log.appendleft({
            "ts": int(time.time()),
            "source": source,
            "raw": raw[:20000],
            "parsed": parsed or []
        })
    except Exception:
        pass

def get_llm_debug(limit: int = 50):
    return list(_llm_debug_log)[:limit]

# ── Voice-optimised system prompt (short, no markdown, faster) ──────────────
VOICE_SYSTEM_PROMPT = """/no_think
You are Hachi, a fast AI voice assistant.
Respond naturally in English or Tagalog/Taglish.
Never use markdown, bullet points, or asterisks.

RESPONSE LENGTH RULES (critical for spoken answers):
- Commands, greetings, and simple requests: respond in exactly ONE short sentence.
- If the user asks for information, a web search, or an explanation, give a NORMAL, complete answer — do not truncate it. Be concise but cover the point.
- Never repeat the user's words back. Answer directly.

TOOL CALLING RULES (critical):
- launch_mode: call whenever user implies gaming/playing, studying/school, watching/movies, focusing/timer - even with casual phrasing like 'i wanna play', 'laro tayo', 'mag-aral', 'watch something'
- close_mode: call when user says stop/done/exit/quit for any mode
- Always call tools immediately without asking permission.

MEMORY:
- You have a memory database of past conversations and tasks. If the user references something from the past — a previous question, a task you did, a mode, or a topic you discussed — call the search_memory tool with relevant keywords before answering, and say what you recall.

Be direct, warm, and concise."""

SYSTEM_PROMPT = """You are Hachi, an agentic desktop AI assistant powered by Qwen.
You speak naturally in English or Tagalog/Taglish depending on what the user speaks.
Be clear, helpful, friendly, and informative.

CAPABILITIES:
- You DO have access to the internet. If the user asks if you have internet access or can browse, say YES and use your search_web or fetch_url tools to look things up in real-time.

TOOL CALLING RULES (follow these strictly):
1. Call launch_mode IMMEDIATELY when the user's message implies any of these intents - even with casual or indirect phrasing:
   - GAMING: 'i wanna play', 'let's game', 'game time', 'laro tayo', 'mag-games', 'open steam', 'time to game', 'i feel like playing something'
   - STUDY: 'time to study', 'mag-aral', 'i need to do homework', 'school work', 'open vscode'
   - MOVIE: 'watch a movie', 'movie time', 'manood', 'let's watch', 'movie night', 'netflix'
   - FOCUS: 'start a timer', 'pomodoro', '25 minutes', 'help me focus', 'deep work', 'mag-focus'
2. Call close_mode when user says stop/done/exit/close/end for any mode.
3. NEVER ask the user for clarification before calling a tool - infer their intent and act.
4. Always call search_web or fetch_url when the user asks to look something up or browse.
5. Call get_system_stats for CPU/RAM/battery questions.
6. If the user references something from the past (a previous question, task, mode, or topic), call search_memory with relevant keywords BEFORE answering, and recall what was said.

MEMORY:
- You have a memory database of all past conversations and tasks. Use it when the user asks about something you discussed before, their history, or wants to continue a past topic.

FORMATTING:
- Use **bold**, bullet points, numbered lists, and headers (##) for structured responses.
- For short answers, plain sentences are fine.
- Keep responses well-structured and easy to scan.

LENGTH:
- Be concise for simple questions — one sentence is ideal.
- For web-search results, explanations, or detailed questions, give a NORMAL, complete answer. Don't truncate it.
"""

# In-session short-term memory (resets on restart)
_session_history = []
_history_lock = threading.Lock()   # protects _session_history (voice + text interleave)


def _load_db_memory(max_turns: int = 12):
    """Preload recent conversations from SQLite into session memory so the model
    can 'remember' past chats across restarts (makes the DB a real memory, not
    just a write-only log)."""
    try:
        msgs = get_recent_messages(max_turns)
        with _history_lock:
            for m in msgs:
                _session_history.append({"role": m["role"], "content": m["content"]})
            if len(_session_history) > 20:
                del _session_history[:-20]
        logging.info(f"[Memory] Preloaded {len(msgs)} recent conversation turns from DB")
    except Exception as e:
        logging.warning(f"[Memory] Could not load DB history: {e}")


_load_db_memory()

# Engine attribution — set per request so the frontend can show which model ran
_last_engine = "qwen"              # "qwen" (local) or "deepseek" (cloud)

# Internal control tokens (pomodoro) — stripped from user-visible text, surfaced separately
_POMO_START = "__START_POMODORO__"
_POMO_STOP = "__STOP_POMODORO__"


class _EscalateToDeepSeek(Exception):
    """Internal signal: Qwen could not handle this — try DeepSeek."""


def _get_history(cap: int) -> list:
    """Thread-safe slice of the session history."""
    with _history_lock:
        return list(_session_history[-cap:])


def _update_history(user_msg: str, assistant_msg: str, cap: int = 20):
    """Thread-safe append to session history, trimmed to cap."""
    with _history_lock:
        _session_history.append({"role": "user", "content": user_msg})
        _session_history.append({"role": "assistant", "content": assistant_msg})
        if len(_session_history) > cap:
            del _session_history[:-cap]


def strip_control_tokens(text: str) -> str:
    """Remove internal control tokens (e.g. pomodoro markers) from user-visible text."""
    return text.replace(_POMO_START, "").replace(_POMO_STOP, "").strip()


def _detect_pomo(full_text: str, tools_info: list) -> Optional[str]:
    """Detect pomodoro intent from final text or executed tool output."""
    blob = (full_text or "") + " " + " ".join(str(t.get("output", "")) for t in tools_info)
    if _POMO_START in blob:
        return "start"
    if _POMO_STOP in blob:
        return "stop"
    return None


# Time-box for Qwen's tool-decide step: bounds worst-case latency so a slow
# local model never blocks voice mode. Escalates to DeepSeek past the budget.
_QWEN_DECIDE_TIMEOUT = 3.0


_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


LOOKUP_PHRASES = (
    "search", "google", "look up", "look up", "look-up", "browse", "find",
    "what is", "who is", "what are", "who are", "when is", "where is",
    "latest release", "release date", "released", "newest release",
    "size", "dimensions", "dimension", "weight", "spec", "specs", "specification",
    "model", "version", "product page", "official page", "official website",
    "news", "weather", "temperature", "how big", "how heavy",
)


def is_lookup_request(user_input: str) -> bool:
    """Return True when a query should browse/search instead of free-guessing."""
    lower = (user_input or "").lower()
    return any(phrase in lower for phrase in LOOKUP_PHRASES)


def build_lookup_query(user_input: str) -> str:
    """Normalize a natural-language lookup into a cleaner search query."""
    lower = (user_input or "").strip().lower()
    lower = re.sub(r"^(can you|could you|please|hey|hachi|would you|will you)\s+", "", lower)
    lower = re.sub(r"^(look\s*up|search\s*for|search|google|find|browse)\s+(for\s+)?", "", lower)
    lower = re.sub(r"^(what(?:'s| is)?|tell me|check|show me|can you tell me)\s+(?:the\s+)?", "", lower)
    lower = re.sub(r"\s+please$", "", lower)
    lower = re.sub(r"[?.!]+$", "", lower).strip()
    return lower or user_input.strip()


def _result_date(line: str):
    """Extract a date (YYYY-MM-DD, or 'Mon DD, YYYY') from a result line for
    freshness ranking. Returns a comparable tuple or None."""
    import re as _re
    m = _re.search(r"(\d{4})-(\d{2})-(\d{2})", line)
    if m:
        return (int(m.group(1)), int(m.group(2)), int(m.group(3)))
    m = _re.search(r"([A-Z][a-z]{2})\s+(\d{1,2}),\s*(\d{4})", line)
    if m:
        mon = _MONTHS.get(m.group(1).lower()[:3])
        if mon:
            return (int(m.group(3)), mon, int(m.group(2)))
    m = _re.search(r"(?:days?|hours?|weeks?|months?|minutes?)\s+ago", line)
    if m:
        return (9999, 99, 99)   # "X ago" → treat as very fresh
    return None


def _freshest_result(results_text: str):
    """Return the result line with the most recent date, plus a rough recency tag."""
    lines = [l for l in results_text.splitlines() if l.strip().startswith("•")]
    if not lines:
        return None, ""
    dated = [(_result_date(l), l) for l in lines if _result_date(l) is not None]
    if dated:
        # Sort newest first; tie-break by position in the original list
        dated.sort(key=lambda t: (t[0], -lines.index(t[1])), reverse=True)
        best_date, best_line = dated[0]
        tag = f"(dated {best_date[0]}-{best_date[1]:02d}-{best_date[2]:02d})" if best_date[0] < 9999 else "(recent)"
        return best_line, tag
    return lines[0], "(date unknown)"


def _parse_tool_args(raw_args, fn: str = "") -> dict:
    """Parse tool-call arguments, with lenient repair for the truncated JSON that
    DeepSeek sometimes emits (e.g. '{"query": "gaming laptop"' missing the '}').
    Returns a dict (possibly empty on unrecoverable failure)."""
    if not isinstance(raw_args, str):
        return raw_args or {}
    s = raw_args.strip()
    if not s:
        return {}
    # Try exact first
    try:
        parsed = json.loads(s)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        pass
    # Repair truncated JSON: append missing closing braces/quotes
    repaired = s
    if repaired.count('"') % 2 == 1:
        repaired += '"'
    if not repaired.rstrip().endswith("}"):
        repaired += "}"
    try:
        parsed = json.loads(repaired)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        pass
    # Last resort: extract key=value pairs from the fragment
    import re as _re
    pairs = _re.findall(r'"([^"]+)"\s*:\s*"([^"]*)"', s)
    if pairs:
        logging.warning(f"[parse_tool_args] repaired fragment for {fn}: {pairs}")
        return {k: v for k, v in pairs}
    logging.warning(f"[parse_tool_args] could not parse args for {fn}: {raw_args[:80]!r}")
    return {}


def _trim_results(results_text: str, max_lines: int = 4, max_chars: int = 1200) -> str:
    """Keep only the top few results and cap total size so Qwen isn't chewing
    a huge dump (the main latency driver)."""
    lines = [l for l in results_text.splitlines() if l.strip()]
    kept = []
    for line in lines:
        if line.startswith("**Live Web Search results"):
            kept.append(line)   # keep the header
            continue
        if line.startswith("•"):
            kept.append(line)
            if len([k for k in kept if k.startswith("•")]) >= max_lines:
                break
    trimmed = "\n".join(kept).strip()
    if len(trimmed) > max_chars:
        trimmed = trimmed[:max_chars] + "…"
    return trimmed or results_text


def _qwen_summarize_search(query: str, results_text: str, timeout: float = 12.0) -> str:
    """
    Have Qwen read web-search results and give the user a clean natural answer
    instead of dumping raw DuckDuckGo output. Surfaces the FRESHEST result
    explicitly (so priors don't beat fresh data), tells Qwen not to invent
    numbers, caps the answer, and falls back to raw results on timeout/offline.
    """
    if not results_text or not results_text.strip():
        return results_text

    # Pre-clean and keep only the top 3 result lines to reduce noise
    lines = [l for l in results_text.splitlines() if l.strip().startswith("•")]
    top_lines = lines[:3]
    trimmed = "\n".join(top_lines)

    freshest, freshest_tag = _freshest_result(results_text)

    # Try to extract URL from the freshest line to fetch full page content
    url_match = re.search(r"(https?://[^)\s]+)", freshest or "")
    top_url = url_match.group(1) if url_match else None

    # Deterministic summarization settings
    qwen_opts = {"num_predict": 250, "temperature": 0.0}

    def _call_qwen(system_msg: str, user_msg: str, opts: dict, out_dict: dict):
        try:
            resp = ollama.chat(model=MODEL_NAME, messages=[
                {"role": "system", "content": system_msg},
                {"role": "user", "content": user_msg},
            ], options=opts)
            out_dict["text"] = resp.message.content or ""
            out_dict["raw_resp"] = resp
        except Exception as e:
            out_dict["error"] = e

    # Prefer summarizing the full page body when available
    if top_url:
        try:
            page = fetch_url(top_url)
            # fetch_url returns a string starting with '**Content from', or an error string
            if page and page.startswith("**Content from"):
                system_msg = "You are Hachi, a concise and factual assistant. Trust the page content supplied and do not hallucinate. If the page doesn't contain the answer, say 'no confirmed answer'."
                user_msg = f"USER QUERY: {query}\n\nMOST RECENT URL: {top_url}\n\nPAGE CONTENT:\n{page}"
                out = {}
                t = threading.Thread(target=_call_qwen, args=(system_msg, user_msg, qwen_opts, out), daemon=True)
                t.start(); t.join(timeout=timeout)
                if "text" in out and out["text"].strip():
                    log_llm_event("qwen_search_summary", user_msg, [{"summary": out["text"].strip()}])
                    return clean_thinking(out["text"]).strip()
                # else fallthrough to snippet-summary
        except Exception as e:
            logging.warning(f"fetch_url or qwen page-summarize failed: {e}")

    # Snippet-based summary (fallback)
    system_msg = "You are Hachi, a concise and factual assistant. Trust the MOST RECENT result provided; do not invent. If the answer is not present, say 'no confirmed answer'."
    user_msg = (
        f"USER QUERY: {query}\n\nSEARCH RESULTS (top 3):\n{trimmed}\n\nMOST RECENT {freshest_tag}: {freshest}"
    )

    out = {}
    t = threading.Thread(target=_call_qwen, args=(system_msg, user_msg, qwen_opts, out), daemon=True)
    t.start(); t.join(timeout=timeout)

    # Retry once with slightly relaxed timeout/num_predict if response missing or unhelpful
    result_text = ""
    if "text" in out and out["text"].strip():
        result_text = clean_thinking(out["text"]).strip()
    else:
        # Retry with more tokens
        qwen_opts_retry = {"num_predict": 400, "temperature": 0.0}
        out2 = {}
        t2 = threading.Thread(target=_call_qwen, args=(system_msg, user_msg, qwen_opts_retry, out2), daemon=True)
        t2.start(); t2.join(timeout=timeout + 6)
        if "text" in out2 and out2["text"].strip():
            result_text = clean_thinking(out2["text"]).strip()
            out = out2

    # Log prompt, raw results, and qwen response for observability
    try:
        log_llm_event("qwen_search_prompt", user_msg, [{"response": result_text[:2000]}])
    except Exception:
        pass

    if result_text:
        return result_text

    logging.warning(f"[Qwen] search-summarize returned empty; returning raw results")
    return results_text


def _qwen_tool_decide(messages, timeout: float = _QWEN_DECIDE_TIMEOUT,
                      escalate_on_timeout: bool = True):
    """
    Run Qwen's tool-decide step in a time-boxed thread.
    Returns (msg, tool_calls). On timeout escalates to DeepSeek (raises
    _EscalateToDeepSeek) unless escalate_on_timeout=False, in which case it
    returns (None, []). On model error it propagates the exception so the
    caller's existing except-handler decides the fallback.
    """
    result = {}

    def _decide():
        try:
            result["resp"] = ollama.chat(
                model=MODEL_NAME, messages=messages, tools=AVAILABLE_TOOLS,
                options={"num_predict": 200, "temperature": 0.7},
            )
        except Exception as e:
            result["error"] = e

    t = threading.Thread(target=_decide, daemon=True)
    t.start()
    t.join(timeout=timeout)

    if "resp" in result:
        msg = result["resp"].message
        return msg, (msg.tool_calls or [])
    if "error" in result:
        if escalate_on_timeout:
            raise result["error"]
        return None, []
    # Timed out — the daemon thread keeps running but we move on
    logging.info("[Qwen] Tool-decide timed out after %.1fs", timeout)
    if escalate_on_timeout:
        raise _EscalateToDeepSeek()
    return None, []


def clean_thinking(response_text: str) -> str:
    """Strip out Qwen internal reasoning thinking blocks."""
    cleaned = re.sub(r'<think>.*?</think>', '', response_text, flags=re.DOTALL)
    return cleaned.strip()

def parse_dsml_tool_calls(text: str) -> list[dict]:
    """
    Parses custom DeepSeek DSML tool call tags from text.
    Format:
    < | | DSML | | tool_calls>
    < | | DSML | | invoke name="tool_name">
    < | | DSML | | parameter name="arg_name" string="true">value</ | | DSML | | parameter>
    </ | | DSML | | invoke>
    </ | | DSML | | tool_calls>
    """
    tool_calls = []
    # Normalize extreme whitespace variants like '< I I DSML I I' by
    # collapsing whitespace INSIDE angle-brackets when 'DSML' appears.
    def _norm_dsml_tag(m):
        inner = m.group(1)
        compact = re.sub(r'\s+', '', inner)
        return f"<{compact}>"
    cleaned = re.sub(r'<([^>]*(?:DSML)[^>]*)>', _norm_dsml_tag, text, flags=re.IGNORECASE)
    # Standardize the common well-formed form used elsewhere
    cleaned = re.sub(r'<\s*\|\s*\|\s*DSML\s*\|\s*\|', '<||DSML||', cleaned)
    cleaned = re.sub(r'</\s*\|\s*\|\s*DSML\s*\|\s*\|', '</||DSML||', cleaned)

    invoke_blocks = re.findall(r'<\|\|DSML\|\|invoke name="([^"]+)"\s*>(.*?)</\|\|DSML\|\|invoke\s*>', cleaned, flags=re.DOTALL)
    # Fallback: be lenient with malformed DSML variants (spaces, odd characters)
    used_fallback = False
    if not invoke_blocks:
        # Try a looser match on malformed tags (e.g. '< I I DSML I I invoke ...>')
        invoke_blocks = re.findall(r'<[^>]*DSML[^>]*invoke[^>]*name\s*=\s*"([^"]+)"[^>]*>(.*?)</[^>]*invoke[^>]*>', text, flags=re.DOTALL | re.IGNORECASE)
        if invoke_blocks:
            used_fallback = True
    # If still empty, attempt a cleaned-replacement repair of common broken patterns
    if not invoke_blocks:
        repaired = re.sub(r'\bI\b\s*I\b', '||', text)
        repaired = re.sub(r'<\s*I\s*I\s*DSML\s*I\s*I\s*>', '<||DSML||>', repaired, flags=re.IGNORECASE)
        invoke_blocks = re.findall(r'<\|\|DSML\|\|invoke name="([^"]+)"\s*>(.*?)</\|\|DSML\|\|invoke\s*>', repaired, flags=re.DOTALL)
        if invoke_blocks:
            used_fallback = True

    for name, block in invoke_blocks:
        params = {}
        param_matches = re.findall(r'<\|\|DSML\|\|parameter name="([^"]+)"[^>]*>(.*?)</\|\|DSML\|\|parameter\s*>', block, flags=re.DOTALL)
        if not param_matches:
            # Fallback parameter matching for malformed tags
            param_matches = re.findall(r'<[^>]*parameter[^>]*name\s*=\s*"([^"]+)"[^>]*>(.*?)</[^>]*parameter[^>]*>', block, flags=re.DOTALL | re.IGNORECASE)
        for p_name, p_val in param_matches:
            params[p_name] = p_val.strip()

        tool_calls.append({
            "id": f"call_dsml_{int(time.time())}",
            "type": "function",
            "function": {
                "name": name,
                "arguments": json.dumps(params)
            }
        })
    # Record debug log
    try:
        log_llm_event("parse_dsml", text, tool_calls)
    except Exception:
        pass
    if used_fallback:
        logging.info("parse_dsml_tool_calls: used fallback loose-DSML parsing for malformed tags")
    return tool_calls

def strip_dsml(text: str) -> str:
    """Strips all DSML blocks and loose DSML tags from output text."""
    cleaned = re.sub(r'<\s*\|\s*\|\s*DSML\s*\|\s*\|tool_calls>.*?</\s*\|\s*\|\s*DSML\s*\|\s*\|tool_calls>', '', text, flags=re.DOTALL)
    cleaned = re.sub(r'<\s*/?\s*\|\s*\|\s*DSML\s*\|\s*\|.*?>', '', cleaned)
    return cleaned.strip()

def detect_intent_tool_call(user_input: str):
    """
    Intent Fallback for small local models or safety checks.
    Ensures tools are executed even if a small model omits the JSON tool_call structure.
    """
    lower = user_input.lower().strip()

    # Close mode triggers
    if any(p in lower for p in ["stop gaming", "exit game", "close game", "done playing"]):
        return "close_mode", {"mode_name": "gaming"}
    if any(p in lower for p in ["stop study", "exit study", "done studying"]):
        return "close_mode", {"mode_name": "study"}
    if any(p in lower for p in ["stop timer", "stop focus", "stop pomodoro"]):
        return "close_mode", {"mode_name": "focus"}

    # Gaming intent
    gaming_patterns = ["play", "game", "gaming", "steam", "discord", "laro", "maglaro", "mag-laro"]
    if any(p in lower for p in gaming_patterns) and not any(neg in lower for neg in ["don't", "no ", "stop", "close"]):
        return "launch_mode", {"mode_name": "gaming"}

    # Study intent
    study_patterns = ["study", "homework", "vscode", "aral", "mag-aral", "magaral", "school"]
    if any(p in lower for p in study_patterns) and not any(neg in lower for neg in ["don't", "no ", "stop", "close"]):
        return "launch_mode", {"mode_name": "study"}

    # Movie intent
    movie_patterns = ["movie", "watch", "film", "manood", "netflix"]
    if any(p in lower for p in movie_patterns) and not any(neg in lower for neg in ["don't", "no ", "stop", "close"]):
        return "launch_mode", {"mode_name": "movie"}

    # Focus / Pomodoro intent
    focus_patterns = ["focus", "pomodoro", "timer", "25 min", "deep work", "clock"]
    if any(p in lower for p in focus_patterns) and not any(neg in lower for neg in ["don't", "no ", "stop", "close"]):
        return "launch_mode", {"mode_name": "focus"}

    return None, None

# DeepSeek v4 spends hidden reasoning tokens before the visible answer. A tight
# max_tokens on a reasoning/web-search query silently empties the response
# (finish_reason='length' with empty content). So: small cap ONLY for simple
# one-liners and tool-decide; any non-simple intent gets room for a full answer.
def _answer_budget(intent: str, user_input: str) -> int:
    if intent in ("GREETING", "SIMPLE_CHAT"):
        return 150      # simple chat → short
    return 700          # tool calls, web search, explanations, reasoning → full answer

def call_deepseek_chat(messages, tools=None, max_tokens=None, temperature=0.7, timeout=25):
    """Call DeepSeek API (OpenAI-compatible) synchronously with tool support."""
    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": DEEPSEEK_MODEL,
        "messages": messages,
        "temperature": temperature
    }
    if tools:
        payload["tools"] = tools
    if max_tokens:
        payload["max_tokens"] = max_tokens

    res = requests.post(DEEPSEEK_URL, headers=headers, json=payload, timeout=timeout)
    res.raise_for_status()
    return res.json()


def check_fast_intent(user_input: str) -> Optional[tuple[str, list]]:
    """
    Fast local command execution bypass (takes ~50ms).
    Matches common computer operations/commands via regex and runs the tool directly.

    Why keywords? This is a SPEED optimization, not the agentic brain. Explicit
    instant commands ("open notepad", "what time is it", "search for X") skip
    BOTH LLMs and execute in ~50ms. Everything this misses falls through to the
    real agentic path (Qwen for text, DeepSeek for voice), which does the actual
    LLM reasoning and tool-call decisions.
    """
    lower = user_input.lower().strip()

    # 1. Shutdown / Turn off
    if any(p in lower for p in ["shutdown", "turn off", "kill hachi", "patayin si hachi", "patayin", "turn-off"]):
        execute_tool_call("shutdown_hachi", {})
        return "Shutting down Hachi and Ollama to free system resources. Paalam!", [{"tool": "shutdown_hachi", "args": {}, "output": "Success"}]

    # 2. Close modes
    if any(p in lower for p in ["stop gaming", "exit game", "close game", "done playing"]):
        res = execute_tool_call("close_mode", {"mode_name": "gaming"})
        return res, [{"tool": "close_mode", "args": {"mode_name": "gaming"}, "output": res}]
    if any(p in lower for p in ["stop study", "exit study", "done studying", "close vscode"]):
        res = execute_tool_call("close_mode", {"mode_name": "study"})
        return res, [{"tool": "close_mode", "args": {"mode_name": "study"}, "output": res}]
    if any(p in lower for p in ["stop timer", "stop focus", "stop pomodoro", "end timer"]):
        res = execute_tool_call("close_mode", {"mode_name": "focus"})
        return res, [{"tool": "close_mode", "args": {"mode_name": "focus"}, "output": res}]

    # 3. Launch modes
    if any(p in lower for p in ["gaming mode", "play games", "game time", "laro tayo", "mag-laro"]):
        res = execute_tool_call("launch_mode", {"mode_name": "gaming"})
        return res, [{"tool": "launch_mode", "args": {"mode_name": "gaming"}, "output": res}]
    if any(p in lower for p in ["study mode", "time to study", "mag-aral", "homework"]):
        res = execute_tool_call("launch_mode", {"mode_name": "study"})
        return res, [{"tool": "launch_mode", "args": {"mode_name": "study"}, "output": res}]
    if any(p in lower for p in ["movie mode", "movie time", "netflix", "watch a movie"]):
        res = execute_tool_call("launch_mode", {"mode_name": "movie"})
        return res, [{"tool": "launch_mode", "args": {"mode_name": "movie"}, "output": res}]
    if any(p in lower for p in ["focus mode", "start a timer", "pomodoro", "start focus"]):
        res = execute_tool_call("launch_mode", {"mode_name": "focus"})
        return res, [{"tool": "launch_mode", "args": {"mode_name": "focus"}, "output": res}]

    # 4. Time / Date queries (instant, no LLM needed)
    if any(p in lower for p in ["what time is it", "what time", "what's the time", "current time"]):
        from datetime import datetime
        now = datetime.now().strftime("%I:%M %p on %A, %B %d")
        return f"It's {now}.", [{"tool": "get_current_time", "args": {}, "output": now}]
    if any(p in lower for p in ["what day is it", "what day", "what's today", "today's date", "date today"]):
        from datetime import datetime
        today = datetime.now().strftime("%A, %B %d, %Y")
        return f"Today is {today}.", [{"tool": "get_current_date", "args": {}, "output": today}]

    # 5. System Stats
    if any(p in lower for p in ["system stats", "cpu usage", "ram usage", "battery status", "computer stats"]):
        res = execute_tool_call("get_system_stats", {})
        return res, [{"tool": "get_system_stats", "args": {}, "output": res}]

    # 5. Dynamic App Launching ("open [app]")
    m_launch = re.search(r"\b(?:open|launch|start|run)\s+(.+?)(?:\s+(?:for me|please|pls|na|naman|po))?[.?!]?$", lower)
    if m_launch:
        app_name = m_launch.group(1).strip()
        # ignore mode names
        if app_name not in ["gaming", "study", "movie", "focus", "timer", "pomodoro", "hachi"]:
            res = execute_tool_call("launch_app", {"app_name": app_name})
            return res, [{"tool": "launch_app", "args": {"app_name": app_name}, "output": res}]

    # 6. Dynamic App Closing ("close [app]" or "kill [app]")
    m_close = re.search(r"\b(?:close|kill|exit|quit)\s+(.+?)(?:\s+(?:for me|please|pls|na|naman|po))?[.?!]?$", lower)
    if m_close:
        app_name = m_close.group(1).strip()
        if app_name not in ["gaming", "study", "movie", "focus", "timer", "pomodoro", "hachi"]:
            res = execute_tool_call("close_app", {"app_name": app_name})
            return res, [{"tool": "close_app", "args": {"app_name": app_name}, "output": res}]

    # 7. Weather (instant — regex → get_weather tool, no LLM)
    weather_loc = None
    m_w = re.search(r"\b(?:weather|temperature|panahon)\s+(?:in|at|sa)\s+([a-z0-9 ,'.-]+?)[.?!]?$", lower)
    if not m_w:
        m_w = re.search(r"\b(?:what'?s|what is|how'?s|how is)\s+(?:the\s+)?(?:weather|temperature)\s+(?:like\s+)?(?:in|at|sa|dito sa)\s+([a-z0-9 ,'.-]+?)[.?!]?$", lower)
    if m_w:
        weather_loc = m_w.group(1).strip()
    elif re.search(r"\b(?:how'?s the weather|what'?s the weather|how is the weather|weather (?:today|now|forecast|outside)|ano(?:ng)? panahon|kumusta ang panahon)\b", lower):
        weather_loc = "Manila"
    if weather_loc:
        res = execute_tool_call("get_weather", {"location": weather_loc})
        return res, [{"tool": "get_weather", "args": {"location": weather_loc}, "output": res}]

    # 8. Web/spec lookup — if DeepSeek is available, PASS THROUGH to the DeepSeek brain
    #    so it searches + summarizes seamlessly (same as voice). Only fall back to
    #    the raw/Qwen path when DeepSeek is disabled or missing a key.
    if is_lookup_request(user_input) and not re.search(r"\b(memory|history|conversation|usapan|alaala)\b", lower):
        query = build_lookup_query(user_input)
        if USE_DEEPSEEK and DEEPSEEK_API_KEY:
            return None   # let the DeepSeek brain handle it
        raw = execute_tool_call("search_web", {"query": query})
        answer = _qwen_summarize_search(query, raw)
        return answer, [{"tool": "search_web", "args": {"query": query}, "output": raw}]

    return None


def classify_intent(user_input: str) -> str:
    """
    Classify user input into routing tiers (~1ms, pure keyword matching).
    Returns: GREETING, SIMPLE_CHAT, TOOL_NEEDED, or COMPLEX
    """
    lower = user_input.lower().strip()
    words = lower.split()
    word_count = len(words)

    # Tier: Greetings / pleasantries (short, casual)
    GREETINGS = {
        "hi", "hello", "hey", "hachi", "sup", "yo", "bye", "goodbye",
        "good morning", "good night", "good evening", "good afternoon",
        "thanks", "thank you", "salamat", "kumusta", "kamusta",
        "how are you", "what's up", "whats up", "magandang",
        "paalam", "ingat", "nice", "cool", "ok", "okay", "sure",
        "haha", "lol", "hehe", "wow",
    }
    if word_count <= 6 and any(g in lower for g in GREETINGS):
        # Don't classify as greeting if the message also has tool keywords
        # e.g. "ok what is the weather" should route to TOOL_NEEDED, not GREETING
        _TOOL_CHECK = {
            "weather", "temperature", "search", "google", "look up", "look-up",
            "find", "what is", "who is", "when is", "where is", "news",
            "cpu", "ram", "battery", "system", "stats",
            "open", "launch", "close", "kill", "start", "run",
            "fetch", "browse", "website", "url",
        }
        if not any(m in lower for m in _TOOL_CHECK):
            return "GREETING"
        # Otherwise fall through to next tier

    # Tier: Tool-needing queries
    TOOL_MARKERS = {
        "weather", "temperature", "search", "google", "look up", "look-up",
        "find", "what is", "who is", "when is", "where is", "news",
        "cpu", "ram", "battery", "system", "stats",
        "open", "launch", "close", "kill", "start", "run",
        "fetch", "browse", "website", "url",
        "size", "dimensions", "dimension", "weight", "spec", "specs",
        "specification", "latest release", "release date", "version", "model",
        "official page", "official website", "product page",
    }
    if any(m in lower for m in TOOL_MARKERS):
        return "TOOL_NEEDED"

    # Tier: Complex queries needing DeepSeek
    COMPLEX_MARKERS = {
        "explain", "compare", "analyze", "analyse", "write me", "create a",
        "help me with", "how do i", "how can i", "step by step", "code",
        "debug", "summarize", "research", "in detail", "elaborate",
        "difference between", "pros and cons", "what are the",
        "give me a", "list of", "teach me",
    }
    if any(m in lower for m in COMPLEX_MARKERS):
        return "COMPLEX"

    # Default: simple chat, Qwen handles it
    return "SIMPLE_CHAT"


def process_agent_request(user_input: str, current_mode: str = "default"):
    """
    Process user input through Local Qwen (Primary Brain for chat/tools).
    DeepSeek API assists only for complex reasoning or when Qwen fails.
    Returns tuple: (final_text, executed_tools_info, engine, pomo)
    engine: "qwen" | "deepseek" | "none"; pomo: "start"|"stop"|None
    """
    global _last_engine

    if not user_input or not user_input.strip():
        return "", [], "none", None

    # Multi-command handling: split conservative sub-requests and run them
    subs = split_into_subrequests(user_input)
    if len(subs) > 1:
        combined_texts = []
        combined_tools = []
        engines = []
        pomos = []
        for sub in subs:
            t, tools, eng, pomo = process_agent_request(sub, current_mode)
            if t:
                combined_texts.append(t)
            if tools:
                combined_tools.extend(tools)
            engines.append(eng)
            pomos.append(pomo)
        final = " \n---\n ".join(combined_texts)
        return final, combined_tools, (engines[-1] if engines else "none"), (pomos[-1] if pomos else None)

    # ── Fast Command Bypass (takes ~50ms) ──────────────────────────────────
    fast_res = check_fast_intent(user_input)
    if fast_res:
        spoken, executed = fast_res
        _last_engine = "qwen"
        pomo = _detect_pomo(spoken, executed)
        spoken = strip_control_tokens(spoken)
        add_message("user", user_input, current_mode)
        add_message("assistant", spoken, current_mode)
        _update_history(user_input, spoken)
        logging.info(f"[Engine] Qwen (local) — fast bypass")
        return spoken, executed, "qwen", pomo

    # ── Intent Router: classify and route to appropriate engine ─────────────
    intent = classify_intent(user_input)
    logging.info(f"[Router] Intent={intent} for: '{user_input}' (Mode: {current_mode})")
    add_message("user", user_input, current_mode)

    history_slice = _get_history(16)
    sys_content = SYSTEM_PROMPT + get_current_time_context()
    messages = [{"role": "system", "content": sys_content}] + history_slice + [{"role": "user", "content": user_input}]
    executed_tools_info = []

    # ── GREETING / SIMPLE_CHAT: Qwen only, no tools, fast ───────────────────
    if intent in ("GREETING", "SIMPLE_CHAT"):
        try:
            _last_engine = "qwen"
            logging.info(f"[Qwen Fast] Simple chat/greeting — skipping DeepSeek")
            fast_opts = {"num_predict": 150, "temperature": 0.8}  # brevity: simple chat = 1-2 sentences
            response = ollama.chat(model=MODEL_NAME, messages=messages, options=fast_opts)
            final_text = strip_control_tokens(clean_thinking(response.message.content or ""))
            _update_history(user_input, final_text)
            add_message("assistant", final_text, current_mode)
            logging.info("[Engine] Qwen (local)")
            return final_text, [], "qwen", None
        except Exception as e:
            logging.warning(f"[Qwen Fast] Error: {e}, falling through to standard path")

    # ── TOOL_NEEDED: Qwen with tools first, DeepSeek fallback ───────────────
    if intent == "TOOL_NEEDED":
        try:
            _last_engine = "qwen"
            logging.info(f"[Qwen Tools] Tool-needing query — Qwen with tools (time-boxed)")
            msg, tool_calls = _qwen_tool_decide(messages)

            if not tool_calls:
                fb_fn, fb_args = detect_intent_tool_call(user_input)
                if fb_fn: tool_calls = [{"function": {"name": fb_fn, "arguments": fb_args}}]
                elif intent == "TOOL_NEEDED":
                    # Qwen + regex both missed the tool → let DeepSeek try
                    raise _EscalateToDeepSeek()

            if tool_calls:
                # Normalize tool_calls to DICT args BEFORE the follow-up call —
                # Ollama rejects string-args (fixes the '{"mode_name": "gaming"}'
                # validation error that cascaded to "connection error").
                cleaned_calls = []
                for tc in tool_calls:
                    if isinstance(tc, dict):
                        fn = tc["function"]["name"]
                        args = _parse_tool_args(tc["function"].get("arguments"), fn)
                    else:
                        fn = tc.function.name
                        args = _parse_tool_args(tc.function.arguments, fn)
                    cleaned_calls.append({"type": "function", "function": {"name": fn, "arguments": args}})
                assistant_msg = {
                    "role": "assistant",
                    "content": getattr(msg, "content", "") or "",
                    "tool_calls": cleaned_calls,
                }
                messages.append(assistant_msg)
                for tc, call in zip(tool_calls, cleaned_calls):
                    fn = call["function"]["name"]
                    args = call["function"]["arguments"]
                    result = execute_tool_call(fn, args)
                    executed_tools_info.append({"tool": fn, "args": args, "output": str(result)})
                    messages.append({"role": "tool", "name": fn, "content": str(result)})

                final_res = ollama.chat(model=MODEL_NAME, messages=messages)
                final_text = clean_thinking(final_res.message.content or "")
            else:
                final_text = clean_thinking(msg.content or "")

            pomo = _detect_pomo(final_text, executed_tools_info)
            final_text = strip_control_tokens(final_text)
            _update_history(user_input, final_text)
            add_message("assistant", final_text, current_mode)
            logging.info("[Engine] Qwen (local)")
            return final_text, executed_tools_info, "qwen", pomo

        except _EscalateToDeepSeek:
            logging.info("[Router] Qwen produced no tool call — escalating to DeepSeek")
        except Exception as e:
            logging.warning(f"[Qwen Tools] Error: {e}, falling through to DeepSeek")

    # ── COMPLEX (or escalation): DeepSeek API ──────────────────────────────
    if USE_DEEPSEEK and DEEPSEEK_API_KEY:
        try:
            _last_engine = "deepseek"
            logging.info(f"[DeepSeek Primary] Processing '{user_input}'...")
            res1 = call_deepseek_chat(messages, tools=AVAILABLE_TOOLS, max_tokens=80)
            choice1 = res1["choices"][0]["message"]
            content1 = choice1.get("content", "") or ""
            tool_calls = choice1.get("tool_calls", [])

            if not tool_calls and "<" in content1 and "DSML" in content1:
                logging.info("DeepSeek returned DSML-like content; attempting parse_dsml_tool_calls")
                tool_calls = parse_dsml_tool_calls(content1)

            if not tool_calls:
                fb_fn, fb_args = detect_intent_tool_call(user_input)
                if fb_fn:
                    tool_calls = [{"id": f"call_fb_{int(time.time())}", "function": {"name": fb_fn, "arguments": json.dumps(fb_args)}}]

            if tool_calls:
                if not choice1.get("content"):
                    choice1["content"] = content1
                if "tool_calls" not in choice1 or not choice1["tool_calls"]:
                    choice1["tool_calls"] = tool_calls
                messages.append(choice1)
                for tc in tool_calls:
                    fn = tc["function"]["name"]
                    raw_args = tc["function"]["arguments"]
                    args = _parse_tool_args(raw_args, fn)
                    logging.info(f"DeepSeek -> executing tool {fn} with args {args}")
                    result = execute_tool_call(fn, args)
                    executed_tools_info.append({"tool": fn, "args": args, "output": str(result)})
                    messages.append({"role": "tool", "tool_call_id": tc.get("id", f"call_{int(time.time())}"), "name": fn, "content": str(result)})

                res2 = call_deepseek_chat(messages, max_tokens=_answer_budget(intent, user_input))
                final_text = res2["choices"][0]["message"].get("content", "") or ""
            else:
                final_text = content1

            pomo = _detect_pomo(final_text, executed_tools_info)
            cleaned_text = strip_control_tokens(strip_dsml(clean_thinking(final_text)))
            _update_history(user_input, cleaned_text)
            add_message("assistant", cleaned_text, current_mode)
            logging.info("[Engine] DeepSeek (cloud)")
            return cleaned_text, executed_tools_info, "deepseek", pomo

        except Exception as ds_err:
            logging.warning(f"[DeepSeek Primary Error] {ds_err}. Falling back to Qwen...")

    # ── FALLBACK ENGINE: Local Qwen via Ollama (Offline / Failover) ─────────
    try:
        _last_engine = "qwen"
        logging.info(f"[Qwen Fallback] Calling local model '{MODEL_NAME}'...")
        msg = None
        tool_calls = []
        for _attempt in range(2):
            msg, tool_calls = _qwen_tool_decide(messages, escalate_on_timeout=False)
            if msg is not None:
                break
            time.sleep(1)

        # Intent fallback to ensure tools execute 100% reliably with Qwen
        if msg is not None and not tool_calls:
            fb_fn, fb_args = detect_intent_tool_call(user_input)
            if fb_fn: tool_calls = [{"function": {"name": fb_fn, "arguments": fb_args}}]

        if tool_calls and msg is not None:
            # Normalize tool_calls to DICT args (Ollama rejects string-args)
            cleaned_calls = []
            for tool_call in tool_calls:
                if isinstance(tool_call, dict):
                    func_name = tool_call["function"]["name"]
                    func_args = _parse_tool_args(tool_call["function"].get("arguments"), func_name)
                else:
                    func_name = tool_call.function.name
                    func_args = _parse_tool_args(tool_call.function.arguments, func_name)
                cleaned_calls.append({"type": "function", "function": {"name": func_name, "arguments": func_args}})
            messages.append({
                "role": "assistant",
                "content": getattr(msg, "content", "") or "",
                "tool_calls": cleaned_calls,
            })
            for tool_call, call in zip(tool_calls, cleaned_calls):
                func_name = call["function"]["name"]
                func_args = call["function"]["arguments"]

                logging.info(f"[Qwen Tool Triggered] {func_name} ({func_args})")
                tool_output = execute_tool_call(func_name, func_args)
                executed_tools_info.append({"tool": func_name, "args": func_args, "output": str(tool_output)})
                messages.append({"role": "tool", "name": func_name, "content": str(tool_output)})

            final_res = ollama.chat(model=MODEL_NAME, messages=messages)
            final_text = final_res.message.content or ""
        elif msg is not None:
            final_text = msg.content or ""
        else:
            # Qwen tool-decide unavailable (timeout/error) — get a plain reply
            try:
                resp = ollama.chat(model=MODEL_NAME, messages=messages,
                                   options={"num_predict": 250, "temperature": 0.75})
                final_text = resp.message.content or ""
            except Exception:
                final_text = ""

        pomo = _detect_pomo(final_text, executed_tools_info)
        cleaned_text = strip_control_tokens(clean_thinking(final_text))
        _update_history(user_input, cleaned_text)
        add_message("assistant", cleaned_text, current_mode)
        logging.info("[Engine] Qwen (local)")
        return cleaned_text, executed_tools_info, "qwen", pomo

    except Exception as qwen_err:
        logging.error(f"[Qwen Fallback Error] {qwen_err}")

    err_msg = f"Sorry, I encountered an issue. Please check Ollama or your connection."
    add_message("assistant", err_msg, current_mode)
    return err_msg, [], "none", None


# ── Voice mode streaming: DeepSeek-primary voice brain, Qwen-first text chat

def process_agent_request_stream(user_input: str, current_mode: str = "default", voice_mode: bool = False):
    """
    Stream for text chat (Qwen-first) and voice (DeepSeek-primary).

    voice_mode=True: DeepSeek (cloud) understands the user, decides which tool to
      call (including search_web/fetch_url — so it can actually browse), the tool
      runs LOCALLY, and DeepSeek synthesizes the spoken answer. Qwen is the
      offline fallback. This is "DeepSeek = voice brain, Qwen/local = tools".

    voice_mode=False (typed text chat): Qwen (local) is primary; DeepSeek escalates
      only for complex reasoning or when Qwen can't produce a tool call.

    Speed safeguards in both: regex command bypass (~50ms) + token streaming.
    """
    global _last_engine

    if not user_input or not user_input.strip():
        yield {"done": True, "full": "", "tools": [], "engine": _last_engine, "pomo": None}
        return

    # Multi-command handling for streams: break into subrequests and yield each
    subs = split_into_subrequests(user_input)
    if len(subs) > 1:
        for sub in subs:
            for evt in process_agent_request_stream(sub, current_mode, voice_mode):
                yield evt
        return

    # ── Speed safeguard: Fast Command Bypass (~50ms, no LLM) ────────────────
    fast_res = check_fast_intent(user_input)
    if fast_res:
        spoken, executed = fast_res
        _last_engine = "qwen"
        pomo = _detect_pomo(spoken, executed)
        spoken = strip_control_tokens(spoken)
        add_message("user", user_input, current_mode)
        add_message("assistant", spoken, current_mode)
        _update_history(user_input, spoken, cap=16)
        logging.info("[Engine] Qwen (local) — fast bypass")
        yield {"done": True, "full": spoken, "tools": executed, "engine": "qwen", "pomo": pomo}
        return

    # ── Intent Router ───────────────────────────────────────────────────────
    intent = classify_intent(user_input)
    logging.info(f"[STREAM] Intent={intent} voice_mode={voice_mode} for: '{user_input}'")
    _low = user_input.lower()
    _is_memory = any(k in _low for k in ("remember", "what did i ask", "what did i say",
                                         "what did we discuss", "our past conversation",
                                         "what did we talk about", "do you remember",
                                         "recall", "what happened before", "earlier"))
    # Memory recalls are meta-queries — don't log them into the DB (they'd pollute
    # future recalls). Everything else gets logged as a normal user turn.
    if not _is_memory:
        add_message("user", user_input, current_mode)

    history_slice = _get_history(10)
    sys_content = VOICE_SYSTEM_PROMPT + get_current_time_context()
    messages = [{"role": "system", "content": sys_content}] + history_slice + [{"role": "user", "content": user_input}]
    executed_tools_info = []

    # ── DEEPSEEK-PRIMARY brain for voice AND for web-search/info/memory in text chat ──
    # Voice: DeepSeek understands + decides tools + answers (best comprehension).
    # Text chat: web-search / info / MEMORY-recall queries route to DeepSeek too,
    # because DeepSeek reliably calls search_memory (qwen2.5:3b hallucinates
    # past conversations instead of reading the DB).
    _is_lookup = intent in ("TOOL_NEEDED", "COMPLEX") and is_lookup_request(user_input)

    # ── MEMORY RECALL: direct DB answer, formatted conversationally ──
    # Query the DB directly (deterministic, can't hallucinate) but PRESENT the
    # results as natural "You said / I said" lines instead of a raw transcript.
    if _is_memory:
        try:
            _last_engine = "qwen"
            from hachi_db import search_history
            mem_terms = [w for w in re.findall(r"[a-z0-9']+", _low) if len(w) > 3][:4]
            found = ""
            for term in mem_terms:
                hit = search_history(query=term, limit=4)
                if hit and "No history" not in hit:
                    found = hit
                    break
            if found:
                # Turn "[ts] (mode) User: X" → "You: X" ; "Assistant: X" → "I: X"
                clean_lines = []
                for line in found.splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    m = re.match(r"\[[^\]]*\]\s*\([^)]*\)\s*(User|Assistant):\s*(.*)", line)
                    if m:
                        role, content = m.group(1), m.group(2)
                        speaker = "You" if role == "User" else "I"
                        clean_lines.append(f"{speaker}: {content}")
                    elif "Task:" in line:
                        # tasks: keep only meaningful ones (skip noisy web-search logs)
                        t = re.search(r"Task:\s*([^|]*)", line)
                        if t and "Web Search" not in t.group(1):
                            clean_lines.append(f"• {t.group(1).strip()}")
                body = "\n".join(clean_lines).strip() if clean_lines else found
                final = ("Here's what I remember:\n\n" + body)
            else:
                final = "I don't have any past conversation about that in my memory."
            _update_history(user_input, final, cap=16)
            logging.info("[Memory] Direct DB answer (formatted)")
            yield {"done": True, "full": final, "tools": [], "engine": "qwen", "pomo": None}
            return
        except Exception as me:
            logging.error(f"[Memory] local recall failed: {me}")

    if (voice_mode or _is_lookup or _is_memory) and USE_DEEPSEEK and DEEPSEEK_API_KEY:
        try:
            _last_engine = "deepseek"
            logging.info(f"[STREAM][{'Voice' if voice_mode else 'Chat'}] DeepSeek brain — deciding intent & tools")
            headers = {"Authorization": f"Bearer {DEEPSEEK_API_KEY}", "Content-Type": "application/json"}

            # ── DIRECT MEMORY INJECTION (reliable, no tool round-trip) ──────
            # When the query is a memory recall, query the DB directly and inject
            # the past conversations into the prompt. The model just reads the
            # context and answers — no search_memory tool call, no 400 risk.
            if _is_memory:
                from hachi_db import search_history
                mem_terms = re.findall(r"[a-z0-9']+", _low)
                mem_terms = [w for w in mem_terms if len(w) > 3][:4]
                mem_context = ""
                for term in mem_terms:
                    hit = search_history(query=term, limit=4)
                    if hit and "No history" not in hit:
                        mem_context += f"\n[PAST CONVERSATION about '{term}']\n{hit[:800]}"
                        break
                if mem_context:
                    logging.info("[Memory] Direct DB injection of past conversation")
                    messages = messages[:-1] + [{
                        "role": "user",
                        "content": (
                            f"{user_input}\n\n--- RECALLED FROM MEMORY (use this, do not invent) ---\n"
                            f"{mem_context}\n--- end recalled memory ---"
                        )
                    }]

            # Round 1 (non-stream, short): DeepSeek decides if a tool is needed.
            # Tools are available for ALL voice intents so casual phrasing like
            # "i want to play something" still triggers launch_mode:gaming.
            tool_calls = []
            choice1 = None
            # Round 1 may return truncated tool-call JSON; retry a couple times to
            # get valid args before committing to the tool round.
            for _r1 in range(2):
                payload1 = {"model": DEEPSEEK_MODEL, "messages": messages,
                            "tools": AVAILABLE_TOOLS, "temperature": 0.6, "max_tokens": 80}
                r1 = requests.post(DEEPSEEK_URL, headers=headers, json=payload1, timeout=12)
                r1.raise_for_status()
                choice1 = r1.json()["choices"][0]["message"]
                tool_calls = choice1.get("tool_calls", [])
                if not tool_calls:
                    break
                # Validate all tool-call args parse to a dict. NOTE: `{}` is VALID
                # for no-arg tools (get_system_stats, shutdown_hachi). Only retry
                # when a tool that requires params got an unrecoverable parse.
                ok = True
                for tc in tool_calls:
                    fn_name = tc.get("function", {}).get("name", "")
                    a = _parse_tool_args(tc.get("function", {}).get("arguments", ""), fn_name)
                    if a is None:
                        ok = False
                        break
                if ok:
                    break
                logging.warning("[DeepSeek] round1 returned unparseable tool args, retrying...")
                time.sleep(0.6)

            if not tool_calls:
                fb_fn, fb_args = detect_intent_tool_call(user_input)
                if fb_fn:
                    tool_calls = [{"id": f"call_fb_{int(time.time())}", "function": {"name": fb_fn, "arguments": json.dumps(fb_args)}}]

            if tool_calls:
                if "tool_calls" not in choice1 or not choice1["tool_calls"]:
                    choice1["tool_calls"] = tool_calls
                messages.append(choice1)
                for tc in tool_calls:
                    fn = tc["function"]["name"]
                    raw_args = tc["function"]["arguments"]
                    args = _parse_tool_args(raw_args, fn)
                    result = execute_tool_call(fn, args)   # local execution (Qwen tool system)
                    executed_tools_info.append({"tool": fn, "args": args, "output": str(result)})
                    # CRITICAL: tool_call_id MUST match the id DeepSeek issued, or it
                    # ignores the result. Fallback calls get a stable id, not time-based.
                    _tc_id = tc.get("id") or f"call_{fn}_{abs(hash((fn, str(args)))) % 100000}"
                    messages.append({"role": "tool", "tool_call_id": _tc_id, "name": fn, "content": str(result)})

            # Round 2 (stream): DeepSeek synthesizes the answer — the LLM "tells"
            # the data the tool fetched, rather than reading raw results aloud.
            # Retry once on transient 4xx/5xx (DeepSeek intermittently 400s).
            max_tokens = _answer_budget(intent, user_input)
            payload2 = {"model": DEEPSEEK_MODEL, "messages": messages, "temperature": 0.6,
                        "stream": True, "max_tokens": max_tokens}
            s_res = None
            for _attempt in range(2):
                try:
                    s_res = requests.post(DEEPSEEK_URL, headers=headers, json=payload2, timeout=25, stream=True)
                    s_res.raise_for_status()
                    break
                except Exception as _e:
                    if s_res is not None:
                        s_res.close()
                    if _attempt == 0:
                        logging.warning(f"[DeepSeek] round2 attempt {_attempt+1} failed ({_e}), retrying...")
                        time.sleep(0.8)
                    else:
                        raise
            assert s_res is not None

            full_text = ""
            for line in s_res.iter_lines():
                if not line: continue
                line_str = line.decode('utf-8')
                if line_str.startswith("data: "):
                    data_body = line_str[6:].strip()
                    if data_body == "[DONE]": break
                    try:
                        chunk_json = json.loads(data_body)
                        delta = chunk_json["choices"][0]["delta"]
                        token = delta.get("content", "") or ""
                        if token:
                            full_text += token
                            yield {"token": token, "done": False}
                    except Exception:
                        pass

            pomo = _detect_pomo(full_text, executed_tools_info)
            cleaned_full = strip_control_tokens(clean_thinking(full_text))
            _update_history(user_input, cleaned_full, cap=16)
            add_message("assistant", cleaned_full, current_mode)
            logging.info("[Engine] DeepSeek (cloud)")
            yield {"done": True, "full": cleaned_full, "tools": executed_tools_info, "engine": "deepseek", "pomo": pomo}
            return

        except Exception as ds_err:
            _last_engine = "qwen"
            logging.warning(f"[STREAM][Voice] DeepSeek error ({ds_err}) — falling back to Qwen")
            if _is_memory:
                # Memory recall must NOT fall back to Qwen — it misclassifies keywords
                # like "gaming" as a mode command. Give a graceful answer instead.
                _update_history(user_input, "I couldn't recall that from memory right now.", cap=16)
                add_message("assistant", "I couldn't recall that from memory right now.", current_mode)
                yield {"done": True, "full": "I couldn't recall that from memory right now.",
                       "tools": [], "engine": "qwen", "pomo": None}
                return

    # ── QWEN-FIRST: local model primary for GREETING / SIMPLE_CHAT / TOOL_NEEDED ──
    if intent in ("GREETING", "SIMPLE_CHAT", "TOOL_NEEDED"):
        try:
            _last_engine = "qwen"
            tool_calls = []
            msg1 = None
            if intent == "TOOL_NEEDED":
                logging.info("[STREAM] Qwen-first: local model with tools (time-boxed)")
                msg1, tool_calls = _qwen_tool_decide(messages)
                if not tool_calls:
                    fb_fn, fb_args = detect_intent_tool_call(user_input)
                    if fb_fn:
                        tool_calls = [{"function": {"name": fb_fn, "arguments": fb_args}}]
                    else:
                        # Qwen + regex both missed the tool → escalate to DeepSeek
                        raise _EscalateToDeepSeek()

            if tool_calls:
                # Normalize tool_calls to DICT args (Ollama rejects string-args)
                cleaned_calls = []
                for tc in tool_calls:
                    if isinstance(tc, dict):
                        fn = tc["function"]["name"]
                        args = _parse_tool_args(tc["function"].get("arguments"), fn)
                    else:
                        fn = tc.function.name
                        args = _parse_tool_args(tc.function.arguments, fn)
                    cleaned_calls.append({"type": "function", "function": {"name": fn, "arguments": args}})
                messages.append({
                    "role": "assistant",
                    "content": getattr(msg1, "content", "") or "",
                    "tool_calls": cleaned_calls,
                })
                for tc, call in zip(tool_calls, cleaned_calls):
                    fn = call["function"]["name"]
                    args = call["function"]["arguments"]
                    result = execute_tool_call(fn, args)
                    executed_tools_info.append({"tool": fn, "args": args, "output": str(result)})
                    messages.append({"role": "tool", "name": fn, "content": str(result)})

            # Speed safeguard: stream Qwen tokens as they arrive
            accumulated = ""
            for chunk in ollama.chat(model=MODEL_NAME, messages=messages, stream=True,
                                     options={"num_predict": 250, "temperature": 0.75}):
                token = chunk.message.content or ""
                if token:
                    accumulated += token
                    yield {"token": token, "done": False}

            pomo = _detect_pomo(accumulated, executed_tools_info)
            full_text = strip_control_tokens(clean_thinking(accumulated))
            _update_history(user_input, full_text, cap=16)
            add_message("assistant", full_text, current_mode)
            logging.info("[Engine] Qwen (local)")
            yield {"done": True, "full": full_text, "tools": executed_tools_info, "engine": "qwen", "pomo": pomo}
            return

        except _EscalateToDeepSeek:
            logging.info("[STREAM] Qwen produced no tool call — escalating to DeepSeek")
        except Exception as e:
            logging.warning(f"[STREAM] Qwen error: {e}, escalating to DeepSeek")

    # ── ESCALATION: DeepSeek (cloud) — COMPLEX reasoning, or Qwen couldn't produce a tool call ──
    if USE_DEEPSEEK and DEEPSEEK_API_KEY:
        try:
            _last_engine = "deepseek"
            logging.info("[STREAM] DeepSeek API Voice Stream...")
            headers = {"Authorization": f"Bearer {DEEPSEEK_API_KEY}", "Content-Type": "application/json"}

            tool_calls = []
            if intent in ("TOOL_NEEDED", "COMPLEX"):
                payload1 = {"model": DEEPSEEK_MODEL, "messages": messages, "tools": AVAILABLE_TOOLS, "temperature": 0.7, "max_tokens": 80}
                r1 = requests.post(DEEPSEEK_URL, headers=headers, json=payload1, timeout=15)
                r1.raise_for_status()
                choice1 = r1.json()["choices"][0]["message"]
                tool_calls = choice1.get("tool_calls", [])

                if not tool_calls:
                    fb_fn, fb_args = detect_intent_tool_call(user_input)
                    if fb_fn:
                        tool_calls = [{"id": f"call_fb_{int(time.time())}", "function": {"name": fb_fn, "arguments": json.dumps(fb_args)}}]

                if tool_calls:
                    if "tool_calls" not in choice1 or not choice1["tool_calls"]:
                        choice1["tool_calls"] = tool_calls
                    messages.append(choice1)
                    for tc in tool_calls:
                        fn = tc["function"]["name"]
                        raw_args = tc["function"]["arguments"]
                        args = _parse_tool_args(raw_args, fn)
                        result = execute_tool_call(fn, args)
                        executed_tools_info.append({"tool": fn, "args": args, "output": str(result)})
                        messages.append({"role": "tool", "tool_call_id": tc.get("id", f"call_{int(time.time())}"), "name": fn, "content": str(result)})

            payload2 = {"model": DEEPSEEK_MODEL, "messages": messages, "temperature": 0.7, "stream": True, "max_tokens": _answer_budget(intent, user_input)}
            s_res = requests.post(DEEPSEEK_URL, headers=headers, json=payload2, timeout=25, stream=True)
            s_res.raise_for_status()

            full_text = ""
            for line in s_res.iter_lines():
                if not line: continue
                line_str = line.decode('utf-8')
                if line_str.startswith("data: "):
                    data_body = line_str[6:].strip()
                    if data_body == "[DONE]": break
                    try:
                        chunk_json = json.loads(data_body)
                        delta = chunk_json["choices"][0]["delta"]
                        token = delta.get("content", "") or ""
                        if token:
                            full_text += token
                            yield {"token": token, "done": False}
                    except Exception:
                        pass

            pomo = _detect_pomo(full_text, executed_tools_info)
            cleaned_full = strip_control_tokens(clean_thinking(full_text))
            _update_history(user_input, cleaned_full, cap=16)
            add_message("assistant", cleaned_full, current_mode)
            logging.info("[Engine] DeepSeek (cloud)")
            yield {"done": True, "full": cleaned_full, "tools": executed_tools_info, "engine": "deepseek", "pomo": pomo}
            return

        except Exception as ds_stream_err:
            logging.warning(f"[STREAM] DeepSeek API stream error ({ds_stream_err}). Using local Qwen stream...")

    # ── FINAL FALLBACK: Local Qwen (offline / DeepSeek failed) ─────────────
    try:
        _last_engine = "qwen"
        logging.info("[STREAM] Local Qwen Voice Stream (fallback)...")
        tool_calls = []
        msg1 = None
        if intent in ("TOOL_NEEDED", "COMPLEX"):
            for _attempt in range(2):
                msg1, tool_calls = _qwen_tool_decide(messages, escalate_on_timeout=False)
                if msg1 is not None:
                    break
                time.sleep(1)
            if msg1 is not None and not tool_calls:
                fb_fn, fb_args = detect_intent_tool_call(user_input)
                if fb_fn:
                    tool_calls = [{"function": {"name": fb_fn, "arguments": fb_args}}]

        if tool_calls:
            # Normalize tool_calls to DICT args (Ollama rejects string-args)
            cleaned_calls = []
            for tc in tool_calls:
                if isinstance(tc, dict):
                    fn = tc["function"]["name"]
                    args = _parse_tool_args(tc["function"].get("arguments"), fn)
                else:
                    fn = tc.function.name
                    args = _parse_tool_args(tc.function.arguments, fn)
                cleaned_calls.append({"type": "function", "function": {"name": fn, "arguments": args}})
            messages.append({
                "role": "assistant",
                "content": getattr(msg1, "content", "") or "",
                "tool_calls": cleaned_calls,
            })
            for tc, call in zip(tool_calls, cleaned_calls):
                fn = call["function"]["name"]
                args = call["function"]["arguments"]
                result = execute_tool_call(fn, args)
                executed_tools_info.append({"tool": fn, "args": args, "output": str(result)})
                messages.append({"role": "tool", "name": fn, "content": str(result)})

        accumulated = ""
        for chunk in ollama.chat(model=MODEL_NAME, messages=messages, stream=True,
                                 options={"num_predict": 250, "temperature": 0.75}):
            token = chunk.message.content or ""
            if token:
                accumulated += token
                yield {"token": token, "done": False}

        pomo = _detect_pomo(accumulated, executed_tools_info)
        full_text = strip_control_tokens(clean_thinking(accumulated))
        _update_history(user_input, full_text, cap=16)
        add_message("assistant", full_text, current_mode)
        logging.info("[Engine] Qwen (local)")
        yield {"done": True, "full": full_text, "tools": executed_tools_info, "engine": "qwen", "pomo": pomo}
    except Exception as e:
        logging.error(f"[STREAM] Error: {e}")
        err = "Sorry, I had a connection error."
        yield {"done": True, "full": err, "tools": [], "error": True, "engine": _last_engine, "pomo": None}


if __name__ == "__main__":
    text, tools = process_agent_request("What's the weather in Manila today?")
    print("Text:", text)
    print("Executed Tools:", tools)

