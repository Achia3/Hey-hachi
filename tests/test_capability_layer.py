import unittest
from types import SimpleNamespace
from unittest.mock import patch

from hachi_tools import delegate_reasoning, get_tool_capabilities, run_routine
from hachi_agent import check_fast_intent, select_tools_for_request
from hachi_browser import browser_action


class CapabilityLayerTests(unittest.TestCase):
    def test_registry_exposes_research_and_cloud_safety_levels(self):
        capabilities = {item["name"]: item for item in get_tool_capabilities()}
        self.assertEqual(capabilities["run_routine"]["safety"], "user_intent")
        self.assertEqual(capabilities["research_web"]["safety"], "read_only")
        self.assertEqual(capabilities["delegate_reasoning"]["safety"], "cloud_read_only")
        self.assertEqual(capabilities["shutdown_hachi"]["safety"], "confirm_required")

    @patch("hachi_tools.add_task")
    @patch("hachi_tools.requests.post")
    def test_cloud_delegate_is_read_only_and_returns_answer(self, post, add_task):
        response = SimpleNamespace(
            raise_for_status=lambda: None,
            json=lambda: {"choices": [{"message": {"content": "A reasoned second opinion."}}]},
        )
        post.return_value = response
        with patch.dict("os.environ", {"DEEPSEEK_API_KEY": "test-key"}):
            result = delegate_reasoning("Explain a difficult concept", "User provided context")

        self.assertIn("CLOUD REASONING", result)
        self.assertIn("A reasoned second opinion.", result)
        self.assertEqual(post.call_args.kwargs["json"]["max_tokens"], 700)
        add_task.assert_called_once()

    @patch("hachi_tools.add_task")
    @patch("hachi_tools.execute_tool_call")
    def test_routine_runs_only_its_bounded_manifest_steps(self, execute, add_task):
        execute.side_effect = ["VS Code opened.", "Spotify opened.", "Focus cycle started."]

        result = run_routine("study sprint")

        self.assertIn("ROUTINE COMPLETED: Study Sprint", result)
        self.assertEqual(
            [call.args[0] for call in execute.call_args_list],
            ["launch_app", "launch_app", "set_focus_cycle"],
        )
        add_task.assert_called_once()

    @patch("hachi_tools.execute_tool_call")
    @patch("hachi_tools._load_routines")
    def test_routine_blocks_actions_outside_allow_list(self, load_routines, execute):
        load_routines.return_value = {
            "unsafe": {"name": "Unsafe", "steps": [{"tool": "close_app", "arguments": {"app_name": "explorer"}}]}
        }

        result = run_routine("unsafe")

        self.assertIn("not an allowed Hachi action", result)
        execute.assert_not_called()

    @patch("hachi_tools.execute_tool_call")
    def test_research_routine_requires_a_topic(self, execute):
        result = run_routine("research brief")

        self.assertIn("needs an input", result)
        execute.assert_not_called()

    def test_voice_dictionary_and_dictation_route_without_model(self):
        calls = []
        def runner(name, args):
            calls.append((name, args)); return "ok"

        check_fast_intent("add Tekken 8 to my voice dictionary", tool_runner=runner)
        check_fast_intent("turn on global dictation", tool_runner=runner)

        self.assertEqual(calls, [
            ("add_voice_dictionary_term", {"term": "Tekken 8"}),
            ("set_global_dictation", {"enabled": True}),
        ])

    def test_tool_router_hides_unrelated_and_raw_fetch_tools(self):
        names = [tool["function"]["name"] for tool in select_tools_for_request(
            "Research the latest Qwen release from official sources"
        )]
        self.assertEqual(names, ["research_web", "search_web"])
        self.assertNotIn("fetch_url", names)
        self.assertLessEqual(len(names), 8)

    def test_browser_tools_are_exposed_for_a_browser_goal_and_block_submit(self):
        names = [tool["function"]["name"] for tool in select_tools_for_request(
            "Open Chrome and search the official Python documentation"
        )]
        self.assertTrue({"browser_search", "browser_navigate", "browser_read", "browser_action"}.issubset(names))
        self.assertIn("requires explicit confirmation", browser_action("submit"))


if __name__ == "__main__":
    unittest.main()
