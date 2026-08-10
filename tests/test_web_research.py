import unittest
from unittest.mock import patch

from hachi_tools import _normalize_search_queries, research_web, search_web, search_web_records


class WebResearchTests(unittest.TestCase):
    def test_normalizes_and_limits_model_queries(self):
        queries = _normalize_search_queries(
            queries=["  Qwen\x00 web search  ", "Qwen web search", "two", "three", "four"]
        )
        self.assertEqual(queries, ["Qwen web search", "two", "three"])

    @patch("hachi_tools._search_provider")
    def test_multi_query_results_are_deduplicated_and_cited(self, search_provider):
        search_provider.side_effect = [
            [
                {"title": "First", "url": "https://example.com/a", "snippet": "First evidence", "provider": "test"},
                {"title": "Duplicate", "url": "https://example.com/a", "snippet": "Duplicate", "provider": "test"},
            ],
            [{"title": "Second", "url": "https://example.org/b", "snippet": "Second evidence", "provider": "test"}],
        ]
        records = search_web_records(queries=["first query", "second query"], max_results=8)
        self.assertEqual({row["url"] for row in records}, {"https://example.com/a", "https://example.org/b"})

        search_provider.side_effect = [[{"title": "First", "url": "https://example.com/a", "snippet": "First evidence", "provider": "test"}]]
        evidence = search_web(queries=["first query"])
        self.assertIn("LIVE WEB EVIDENCE", evidence)
        self.assertIn("[1] First", evidence)
        self.assertIn("URL: https://example.com/a", evidence)

    @patch("hachi_tools.add_task")
    @patch("hachi_tools.fetch_url")
    @patch("hachi_tools._is_public_http_url", return_value=True)
    @patch("hachi_tools.search_web_records")
    def test_research_reads_sources_and_marks_them_for_citation(self, records, is_public, fetch_url, add_task):
        records.return_value = [
            {"title": "Official release news", "url": "https://example.com/news", "snippet": "Released today", "provider": "test", "relevance": 3},
            {"title": "Secondary coverage", "url": "https://example.org/story", "snippet": "Coverage", "provider": "test", "relevance": 1},
        ]
        fetch_url.return_value = "**Untrusted web content from https://example.com/news:**\n\nOfficial page confirms the release."

        evidence = research_web("latest example release")

        self.assertIn("RESEARCH EVIDENCE", evidence)
        self.assertIn("[1] Official release news", evidence)
        self.assertIn("Page evidence", evidence)
        self.assertEqual(fetch_url.call_count, 2)
        add_task.assert_called_once()


if __name__ == "__main__":
    unittest.main()
