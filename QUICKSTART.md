# HACHI Agentic Assistant — Quick Start Guide

## ⚡ 1-Click Execution (Super Simple!)

Just double-click **`run.bat`**!

```cmd
run.bat
```

### What `run.bat` does automatically for you:
1. 🚀 Checks if Ollama is running, and starts it in the background if it's off.
2. 🖥️ Launches the Hachi Desktop Application window.
3. 🧹 **Frees your RAM on exit**: When you close the Hachi window, it automatically closes Ollama in the background so it doesn't waste your computer's memory!

---

## 🛠️ Setup (First Time Only)

On a new computer, run **`setup.bat`** once to install Python dependencies:
```cmd
setup.bat
```

---

## 🎤 Sample Commands to Try

- *"I want to play a game"* ➔ Launches Steam (Big Picture), Discord, Spotify.
- *"I need to study"* ➔ Launches VS Code, ChatGPT, Spotify.
- *"I want to focus for 25 minutes"* ➔ Opens Spotify + reveals Pomodoro timer.
- *"I don't want to play games anymore"* ➔ Closes Steam & Discord.
- *"Close Chrome"* ➔ Closes Google Chrome.
- *"What's the weather in Manila today?"* ➔ Fetches live weather forecast.
- *"What's the newest game right now?"* ➔ Performs live DuckDuckGo web search.
- *"Check my PC performance"* ➔ Reads CPU, RAM, and battery stats.
- *"What did I do last Tuesday?"* ➔ Searches SQLite memory database.

---

## ⚙️ Model Settings (`config.json`)

To change the Ollama model (e.g., `qwen2.5:3b`, `qwen2.5:7b`), edit `config.json`:

```json
{
  "model_name": "qwen2.5:3b"
}
```
