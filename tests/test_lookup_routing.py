import unittest
from types import SimpleNamespace
from unittest.mock import patch

from hachi_agent import (
    _run_qwen_agent_loop,
    build_lookup_query,
    classify_intent,
    detect_intent_tool_call,
)


class LookupRoutingTests(unittest.TestCase):
    QUERY = "what's the latest game released by bandai namco"

    def test_latest_game_release_uses_tool_enabled_route(self):
        self.assertEqual(classify_intent(self.QUERY), "TOOL_NEEDED")

    def test_current_season_uses_tool_enabled_route(self):
        self.assertEqual(classify_intent("what season is it in tekken 8?"), "TOOL_NEEDED")

    def test_lookup_precedes_game_mode_shortcut(self):
        tool_name, args = detect_intent_tool_call(self.QUERY)
        self.assertEqual(tool_name, "research_web")
        self.assertEqual(args, {"query": build_lookup_query(self.QUERY)})

    @patch("hachi_agent._qwen_tool_decide")
    def test_confident_offline_answer_is_replaced_with_live_search(self, decide):
        decide.side_effect = [
            (SimpleNamespace(content="I do not have real-time access."), []),
            (SimpleNamespace(content="The live result is cited below [1]."), []),
        ]
        calls = []

        def run_tool(name, args, call_id):
            calls.append((name, args, call_id))
            return "LIVE WEB EVIDENCE for: latest game released by bandai namco\n[1] Current game"

        answer, tools, handled = _run_qwen_agent_loop(
            [{"role": "user", "content": self.QUERY}], self.QUERY, run_tool, lambda: None
        )

        self.assertTrue(handled)
        self.assertEqual(answer, "The live result is cited below [1].")
        self.assertEqual(calls[0][0], "research_web")
        self.assertEqual(tools[0]["tool"], "research_web")

    @patch("hachi_agent.DEEPSEEK_API_KEY", "test-key")
    @patch("hachi_agent._qwen_tool_decide")
    def test_unknown_non_web_answer_delegates_to_cloud_reasoning(self, decide):
        query = "An unfamiliar abstract concept"
        decide.side_effect = [
            (SimpleNamespace(content="I do not know."), []),
            (SimpleNamespace(content="Here is the delegated explanation."), []),
        ]
        calls = []

        def run_tool(name, args, call_id):
            calls.append((name, args, call_id))
            return "CLOUD REASONING (read-only second opinion): explanation"

        answer, tools, handled = _run_qwen_agent_loop(
            [{"role": "user", "content": query}], query, run_tool, lambda: None
        )

        self.assertTrue(handled)
        self.assertEqual(answer, "Here is the delegated explanation.")
        self.assertEqual(calls[0][0], "delegate_reasoning")
        self.assertEqual(tools[0]["capability"]["safety"], "cloud_read_only")


if __name__ == "__main__":
    unittest.main()
