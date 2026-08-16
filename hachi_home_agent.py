"""Focused local-Qwen interpreter for Hachi's smart-home simulator."""

from __future__ import annotations

import json
import threading
import time
from typing import Any

import ollama

from hachi_agent import MODEL_NAME, _parse_tool_args
from hachi_home import get_smart_home_state, smart_home_prompt_context
from hachi_tools import AVAILABLE_TOOLS, execute_tool_call


_HOME_TOOL_NAMES = {"control_smart_home", "get_smart_home_state"}
HOME_TOOLS = [
    tool for tool in AVAILABLE_TOOLS
    if tool.get("function", {}).get("name") in _HOME_TOOL_NAMES
]

# Tool selection should be quick and deterministic.  Qwen 3.5's default
# reasoning mode can spend minutes "thinking" before emitting a tiny tool call,
# which makes the simulator appear broken.  This client also prevents a failed
# local runtime from leaving the interface waiting forever.
_HOME_CLIENT = ollama.Client(timeout=60.0)
_ACTIVITY_LOCK = threading.RLock()
_ACTIVITY = {"pending": False, "command": "", "sequence": 0}


def _set_smart_home_activity(pending: bool, command: str = "") -> None:
    with _ACTIVITY_LOCK:
        _ACTIVITY["pending"] = bool(pending)
        _ACTIVITY["command"] = command if pending else ""
        _ACTIVITY["sequence"] += 1


def get_smart_home_activity() -> dict:
    """Return live agent progress for the separate simulator window."""
    with _ACTIVITY_LOCK:
        return dict(_ACTIVITY)


def _chat(messages: list[dict], *, num_predict: int) -> Any:
    return _HOME_CLIENT.chat(
        model=MODEL_NAME,
        messages=messages,
        tools=HOME_TOOLS,
        think=False,
        keep_alive="10m",
        options={"temperature": 0.0, "num_predict": num_predict},
    )


def get_smart_home_runtime_status() -> dict:
    """Report whether Ollama is reachable and the configured model is installed."""
    try:
        response = ollama.list()
        models = getattr(response, "models", None)
        if models is None and isinstance(response, dict):
            models = response.get("models", [])
        names = []
        for model in models or []:
            if isinstance(model, dict):
                names.append(str(model.get("model") or model.get("name") or ""))
            else:
                names.append(str(getattr(model, "model", "") or getattr(model, "name", "")))
        installed = MODEL_NAME in names
        return {
            "ollama_running": True,
            "model": MODEL_NAME,
            "model_installed": installed,
            "message": "Local Qwen is ready." if installed else f"Run: ollama pull {MODEL_NAME}",
        }
    except Exception:
        return {
            "ollama_running": False,
            "model": MODEL_NAME,
            "model_installed": False,
            "message": "Start Ollama before sending AI commands.",
        }


def _normalise_call(tool_call: Any) -> tuple[str, dict]:
    if isinstance(tool_call, dict):
        function = tool_call.get("function", {})
        name = str(function.get("name", ""))
        arguments = function.get("arguments", {})
    else:
        function = getattr(tool_call, "function", None)
        name = str(getattr(function, "name", ""))
        arguments = getattr(function, "arguments", {})
    return name, _parse_tool_args(arguments, name)


def _message_parts(response: Any) -> tuple[str, list]:
    message = getattr(response, "message", None)
    if message is None and isinstance(response, dict):
        message = response.get("message", {})
    if isinstance(message, dict):
        return str(message.get("content", "") or "").strip(), list(message.get("tool_calls", []) or [])
    return str(getattr(message, "content", "") or "").strip(), list(getattr(message, "tool_calls", []) or [])


def _state_sentence(devices: dict) -> str:
    living = "on" if devices["living_room_light"]["on"] else "off"
    kitchen = "on" if devices["kitchen_light"]["on"] else "off"
    door = "locked" if devices["front_door_lock"]["locked"] else "unlocked"
    thermostat = devices["living_room_thermostat"]["temperature_c"]
    media = devices["entertainment"]
    media_text = media["status"] + (f" ({media['title']})" if media.get("title") else "")
    return (
        f"Living-room light: {living}; kitchen light: {kitchen}; thermostat: "
        f"{thermostat} °C; front door: {door}; entertainment: {media_text}."
    )


def _success_sentence(result: dict) -> str:
    devices = result["state"]["devices"]
    parts = []
    for change in result.get("changes", []):
        target = change["target"]
        if target in {"living_room_light", "kitchen_light"}:
            label = "Living-room light" if target == "living_room_light" else "Kitchen light"
            parts.append(f"{label} is now {'on' if devices[target]['on'] else 'off'}")
        elif target == "living_room_thermostat":
            parts.append(f"Thermostat is now {devices[target]['temperature_c']} °C")
        elif target == "front_door_lock":
            parts.append(f"Front door is now {'locked' if devices[target]['locked'] else 'unlocked'}")
        elif target == "entertainment":
            media = devices[target]
            detail = f" {media['title']}" if media.get("title") else ""
            parts.append(f"Entertainment is now {media['status']}{detail}")
    return ". ".join(parts) + ("." if parts else "The requested state was already set.")


def _friendly_model_error(exc: Exception) -> str:
    message = str(exc)
    lowered = message.lower()
    if "connect" in lowered or "refused" in lowered:
        return "Ollama is not running. Start Ollama, then try the command again."
    if "not found" in lowered or "pull" in lowered:
        return f"The model {MODEL_NAME} is not installed. Run: ollama pull {MODEL_NAME}"
    return f"Local Qwen could not process that command: {message}"


def run_smart_home_command(user_input: str) -> dict:
    """Ask only local Qwen to choose validated smart-home actions."""
    command = (user_input or "").strip()
    if not command:
        return {"success": False, "error": "Enter a smart-home request first."}

    _set_smart_home_activity(True, command)
    started_at = time.perf_counter()
    system = (
        "/no_think\nYou control only Hachi's software-simulated smart home. "
        "Understand the user's intended outcome, including indirect needs. Call "
        "control_smart_home once with every requested change, or call "
        "get_smart_home_state for a state question. Never claim a change without a "
        "successful tool result. Ask one concise question only when a necessary "
        "target, temperature, or desired state truly cannot be inferred."
        + smart_home_prompt_context()
    )
    messages = [{"role": "system", "content": system}, {"role": "user", "content": command}]

    try:
        response = _chat(messages, num_predict=120)
        content, tool_calls = _message_parts(response)

        if not tool_calls and "?" not in content:
            messages.extend([
                {"role": "assistant", "content": content},
                {"role": "user", "content": "This is a simulator request. If an action is inferable, call the appropriate smart-home tool now instead of only describing it."},
            ])
            response = _chat(messages, num_predict=100)
            content, tool_calls = _message_parts(response)

        if not tool_calls:
            return {
                "success": False,
                "clarification": bool(content),
                "response": content or "I could not infer a safe smart-home action. Please name the device and desired result.",
                "model": MODEL_NAME,
                "state": get_smart_home_state(),
            }

        executed = []
        successful_control = None
        state_read = None
        for tool_call in tool_calls:
            name, arguments = _normalise_call(tool_call)
            if name not in _HOME_TOOL_NAMES:
                continue
            if name == "control_smart_home":
                arguments["_original_command"] = command
                arguments["_request_started_at"] = started_at
            raw_output = execute_tool_call(name, arguments)
            try:
                output = json.loads(raw_output)
            except (TypeError, json.JSONDecodeError):
                output = {"success": False, "error": str(raw_output)}
            executed.append({"tool": name, "args": arguments, "output": output})
            if name == "control_smart_home" and output.get("success"):
                successful_control = output
            if name == "get_smart_home_state":
                state_read = output

        if successful_control:
            return {
                "success": True,
                "response": _success_sentence(successful_control),
                "model": MODEL_NAME,
                "tools": executed,
                "state": successful_control["state"],
            }
        if state_read and state_read.get("devices"):
            return {
                "success": True,
                "response": _state_sentence(state_read["devices"]),
                "model": MODEL_NAME,
                "tools": executed,
                "state": state_read,
            }
        error = next((row["output"].get("error") for row in executed if row["output"].get("error")), None)
        return {
            "success": False,
            "error": error or "Qwen did not produce a valid smart-home action.",
            "model": MODEL_NAME,
            "tools": executed,
            "state": get_smart_home_state(),
        }
    except Exception as exc:
        return {
            "success": False,
            "error": _friendly_model_error(exc),
            "model": MODEL_NAME,
            "state": get_smart_home_state(),
        }
    finally:
        _set_smart_home_activity(False)
