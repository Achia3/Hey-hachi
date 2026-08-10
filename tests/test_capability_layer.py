import unittest
from types import SimpleNamespace
from unittest.mock import patch

from hachi_tools import delegate_reasoning, get_tool_capabilities


class CapabilityLayerTests(unittest.TestCase):
    def test_registry_exposes_research_and_cloud_safety_levels(self):
        capabilities = {item["name"]: item for item in get_tool_capabilities()}
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


if __name__ == "__main__":
    unittest.main()
