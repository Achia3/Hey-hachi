import os
import time
import ollama
import requests
import json
import logging
import re
from datetime import datetime
from hachi_tools import AVAILABLE_TOOLS, execute_tool_call
from hachi_db import add_message, search_history

def get_current_time_context() -> str:
    """Dynamically generate current system date/time context for the LLM."""
    now = datetime.now()
    return f"\n\nCURRENT DATE & TIME: {now.strftime('%A, %B %d, %Y, %I:%M %p')}"

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
You are Hachi, a fast AI voice assistant.
Respond naturally in English or Tagalog/Taglish.
Never use markdown, bullet points, or asterisks.

RESPONSE LENGTH RULES:
- If the user asks a simple, conversational, or command-like question, respond in 1 SHORT sentence.
- If they ask for information, keep it to a maximum of 2 sentences. Be extremely concise.

TOOL CALLING RULES (critical):
- launch_mode: call whenever user implies gaming/playing, studying/school, watching/movies, focusing/timer - even with casual phrasing like 'i wanna play', 'laro tayo', 'mag-aral', 'watch something'
- close_mode: call when user says stop/done/exit/quit for any mode
- Always call tools immediately without asking permission.
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
    # Standardize tag formatting by removing inner spaces inside DSML tags
    cleaned = re.sub(r'<\s*\|\s*\|\s*DSML\s*\|\s*\|', '<||DSML||', text)
    cleaned = re.sub(r'</\s*\|\s*\|\s*DSML\s*\|\s*\|', '</||DSML||', cleaned)

    invoke_blocks = re.findall(r'<\|\|DSML\|\|invoke name="([^"]+)"\s*>(.*?)</\|\|DSML\|\|invoke\s*>', cleaned, flags=re.DOTALL)
    for name, block in invoke_blocks:
        params = {}
        param_matches = re.findall(r'<\|\|DSML\|\|parameter name="([^"]+)"[^>]*>(.*?)</\|\|DSML\|\|parameter\s*>', block, flags=re.DOTALL)
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


def check_fast_intent(user_input: str) -> Optional[tuple[str, list]]:
    """
    Fast local command execution bypass (takes ~50ms).
    Matches common computer operations/commands via regex and runs the tool directly.
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

    # 4. System Stats
    if any(p in lower for p in ["system stats", "cpu usage", "ram usage", "battery status", "computer stats"]):
        res = execute_tool_call("get_system_stats", {})
        return res, [{"tool": "get_system_stats", "args": {}, "output": res}]

    # 5. Dynamic App Launching ("open [app]")
    m_launch = re.match(r"^(?:open|launch|start)\s+([a-zA-Z0-9\s\.\-_]+)$", lower)
    if m_launch:
        app_name = m_launch.group(1).strip()
        # ignore mode names
        if app_name not in ["gaming", "study", "movie", "focus", "timer", "pomodoro", "hachi"]:
            res = execute_tool_call("launch_app", {"app_name": app_name})
            return res, [{"tool": "launch_app", "args": {"app_name": app_name}, "output": res}]

    # 6. Dynamic App Closing ("close [app]" or "kill [app]")
    m_close = re.match(r"^(?:close|kill|exit|stop)\s+([a-zA-Z0-9\s\.\-_]+)$", lower)
    if m_close:
        app_name = m_close.group(1).strip()
        if app_name not in ["gaming", "study", "movie", "focus", "timer", "pomodoro", "hachi"]:
            res = execute_tool_call("close_app", {"app_name": app_name})
            return res, [{"tool": "close_app", "args": {"app_name": app_name}, "output": res}]

    return None


def process_agent_request(user_input: str, current_mode: str = "default"):
    """
    Process user input through Local Qwen (Primary Brain for chat/tools).
    If Qwen encounters a heavy/complex task, DeepSeek API assists.
    Returns tuple: (final_spoken_text, executed_tools_info_list)
    """
    global _session_history

    if not user_input or not user_input.strip():
        return "", []

    # ── Fast Command Bypass (takes ~50ms) ──────────────────────────────────
    fast_res = check_fast_intent(user_input)
    if fast_res:
        spoken, executed = fast_res
        add_message("assistant", spoken, current_mode)
        # Update short term history
        _session_history.append({"role": "user", "content": user_input})
        _session_history.append({"role": "assistant", "content": spoken})
        if len(_session_history) > 20: _session_history = _session_history[-20:]
        return spoken, executed

    logging.info(f"[Qwen Engine] Processing Request: '{user_input}' (Mode: {current_mode})")
    add_message("user", user_input, current_mode)

    history_slice = _session_history[-16:]
    sys_content = SYSTEM_PROMPT + get_current_time_context()
    messages = [{"role": "system", "content": sys_content}] + history_slice + [{"role": "user", "content": user_input}]
    executed_tools_info = []

    # ── PRIMARY ENGINE: DeepSeek API (Fastest when Online) ──────────────────
    if USE_DEEPSEEK and DEEPSEEK_API_KEY:
        try:
            logging.info(f"[DeepSeek Primary] Processing '{user_input}'...")
            res1 = call_deepseek_chat(messages, tools=AVAILABLE_TOOLS)
            choice1 = res1["choices"][0]["message"]
            content1 = choice1.get("content", "") or ""
            tool_calls = choice1.get("tool_calls", [])

            if not tool_calls and "<" in content1 and "DSML" in content1:
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
                    args = json.loads(raw_args) if isinstance(raw_args, str) else (raw_args or {})
                    result = execute_tool_call(fn, args)
                    executed_tools_info.append({"tool": fn, "args": args, "output": str(result)})
                    messages.append({"role": "tool", "tool_call_id": tc.get("id", f"call_{int(time.time())}"), "name": fn, "content": str(result)})

                res2 = call_deepseek_chat(messages)
                final_text = res2["choices"][0]["message"].get("content", "") or ""
            else:
                final_text = content1

            cleaned_text = strip_dsml(clean_thinking(final_text))
            _session_history.append({"role": "user", "content": user_input})
            _session_history.append({"role": "assistant", "content": cleaned_text})
            if len(_session_history) > 20: _session_history = _session_history[-20:]
            add_message("assistant", cleaned_text, current_mode)
            return cleaned_text, executed_tools_info

        except Exception as ds_err:
            logging.warning(f"[DeepSeek Primary Error] {ds_err}. Falling back to Qwen...")

    # ── FALLBACK ENGINE: Local Qwen via Ollama (Offline / Failover) ─────────
    try:
        logging.info(f"[Qwen Fallback] Calling local model '{MODEL_NAME}'...")
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
        logging.error(f"[Qwen Fallback Error] {qwen_err}")

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
    sys_content = VOICE_SYSTEM_PROMPT + get_current_time_context()
    messages = [{"role": "system", "content": sys_content}] + history_slice + [{"role": "user", "content": user_input}]
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

    fast_opts = {"num_predict": 250, "temperature": 0.75}  # Safe cap to prevent mid-sentence cutoff
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


# ── DeepSeek Voice Pipeline ──────────────────────────────────────────────────
# DeepSeek = voice understanding brain (natural language, intent detection)
# Qwen     = tool execution engine (launching apps, searching, etc.)
# This replaces all keyword-based routing for voice mode.

DEEPSEEK_VOICE_SYSTEM = """/no_think
You are Hachi, a smart bilingual voice assistant (English + Tagalog/Filipino).
This is VOICE — keep every reply extremely short.

CAPABILITIES:
- You DO have access to the internet. If the user asks if you have internet access or can browse, say YES and use the [DO:search_web:query] tag to look it up.

RESPONSE LENGTH RULES:
- If the user asks a simple, conversational, or command-like question, respond in 1 SHORT sentence.
- If they ask for information, limit the response to a maximum of 2 sentences. Be extremely concise.

NEVER use markdown, asterisks, bullet points, or code blocks.
Respond in the same language the user spoke.

You can trigger actions by embedding tags in your reply:
  [DO:launch_mode:gaming]   – start gaming setup
  [DO:launch_mode:study]    – start study setup
  [DO:launch_mode:movie]    – start movie/chill setup
  [DO:launch_mode:focus]    – start focus/Pomodoro timer
  [DO:close_mode:gaming]    – stop gaming mode (and the rest)
  [DO:search_web:your query here] – search the internet
  [DO:get_weather:location] – get weather for a place
  [DO:launch_app:appname]   – open a specific app
  [DO:close_app:appname]    – close a specific app
  [DO:system_stats]         – get CPU/RAM/battery stats
  [DO:shutdown_hachi]       – shut down Hachi completely

Rules:
- Only embed ONE or TWO actions max per reply.
- Always embed an action when the user's intent clearly maps to one.
- Infer intent from casual phrasing (e.g. "laro tayo" → [DO:launch_mode:gaming]).
- If search results are provided, use them to answer — don't hallucinate facts.
"""


def _parse_do_actions(response_text: str):
    """
    Extract [DO:action_name:param] tags from DeepSeek response.
    Returns (spoken_text_without_tags, list_of_(action, param)_tuples).
    """
    pattern = r"\[DO:([^:\]]+)(?::([^\]]*))?\]"
    actions = re.findall(pattern, response_text)
    spoken  = re.sub(r"\[DO:[^\]]*\]", "", response_text).strip()
    return spoken, actions


def _call_deepseek_voice(messages: list, max_tokens: int = 250) -> str:
    """
    Single DeepSeek call for the voice pipeline.
    Returns raw response text or empty string on failure.
    """
    if not USE_DEEPSEEK or not DEEPSEEK_API_KEY:
        return ""
    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json",
    }
    sys_content = DEEPSEEK_VOICE_SYSTEM + get_current_time_context()
    payload = {
        "model":       DEEPSEEK_MODEL,
        "messages":    [{"role": "system", "content": sys_content}] + messages,
        "temperature": 0.7,
        "max_tokens":  max_tokens,
    }
    try:
        res = requests.post(DEEPSEEK_URL, headers=headers, json=payload, timeout=20)
        res.raise_for_status()
        return res.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        logging.error(f"[DeepSeek Voice] API error: {e}")
        return ""


def process_voice_request(user_input: str, current_mode: str = "default"):
    """
    Full voice pipeline:
      1. DeepSeek understands user intent naturally (no hardcoded keywords).
      2. Parse [DO:action:param] action tags from its response.
      3. For each action, execute via Qwen tool system.
      4. For search_web, feed results back to DeepSeek for a spoken answer.
      5. Return (spoken_response, executed_tools_list).

    Falls back to process_agent_request() if DeepSeek is unavailable.
    """
    global _session_history

    if not user_input or not user_input.strip():
        return "", []

    # ── Fast Command Bypass (takes ~50ms) ──────────────────────────────────
    fast_res = check_fast_intent(user_input)
    if fast_res:
        spoken, executed = fast_res
        add_message("assistant", spoken, current_mode)
        # Update short term history
        _session_history.append({"role": "user", "content": user_input})
        _session_history.append({"role": "assistant", "content": spoken})
        if len(_session_history) > 20: _session_history = _session_history[-20:]
        return spoken, executed

    # Determine limit: local commands/greetings get a small 70 token budget for speed.
    # Questions requiring search, explanations, or weather get a full 250 token budget.
    info_keywords = ["explain", "why", "how", "what is", "who is", "search", "google", "weather", "look up", "find online", "news", "tell me about", "describe"]
    is_info_request = any(k in user_input.lower() for k in info_keywords)
    voice_tokens_limit = 250 if is_info_request else 70

    logging.info(f"[Voice Pipeline] '{user_input}'")
    add_message("user", user_input, current_mode)

    # Build message history (last 6 turns for voice — keep context short)
    history_slice = _session_history[-6:]
    messages = history_slice + [{"role": "user", "content": user_input}]

    # ── Step 1: DeepSeek interprets the user's intent ─────────────────────
    raw = _call_deepseek_voice(messages, max_tokens=voice_tokens_limit)

    if not raw:
        logging.warning("[Voice Pipeline] DeepSeek unavailable — falling back to Qwen.")
        return process_agent_request(user_input, current_mode)

    spoken, actions = _parse_do_actions(raw)
    executed_tools  = []

    # ── Step 2: Execute each action via Python tools / Qwen ───────────────
    for action_name, action_param in actions:
        action_name  = action_name.strip().lower()
        action_param = action_param.strip() if action_param else ""
        logging.info(f"[Voice Action] {action_name}({action_param!r})")

        try:
            if action_name == "search_web":
                # Execute search, then ask DeepSeek to formulate a spoken answer
                result = execute_tool_call("search_web", {"query": action_param})
                executed_tools.append({"tool": "search_web", "args": {"query": action_param}, "output": str(result)})

                if result and "Error" not in str(result):
                    follow_up = messages + [
                        {"role": "assistant", "content": raw},
                        {"role": "user", "content": (
                            f"Search results:\n{str(result)[:900]}\n\n"
                            f"Now give a SHORT spoken answer (1-3 sentences) to: {user_input}"
                        )},
                    ]
                    spoken_with_results = _call_deepseek_voice(follow_up)
                    if spoken_with_results:
                        spoken, _ = _parse_do_actions(spoken_with_results)

            elif action_name == "get_weather":
                result = execute_tool_call("get_weather", {"location": action_param})
                executed_tools.append({"tool": "get_weather", "args": {"location": action_param}, "output": str(result)})

            elif action_name == "launch_mode":
                result = execute_tool_call("launch_mode", {"mode_name": action_param})
                executed_tools.append({"tool": "launch_mode", "args": {"mode_name": action_param}, "output": str(result)})

            elif action_name == "close_mode":
                result = execute_tool_call("close_mode", {"mode_name": action_param})
                executed_tools.append({"tool": "close_mode", "args": {"mode_name": action_param}, "output": str(result)})

            elif action_name == "launch_app":
                result = execute_tool_call("launch_app", {"app_name": action_param})
                executed_tools.append({"tool": "launch_app", "args": {"app_name": action_param}, "output": str(result)})

            elif action_name == "close_app":
                result = execute_tool_call("close_app", {"app_name": action_param})
                executed_tools.append({"tool": "close_app", "args": {"app_name": action_param}, "output": str(result)})

            elif action_name == "system_stats":
                result = execute_tool_call("get_system_stats", {})
                executed_tools.append({"tool": "system_stats", "args": {}, "output": str(result)})

            elif action_name == "shutdown_hachi":
                execute_tool_call("shutdown_hachi", {})
                executed_tools.append({"tool": "shutdown_hachi", "args": {}, "output": "Shutting down."})

        except Exception as e:
            logging.error(f"[Voice Action] {action_name} failed: {e}")

    # ── Step 3: Update session history ────────────────────────────────────
    final_response = spoken or raw
    final_response = clean_thinking(final_response)

    _session_history.append({"role": "user",      "content": user_input})
    _session_history.append({"role": "assistant", "content": final_response})
    if len(_session_history) > 20:
        _session_history = _session_history[-20:]

    add_message("assistant", final_response, current_mode)
    return final_response, executed_tools


if __name__ == "__main__":
    text, tools = process_agent_request("What's the weather in Manila today?")
    print("Text:", text)
    print("Executed Tools:", tools)

