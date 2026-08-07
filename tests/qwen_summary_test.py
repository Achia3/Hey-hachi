import sys, os
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from hachi_tools import search_web
from hachi_agent import _qwen_summarize_search

q = 'python 3.11 release date'
raw = search_web(q)
print('RAW (truncated):')
print(raw[:800])
print('\n--- Running _qwen_summarize_search() ---')
res = _qwen_summarize_search(q, raw, timeout=10.0)
print('SUMMARY:')
print(res)
