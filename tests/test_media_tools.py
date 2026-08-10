import sys
import unittest
from unittest.mock import patch

from hachi_agent import check_fast_intent, detect_intent_tool_call
from hachi_tools import media_control, play_spotify, play_youtube


class MediaToolTests(unittest.TestCase):
    @patch("hachi_tools.add_task")
    @patch("hachi_tools._send_media_key", return_value=True)
    def test_media_control_uses_native_key_path(self, send_key, add_task):
        result = media_control("volume up")

        self.assertIn("Raised system volume", result)
        send_key.assert_called_once_with("volume_up", 5)
        add_task.assert_called_once()

    @patch("hachi_tools.add_task")
    @patch("hachi_tools.os.startfile")
    def test_spotify_opens_protocol_without_gui_dependencies(self, startfile, add_task):
        with patch.dict(sys.modules, {"pyautogui": None, "pyperclip": None}):
            result = play_spotify("Blinding Lights")

        self.assertIn("Opened Spotify search", result)
        self.assertIn("spotify:search:Blinding%20Lights", startfile.call_args.args[0])
        add_task.assert_called_once()

    @patch("hachi_tools.add_task")
    @patch("hachi_tools.webbrowser.open")
    @patch("hachi_tools.search_web_records")
    def test_youtube_opens_live_video_result(self, search, browser_open, add_task):
        search.return_value = [{"url": "https://www.youtube.com/watch?v=abc123"}]

        result = play_youtube("lofi music")

        self.assertIn("live YouTube result", result)
        self.assertEqual(browser_open.call_args.args[0], "https://www.youtube.com/watch?v=abc123&autoplay=1")
        add_task.assert_called_once()

    def test_spotify_and_youtube_do_not_route_to_gaming_mode(self):
        spotify_tool, spotify_args = detect_intent_tool_call("play Blinding Lights on Spotify")
        youtube_tool, youtube_args = detect_intent_tool_call("watch lo-fi beats on YouTube")

        self.assertEqual((spotify_tool, spotify_args), ("play_spotify", {"query": "Blinding Lights"}))
        self.assertEqual((youtube_tool, youtube_args), ("play_youtube", {"query": "lo-fi beats"}))

    def test_fast_media_route_has_no_model_dependency(self):
        calls = []

        def runner(name, args):
            calls.append((name, args))
            return "done"

        _answer, trace = check_fast_intent("pause", tool_runner=runner)

        self.assertEqual(calls, [("media_control", {"action": "pause"})])
        self.assertEqual(trace[0]["tool"], "media_control")


if __name__ == "__main__":
    unittest.main()
