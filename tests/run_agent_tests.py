import json
import time
import sys
import os
# Ensure project root is on sys.path so local module imports work from tests/
PROJECT_ROOT = os.path.dirname(os.path.dirname(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
from hachi_agent import process_agent_request, process_agent_request_stream

cases = [
    {
        "name": "Date query",
        "input": "what is the date today?",
    },
    {
        "name": "Multi-command example",
        "input": "what is the date today? oh also i need you to check time oh and can you open obsidian for me i need to take notes",
    },
    {
        "name": "Web search (MoYu cube)",
        "input": "search for MoYu new cube release 2026 latest announcement",
    },
    {
        "name": "Open Obsidian (launch_app)",
        "input": "open obsidian",
    }
]

print("Running agent tests...\n")
results = []
for case in cases:
    name = case['name']
    inp = case['input']
    print(f"-- {name} --")
    try:
        text, tools, engine, pomo = process_agent_request(inp)
        print("Result text:", text)
        print("Executed tools:", tools)
        print("Engine:", engine)
    except Exception as e:
        print("Error:", e)
    print()

# Streaming test for a combined prompt
stream_input = "what is the date today? oh also open obsidian please"
print("-- Streaming test --")
try:
    pieces = []
    for evt in process_agent_request_stream(stream_input, voice_mode=False):
        if evt.get('done'):
            print('Done. full:', evt.get('full'))
            print('tools:', evt.get('tools'))
            print('engine:', evt.get('engine'))
            break
        # show token fragments (trim for readability)
        tok = evt.get('token')
        if tok:
            pieces.append(tok)
    # small sleep to allow any background tasks to settle
    time.sleep(0.2)
except Exception as e:
    print('Stream error:', e)

print('\nTests complete.')
