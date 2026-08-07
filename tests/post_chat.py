import requests
import json

def post_chat(msg):
    url = 'http://127.0.0.1:5000/api/chat'
    data = {'message': msg, 'mode': 'default', 'voice_mode': False}
    r = requests.post(url, json=data, timeout=15)
    print('Status:', r.status_code)
    print('Response:', r.json())

if __name__ == '__main__':
    msg = "what is the date today? oh also open obsidian for me"
    post_chat(msg)
