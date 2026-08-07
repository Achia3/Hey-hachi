import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from hachi_agent import classify_intent, check_fast_intent, is_lookup_request, build_lookup_query

queries = [
    "what's the size of rs3m v5",
    "can you look up the latest release from dayan",
    "what's the latest release from qiyi",
    "search for dayan cube size",
]

for q in queries:
    print(f"QUERY: {q}")
    print("lookup?", is_lookup_request(q))
    print("intent:", classify_intent(q))
    print("normalized:", build_lookup_query(q))
    fast = check_fast_intent(q)
    print("fast_result_is_none:", fast is None)
    if fast:
        text, tools = fast
        print("text:", text[:300])
        print("tools:", tools)
    print("---")
