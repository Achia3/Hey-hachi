from flask import Flask, render_template, request, jsonify
import speech_recognition as sr
import pyttsx3
import ollama
import threading
import logging
import json
from datetime import datetime
import subprocess
import sys
import os
import re
import webbrowser

# Configure logging
logging.basicConfig(
    filename="hachi.log",
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)

app = Flask(__name__)

# Initialize voice components
recognizer = sr.Recognizer()
recognizer.energy_threshold = 4000
recognizer.dynamic_energy_threshold = True

engine = pyttsx3.init()
engine.setProperty("rate", 150)
tts_lock = threading.Lock()
tts_state_lock = threading.Lock()
speech_generation = 0

# AI Configuration
AI_NAME = "Hachi"
WAKE_WORD = "hey hachi"
MODEL = "qwen2.5:3b"
SELECTED_MIC = None
SYSTEM_PROMPT = """You are Hachi, a helpful desktop assistant. Give clear, calm,
concise answers. Use short sentences and short numbered steps only when they help.
For recipes, give a small ingredient list followed by 3 to 6 simple steps. Do not
use Markdown syntax: no hashtags, asterisks, bold text, tables, or long essays."""

def clean_ai_response(text):
    """Remove any Markdown that a model returns despite the response style."""
    text = re.sub(r'(?m)^\s{0,3}#{1,6}\s*', '', text)
    text = text.replace('**', '').replace('__', '').replace('`', '')
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()

# Mode configurations - define which apps launch for each mode
MODES = {
    "gaming mode": {
        "name": "Gaming",
        "description": "Gaming mode activated.",
        "apps": ["discord", "steam"],
        "icon": "🎮"
    },
    "office mode": {
        "name": "Office",
        "description": "Office mode activated.",
        "apps": ["vscode", "chatgpt"],
        "icon": "💼"
    },
    "study mode": {
        "name": "Study",
        "description": "Study mode activated - launching learning apps",
        "apps": ["vscode"],
        "icon": "📚"
    },
}

# Commands must include "start" so normal conversation never launches apps.
MODE_COMMANDS = {
    "start gaming mode": "gaming mode",
    "start office mode": "office mode",
}

# App paths for Windows - you can customize these
APP_PATHS = {
    "discord": [
        r"C:\Users\{user}\AppData\Local\Discord\app-*\Discord.exe",
        "discord",  # Fallback to just try launching by name
    ],
    "steam": [
        r"C:\Program Files (x86)\Steam\steam.exe",
        r"C:\Program Files\Steam\steam.exe",
        "steam",
    ],
    "slack": [
        r"C:\Users\{user}\AppData\Local\slack\slack.exe",
        "slack",
    ],
    "vscode": [
        r"C:\Users\{user}\AppData\Local\Programs\Microsoft VS Code\Code.exe",
        r"C:\Program Files\Microsoft VS Code\Code.exe",
        "code",
    ],
    "outlook": [
        r"C:\Program Files\Microsoft Office\root\Office16\OUTLOOK.EXE",
        r"C:\Program Files (x86)\Microsoft Office\root\Office16\OUTLOOK.EXE",
        "outlook",
    ],
}

def get_app_path(app_name):
    """Find the actual path for an application"""
    if app_name not in APP_PATHS:
        return None
    
    username = os.getenv('USERNAME', 'User')
    paths = APP_PATHS[app_name]
    
    for path_pattern in paths:
        # Replace username placeholder
        path = path_pattern.format(user=username)
        
        # Handle wildcard patterns (like for Discord)
        if '*' in path:
            import glob
            matches = glob.glob(path)
            if matches:
                return matches[0]
        
        # Check if file exists
        if os.path.exists(path):
            return path
    
    return None

def launch_app(app_name):
    """Launch an application"""
    try:
        if app_name == "chatgpt":
            webbrowser.open("https://chatgpt.com", new=2)
            logging.info("Opened ChatGPT in the default browser")
            return True

        app_path = get_app_path(app_name)
        
        if app_path is None:
            logging.warning(f"Could not find path for {app_name}")
            return False
        
        # Check if app is already running
        if sys.platform == 'win32':
            # Try to launch
            subprocess.Popen(app_path, shell=False)
            logging.info(f"Launched: {app_name}")
            return True
        
    except Exception as e:
        logging.error(f"Error launching {app_name}: {e}")
        return False

def detect_mode(text):
    """Detect an explicitly requested application-launching mode."""
    text_lower = " ".join(text.lower().split())
    
    for command, mode_key in MODE_COMMANDS.items():
        if command in text_lower:
            return mode_key
    
    return None

# Get list of available microphones
def get_microphones_list():
    try:
        import pyaudio
        p = pyaudio.PyAudio()
        mics = []
        device_count = p.get_device_count()
        
        for i in range(device_count):
            info = p.get_device_info_by_index(i)
            if info['maxInputChannels'] > 0:  # Input device
                mics.append({
                    "id": i,
                    "name": info['name'],
                    "channels": info['maxInputChannels']
                })
        
        p.terminate()
        return mics
    except Exception as e:
        logging.error(f"Error getting microphones: {e}")
        return []

# Find best microphone
def find_best_microphone():
    try:
        import pyaudio
        p = pyaudio.PyAudio()
        preferred = ["Razer BlackShark", "Microphone (USB", "Microphone"]
        device_count = p.get_device_count()
        default_device = None
        
        for i in range(device_count):
            info = p.get_device_info_by_index(i)
            if info['maxInputChannels'] > 0:
                device_name = info['name']
                for pref in preferred:
                    if pref.lower() in device_name.lower():
                        p.terminate()
                        return i
                if default_device is None:
                    default_device = i
        
        if default_device is not None:
            p.terminate()
            return default_device
        
        p.terminate()
        return None
    except Exception as e:
        logging.error(f"Error finding microphone: {e}")
        return None

MICROPHONE_INDEX = find_best_microphone()
SELECTED_MIC = MICROPHONE_INDEX

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/microphones', methods=['GET'])
def get_microphones():
    """Get list of available microphones"""
    mics = get_microphones_list()
    return jsonify({
        "success": True,
        "microphones": mics,
        "selected": SELECTED_MIC
    })

@app.route('/api/set-microphone', methods=['POST'])
def set_microphone():
    """Set the selected microphone"""
    global SELECTED_MIC
    data = request.json
    mic_id = data.get('mic_id')
    
    try:
        SELECTED_MIC = int(mic_id) if mic_id is not None else None
        logging.info(f"Microphone changed to: {SELECTED_MIC}")
        return jsonify({"success": True, "selected": SELECTED_MIC})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

@app.route('/api/listen', methods=['POST'])
def listen():
    """Listen for audio input"""
    try:
        if SELECTED_MIC is not None:
            source = sr.Microphone(device_index=SELECTED_MIC)
        else:
            source = sr.Microphone()
        
        with source as mic_source:
            recognizer.adjust_for_ambient_noise(mic_source, duration=0.5)
            
            try:
                audio = recognizer.listen(
                    mic_source,
                    timeout=15,
                    phrase_time_limit=15
                )
            except sr.WaitTimeoutError:
                return jsonify({"success": False, "error": "Timeout - no audio detected"})
            
            try:
                text = recognizer.recognize_google(audio)
                return jsonify({"success": True, "text": text.lower()})
            except sr.UnknownValueError:
                return jsonify({"success": False, "error": "Could not understand audio"})
            except sr.RequestError as e:
                return jsonify({"success": False, "error": f"API Error: {str(e)[:50]}"})
    
    except Exception as e:
        logging.error(f"Listen error: {e}")
        return jsonify({"success": False, "error": str(e)[:50]})

@app.route('/api/chat', methods=['POST'])
def chat():
    """Get AI response"""
    try:
        data = request.json
        user_input = data.get('message', '')
        
        if not user_input:
            return jsonify({"success": False, "error": "No message provided"})
        
        response = ollama.chat(
            model=MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_input},
            ],
            options={"temperature": 0.3}
        )
        
        ai_response = clean_ai_response(response['message']['content'])
        
        logging.info(f"User: {user_input}")
        logging.info(f"Hachi: {ai_response}")
        
        return jsonify({"success": True, "response": ai_response})
    
    except Exception as e:
        logging.error(f"Chat error: {e}")
        return jsonify({"success": False, "error": str(e)})

@app.route('/api/speak', methods=['POST'])
def speak():
    """Speak text"""
    global speech_generation
    try:
        data = request.json
        text = data.get('text', '')
        
        if not text:
            return jsonify({"success": False, "error": "No text provided"})
        
        # A stop request invalidates queued speech before it gets the engine.
        with tts_state_lock:
            speech_generation += 1
            request_generation = speech_generation

        # Run text-to-speech in background
        def speak_async():
            try:
                # pyttsx3 supports only one active event loop at a time.
                with tts_lock:
                    with tts_state_lock:
                        if request_generation != speech_generation:
                            return
                    engine.say(text)
                    engine.runAndWait()
            except Exception as e:
                logging.error(f"TTS error: {e}")
        
        thread = threading.Thread(target=speak_async, daemon=True)
        thread.start()
        
        return jsonify({"success": True})
    
    except Exception as e:
        logging.error(f"Speak error: {e}")
        return jsonify({"success": False, "error": str(e)})

@app.route('/api/stop-speaking', methods=['POST'])
def stop_speaking():
    """Stop speech now and cancel any speech that is still queued."""
    global speech_generation
    try:
        with tts_state_lock:
            speech_generation += 1
        engine.stop()
        return jsonify({"success": True})
    except Exception as e:
        logging.error(f"Stop speaking error: {e}")
        return jsonify({"success": False, "error": str(e)})

@app.route('/api/activate-mode', methods=['POST'])
def activate_mode():
    """Activate a mode (gaming, office, study, etc)"""
    try:
        data = request.json
        user_text = data.get('text', '').lower()
        
        # Detect which mode was requested
        detected_mode = detect_mode(user_text)
        
        if not detected_mode:
            return jsonify({
                "success": False,
                "error": "Say 'start gaming mode' or 'start office mode'."
            })
        
        mode_info = MODES[detected_mode]
        
        # Launch all apps for this mode
        launched_apps = []
        for app_name in mode_info["apps"]:
            if launch_app(app_name):
                launched_apps.append(app_name)
        
        response_text = f"{mode_info['description']}"
        if launched_apps:
            response_text += f" Launched: {', '.join(launched_apps)}."
        
        logging.info(f"Mode activated: {detected_mode}, Apps launched: {launched_apps}")
        
        return jsonify({
            "success": True,
            "mode": mode_info["name"],
            "icon": mode_info["icon"],
            "response": response_text,
            "launched_apps": launched_apps
        })
    
    except Exception as e:
        logging.error(f"Mode activation error: {e}")
        return jsonify({"success": False, "error": str(e)})

if __name__ == '__main__':
    print("\n" + "="*60)
    print("  HACHI - AI Voice Assistant (Web UI)")
    print("="*60)
    print("\n🌐 Opening at: http://localhost:5000")
    print("🎤 Microphone:", "Found" if MICROPHONE_INDEX is not None else "Using default")
    print("🤖 Model: qwen2.5:3b")
    print("\nMake sure Ollama is running! Press Ctrl+C to stop.\n")
    
    app.run(debug=False, port=5000)
