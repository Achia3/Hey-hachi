import requests
import json

r = requests.get('http://127.0.0.1:5000/api/llm_debug?limit=20', timeout=10)
print('Status:', r.status_code)
print(json.dumps(r.json(), indent=2))
