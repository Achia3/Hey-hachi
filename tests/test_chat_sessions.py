import unittest
from uuid import uuid4

from hachi_agent import _get_history, _update_history


class ChatSessionTests(unittest.TestCase):
    def test_in_session_history_is_isolated_by_conversation_id(self):
        first = f"first-{uuid4().hex}"
        second = f"second-{uuid4().hex}"

        _update_history("first question", "first answer", conversation_id=first)
        _update_history("second question", "second answer", conversation_id=second)

        self.assertEqual(_get_history(10, first)[0]["content"], "first question")
        self.assertEqual(_get_history(10, second)[0]["content"], "second question")
        self.assertNotIn("second question", str(_get_history(10, first)))


if __name__ == "__main__":
    unittest.main()
