"""Master-model integration regressions with isolated storage and mocked devices."""
import json
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

import pytest

import hachi_agent
import hachi_db
import hachi_productivity
import hachi_tools


@pytest.mark.parametrize("user_input, expected", [
    ("Open Blender", "manage_app"),
    ("Open Chrome", "manage_app"),
    ("Close Notepad", "manage_app"),
    ("Buksan mo ang Discord", "manage_app"),
    ("Start gaming mode", "manage_mode"),
    ("Run my daily briefing routine", "run_routine"),
    ("Play music on Spotify", "media"),
    ("Complete my todo", "manage_productivity"),
    ("Ipaalala mo ang assignment ko", "manage_productivity"),
    ("Remember my favorite color", "manage_productivity"),
    ("Search the web for Python", "web_research"),
    ("Check CPU and RAM usage", "system_control"),
    ("Copy this to my clipboard", "system_control"),
])
def test_router_presents_trained_contract(user_input, expected):
    names = [t["function"]["name"] for t in hachi_agent.select_tools_for_request(user_input)]
    assert expected in names
    assert len(names) <= 8
    assert not set(names) & {"launch_app", "save_note", "play_spotify", "get_system_stats", "set_reminder"}


@pytest.mark.parametrize("args", [
    {"routine_name": "research_brief", "input_text": "local models"},
    {"name": "research_brief", "routine_input": "local models"},
])
def test_trained_and_legacy_routine_arguments_reach_executor(args):
    assert hachi_agent._validate_tool_args("run_routine", args)[0]
    with patch("hachi_tools.run_routine", return_value="done") as run:
        assert hachi_tools.execute_tool_call("run_routine", args) == "done"
    run.assert_called_once_with("research_brief", "local models")


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(hachi_db, "DB_PATH", str(tmp_path / "master.db"))
    hachi_db.init_db()


def test_complete_todo_persists_and_is_idempotent(isolated_db):
    hachi_productivity.add_todo("Review Hachi")
    result = hachi_tools.execute_tool_call("manage_productivity", {
        "action": "complete", "type": "todo", "title": "Review Hachi"})
    assert "Completed to-do #1" in result
    with closing(hachi_db.get_connection()) as conn:
        row = conn.execute("SELECT status,completed_at FROM todos WHERE id=1").fetchone()
    assert row["status"] == "completed" and row["completed_at"]
    assert "Review Hachi" not in hachi_productivity.list_todos()
    assert "already completed" in hachi_tools.execute_tool_call("manage_productivity", {
        "action": "complete", "type": "todo", "todo_id": 1})


def test_ambiguous_missing_and_invalid_todos_do_not_change_storage(isolated_db):
    hachi_productivity.add_todo("Review")
    hachi_productivity.add_todo("Review")
    assert "Provide its ID" in hachi_productivity.complete_todo("Review")
    assert "No matching" in hachi_productivity.complete_todo("Missing")
    assert "positive integer" in hachi_productivity.complete_todo(todo_id=True)
    with closing(hachi_db.get_connection()) as conn:
        assert conn.execute("SELECT count(*) FROM todos WHERE status='pending'").fetchone()[0] == 2
    assert "Completed to-do #2" in hachi_productivity.complete_todo(todo_id=2)


def test_rejected_memory_is_not_reported_saved():
    with patch("hachi_tools.save_memory", return_value={"status": "rejected", "reason": "memory_too_short"}):
        result = hachi_tools.execute_tool_call("manage_productivity", {
            "action": "create", "type": "memory", "content": "x"})
    assert "Could not save memory" in result


@pytest.mark.parametrize("tool, args, dependency", [
    ("manage_app", {"action": "invented", "app_name": "Discord"}, "launch_app"),
    ("manage_app", {"action": "launch"}, "launch_app"),
    ("manage_mode", {"action": "invented", "mode_name": "gaming"}, "launch_mode"),
    ("media", {"action": "invented"}, "media_control"),
    ("manage_productivity", {"type": "note", "action": "delete", "title": "X"}, "list_notes"),
    ("system_control", {"action": "set_brightness", "value": 50}, "media_control"),
])
def test_unsupported_actions_never_fall_through_to_success(tool, args, dependency):
    with patch("hachi_tools." + dependency) as operation:
        result = hachi_tools.execute_tool_call(tool, args)
    operation.assert_not_called()
    assert "completed" not in result.lower()
    assert "unsupported" in result.lower() or "needs" in result.lower()


def test_model_enum_validation_rejects_unsupported_actions():
    assert not hachi_agent._validate_tool_args("system_control", {"action": "set_brightness"})[0]
    assert not hachi_agent._validate_tool_args("manage_productivity", {
        "action": "complete", "type": "todo", "todo_id": True})[0]


def test_system_stats_and_clipboard_reach_real_handlers():
    with patch("hachi_tools.get_system_stats", return_value="CPU 12%") as stats:
        assert hachi_tools.execute_tool_call("system_control", {"action": "get_stats"}) == "CPU 12%"
    stats.assert_called_once()
    with patch("hachi_tools.clipboard_set", return_value="copied") as clipboard:
        assert hachi_agent._validate_tool_args("system_control", {"action": "clipboard_set", "text": "Hello"})[0]
        assert hachi_tools.execute_tool_call("system_control", {"action": "clipboard_set", "text": "Hello"}) == "copied"
    clipboard.assert_called_once_with("Hello")


def test_media_search_does_not_start_playback():
    with patch("hachi_tools.os.startfile") as start, patch("hachi_tools.play_spotify") as play, patch("hachi_tools.media_control") as media:
        result = hachi_tools.execute_tool_call("media", {"action": "search", "target": "spotify", "query": "lofi"})
    start.assert_called_once_with("spotify:search:lofi")
    play.assert_not_called()
    media.assert_not_called()
    assert "Playback was not requested" in result


def test_trained_web_actions_reach_correct_handlers():
    with patch("hachi_tools.fetch_url", return_value="page") as fetch, patch("hachi_tools.research_web", return_value="sources") as research:
        assert hachi_tools.execute_tool_call("web_research", {"action": "fetch_url", "query": "page", "url": "https://example.com"}) == "page"
        assert hachi_tools.execute_tool_call("web_research", {"action": "research_brief", "query": "Qwen"}) == "sources"
    fetch.assert_called_once_with("https://example.com")
    research.assert_called_once_with("Qwen")


@pytest.mark.parametrize("action,key,presses", [("volume_up", "volume_up", 5), ("volume_down", "volume_down", 5), ("stop", "stop", 1)])
def test_master_media_actions_send_correct_key(action, key, presses):
    with patch("hachi_tools._send_media_key", return_value=True) as send, patch("hachi_tools.add_task"):
        hachi_tools.execute_tool_call("media", {"action": action})
    send.assert_called_once_with(key, presses)


def test_full_model_loop_completes_todo_in_database(isolated_db):
    from types import SimpleNamespace
    hachi_productivity.add_todo("Review model")
    replies = [
        (SimpleNamespace(content=""), [{"id": "done-1", "function": {"name": "manage_productivity",
          "arguments": {"action": "complete", "type": "todo", "title": "Review model"}}}]),
        (SimpleNamespace(content="Completed your todo."), []),
    ]
    def run(name, args, call_id):
        assert hachi_agent._validate_tool_args(name, args)[0]
        return hachi_tools.execute_tool_call(name, args)
    with patch("hachi_agent._qwen_tool_decide", side_effect=replies):
        answer, actions, handled = hachi_agent._run_qwen_agent_loop(
            [{"role": "user", "content": "Complete my todo Review model"}],
            "Complete my todo Review model", run, lambda: None)
    assert handled and len(actions) == 1
    assert "Completed to-do" in actions[0]["output"]
    assert "Review model" not in hachi_productivity.list_todos()
