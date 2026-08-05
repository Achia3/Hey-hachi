import os
import time
import ollama
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
MODEL_NAME = "qwen3.5:2b"

if os.path.exists(CONFIG_PATH):
    try:
        with open(CONFIG_PATH, "r") as f:
            cfg = json.load(f)
            MODEL_NAME = cfg.get("model_name", "qwen3.5:2b")
    except Exception as e:
        logging.warning(f"Could not load config.json: {e}. Using defaults.")

SYSTEM_PROMPT = """You are Hachi, an agentic desktop AI assistant.
You speak naturally in English or Tagalog/Taglish depending on what the user speaks.
Be clear, helpful, friendly, and concise.

You have full tool capabilities to assist the user:
- launch_mode: Trigger desktop modes (gaming, study, movie, focus) based on user intent.
- close_mode: Close apps for a mode when the user wants to stop.
- close_app: Close ANY desktop application running on Windows by name.
- shutdown_hachi: Turn off Hachi and free system RAM when the user wants to exit.
- get_weather: Check live weather conditions and temperature.
- search_web: Search the web for real-time facts, new game releases, or news.
- search_memory: Check past conversations, tasks, and activities logged on specific dates.
- get_system_stats: Check CPU, RAM, and battery performance.

IMPORTANT:
1. Always execute tools autonomously when the user's intent matches a tool capability.
2. Do not use Markdown formatting (no asterisks, hash signs, bold tags) in spoken responses.
3. Keep spoken answers concise so they can be spoken quickly out loud.
"""

# In-session short-term memory (resets on restart)
_session_history = []

def clean_thinking(response_text: str) -> str:
    """Strip out Qwen internal reasoning thinking blocks."""
    cleaned = re.sub(r'<think>.*.*?/think>', '', response_text, flags=re.DOTALL)
    cleaned = re.sub(r'[*#_`~]', '', cleaned)
    return cleaned.strip()

def process_agent_request(user_input: str, current_mode: str = "default"):
    """
    Process user input through Ollama with tool execution and memory logging.
    Returns tuple: (final_spoken_text, executed_tools_info_list)
    """
    global _session_history

    if not user_input or not user_input.strip():
        return "", []

    logging.info(f"Agent Processing Request: '{user_input}' (Mode: {current_mode})")
    
    # Log user message to database
    add_message("user", user_input, current_mode)

    # Build message list with short-term session history (last 8 exchanges max)
    history_slice = _session_history[-16:]  # 8 user+assistant pairs
    messages = [{"role": "system", "content": SYSTEM_PROMPT}] + history_slice + [{"role": "user", "content": user_input}]

    executed_tools_info = []

    try:
        # Attempt Ollama chat with one auto-retry if server is still warming up
        try:
            response = ollama.chat(
                model=MODEL_NAME,
                messages=messages,
                tools=AVAILABLE_TOOLS
            )
        except Exception as first_err:
            logging.warning(f"Ollama initial call error ({first_err}), retrying in 1.5s...")
            time.sleep(1.5)
            response = ollama.chat(
                model=MODEL_NAME,
                messages=messages,
                tools=AVAILABLE_TOOLS
            )

        # CORRECT: Access ollama response as typed object, NOT dict
        msg = response.message
        tool_calls = msg.tool_calls or []

        if tool_calls:
            # Append assistant response containing tool calls once
            messages.append(msg)

            for tool_call in tool_calls:
                func_name = tool_call.function.name
                func_args = tool_call.function.arguments or {}
                if isinstance(func_args, str):
                    try:
                        func_args = json.loads(func_args)
                    except Exception:
                        func_args = {}

                logging.info(f"LLM Tool Triggered: {func_name} ({func_args})")
                tool_output = execute_tool_call(func_name, func_args)
                executed_tools_info.append({"tool": func_name, "args": func_args, "output": str(tool_output)})

                # Append tool result with required 'name' field
                messages.append({
                    "role": "tool",
                    "name": func_name,
                    "content": str(tool_output)
                })

            # Send updated conversation back to model for final spoken answer
            final_res = ollama.chat(model=MODEL_NAME, messages=messages)
            final_text = final_res.message.content or ""
        else:
            final_text = msg.content or ""

        cleaned_text = clean_thinking(final_text)

        # Update short-term in-session history
        _session_history.append({"role": "user", "content": user_input})
        _session_history.append({"role": "assistant", "content": cleaned_text})
        # Cap session history to last 20 messages
        if len(_session_history) > 20:
            _session_history = _session_history[-20:]

        # Log assistant response to database
        add_message("assistant", cleaned_text, current_mode)
        return cleaned_text, executed_tools_info

    except Exception as e:
        logging.error(f"Agent processing error: {e}")
        err_msg = f"Sorry, I had trouble connecting to my AI brain. Please ensure Ollama is running with the '{MODEL_NAME}' model."
        add_message("assistant", err_msg, current_mode)
        return err_msg, []

if __name__ == "__main__":
    text, tools = process_agent_request("What's the weather in Manila today?")
    print("Text:", text)
    print("Executed Tools:", tools)
