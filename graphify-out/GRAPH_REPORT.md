# Graph Report - C:/Users/Beo/Downloads/02_Programming/01_Python/02_Project/AI-LAB-WORKS/Hey-hachi  (2026-08-06)

## Corpus Check
- 19 files · ~83,575 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 278 nodes · 447 edges · 12 communities (9 shown, 3 thin omitted)
- Extraction: 95% EXTRACTED · 4% INFERRED · 0% AMBIGUOUS · INFERRED: 20 edges (avg confidence: 0.77)
- Token cost: 83,020 input · 0 output

## Community Hubs (Navigation)
- Agent Core & Intent Detection
- Documentation & Architecture
- Tool System & App Launching
- Web Server & API Endpoints
- Legacy GUI Application
- Speech & TTS Engine
- Application Bootstrap & Wake Word
- Project Dependencies
- Audio Diagnostics
- System Verification
- Ollama Backend Setup
- Mic Status Polling

## God Nodes (most connected - your core abstractions)
1. `process_agent_request()` - 22 edges
2. `process_agent_request_stream()` - 19 edges
3. `HachiAI` - 17 edges
4. `execute_tool_call()` - 16 edges
5. `add_task()` - 14 edges
6. `Hachi AI Dependency Manifest` - 11 edges
7. `search_history()` - 9 edges
8. `speak()` - 9 edges
9. `add_message()` - 8 edges
10. `launch_app()` - 8 edges

## Surprising Connections (you probably didn't know these)
- `detectUserIntent() — Client-Side Intent Detection` --semantically_similar_to--> `Agentic Function Calling`  [INFERRED] [semantically similar]
  templates/index.html → README.md
- `sanitizeHtml() — XSS Sanitizer` --semantically_similar_to--> `Agentic Function Calling`  [INFERRED] [semantically similar]
  templates/index.html → README.md
- `Graphify Knowledge Graph Viewer` --references--> `Hachi — Agentic AI Voice Assistant`  [INFERRED]
  .planning/graphs/graph.html → README.md
- `check_fast_intent()` --calls--> `execute_tool_call()`  [EXTRACTED]
  hachi_agent.py → hachi_tools.py
- `process_agent_request()` --calls--> `execute_tool_call()`  [EXTRACTED]
  hachi_agent.py → hachi_tools.py

## Import Cycles
- None detected.

## Hyperedges (group relationships)
- **Hachi AI Tech Stack** — hey_hachi_requirements_manifest, hey_hachi_requirements_edge_tts, hey_hachi_requirements_pywebview, hey_hachi_requirements_flask, hey_hachi_requirements_speechrecognition, hey_hachi_requirements_pyaudio, hey_hachi_requirements_ollama, hey_hachi_requirements_psutil, hey_hachi_requirements_requests, hey_hachi_requirements_beautifulsoup, hey_hachi_requirements_ddgs, hey_hachi_requirements_dotenv [EXTRACTED 1.00]
- **Context-Driven Modes System** — readme_gamingmode, readme_studymode, readme_moviemode, readme_focusmode, templates_index_modechipsui, readme_hachitools_py [INFERRED 0.85]
- **Voice Conversation Pipeline (Listen → Process → Speak)** — templates_index_startvoiceconversation, templates_index_listenoneturn, templates_index_streamandspeakresponse, templates_index_playaudio, templates_index_voiceoverlayui, readme_tagalogenglishvoice, readme_hachispeech_py [EXTRACTED 1.00]
- **Pomodoro Timer Subsystem** — templates_index_startpomodoro, templates_index_stoppomodoro, templates_index_togglepomodoro, templates_index_pomonextaction, templates_index_applypompsignals, templates_index_pomodorotimerwidget, readme_focusmode [EXTRACTED 1.00]

## Communities (12 total, 3 thin omitted)

### Community 0 - "Agent Core & Intent Detection"
Cohesion: 0.06
Nodes (62): Exception, _answer_budget(), call_deepseek_chat(), check_fast_intent(), classify_intent(), clean_thinking(), detect_intent_tool_call(), _detect_pomo() (+54 more)

### Community 1 - "Documentation & Architecture"
Cohesion: 0.06
Nodes (47): Graphify Knowledge Graph Viewer, Hachi Agentic Assistant — Quick Start Guide, setup.bat — First-Time Setup Script, Agentic Function Calling, config.json — Model and Voice Settings, Qwen-First Dual-Mode Engine Routing, Focus Mode with Pomodoro Timer, Gaming Mode (+39 more)

### Community 2 - "Tool System & App Launching"
Cohesion: 0.08
Nodes (41): add_task(), Log a task or system action executed by Hachi., close_app(), close_mode(), execute_tool_call(), fetch_url(), find_app_in_start_menu(), _geocode() (+33 more)

### Community 3 - "Web Server & API Endpoints"
Cohesion: 0.09
Nodes (33): api_chat(), api_fetch_url(), api_interrupt_speech(), api_mic_status(), api_stream_chat(), api_tts_audio(), api_voice_mode(), api_voice_stream() (+25 more)

### Community 4 - "Legacy GUI Application"
Cohesion: 0.11
Nodes (16): check_ollama_connection(), HachiAI, main(), Find the best available microphone, Display a message in the conversation log, Check if Ollama is running and accessible, Clear the conversation log, Listen for audio input and convert to text (+8 more)

### Community 5 - "Speech & TTS Engine"
Cohesion: 0.16
Nodes (18): clean_speech_text(), _generate_edge_tts_file(), generate_tts_audio(), interrupt_speech(), listen_voice_input(), _pick_voice(), _play_mp3_interruptible(), Generate Edge TTS audio for text and return the temp file path. Returns None if… (+10 more)

### Community 6 - "Application Bootstrap & Wake Word"
Cohesion: 0.19
Nodes (13): main(), Poll until Flask is accepting connections. Much more reliable than a fixed…, Run Flask server in background thread. Errors are logged but won't crash the…, Main application entry point, run_flask(), _wait_for_flask(), init_db(), Initialize database tables and indexes if they do not exist. Called ONCE at… (+5 more)

### Community 7 - "Project Dependencies"
Cohesion: 0.17
Nodes (12): BeautifulSoup4 (HTML Parsing), ddgs (DuckDuckGo Search), python-dotenv (Config), edge-tts (Text-to-Speech), Flask (Web Backend), Hachi AI Dependency Manifest, Ollama (LLM Client), psutil (System Stats) (+4 more)

### Community 8 - "Audio Diagnostics"
Cohesion: 0.31
Nodes (8): list_audio_devices(), main(), HACHI Audio Diagnostic Tool Helps troubleshoot microphone and speech…, List all available audio devices, Test microphone input, Test text-to-speech engines, test_microphone(), test_speech_engines()

## Ambiguous Edges - Review These
- `togglePomodoro() — Pause/Resume Timer` → `applyPomoSignals() — Pomodoro Signal Handler`  [AMBIGUOUS]
  templates/index.html · relation: calls

## Knowledge Gaps
- **29 isolated node(s):** `edge-tts (Text-to-Speech)`, `pywebview (Desktop Shell)`, `Flask (Web Backend)`, `SpeechRecognition (STT)`, `PyAudio (Microphone Audio)` (+24 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **3 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **What is the exact relationship between `togglePomodoro() — Pause/Resume Timer` and `applyPomoSignals() — Pomodoro Signal Handler`?**
  _Edge tagged AMBIGUOUS (relation: calls) - confidence is low._
- **Why does `process_agent_request()` connect `Agent Core & Intent Detection` to `Tool System & App Launching`, `Web Server & API Endpoints`?**
  _High betweenness centrality (0.046) - this node is a cross-community bridge._
- **Why does `execute_tool_call()` connect `Tool System & App Launching` to `Agent Core & Intent Detection`?**
  _High betweenness centrality (0.039) - this node is a cross-community bridge._
- **Why does `process_agent_request_stream()` connect `Agent Core & Intent Detection` to `Tool System & App Launching`, `Web Server & API Endpoints`?**
  _High betweenness centrality (0.036) - this node is a cross-community bridge._
- **What connects `edge-tts (Text-to-Speech)`, `pywebview (Desktop Shell)`, `Flask (Web Backend)` to the rest of the system?**
  _29 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `Agent Core & Intent Detection` be split into smaller, more focused modules?**
  _Cohesion score 0.05555555555555555 - nodes in this community are weakly interconnected._
- **Should `Documentation & Architecture` be split into smaller, more focused modules?**
  _Cohesion score 0.060129509713228495 - nodes in this community are weakly interconnected._