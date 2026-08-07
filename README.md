# HACHI - Agentic AI Voice Assistant

A fully autonomous, voice-enabled **Agentic AI Desktop Assistant** built for local execution using Ollama, tool calling, local SQLite memory, Microsoft Edge Neural TTS, and PyWebView desktop interface.

---

## ✨ Features

- 🤖 **Agentic Function Calling**: Automatically understands intent and triggers system tools (no hardcoded keywords required).
- 🇵🇭 **Tagalog & English Voice Support**: Native Tagalog (`fil-PH`) and English speech recognition with Microsoft Edge Neural Voices (`fil-PH-AngeloNeural` / `en-US-AvaNeural`).
- 🗄️ **Local SQLite Database Memory**: Tracks past conversations, executed tasks, and dates so Hachi can recall historical activity (*"What did I do last Tuesday?"*).
- 🎯 **Context-Driven Modes**:
  - 🎮 **Gaming Mode**: Steam (Big Picture), Discord, Spotify.
  - 📚 **Study Mode**: VS Code, ChatGPT (Desktop app or Web tab), Spotify.
  - 🎬 **Movie Mode**: YouTube & Netflix browser tabs.
  - ⏱️ **Focus Mode**: Spotify + integrated Focus Pomodoro Timer.
- 🚪 **Universal App Control**: Close ANY running application on Windows (*"Close Chrome"*, *"Close Notepad"*).
- 🌐 **Live Web Scraping & Weather**: Scrapes live weather forecasts and performs instant DuckDuckGo web searches.
- 📊 **PC System Diagnostics**: Live CPU usage, RAM memory consumption, and battery status.
- 🖥️ **Native Desktop Interface**: Sleek PyWebView application window with real-time progress bar.

---

## 🛠️ Requirements

- **Python 3.8+**
- **Ollama** running locally (`http://localhost:11434`)
- **Qwen Model** (configured with `qwen2.5:3b` in `config.json`)
- **Microphone & Speaker**
- **Windows OS**

---

## 🚀 Quick Execution

### 1-Click Launch (Recommended)
Simply double-click:
```cmd
run.bat
```
*(Automatically starts Ollama in the background, launches Hachi, and **kills Ollama on window exit to free up RAM**!)*

### First Time Setup
On a new PC, run `setup.bat` once to install Python packages:
```cmd
setup.bat
```

---

## ⚙️ Customization (`config.json`)

Edit `config.json` to change the Ollama model or TTS voices dynamically:

```json
{
  "model_name": "qwen2.5:3b",
  "use_deepseek": true,
  "deepseek_model": "deepseek-chat",
  "tagalog_voice": "fil-PH-AngeloNeural",
  "english_voice": "en-US-AvaNeural"
}
```

### 🧠 Dual-Mode Engine Routing

Hachi uses a **Qwen-first dual mode**: the local LLM (Qwen via Ollama) is the primary brain and handles every request. DeepSeek (cloud) escalates only when Qwen can't handle it.

| Intent | Qwen (local) | DeepSeek (cloud) |
|--------|--------------|------------------|
| Greetings / simple chat | ✅ primary | — |
| Tool commands (open/close apps, modes, system stats, weather) | ✅ primary with tools | escalate only if Qwen produces no tool call |
| Knowledge tools (web search, URL fetch) | ✅ tried first | escalate for tool call + final synthesis |
| Complex reasoning (explain/compare/code) | quick local-action pass | ✅ primary for the reasoning answer |

The chat bubble shows which engine answered: **"Qwen · local"** or **"DeepSeek · cloud"**. Set `"use_deepseek": false` (or remove the API key from `.env`) to run Qwen-only, fully offline. Set `DEEPSEEK_API_KEY` in `.env` (never in `config.json`) to enable the cloud escalator.

---

## 📊 File Architecture

```
Hey-hachi/
├── hachi_app.py        # Desktop App Launcher (PyWebView)
├── hachi_agent.py      # Ollama Function Calling Core
├── hachi_tools.py      # System Tools (Modes, App Control, Weather, Web Search)
├── hachi_speech.py     # Speech Recognition & Edge Neural TTS
├── hachi_db.py         # SQLite Local Memory Database Manager
├── hachi_web.py        # Flask REST API Backend
├── hachi_memory.db     # SQLite Database File
├── config.json         # Model & Voice Settings
├── setup.bat           # Portable Setup Script
├── requirements.txt    # Python Dependencies
├── templates/
│   └── index.html      # Desktop App UI & Pomodoro Widget
└── old_version/        # Archived Prototype Files
```

---

## 📄 License & Credits

Developed for AI Lab Works. Powered by **Ollama**, **Qwen 3.5**, and **Microsoft Edge TTS**.
