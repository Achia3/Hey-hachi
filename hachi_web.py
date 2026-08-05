import os
import logging
import threading
from flask import Flask, render_template, request, jsonify
from hachi_agent import process_agent_request
from hachi_speech import speak, listen_voice_input

# Logging is configured once in hachi_app.py (the entry point).
# Do NOT call logging.basicConfig() here to avoid double-config.

app = Flask(__name__)

# Port constant — single source of truth referenced by hachi_app.py too
FLASK_PORT = 5000

@app.route('/')
def index():
    """Render main application UI."""
    return render_template('index.html')


@app.route('/api/chat', methods=['POST'])
def api_chat():
    """Handle text chat request."""
    try:
        data = request.json or {}
        user_msg = data.get('message', '').strip()
        current_mode = data.get('mode', 'default')
        if not user_msg:
            return jsonify({'response': '', 'tools': []})

        agent_response, executed_tools = process_agent_request(user_msg, current_mode)

        # Speak response in background thread so HTTP response is returned immediately
        threading.Thread(target=speak, args=(agent_response,), daemon=True).start()

        return jsonify({'response': agent_response, 'tools': executed_tools})
    except Exception as e:
        logging.error(f"api_chat error: {e}")
        return jsonify({'response': 'Sorry, something went wrong on my end.', 'tools': [], 'error': str(e)}), 500


@app.route('/api/voice_listen', methods=['POST'])
def api_voice_listen():
    """Trigger voice recognition input and process agent response."""
    try:
        current_mode = (request.json or {}).get('mode', 'default')
        user_text = listen_voice_input()
        if not user_text:
            return jsonify({'user_text': '', 'response': 'Did not hear any voice input.', 'tools': []})

        agent_response, executed_tools = process_agent_request(user_text, current_mode)

        # Speak response in background thread
        threading.Thread(target=speak, args=(agent_response,), daemon=True).start()

        return jsonify({
            'user_text': user_text,
            'response': agent_response,
            'tools': executed_tools
        })
    except Exception as e:
        logging.error(f"api_voice_listen error: {e}")
        return jsonify({'user_text': '', 'response': 'Voice processing failed.', 'tools': [], 'error': str(e)}), 500


if __name__ == '__main__':
    print(f"Starting Hachi Agent Web Backend on http://127.0.0.1:{FLASK_PORT}...")
    app.run(host='127.0.0.1', port=FLASK_PORT, debug=False, use_reloader=False, threaded=True)
