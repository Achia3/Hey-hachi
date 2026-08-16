from types import SimpleNamespace
from unittest.mock import patch

import pytest

import hachi_home
import hachi_home_agent


@pytest.fixture(autouse=True)
def clean_home(tmp_path, monkeypatch):
    monkeypatch.setattr(hachi_home, "_LOG_PATH", str(tmp_path / "assistant_execution.log"))
    hachi_home.reset_smart_home("agent test reset")


def _response(content="", tool_calls=None):
    return SimpleNamespace(message=SimpleNamespace(content=content, tool_calls=tool_calls or []))


def test_focused_agent_executes_qwen_multi_action_tool_call():
    tool_call = {
        "function": {
            "name": "control_smart_home",
            "arguments": {
                "goal": "Make the room brighter and warmer",
                "actions": [
                    {"action": "turn_on", "target": "living_room_light"},
                    {"action": "increase_temperature", "target": "living_room_thermostat", "value": 2},
                ],
            },
        }
    }
    def qwen_response(**_kwargs):
        assert hachi_home_agent.get_smart_home_activity()["pending"] is True
        return _response(tool_calls=[tool_call])

    with patch("hachi_home_agent._HOME_CLIENT.chat", side_effect=qwen_response) as chat:
        result = hachi_home_agent.run_smart_home_command("It is dark and I am freezing.")

    assert result["success"] is True
    assert result["state"]["devices"]["living_room_light"]["on"] is True
    assert result["state"]["devices"]["living_room_thermostat"]["temperature_c"] == 22
    assert result["tools"][0]["tool"] == "control_smart_home"
    assert chat.call_args.kwargs["tools"] == hachi_home_agent.HOME_TOOLS
    assert chat.call_args.kwargs["think"] is False
    assert chat.call_args.kwargs["keep_alive"] == "10m"
    assert hachi_home_agent.get_smart_home_activity()["pending"] is False


def test_chat_stream_opens_simulator_before_qwen_runs():
    import hachi_agent

    result = {"success": True, "response": "Front door is now locked.", "tools": []}
    with (
        patch("hachi_home.is_smart_home_request", return_value=True),
        patch("hachi_home_agent.run_smart_home_command", return_value=result),
        patch("hachi_agent.add_message"),
        patch("hachi_agent._update_history"),
    ):
        events = list(hachi_agent.process_agent_request_stream("Lock the front door."))

    assert events[0] == {"done": False, "open_smart_home": True}
    assert events[-1]["done"] is True


def test_focused_agent_returns_a_model_clarification_without_changing_state():
    before = hachi_home.get_smart_home_state()["devices"]
    with patch("hachi_home_agent._HOME_CLIENT.chat", return_value=_response("Which light would you like me to turn on?")):
        result = hachi_home_agent.run_smart_home_command("Turn it on.")

    assert result["success"] is False
    assert result["clarification"] is True
    assert hachi_home.get_smart_home_state()["devices"] == before


def test_focused_agent_explains_when_ollama_is_offline():
    with patch("hachi_home_agent._HOME_CLIENT.chat", side_effect=ConnectionError("connection refused")):
        result = hachi_home_agent.run_smart_home_command("Turn on the kitchen light.")

    assert result["success"] is False
    assert "Ollama is not running" in result["error"]


def test_runtime_status_reports_missing_configured_model():
    listed = SimpleNamespace(models=[SimpleNamespace(model="some-other-model:latest")])
    with patch("hachi_home_agent.ollama.list", return_value=listed):
        status = hachi_home_agent.get_smart_home_runtime_status()

    assert status["ollama_running"] is True
    assert status["model_installed"] is False
    assert "ollama pull" in status["message"]


def test_smart_home_page_is_separate_from_main_chat():
    from hachi_web import app

    client = app.test_client()
    main = client.get("/")
    simulator = client.get("/smart-home")
    assert main.status_code == 200
    assert simulator.status_code == 200
    assert b"Smart Home Simulation" not in main.data
    assert b'id="smartHomeNav"' not in main.data
    assert b"Smart Home Simulation" in simulator.data


def test_desktop_api_reuses_an_open_simulator_window():
    from hachi_app import DesktopApi

    class FakeEvent:
        def __init__(self):
            self.handlers = []
        def is_set(self):
            return False
        def __iadd__(self, handler):
            self.handlers.append(handler)
            return self

    class FakeWindow:
        def __init__(self):
            self.events = SimpleNamespace(closed=FakeEvent())
            self.restored = 0
            self.shown = 0
        def restore(self):
            self.restored += 1
        def show(self):
            self.shown += 1
        def evaluate_js(self, script):
            self.script = script

    fake_window = FakeWindow()
    api = DesktopApi()
    with patch("hachi_app.webview.create_window", return_value=fake_window) as create:
        first = api.open_smart_home()
        second = api.open_smart_home()

    assert first == {"opened": True, "reused": False}
    assert second == {"opened": True, "reused": True}
    create.assert_called_once()
    assert create.call_args.kwargs["url"].endswith("/smart-home?auto=1")
    assert fake_window.restored == 1
    assert fake_window.shown == 1
    assert "hachiSmartHomeBegin" in fake_window.script
