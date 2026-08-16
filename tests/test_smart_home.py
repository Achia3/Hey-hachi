import json

import pytest
from pydantic import ValidationError

import hachi_home


@pytest.fixture(autouse=True)
def clean_home(tmp_path, monkeypatch):
    log_path = tmp_path / "assistant_execution.log"
    monkeypatch.setattr(hachi_home, "_LOG_PATH", str(log_path))
    hachi_home.reset_smart_home("test reset")
    return log_path


def test_demo_state_is_predictable():
    devices = hachi_home.get_smart_home_state()["devices"]
    assert devices["living_room_light"]["on"] is False
    assert devices["kitchen_light"]["on"] is True
    assert devices["living_room_thermostat"]["temperature_c"] == 20
    assert devices["front_door_lock"]["locked"] is False
    assert devices["entertainment"]["status"] == "stopped"


def test_multi_action_command_updates_and_verifies_every_device(clean_home):
    result = hachi_home.apply_smart_home_actions(
        goal="Make the room comfortable and secure",
        original_command="It is dark and cold; secure the door.",
        actions=[
            {"action": "turn_on", "target": "living_room_light"},
            {"action": "increase_temperature", "target": "living_room_thermostat", "value": 2},
            {"action": "lock", "target": "front_door_lock"},
        ],
    )

    devices = result["state"]["devices"]
    assert result["verification"]["success"] is True
    assert len(result["changes"]) == 3
    assert devices["living_room_light"]["on"] is True
    assert devices["living_room_thermostat"]["temperature_c"] == 22
    assert devices["front_door_lock"]["locked"] is True

    rows = [json.loads(line) for line in clean_home.read_text(encoding="utf-8").splitlines()]
    assert rows[-1]["transcript"] == "It is dark and cold; secure the door."
    assert rows[-1]["validation_success"] is True
    assert rows[-1]["execution_verified"] is True


def test_invalid_action_target_is_rejected_without_state_change():
    before = hachi_home.get_smart_home_state()["devices"]
    with pytest.raises(ValidationError):
        hachi_home.apply_smart_home_actions([
            {"action": "turn_on", "target": "living_room_light"},
            {"action": "unlock", "target": "kitchen_light"},
        ])
    assert hachi_home.get_smart_home_state()["devices"] == before


def test_out_of_range_relative_temperature_is_atomic():
    before = hachi_home.get_smart_home_state()["devices"]
    with pytest.raises(ValueError, match="resulting thermostat"):
        hachi_home.apply_smart_home_actions([
            {"action": "turn_on", "target": "living_room_light"},
            {"action": "decrease_temperature", "target": "living_room_thermostat", "value": 10},
        ])
    assert hachi_home.get_smart_home_state()["devices"] == before


def test_media_title_and_stop_behavior():
    playing = hachi_home.apply_smart_home_actions([
        {"action": "play_media", "target": "entertainment", "title": "Study Music"}
    ])
    assert playing["state"]["devices"]["entertainment"] == {"status": "playing", "title": "Study Music"}

    stopped = hachi_home.apply_smart_home_actions([
        {"action": "stop_media", "target": "entertainment"}
    ])
    assert stopped["state"]["devices"]["entertainment"] == {"status": "stopped", "title": ""}


@pytest.mark.parametrize("phrase", [
    "Turn on the kitchen light",
    "I am freezing in the living room",
    "Secure the front door",
    "It is getting dark in here",
    "Play study music for me",
])
def test_home_request_detection(phrase):
    assert hachi_home.is_smart_home_request(phrase)


def test_home_tool_router_exposes_only_the_relevant_home_capabilities():
    from hachi_agent import select_tools_for_request

    names = [tool["function"]["name"] for tool in select_tools_for_request("I am freezing in the living room")]
    assert names[:2] == ["control_smart_home", "get_smart_home_state"]


def test_invalid_qwen_tool_output_is_reported_without_crashing_or_mutating():
    from hachi_tools import execute_tool_call

    before = hachi_home.get_smart_home_state()["devices"]
    result = json.loads(execute_tool_call("control_smart_home", {
        "goal": "Invalid generated action",
        "actions": [{"action": "unlock", "target": "kitchen_light"}],
        "_original_command": "Unlock the kitchen light",
    }))
    assert result["success"] is False
    assert result["state_unchanged"] is True
    state = hachi_home.get_smart_home_state()
    assert state["devices"] == before
    assert state["events"][0]["validation_success"] is False
