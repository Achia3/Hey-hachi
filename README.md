# 🐾 HACHI — Agentic AI Voice Assistant

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python: 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/)
[![Model: Qwen 3.5](https://img.shields.io/badge/LLM-Qwen%203.5-orange.svg)](https://ollama.com/)
[![Tests: 77 Passed](https://img.shields.io/badge/Tests-77%20Passed-brightgreen.svg)](tests/)

A fully autonomous, bilingual, voice-enabled **Agentic Desktop Assistant** built for 100% private local execution using Ollama, tool calling, hybrid vector SQLite memory, Microsoft Edge Neural TTS, simulated smart home IoT controls, and a modern desktop interface.

---

## ✨ Key Features

### 🤖 1. Agentic Decision-Making & Tool Orchestration
- **Dynamic Tool Routing**: Automatically infers user intent without rigid keywords or commands.
- **Fast-Intent Bypasses**: Instant zero-latency execution (~50ms) for high-frequency commands like volume controls, app launches, and system health checks.
- **Multi-Step Workflows**: Chains multiple tools autonomously (e.g. searching the web, extracting text, synthesizing findings, and setting a reminder).

### 🎙️ 2. Bilingual Speech & Neural Voice
- **Tagalog & English Recognition**: Seamlessly processes both English and Tagalog (`fil-PH`) speech inputs.
- **Natural Neural Synthesis**: Powered by Microsoft Edge Neural Voices (`fil-PH-AngeloNeural` and `en-US-AvaNeural`) with wake-word and acoustic sound cues.
- **Local Whisper Fallback**: Offline fallback speech-to-text using local Whisper models.

### 🧠 3. Durable Memory & Entity Supersession
- **Hashed Trigram Vector Embeddings**: Dependency-free semantic search combined with token lexical matching.
- **Entity Supersession**: Automatically updates and supersedes older conflicting facts (e.g., safe codes, passwords, preferences) while preserving memory history across chat sessions.
- **Direct Conversational Recall**: Answers memory queries naturally and directly without cluttered dumps.

### 🏠 4. Interactive Smart Home Simulation
- **Full IoT Control Dashboard**: Control smart lights (brightness/RGB colors), locks, thermostats, entertainment systems, and fans.
- **Real-Time Visualizer**: Interactive web dashboard (`/smart_home`) with mechanical animations, gold radial state indicators, and Server-Sent Events (SSE).
- **Routines & Scenes**: Automated routines (`Morning Routine`, `Good Night`, `Party Mode`, `Study Scene`).

### 📄 5. PDF & Document Intelligence
- **Document Attachment Analysis**: Attach PDF documents directly into the chat interface for instant summarization, key point extraction, and grounded Q&A.
- **Local File & Folder Navigation**: Open folders, documents, and files directly on Windows desktop.

### 🌐 6. Web Research & Headless Browser Automation
- **Multi-Source Synthesis**: Performs multi-query web searches via DuckDuckGo (or Brave/Tavily) and synthesizes source-grounded answers with citations `[1]`.
- **Playwright Headless Browser**: Navigates, clicks, and extracts content from live web pages.

### 🎯 7. Preset Environment Modes
- 🎮 **Gaming Mode**: Launches Steam, Discord, sets ambient RGB lights, and opens Spotify.
- 📚 **Study Mode**: Launches VS Code, Notion/ChatGPT, sets study lighting, and starts ambient music.
- 🎬 **Movie Mode**: Launches media player/Netflix and dims the room lights.
- ⏱️ **Focus Mode**: Starts an integrated Pomodoro timer with Spotify focus audio.

---

## 🛠️ System Architecture

```
Hey-hachi/
├── hachi_app.py                # Desktop GUI Application (PyWebView)
├── hachi_agent.py              # Agentic Decision Engine & Tool Dispatcher
├── hachi_tools.py              # Comprehensive Tool Registry & Schemas
├── hachi_memory.py             # Durable Hybrid Vector Memory & Supersession
├── hachi_db.py                 # SQLite Database Manager (Chats, Tasks, Memory)
├── hachi_home.py               # Smart Home State Manager & Automation Logic
├── hachi_home_agent.py         # Smart Home Natural Language Agent
├── hachi_productivity.py       # Notes, Todos, Reminders, File & Clipboard Tools
├── hachi_speech.py             # Microphone Capture & Edge Neural TTS
├── hachi_whisper.py            # Local Whisper Speech-to-Text Fallback
├── hachi_dictation.py          # Continuous Voice Dictation Engine
├── hachi_browser.py            # Playwright Headless Browser Automation
├── hachi_web.py                # Flask Backend API & SSE Event Stream
├── hachi_voice_dictionary.py   # Phonetic Voice Matcher for Tagalog / Slang
├── config.json                 # Core Configuration (Model, Voices, Settings)
├── hachi_routines.json         # Smart Home Routine Presets
├── requirements.txt            # Python Dependencies
├── setup.bat                   # 1-Click Environment Setup Script
├── run.bat                     # 1-Click Application Launcher
├── stop.bat                    # Clean Process & Ollama Cleanup Script
├── templates/
│   ├── index.html              # Main Desktop Assistant Chat & Voice UI
│   └── smart_home.html         # Smart Home Simulation Dashboard
├── static/                     # Web Fonts, UI Icons, Audio Chimes, Marked.js
└── tests/                      # Automated Pytest Suite (77 Unit & Integration Tests)
```

---

## 🚀 Getting Started

### Prerequisites
- **Operating System**: Windows 10 or Windows 11
- **Python**: Version 3.10, 3.11, or 3.12
- **Ollama**: Installed from [ollama.com](https://ollama.com/) with `qwen2.5:3b` or `qwen3.5:2b`

### 1. One-Click Setup
Run `setup.bat` to automatically create a virtual environment and install all dependencies:
```cmd
setup.bat
```

### 2. Launching Hachi
Double-click `run.bat` to launch the assistant:
```cmd
run.bat
```
*(This script automatically launches the Ollama server in the background, starts the Flask API, opens the PyWebView desktop app, and terminates background services upon closing to save RAM).*

### 3. Stopping Hachi
To stop all background processes and free system memory:
```cmd
stop.bat
```

---

## ⚙️ Configuration (`config.json`)

Customize model selection, speech voices, and search providers in `config.json`:

```json
{
  "model_name": "qwen2.5:3b",
  "use_deepseek": false,
  "deepseek_model": "deepseek-chat",
  "tagalog_voice": "fil-PH-AngeloNeural",
  "english_voice": "en-US-AvaNeural",
  "web_search_provider": "duckduckgo",
  "sound_feedback": true,
  "wake_word_enabled": true
}
```

---

## 🧪 Testing & Verification

Hachi includes a comprehensive automated test suite covering tool schemas, database migrations, smart home actions, memory retrieval, and agent routing:

```cmd
python -m pytest
```

```
============================= 77 passed in 2.37s =============================
```

---

## 📄 License

This project is licensed under the **MIT License** — see the [LICENSE](LICENSE) file for details.
