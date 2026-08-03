# HACHI Quick Start Guide

## 🚀 5-Minute Setup

### Step 1: Install Dependencies
```bash
cd c:\Users\AxeilAchia\Desktop\ai
python -m pip install --upgrade pip
pip install -r requirements.txt
```

**Or simply run the setup script:**
```bash
setup.bat
```

### Step 2: Make Sure Ollama is Running

Open a new terminal/PowerShell and run:
```bash
ollama serve
```

You should see something like:
```
pulling manifest
...
Started serving on 127.0.0.1:11434
```

### Step 3: Verify Qwen Model is Installed

In another terminal, check if the model is installed:
```bash
ollama list
```

If `qwen2.5:3b` is not listed, pull it:
```bash
ollama pull qwen2.5:3b
```

### Step 4: Launch HACHI

```bash
python hachi_gui.py
```

The GUI window will open. Click **"Start Listening"** and say:
```
"Hey, Hachi"
```

Then speak your command!

---

## 🎤 Voice Commands Example

After saying "Hey, Hachi", you can ask:

- "What is Python?"
- "Tell me a joke"
- "How do I make a GUI?"
- "Explain machine learning"
- "What's the weather like?" (varies by model)
- "Write me a poem"
- "How to learn programming?"

---

## 🔧 Troubleshooting

### Problem: "ModuleNotFoundError: No module named 'speech_recognition'"
**Solution:** Run pip install again
```bash
pip install -r requirements.txt
```

### Problem: "No module named 'pyttsx3'"
**Solution:** Install text-to-speech library
```bash
pip install pyttsx3
```

### Problem: Microphone not working
**Solution:** 
- Check Windows Sound Settings
- Make sure microphone is plugged in
- Try running as Administrator
- Test microphone in Windows Sound settings first

### Problem: "ollama.ResponseError: connection error"
**Solution:**
- Make sure Ollama is running: `ollama serve`
- Check http://localhost:11434 is accessible
- Verify Ollama installed correctly

### Problem: Google Speech Recognition fails
**Solution:**
- Check internet connection
- Wait a moment and try again
- API may have rate limits

---

## 📝 Tips for Best Results

1. **Clear Speech**: Speak clearly and at normal speed
2. **Good Microphone**: Use a quality microphone for better recognition
3. **Quiet Environment**: Minimize background noise
4. **Clear Activation**: Say "Hey, Hachi" clearly
5. **Pause After Wake Word**: Wait for the system to acknowledge before speaking command

---

## 📊 File Structure

```
c:\Users\AxeilAchia\Desktop\ai\
├── hachi_gui.py              # Main application
├── app_verification.py       # System verification
├── requirements.txt          # Python dependencies
├── setup.bat                 # Windows setup script
├── README.md                 # Full documentation
├── QUICKSTART.md            # This file
├── hachi.log                # Application logs (created on first run)
└── system_verification.log   # System logs (created on first run)
```

---

## 🎯 What's Next?

After getting Hachi running, you can:

1. **Customize the Name**: Edit `self.ai_name` in `hachi_gui.py`
2. **Change Wake Word**: Edit `self.wake_word` in `hachi_gui.py`
3. **Adjust Speech Speed**: Modify `setProperty("rate", 150)`
4. **Switch Model**: Change `self.model` to use different Ollama models
5. **Add More Features**: Extend the code with your own features!

---

## ❓ Need Help?

Check the logs:
- **hachi.log** - Latest interactions
- **system_verification.log** - System checks

Run system verification:
```bash
python app_verification.py
```

---

**Enjoy your AI assistant! 🎤🤖**
