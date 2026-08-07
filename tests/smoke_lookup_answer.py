import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from hachi_agent import process_agent_request

queries = [
    "what's the size of rs3m v5",
    "what's the latest release from dayan",
]

for query in queries:
    print(f"QUERY: {query}")
    text, tools, engine, pomo = process_agent_request(query)
    print(f"ENGINE: {engine}")
    print(f"POMO: {pomo}")
    print("ANSWER:")
    print(text)
    print("TOOLS:")
    for tool in tools:
        print(tool)
    print("---")
