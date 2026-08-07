import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from hachi_tools import search_web
from hachi_agent import _qwen_summarize_search

queries = [
    "what's the size of rs3m v5",
    "what's the latest release from dayan",
]

for query in queries:
    print(f"QUERY: {query}")
    raw = search_web(query)
    print("RAW SEARCH:")
    print(raw)
    print("ANSWER:")
    try:
        answer = _qwen_summarize_search(query, raw, timeout=10.0)
    except Exception as e:
        answer = f"<summary failed: {e}>"
    print(answer)
    print("---")
