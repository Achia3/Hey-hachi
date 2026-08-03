# HACHI - AI Voice Assistant with GUI

A fully-featured voice-enabled AI assistant with a graphical interface. Say "Hey, Hachi" to activate and interact with your AI!

## Features

✨ **Voice Activation** - Say "Hey, Hachi" wake word to activate
🎤 **Real-time Voice Input** - Speak your commands naturally
🔊 **Text-to-Speech** - Hachi responds with voice
💬 **Conversation History** - Full chat log displayed in GUI
🖥️ **Modern GUI Interface** - Clean, intuitive interface
🚀 **Powered by Ollama** - Uses local Qwen 2.5 3B model
📊 **Logging** - All interactions logged to hachi.log

## Requirements

- Python 3.8+
- Ollama running locally (http://localhost:11434)
- Microphone/speaker on your system
- Internet connection for Google Speech Recognition API

## Setup Instructions

### 1. Install Python Dependencies

```bash
cd c:\Users\AxeilAchia\Desktop\ai
pip install -r requirements.txt
```

### 2. Verify Ollama is Running

Make sure Ollama is running with the Qwen 2.5 3B model:
```bash
ollama serve
```

In another terminal, pull the model if not already present:
```bash
ollama pull qwen2.5:3b
```

### 3. Run Hachi

```bash
python hachi_gui.py
```

## How to Use

1. **Start the Application** - Run `python hachi_gui.py`
2. **Click "Start Listening"** - Begin voice mode
3. **Say "Hey, Hachi"** - Activate the AI
4. **Speak your command** - Ask Hachi anything
5. **Receive response** - Hachi responds with voice + text

## Customization

You can customize Hachi by editing these variables in `hachi_gui.py`:

```python
self.ai_name = "Hachi"           # AI name
self.wake_word = "hey hachi"     # Wake word
self.model = "qwen2.5:3b"        # Ollama model
self.engine.setProperty("rate", 150)  # Speech speed
```

## Troubleshooting

### Microphone Not Detected
- Check if microphone is connected
- Verify system audio settings
- May need to run as Administrator on Windows

### "Could not understand audio"
- Speak clearly and slowly
- Reduce background noise
- Ensure mic is working in Windows Sound Settings

### No response from Ollama
- Verify Ollama is running: `http://localhost:11434`
- Check that `qwen2.5:3b` model is installed
- Run: `ollama list`

### Google Speech Recognition failing
- Ensure internet connection
- Try again - API may be rate limited

## Log Files

- **hachi.log** - All interaction logs
- **system_verification.log** - System check logs

## Architecture

```
Hachi AI Flow:
1. User says "Hey, Hachi" (wake word detection)
2. System listens to user command
3. Audio converted to text (Google Speech Recognition)
4. Text sent to Ollama (Qwen 2.5 3B model)
5. AI generates response
6. Response displayed in GUI
7. Response spoken via text-to-speech (pyttsx3)
```

## Project Files

- **hachi_gui.py** - Main GUI application with voice interaction
- **app_verification.py** - System verification script
- **requirements.txt** - Python dependencies
- **README.md** - This file

## License

APEX TECH LOCAL AI ENGINE

---

**Enjoy using HACHI! 🎤🤖**
