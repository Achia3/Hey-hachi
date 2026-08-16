import unittest
from uuid import uuid4
import os
import tempfile

from hachi_agent import _confirmed_research_query, _get_history, _update_history, is_lookup_request
import hachi_agent
import hachi_db


class ChatSessionTests(unittest.TestCase):
    def test_in_session_history_is_isolated_by_conversation_id(self):
        first = f"first-{uuid4().hex}"
        second = f"second-{uuid4().hex}"

        _update_history("first question", "first answer", conversation_id=first)
        _update_history("second question", "second answer", conversation_id=second)

        self.assertEqual(_get_history(10, first)[0]["content"], "first question")
        self.assertEqual(_get_history(10, second)[0]["content"], "second question")
        self.assertNotIn("second question", str(_get_history(10, first)))

    def test_persisted_history_is_scoped_to_its_conversation(self):
        """A restart must not leak another UI chat into the prompt context."""
        with tempfile.TemporaryDirectory() as temp_dir:
            original_path = hachi_db.DB_PATH
            original_write_conn = hachi_db._write_conn
            hachi_db.DB_PATH = os.path.join(temp_dir, "hachi.db")
            hachi_db._write_conn = None
            try:
                hachi_db.init_db()
                hachi_db.add_message("user", "alpha only", conversation_id="alpha")
                hachi_db.add_message("assistant", "beta only", conversation_id="beta")
                hachi_db.add_task("alpha task", "Success", conversation_id="alpha")
                hachi_db.add_task("beta task", "Success", conversation_id="beta")
                alpha = hachi_db.get_recent_messages(10, conversation_id="alpha")
                beta = hachi_db.get_recent_messages(10, conversation_id="beta")
                self.assertEqual(alpha, [{"role": "user", "content": "alpha only"}])
                self.assertEqual(beta, [{"role": "assistant", "content": "beta only"}])
                self.assertIn("alpha only", hachi_db.search_history("alpha", conversation_id="alpha"))
                self.assertIn("No history", hachi_db.search_history("alpha", conversation_id="beta"))
                self.assertIn("alpha task", hachi_db.search_history("task", conversation_id="alpha"))
                self.assertNotIn("beta task", hachi_db.search_history("task", conversation_id="alpha"))
            finally:
                if hachi_db._write_conn is not None:
                    hachi_db._write_conn.close()
                hachi_db._write_conn = original_write_conn
                hachi_db.DB_PATH = original_path

    def test_restores_a_selected_chat_after_restart(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            original_path = hachi_db.DB_PATH
            original_write_conn = hachi_db._write_conn
            chat_id = f"restored-{uuid4().hex}"
            hachi_db.DB_PATH = os.path.join(temp_dir, "hachi.db")
            hachi_db._write_conn = None
            try:
                hachi_db.init_db()
                hachi_db.add_message("user", "persisted question", conversation_id=chat_id)
                hachi_db.add_message("assistant", "persisted answer", conversation_id=chat_id)
                with hachi_agent._history_lock:
                    hachi_agent._session_histories.pop(chat_id, None)
                    hachi_agent._db_history_loaded.discard(chat_id)
                hachi_agent._ensure_db_history_loaded(chat_id)
                self.assertIn("persisted question", str(_get_history(10, chat_id)))
                self.assertIn("persisted answer", str(_get_history(10, chat_id)))
            finally:
                if hachi_db._write_conn is not None:
                    hachi_db._write_conn.close()
                hachi_db._write_conn = original_write_conn
                hachi_db.DB_PATH = original_path

    def test_affirmative_continues_the_immediately_previous_research_offer(self):
        chat_id = f"confirm-{uuid4().hex}"
        _update_history("what president israel", "I can search the web. Would you like me to look this up?", conversation_id=chat_id)
        self.assertEqual(_confirmed_research_query("Yes", chat_id), "what president israel")

    def test_leader_questions_are_live_lookup_requests(self):
        self.assertTrue(is_lookup_request("what president israel"))


if __name__ == "__main__":
    unittest.main()
