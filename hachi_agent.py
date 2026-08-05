import os
import time
import ollama
import requests
import json
import logging
import re
from hachi_tools import AVAILABLE_TOOLS, execute_tool_call
from hachi_db import add_message, search_history

# Configure logging once at module level
log_path = os.path.join(os.path.dirname(__file__), "hachi.log")
logging.basicConfig(filename=log_path, level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# Load configuration
CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.json")
MODEL_NAME = "qwen2.5:3b"
USE_DEEPSEEK = True
DEEPSEEK_API_KEY = ""
DEEPSEEK_MODEL = "deepseek-chat"
DEEPSEEK_URL = "https://api.deepseek.com/chat/completions"

if os.path.exists(CONFIG_PATH):
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg = json.load(f)
            MODEL_NAME = cfg.get("model_name", "qwen2.5:3b")
            USE_DEEPSEEK = cfg.get("use_deepseek", True)
            DEEPSEEK_API_KEY = cfg.get("deepseek_api_key", "").strip()
            DEEPSEEK_MODEL = cfg.get("deepseek_model", "deepseek-chat")
    except Exception as e:
        logging.warning(f"Could not load config.json: {e}. Using defaults.")

# ── Voice-optimised system prompt (short, no markdown, faster) ──────────────
VOICE_SYSTEM_PROMPT = """/no_think
You are Hachi, a fast AI voice assistant. Keep every reply SHORT - 1 to 3 sentences.
Speak naturally in English or Tagalog/Taglish depending on the user.
Never use markdown, bullet points, asterisks, or code blocks - this is spoken audio.

TOOL CALLING RULES (critical):
- launch_mode: call whenever user implies gaming/playing, studying/school, watching/movies, focusing/timer - even with casual phrasing like 'i wanna play', 'laro tayo', 'mag-aral', 'watch something'
- close_mode: call when user says stop/done/exit/quit for any mode
- Always call tools immediately without asking permission.
Be direct, warm, and concise."""

SYSTEM_PROMPT = """You are Hachi, an agentic desktop AI assistant powered by Qwen.
You speak naturally in English or Tagalog/Taglish depending on what the user speaks.
Be clear, helpful, friendly, and informative.

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

FORMATTING:
- Use **bold**, bullet points, numbered lists, and headers (##) for structured responses.
- For short answers, plain sentences are fine.
- Keep responses well-structured and easy to scan.
"""

# In-session short-term memory (resets on restart)
_session_history = []

def clean_thinking(response_text: str) -> str:
    """Strip out Qwen internal reasoning thinking blocks."""
    cleaned = re.sub(r'<think>.*?</think>', '', response_text, flags=re.DOTALL)
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

def call_deepseek_chat(messages, tools=None):
    """Call DeepSeek API (OpenAI-compatible) synchronously with tool support."""
    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": DEEPSEEK_MODEL,
        "messages": messages,
        "temperature": 0.7
    }
    if tools:
        payload["tools"] = tools

    res = requests.post(DEEPSEEK_URL, headers=headers, json=payload, timeout=25)
    res.raise_for_status()
    return res.json()


def process_agent_request(user_input: str, current_mode: str = "default"):
    """
    Process user input through Local Qwen (Primary Brain for chat/tools).
    If Qwen encounters a heavy/complex task, DeepSeek API assists.
    Returns tuple: (final_spoken_text, executed_tools_info_list)
    """
    global _session_history

    if not user_input or not user_input.strip():
        return "", []

    logging.info(f"[Qwen Engine] Processing Request: '{user_input}' (Mode: {current_mode})")
    add_message("user", user_input, current_mode)

    history_slice = _session_history[-16:]
    messages = [{"role": "system", "content": SYSTEM_PROMPT}] + history_slice + [{"role": "user", "content": user_input}]
    executed_tools_info = []

    # ── Online Search Pipeline: DeepSeek API fetches search context -> Qwen responds ──
    is_search_query = any(k in user_input.lower() for k in ["search", "google", "weather", "look up", "find online", "who is", "what is the news"])
    if is_search_query and USE_DEEPSEEK and DEEPSEEK_API_KEY:
        try:
            logging.info("[DeepSeek -> Qwen Pipeline] DeepSeek fetching web search context...")
            ds_res = call_deepseek_chat(messages, tools=AVAILABLE_TOOLS)
            ds_choice = ds_res["choices"][0]["message"]
            ds_tools = ds_choice.get("tool_calls", [])
            if ds_tools:
                messages.append(ds_choice)
                for tc in ds_tools:
                    fn = tc["function"]["name"]
                    raw_args = tc["function"]["arguments"]
                    args = json.loads(raw_args) if isinstance(raw_args, str) else (raw_args or {})
                    result = execute_tool_call(fn, args)
                    executed_tools_info.append({"tool": fn, "args": args, "output": str(result)})
                    messages.append({"role": "tool", "tool_call_id": tc.get("id", f"call_{int(time.time())}"), "name": fn, "content": str(result)})
                logging.info("[DeepSeek -> Qwen Pipeline] Web context passed to local Qwen...")
        except Exception as ds_err:
            logging.warning(f"[DeepSeek -> Qwen Pipeline Error] {ds_err}")

    # ── PRIMARY ENGINE: Local Qwen via Ollama ──────────────────────────────
    try:
        logging.info(f"[Qwen Engine] Calling local model '{MODEL_NAME}'...")
        try:
            response = ollama.chat(model=MODEL_NAME, messages=messages, tools=AVAILABLE_TOOLS)
        except Exception:
            time.sleep(1)
            response = ollama.chat(model=MODEL_NAME, messages=messages, tools=AVAILABLE_TOOLS)

        msg = response.message
        tool_calls = msg.tool_calls or []

        # Intent fallback to ensure tools execute 100% reliably with Qwen
        if not tool_calls:
            fb_fn, fb_args = detect_intent_tool_call(user_input)
            if fb_fn: tool_calls = [{"function": {"name": fb_fn, "arguments": fb_args}}]

        if tool_calls:
            messages.append(msg if hasattr(msg, 'role') else {"role": "assistant", "content": getattr(msg, 'content', "") or ""})
            for tool_call in tool_calls:
                if isinstance(tool_call, dict):
                    func_name = tool_call["function"]["name"]
                    func_args = tool_call["function"]["arguments"]
                else:
                    func_name = tool_call.function.name
                    func_args = tool_call.function.arguments or {}
                    if isinstance(func_args, str):
                        try: func_args = json.loads(func_args)
                        except Exception: func_args = {}

                logging.info(f"[Qwen Tool Triggered] {func_name} ({func_args})")
                tool_output = execute_tool_call(func_name, func_args)
                executed_tools_info.append({"tool": func_name, "args": func_args, "output": str(tool_output)})
                messages.append({"role": "tool", "name": func_name, "content": str(tool_output)})

            final_res = ollama.chat(model=MODEL_NAME, messages=messages)
            final_text = final_res.message.content or ""
        else:
            final_text = msg.content or ""

        cleaned_text = clean_thinking(final_text)
        _session_history.append({"role": "user", "content": user_input})
        _session_history.append({"role": "assistant", "content": cleaned_text})
        if len(_session_history) > 20: _session_history = _session_history[-20:]
        add_message("assistant", cleaned_text, current_mode)
        return cleaned_text, executed_tools_info

    except Exception as qwen_err:
        logging.warning(f"[Qwen Engine] Local execution error ({qwen_err}). DeepSeek API assisting...")

    # ── DEEPSEEK API ASSIST: For heavy text tasks if local Qwen is busy ──────
    if USE_DEEPSEEK and DEEPSEEK_API_KEY:
        try:
            logging.info(f"[DeepSeek Assist] Processing '{user_input}'...")
            res1 = call_deepseek_chat(messages, tools=AVAILABLE_TOOLS)
            choice1 = res1["choices"][0]["message"]
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
                    args = json.loads(raw_args) if isinstance(raw_args, str) else (raw_args or {})
                    result = execute_tool_call(fn, args)
                    executed_tools_info.append({"tool": fn, "args": args, "output": str(result)})
                    messages.append({"role": "tool", "tool_call_id": tc.get("id", f"call_{int(time.time())}"), "name": fn, "content": str(result)})

                res2 = call_deepseek_chat(messages)
                final_text = res2["choices"][0]["message"].get("content", "") or ""
            else:
                final_text = choice1.get("content", "") or ""

            cleaned_text = clean_thinking(final_text)
            _session_history.append({"role": "user", "content": user_input})
            _session_history.append({"role": "assistant", "content": cleaned_text})
            if len(_session_history) > 20: _session_history = _session_history[-20:]
            add_message("assistant", cleaned_text, current_mode)
            return cleaned_text, executed_tools_info

        except Exception as ds_err:
            logging.error(f"[DeepSeek Assist Error] {ds_err}")

    err_msg = f"Sorry, I encountered an issue. Please check Ollama or your connection."
    add_message("assistant", err_msg, current_mode)
    return err_msg, []


# ── Voice mode streaming: DeepSeek API (for speed) with Local Qwen Fallback 

def process_agent_request_stream(user_input: str, current_mode: str = "default"):
    """
    Voice mode stream.
    Uses DeepSeek API for fast sentence streaming (or Qwen if offline).
    """
    global _session_history

    if not user_input or not user_input.strip():
        yield {"done": True, "full": "", "tools": []}
        return

    logging.info(f"[STREAM] Voice request: '{user_input}'")
    add_message("user", user_input, current_mode)

    history_slice = _session_history[-10:]
    messages = [{"role": "system", "content": VOICE_SYSTEM_PROMPT}] + history_slice + [{"role": "user", "content": user_input}]
    executed_tools_info = []

    # ── Voice Stream Option 1: DeepSeek API Speed Pass ─────────────────────
    if USE_DEEPSEEK and DEEPSEEK_API_KEY:
        try:
            logging.info("[STREAM] DeepSeek API Voice Stream...")
            headers = {"Authorization": f"Bearer {DEEPSEEK_API_KEY}", "Content-Type": "application/json"}

            payload1 = {"model": DEEPSEEK_MODEL, "messages": messages, "tools": AVAILABLE_TOOLS, "temperature": 0.7}
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
                    args = json.loads(raw_args) if isinstance(raw_args, str) else (raw_args or {})
                    result = execute_tool_call(fn, args)
                    executed_tools_info.append({"tool": fn, "args": args, "output": str(result)})
                    messages.append({"role": "tool", "tool_call_id": tc.get("id", f"call_{int(time.time())}"), "name": fn, "content": str(result)})

            payload2 = {"model": DEEPSEEK_MODEL, "messages": messages, "temperature": 0.7, "stream": True}
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

            cleaned_full = clean_thinking(full_text)
            _session_history.append({"role": "user", "content": user_input})
            _session_history.append({"role": "assistant", "content": cleaned_full})
            if len(_session_history) > 16: _session_history = _session_history[-16:]
            add_message("assistant", cleaned_full, current_mode)

            yield {"done": True, "full": cleaned_full, "tools": executed_tools_info}
            return

        except Exception as ds_stream_err:
            logging.warning(f"[STREAM] DeepSeek API stream error ({ds_stream_err}). Using local Qwen stream...")

    # ── Voice Stream Option 2: Local Qwen Stream ───────────────────────────
    fast_opts = {"num_predict": 280, "temperature": 0.75}
    try:
        logging.info("[STREAM] Local Qwen Voice Stream...")
        try:
            resp1 = ollama.chat(model=MODEL_NAME, messages=messages, tools=AVAILABLE_TOOLS, options=fast_opts)
        except Exception:
            time.sleep(1)
            resp1 = ollama.chat(model=MODEL_NAME, messages=messages, tools=AVAILABLE_TOOLS, options=fast_opts)

        msg1 = resp1.message
        tool_calls = msg1.tool_calls or []

        if not tool_calls:
            fb_fn, fb_args = detect_intent_tool_call(user_input)
            if fb_fn: tool_calls = [{"function": {"name": fb_fn, "arguments": fb_args}}]

        if tool_calls:
            messages.append(msg1 if hasattr(msg1, 'role') else {"role": "assistant", "content": getattr(msg1, 'content', "") or ""})
            for tc in tool_calls:
                if isinstance(tc, dict):
                    fn = tc["function"]["name"]
                    args = tc["function"]["arguments"]
                else:
                    fn = tc.function.name
                    args = tc.function.arguments or {}
                    if isinstance(args, str):
                        try: args = json.loads(args)
                        except Exception: args = {}
                result = execute_tool_call(fn, args)
                executed_tools_info.append({"tool": fn, "args": args, "output": str(result)})
                messages.append({"role": "tool", "name": fn, "content": str(result)})

            accumulated = ""
            for chunk in ollama.chat(model=MODEL_NAME, messages=messages, stream=True, options=fast_opts):
                token = chunk.message.content or ""
                if token:
                    accumulated += token
                    yield {"token": token, "done": False}
            full_text = clean_thinking(accumulated)
        else:
            raw = msg1.content or ""
            full_text = clean_thinking(raw)
            words = full_text.split()
            for i in range(0, len(words), 4):
                chunk = " ".join(words[i : i + 4]) + " "
                yield {"token": chunk, "done": False}

        _session_history.append({"role": "user", "content": user_input})
        _session_history.append({"role": "assistant", "content": full_text})
        if len(_session_history) > 16: _session_history = _session_history[-16:]
        add_message("assistant", full_text, current_mode)

        yield {"done": True, "full": full_text, "tools": executed_tools_info}

    except Exception as e:
        logging.error(f"[STREAM] Error: {e}")
        err = f"Sorry, I had a connection error."
        yield {"done": True, "full": err, "tools": [], "error": True}


if __name__ == "__main__":
    text, tools = process_agent_request("What's the weather in Manila today?")
    print("Text:", text)
    print("Executed Tools:", tools)
