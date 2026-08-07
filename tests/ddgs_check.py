import sys
import traceback
import os
# Ensure repo root is on sys.path for local imports
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
from hachi_tools import search_web

print('PYTHON', sys.version)
# Test import of ddgs
try:
    import ddgs
    print('ddgs imported:', ddgs)
except Exception as e:
    print('ddgs import failed:', e)
    traceback.print_exc()

# Run search_web directly
try:
    print('\nCalling search_web("python release date")...')
    out = search_web('python release date')
    print('search_web returned (truncated 1000 chars):')
    print(out[:1000])
except Exception as e:
    print('search_web raised:', e)
    traceback.print_exc()
