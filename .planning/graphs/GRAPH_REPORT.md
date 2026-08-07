# Graph Report - Hey-hachi  (2026-08-06)

## Corpus Check
- 13 files · ~24,021 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 285 nodes · 475 edges · 13 communities (11 shown, 2 thin omitted)
- Extraction: 94% EXTRACTED · 6% INFERRED · 0% AMBIGUOUS · INFERRED: 29 edges (avg confidence: 0.79)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `f37bd330`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- hachi_web.py
- streamAndSpeakResponse
- HachiAI
- hachi_tools.py
- hachi_agent.py
- hachi_app.py
- HACHI Agentic AI Voice Assistant
- Hachi AI Dependency Manifest
- audio_diagnostic.py
- pomoTick
- run_system_verification
- togglePomodoro
- hachi_speech.py

## God Nodes (most connected - your core abstractions)
1. `process_agent_request()` - 22 edges
2. `process_agent_request_stream()` - 19 edges
3. `HachiAI` - 17 edges
4. `execute_tool_call()` - 16 edges
5. `add_task()` - 14 edges
6. `HACHI Agentic AI Voice Assistant` - 13 edges
7. `streamAndSpeakResponse` - 12 edges
8. `Hachi AI Dependency Manifest` - 11 edges
9. `search_history()` - 9 edges
10. `speak()` - 9 edges

## Surprising Connections (you probably didn't know these)
- `Edge TTS Audio` --semantically_similar_to--> `edge-tts (Text-to-Speech)`  [INFERRED] [semantically similar]
  templates/index.html → requirements.txt
- `listenOneTurn` --semantically_similar_to--> `SpeechRecognition (STT)`  [INFERRED] [semantically similar]
  templates/index.html → requirements.txt
- `process_agent_request()` --calls--> `add_message()`  [EXTRACTED]
  hachi_agent.py → hachi_db.py
- `api_chat()` --calls--> `process_agent_request()`  [EXTRACTED]
  hachi_web.py → hachi_agent.py
- `process_agent_request_stream()` --calls--> `add_message()`  [EXTRACTED]
  hachi_agent.py → hachi_db.py

## Import Cycles
- None detected.

## Hyperedges (group relationships)
- **Local-First Execution Stack** — hey_hachi_readme_ollama, hey_hachi_readme_qwen, hey_hachi_readme_sqlite_memory, hey_hachi_readme_pywebview, hey_hachi_readme_flask, hey_hachi_readme_local_first [INFERRED 0.95]
- **Voice Conversation System** — templates_index_openvoice, templates_index_closevoice, templates_index_startvoiceconversation, templates_index_listenoneturn, templates_index_streamandspeakresponse, templates_index_playaudio, templates_index_voice_mode, templates_index_barge_in [EXTRACTED 1.00]
- **Pomodoro Timer System** — templates_index_startpomodoro, templates_index_pomotick, templates_index_pomosessionend, templates_index_shownotonification, templates_index_pomonextaction, templates_index_togglepomodoro, templates_index_stoppomodoro, templates_index_applypomosignals, templates_index_pomodoro_timer [EXTRACTED 1.00]
- **Hachi AI Tech Stack** — hey_hachi_requirements_manifest, hey_hachi_requirements_edge_tts, hey_hachi_requirements_pywebview, hey_hachi_requirements_flask, hey_hachi_requirements_speechrecognition, hey_hachi_requirements_pyaudio, hey_hachi_requirements_ollama, hey_hachi_requirements_psutil, hey_hachi_requirements_requests, hey_hachi_requirements_beautifulsoup, hey_hachi_requirements_ddgs, hey_hachi_requirements_dotenv [EXTRACTED 1.00]

## Communities (13 total, 2 thin omitted)

### Community 0 - "hachi_web.py"
Cohesion: 0.08
Nodes (35): fetch_url(), Fetch and extract readable text content from a specific URL. Returns the main…, api_chat(), api_fetch_url(), api_interrupt_speech(), api_mic_status(), api_stream_chat(), api_tts_audio() (+27 more)

### Community 1 - "streamAndSpeakResponse"
Cohesion: 0.10
Nodes (37): SpeechRecognition (STT), addMessage, /api/chat, /api/interrupt_speech, /api/stream_chat, /api/tts_audio, /api/voice_mode, /api/voice_stream (+29 more)

### Community 2 - "HachiAI"
Cohesion: 0.11
Nodes (16): check_ollama_connection(), HachiAI, main(), Find the best available microphone, Display a message in the conversation log, Check if Ollama is running and accessible, Clear the conversation log, Listen for audio input and convert to text (+8 more)

### Community 3 - "hachi_tools.py"
Cohesion: 0.05
Nodes (55): _load_db_memory(), Preload recent conversations from SQLite into session memory so the model can…, add_message(), add_task(), get_connection(), get_recent_messages(), _get_write_conn(), _like_escape() (+47 more)

### Community 4 - "hachi_agent.py"
Cohesion: 0.08
Nodes (46): Exception, _answer_budget(), call_deepseek_chat(), check_fast_intent(), classify_intent(), clean_thinking(), detect_intent_tool_call(), _detect_pomo() (+38 more)

### Community 5 - "hachi_app.py"
Cohesion: 0.19
Nodes (13): main(), Poll until Flask is accepting connections. Much more reliable than a fixed…, Run Flask server in background thread. Errors are logged but won't crash the…, Main application entry point, run_flask(), _wait_for_flask(), init_db(), Initialize database tables and indexes if they do not exist. Called ONCE at… (+5 more)

### Community 6 - "HACHI Agentic AI Voice Assistant"
Cohesion: 0.19
Nodes (15): config.json Model Configuration, run.bat Launcher Script, setup.bat Installer Script, Agentic Function Calling Architecture, Context-Driven Operation Modes, Microsoft Edge Neural TTS, Flask REST API Backend, HACHI Agentic AI Voice Assistant (+7 more)

### Community 7 - "Hachi AI Dependency Manifest"
Cohesion: 0.17
Nodes (12): BeautifulSoup4 (HTML Parsing), ddgs (DuckDuckGo Search), python-dotenv (Config), edge-tts (Text-to-Speech), Flask (Web Backend), Hachi AI Dependency Manifest, Ollama (LLM Client), psutil (System Stats) (+4 more)

### Community 8 - "audio_diagnostic.py"
Cohesion: 0.31
Nodes (8): list_audio_devices(), main(), HACHI Audio Diagnostic Tool Helps troubleshoot microphone and speech…, List all available audio devices, Test microphone input, Test text-to-speech engines, test_microphone(), test_speech_engines()

### Community 9 - "pomoTick"
Cohesion: 0.50
Nodes (4): pomoNextAction, pomoSessionEnd, pomoTick, showPomoNotification

### Community 12 - "hachi_speech.py"
Cohesion: 0.16
Nodes (18): clean_speech_text(), _generate_edge_tts_file(), generate_tts_audio(), interrupt_speech(), listen_voice_input(), _pick_voice(), _play_mp3_interruptible(), Generate Edge TTS audio for text and return the temp file path. Returns None if… (+10 more)

## Knowledge Gaps
- **23 isolated node(s):** `setup.bat Installer Script`, `PyWebView Desktop Framework`, `Flask REST API Backend`, `Tagalog and English Bilingual Voice Support`, `pywebview (Desktop Shell)` (+18 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **2 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `process_agent_request()` connect `hachi_agent.py` to `hachi_web.py`, `hachi_tools.py`?**
  _High betweenness centrality (0.044) - this node is a cross-community bridge._
- **Why does `execute_tool_call()` connect `hachi_agent.py` to `hachi_web.py`, `hachi_tools.py`?**
  _High betweenness centrality (0.038) - this node is a cross-community bridge._
- **Why does `process_agent_request_stream()` connect `hachi_agent.py` to `hachi_web.py`, `hachi_tools.py`?**
  _High betweenness centrality (0.035) - this node is a cross-community bridge._
- **What connects `setup.bat Installer Script`, `PyWebView Desktop Framework`, `Flask REST API Backend` to the rest of the system?**
  _23 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `hachi_web.py` be split into smaller, more focused modules?**
  _Cohesion score 0.08095238095238096 - nodes in this community are weakly interconnected._
- **Should `streamAndSpeakResponse` be split into smaller, more focused modules?**
  _Cohesion score 0.1021021021021021 - nodes in this community are weakly interconnected._
- **Should `HachiAI` be split into smaller, more focused modules?**
  _Cohesion score 0.1053763440860215 - nodes in this community are weakly interconnected._