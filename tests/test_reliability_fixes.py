import os
import io
from pathlib import Path
import tempfile
import threading
import types
import unittest
from unittest.mock import patch

try:
    import ollama  # noqa: F401
except ImportError:
    import sys
    sys.modules["ollama"] = types.SimpleNamespace(chat=lambda *args, **kwargs: None)

import hachi_agent
import hachi_db
import hachi_memory
import hachi_productivity
import hachi_tools
from hachi_runtime import TurnCancelled, create_turn, finish_turn


class MultiCommandTests(unittest.TestCase):
    def test_extracts_explicit_app_batch(self):
        self.assertEqual(
            hachi_agent._extract_app_batch("Open Discord, Spotify, and Chrome please"),
            ["Discord", "Spotify", "Chrome"],
        )

    def test_does_not_split_dependent_or_search_language(self):
        self.assertEqual(hachi_agent._extract_app_batch("Open Chrome and search for cats and dogs"), [])

    def test_fast_batch_executes_every_app_and_reports_each_result(self):
        outputs = {
            "Discord": "Opened Discord successfully.",
            "Spotify": "Sent the command to open Spotify, but I could not verify its window.",
            "Chrome": "Sorry, I couldn't find or open Chrome.",
        }

        def fake_tool(_name, arguments):
            return outputs[arguments["app_name"]]

        response, actions = hachi_agent.check_fast_intent(
            "open Discord, Spotify, and Chrome", tool_runner=fake_tool
        )
        self.assertEqual([row["args"]["app_name"] for row in actions], ["Discord", "Spotify", "Chrome"])
        self.assertIn("Opened Discord", response)
        self.assertIn("could not verify", response)
        self.assertIn("Could not open Chrome", response)

    def test_stream_emits_one_terminal_event_for_multiple_model_actions(self):
        actions = [
            {"tool": "launch_app", "args": {"app_name": "first"}, "output": "done first"},
            {"tool": "launch_app", "args": {"app_name": "second"}, "output": "done second"},
        ]
        with patch(
            "hachi_agent._run_qwen_agent_loop",
            return_value=("done first done second", actions, True),
        ), patch("hachi_agent.add_message"), patch("hachi_agent._update_history"):
            events = list(hachi_agent.process_agent_request_stream("open first and second"))
        terminals = [event for event in events if event.get("done")]
        self.assertEqual(len(terminals), 1)
        self.assertEqual(terminals[0]["full"], "done first done second")
        self.assertEqual(len(terminals[0]["tools"]), 2)


class ModelToolLoopTests(unittest.TestCase):
    def test_model_can_call_another_tool_after_result(self):
        decisions = [
            types.SimpleNamespace(content="", tool_calls=[{
                "id": "search-1", "function": {"name": "search_web", "arguments": {"query": "topic"}}
            }]),
            types.SimpleNamespace(content="", tool_calls=[{
                "id": "fetch-1", "function": {"name": "fetch_url", "arguments": {"url": "https://example.com"}}
            }]),
            types.SimpleNamespace(content="Finished from both sources.", tool_calls=[]),
        ]
        calls = []

        def fake_decide(_messages, **_kwargs):
            msg = decisions.pop(0)
            return msg, msg.tool_calls

        def fake_tool(name, args, call_id=""):
            calls.append((name, args, call_id))
            return f"result from {name}"

        with patch("hachi_agent._qwen_tool_decide", side_effect=fake_decide):
            answer, executed, handled = hachi_agent._run_qwen_agent_loop(
                [{"role": "user", "content": "research topic"}], "research topic", fake_tool, lambda: None
            )
        self.assertTrue(handled)
        self.assertEqual(answer, "Finished from both sources.")
        self.assertEqual([row[0] for row in calls], ["search_web", "fetch_url"])
        self.assertEqual([row["tool"] for row in executed], ["search_web", "fetch_url"])

    def test_unknown_answer_automatically_searches_web(self):
        decisions = [
            types.SimpleNamespace(content="I don't know.", tool_calls=[]),
            types.SimpleNamespace(content="I found the current answer.", tool_calls=[]),
        ]
        calls = []

        def fake_decide(_messages, **_kwargs):
            msg = decisions.pop(0)
            return msg, msg.tool_calls

        def fake_tool(name, args, call_id=""):
            calls.append(name)
            return "live evidence"

        with patch("hachi_agent._qwen_tool_decide", side_effect=fake_decide):
            answer, executed, handled = hachi_agent._run_qwen_agent_loop(
                [{"role": "user", "content": "what is current X"}], "what is current X", fake_tool, lambda: None
            )
        self.assertTrue(handled)
        self.assertEqual(answer, "I found the current answer.")
        self.assertEqual(calls, ["research_web"])
        self.assertEqual(executed[0]["tool"], "research_web")


class RuntimeTests(unittest.TestCase):
    def test_turn_actions_are_idempotent_across_provider_call_ids(self):
        ctx = create_turn("test-idempotency")
        calls = []
        try:
            first, reused_first = ctx.run_action(
                "launch_app", {"app_name": "Discord"}, lambda: calls.append(1) or "ok", call_id="deepseek-1"
            )
            second, reused_second = ctx.run_action(
                "launch_app", {"app_name": "Discord"}, lambda: calls.append(2) or "wrong", call_id="qwen-9"
            )
            self.assertEqual((first, second), ("ok", "ok"))
            self.assertFalse(reused_first)
            self.assertTrue(reused_second)
            self.assertEqual(calls, [1])
        finally:
            finish_turn(ctx.turn_id)

    def test_cancelled_turn_rejects_future_actions(self):
        ctx = create_turn("test-cancel")
        try:
            ctx.cancel_event.set()
            with self.assertRaises(TurnCancelled):
                ctx.run_action("launch_app", {"app_name": "Discord"}, lambda: "should not run")
        finally:
            finish_turn(ctx.turn_id)


class ToolProtocolTests(unittest.TestCase):
    def test_repairs_truncated_json(self):
        self.assertEqual(hachi_agent._parse_tool_args('{"query": "hachi voice"', "search_web"), {"query": "hachi voice"})

    def test_repairs_fenced_nested_json(self):
        repaired = hachi_agent._parse_tool_args(
            '```json\n{"options": {"apps": ["Discord", "Spotify"]}}\n```', "launch_app"
        )
        self.assertEqual(repaired["options"]["apps"], ["Discord", "Spotify"])

    def test_schema_rejects_missing_required_argument(self):
        valid, message = hachi_agent._validate_tool_args("launch_app", {})
        self.assertFalse(valid)
        self.assertIn("app_name", message)

    def test_schema_rejects_unknown_tool(self):
        valid, _message = hachi_agent._validate_tool_args("delete_everything", {})
        self.assertFalse(valid)


class WindowsAppTests(unittest.TestCase):
    def test_start_app_exact_resolution(self):
        rows = [
            {"name": "Calculator", "app_id": "Microsoft.WindowsCalculator_8wekyb3d8bbwe!App"},
            {"name": "Clock", "app_id": "Microsoft.WindowsAlarms_8wekyb3d8bbwe!App"},
        ]
        with patch("hachi_tools._get_start_apps", return_value=rows):
            match, ambiguous = hachi_tools._resolve_start_app("calculator")
        self.assertFalse(ambiguous)
        self.assertEqual(match["name"], "Calculator")

    def test_private_fetch_targets_are_blocked(self):
        self.assertFalse(hachi_tools._is_public_http_url("http://127.0.0.1/private"))
        self.assertFalse(hachi_tools._is_public_http_url("file:///C:/secret.txt"))

    def test_close_both_targets_recently_opened_apps(self):
        original = list(hachi_tools._recent_opened_apps)
        original_loaded = hachi_tools._recent_apps_loaded
        hachi_tools._recent_opened_apps[:] = ["Discord", "Chrome"]
        hachi_tools._recent_apps_loaded = True
        try:
            with patch("hachi_tools.close_app", side_effect=lambda name: f"Closed {name}.") as close:
                result = hachi_tools.close_recent_apps(2)
            self.assertEqual([call.args[0] for call in close.call_args_list], ["Chrome", "Discord"])
            self.assertIn("Discord", result)
            self.assertIn("Chrome", result)
        finally:
            hachi_tools._recent_opened_apps[:] = original
            hachi_tools._recent_apps_loaded = original_loaded

    def test_gaming_launch_uses_steam_big_picture_protocol(self):
        with patch("hachi_tools.os.startfile") as startfile, patch(
            "hachi_tools._visible_window_processes", return_value=set()
        ), patch("hachi_tools._wait_for_app_window", return_value=True):
            detail = hachi_tools.launch_app_detailed("steam", args=["-bigpicture"])
        startfile.assert_called_once_with("steam://open/bigpicture")
        self.assertTrue(detail["verified"])
        self.assertEqual(detail["app"], "Steam Big Picture")


class VoiceContractTests(unittest.TestCase):
    def test_stop_phrase_matching_is_exact(self):
        import hachi_speech

        self.assertTrue(hachi_speech._is_stop_phrase("Hachi stop"))
        self.assertFalse(hachi_speech._is_stop_phrase("don't stop"))
        self.assertFalse(hachi_speech._is_stop_phrase("the bus stop is nearby"))

    def test_cancel_endpoint_marks_active_turn(self):
        import hachi_web

        ctx = create_turn("endpoint-cancel-test")
        try:
            with hachi_web.app.test_client() as client:
                response = client.post("/api/cancel_turn", json={"turn_id": ctx.turn_id})
            self.assertEqual(response.status_code, 200)
            self.assertTrue(ctx.cancelled)
        finally:
            finish_turn(ctx.turn_id)

    def test_audio_interrupt_endpoint_recognizes_stop_and_cancels(self):
        import hachi_web

        ctx = create_turn("audio-interrupt-test")
        try:
            with patch("hachi_whisper.transcribe_audio_file", return_value="Hachi stop"), patch(
                "hachi_web.interrupt_speech"
            ) as interrupt, hachi_web.app.test_client() as client:
                response = client.post(
                    "/api/transcribe_interrupt",
                    data={"turn_id": ctx.turn_id, "audio": (io.BytesIO(b"RIFFdummy"), "interrupt.wav")},
                    content_type="multipart/form-data",
                )
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.get_json()["stop"])
            self.assertTrue(ctx.cancelled)
            interrupt.assert_called_once()
        finally:
            finish_turn(ctx.turn_id)


class SearchTests(unittest.TestCase):
    def test_search_deduplicates_urls_across_subqueries(self):
        rows = [
            {"title": "Hachi", "url": "https://example.com/hachi", "snippet": "Hachi voice assistant", "provider": "duckduckgo", "query": "q"},
            {"title": "Duplicate", "url": "https://example.com/hachi/", "snippet": "same page", "provider": "duckduckgo", "query": "q2"},
        ]
        with patch("hachi_tools._focused_search_queries", return_value=["q", "q2"]), patch(
            "hachi_tools._search_ddgs", return_value=rows
        ):
            result = hachi_tools.search_web_records("Hachi voice")
        self.assertEqual(len(result), 1)


class DurableMemoryTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_db_path = hachi_db.DB_PATH
        self.original_write_conn = hachi_db._write_conn
        hachi_db.DB_PATH = os.path.join(self.temp_dir.name, "test_memory.db")
        hachi_db._write_conn = None

    def tearDown(self):
        if hachi_db._write_conn is not None:
            hachi_db._write_conn.close()
        hachi_db._write_conn = self.original_write_conn
        hachi_db.DB_PATH = self.original_db_path
        self.temp_dir.cleanup()

    def test_duplicate_and_superseding_memory(self):
        first = hachi_memory.save_memory("My favorite color is blue", subject="favorite color")
        duplicate = hachi_memory.save_memory("My favorite color is blue", subject="favorite color")
        changed = hachi_memory.save_memory("My favorite color is green", subject="favorite color")
        self.assertEqual(first["status"], "saved")
        self.assertEqual(duplicate["status"], "duplicate")
        self.assertEqual(changed["supersedes_id"], first["id"])
        matches = hachi_memory.search_memories("what color do I like", min_score=-1)
        self.assertEqual(len(matches), 1)
        self.assertIn("green", matches[0]["content"])

    def test_memory_scope_isolated_by_user(self):
        hachi_memory.save_memory("I prefer tea", user_id="alice")
        self.assertEqual(hachi_memory.search_memories("tea", user_id="bob", min_score=-1), [])

    def test_allergy_is_stored_as_a_structured_personal_fact(self):
        saved = hachi_memory.save_memory("I'm allergic to peanuts")
        self.assertEqual(saved["status"], "saved")
        matches = hachi_memory.search_memories("What am I allergic to?", min_score=-1)
        self.assertEqual(matches[0]["category"], "health")
        self.assertEqual(matches[0]["subject"], "allergies")
        self.assertIn("peanuts", matches[0]["content"])

    def test_personal_fact_question_routes_to_memory(self):
        self.assertTrue(hachi_agent._is_memory_request("What am I allergic to?"))
        self.assertTrue(hachi_agent._is_memory_request("What do I prefer?"))
        self.assertFalse(hachi_agent._is_memory_request("What is the weather?"))

    def test_memory_search_terms_prefer_the_topic_over_question_words(self):
        terms = hachi_agent._memory_search_terms("What did I tell you about my AI project idea last week?")
        self.assertIn("project", terms)
        self.assertNotIn("what", terms)


class ProductivityTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_db_path = hachi_db.DB_PATH
        self.original_write_conn = hachi_db._write_conn
        self.original_roots = hachi_productivity.ALLOWED_FILE_ROOTS
        hachi_db.DB_PATH = os.path.join(self.temp_dir.name, "productivity.db")
        hachi_db._write_conn = None
        hachi_productivity.ALLOWED_FILE_ROOTS = (Path(self.temp_dir.name).resolve(),)

    def tearDown(self):
        if hachi_db._write_conn is not None:
            hachi_db._write_conn.close()
        hachi_db._write_conn = self.original_write_conn
        hachi_db.DB_PATH = self.original_db_path
        hachi_productivity.ALLOWED_FILE_ROOTS = self.original_roots
        self.temp_dir.cleanup()

    def test_reminder_assignment_note_and_todo_are_persistent(self):
        self.assertIn("Reminder #", hachi_productivity.set_reminder("Stretch", minutes_from_now=5))
        self.assertIn("Stretch", hachi_productivity.list_reminders())
        self.assertIn(
            "Assignment #",
            hachi_productivity.add_assignment_deadline("Essay", "tomorrow 5 PM", "English"),
        )
        self.assertIn("Essay", hachi_productivity.list_assignment_deadlines(7))
        self.assertIn("Saved note #", hachi_productivity.save_note("Use chapter three", "Research"))
        self.assertIn("chapter three", hachi_productivity.list_notes(query="chapter"))
        self.assertIn("Added to-do #", hachi_productivity.add_todo("Review citations"))
        self.assertIn("Review citations", hachi_productivity.list_todos())

    def test_reads_local_text_document_from_allowed_root(self):
        document = Path(self.temp_dir.name) / "sample.txt"
        document.write_text("Alpha beta gamma", encoding="utf-8")
        result = hachi_productivity.read_document(str(document))
        self.assertIn("Alpha beta gamma", result)


if __name__ == "__main__":
    unittest.main()
