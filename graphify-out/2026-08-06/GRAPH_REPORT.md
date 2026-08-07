# Graph Report - .  (2026-08-06)

## Corpus Check
- Corpus is ~17,092 words - fits in a single context window. You may not need a graph.

## Summary
- 221 nodes · 362 edges · 12 communities (10 shown, 2 thin omitted)
- Extraction: 93% EXTRACTED · 7% INFERRED · 0% AMBIGUOUS · INFERRED: 26 edges (avg confidence: 0.84)
- Token cost: 87,352 input · 0 output

## Community Hubs (Navigation)
- Speech & Web API
- Frontend UI & Voice JS
- Legacy GUI
- Tools & System Actions
- Agent & Intent Processing
- App Lifecycle & DB
- Documentation & Concepts
- Dependency Stack
- Audio Diagnostics
- Pomodoro Internals
- App Verification
- Pomodoro Toggle

## God Nodes (most connected - your core abstractions)
1. `HachiAI` - 17 edges
2. `execute_tool_call()` - 16 edges
3. `process_agent_request()` - 14 edges
4. `add_task()` - 13 edges
5. `HACHI Agentic AI Voice Assistant` - 13 edges
6. `streamAndSpeakResponse` - 12 edges
7. `Hachi AI Dependency Manifest` - 11 edges
8. `process_agent_request_stream()` - 9 edges
9. `speak()` - 9 edges
10. `addMessage` - 9 edges

## Surprising Connections (you probably didn't know these)
- `Edge TTS Audio` --semantically_similar_to--> `edge-tts (Text-to-Speech)`  [INFERRED] [semantically similar]
  templates/index.html → requirements.txt
- `listenOneTurn` --semantically_similar_to--> `SpeechRecognition (STT)`  [INFERRED] [semantically similar]
  templates/index.html → requirements.txt
- `check_fast_intent()` --calls--> `execute_tool_call()`  [EXTRACTED]
  hachi_agent.py → hachi_tools.py
- `process_agent_request()` --calls--> `execute_tool_call()`  [EXTRACTED]
  hachi_agent.py → hachi_tools.py
- `api_chat()` --calls--> `process_agent_request()`  [EXTRACTED]
  hachi_web.py → hachi_agent.py

## Import Cycles
- None detected.

## Hyperedges (group relationships)
- **Local-First Execution Stack** — hey_hachi_readme_ollama, hey_hachi_readme_qwen, hey_hachi_readme_sqlite_memory, hey_hachi_readme_pywebview, hey_hachi_readme_flask, hey_hachi_readme_local_first [INFERRED 0.95]
- **Voice Conversation System** — templates_index_openvoice, templates_index_closevoice, templates_index_startvoiceconversation, templates_index_listenoneturn, templates_index_streamandspeakresponse, templates_index_playaudio, templates_index_voice_mode, templates_index_barge_in [EXTRACTED 1.00]
- **Pomodoro Timer System** — templates_index_startpomodoro, templates_index_pomotick, templates_index_pomosessionend, templates_index_shownotonification, templates_index_pomonextaction, templates_index_togglepomodoro, templates_index_stoppomodoro, templates_index_applypomosignals, templates_index_pomodoro_timer [EXTRACTED 1.00]
- **Hachi AI Tech Stack** — hey_hachi_requirements_manifest, hey_hachi_requirements_edge_tts, hey_hachi_requirements_pywebview, hey_hachi_requirements_flask, hey_hachi_requirements_speechrecognition, hey_hachi_requirements_pyaudio, hey_hachi_requirements_ollama, hey_hachi_requirements_psutil, hey_hachi_requirements_requests, hey_hachi_requirements_beautifulsoup, hey_hachi_requirements_ddgs, hey_hachi_requirements_dotenv [EXTRACTED 1.00]

## Communities (12 total, 2 thin omitted)

### Community 0 - "Speech & Web API"
Cohesion: 0.07
Nodes (42): clean_speech_text(), _generate_edge_tts_file(), generate_tts_audio(), interrupt_speech(), listen_for_wakeword(), listen_voice_input(), _pick_voice(), _play_mp3_interruptible() (+34 more)

### Community 1 - "Frontend UI & Voice JS"
Cohesion: 0.10
Nodes (37): SpeechRecognition (STT), addMessage, /api/chat, /api/interrupt_speech, /api/stream_chat, /api/tts_audio, /api/voice_mode, /api/voice_stream (+29 more)

### Community 2 - "Legacy GUI"
Cohesion: 0.11
Nodes (16): check_ollama_connection(), HachiAI, main(), Find the best available microphone, Display a message in the conversation log, Check if Ollama is running and accessible, Clear the conversation log, Listen for audio input and convert to text (+8 more)

### Community 3 - "Tools & System Actions"
Cohesion: 0.13
Nodes (26): add_task(), Log a task or system action executed by Hachi., close_app(), close_mode(), execute_tool_call(), fetch_url(), find_app_in_start_menu(), get_app_path() (+18 more)

### Community 4 - "Agent & Intent Processing"
Cohesion: 0.14
Nodes (22): call_deepseek_chat(), check_fast_intent(), classify_intent(), clean_thinking(), detect_intent_tool_call(), get_current_time_context(), parse_dsml_tool_calls(), process_agent_request() (+14 more)

### Community 5 - "App Lifecycle & DB"
Cohesion: 0.20
Nodes (13): main(), Poll until Flask is accepting connections. Much more reliable than a fixed…, Run Flask server in background thread. Errors are logged but won't crash the…, Main application entry point, run_flask(), _wait_for_flask(), get_connection(), init_db() (+5 more)

### Community 6 - "Documentation & Concepts"
Cohesion: 0.19
Nodes (15): config.json Model Configuration, run.bat Launcher Script, setup.bat Installer Script, Agentic Function Calling Architecture, Context-Driven Operation Modes, Microsoft Edge Neural TTS, Flask REST API Backend, HACHI Agentic AI Voice Assistant (+7 more)

### Community 7 - "Dependency Stack"
Cohesion: 0.17
Nodes (12): BeautifulSoup4 (HTML Parsing), ddgs (DuckDuckGo Search), python-dotenv (Config), edge-tts (Text-to-Speech), Flask (Web Backend), Hachi AI Dependency Manifest, Ollama (LLM Client), psutil (System Stats) (+4 more)

### Community 8 - "Audio Diagnostics"
Cohesion: 0.31
Nodes (8): list_audio_devices(), main(), HACHI Audio Diagnostic Tool Helps troubleshoot microphone and speech…, List all available audio devices, Test microphone input, Test text-to-speech engines, test_microphone(), test_speech_engines()

### Community 9 - "Pomodoro Internals"
Cohesion: 0.50
Nodes (4): pomoNextAction, pomoSessionEnd, pomoTick, showPomoNotification

## Knowledge Gaps
- **23 isolated node(s):** `setup.bat Installer Script`, `PyWebView Desktop Framework`, `Flask REST API Backend`, `Tagalog and English Bilingual Voice Support`, `pywebview (Desktop Shell)` (+18 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **2 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `execute_tool_call()` connect `Tools & System Actions` to `Agent & Intent Processing`, `App Lifecycle & DB`?**
  _High betweenness centrality (0.039) - this node is a cross-community bridge._
- **Why does `process_agent_request()` connect `Agent & Intent Processing` to `Speech & Web API`, `Tools & System Actions`?**
  _High betweenness centrality (0.036) - this node is a cross-community bridge._
- **Why does `fetch_url()` connect `Tools & System Actions` to `Speech & Web API`?**
  _High betweenness centrality (0.028) - this node is a cross-community bridge._
- **Are the 11 inferred relationships involving `HACHI Agentic AI Voice Assistant` (e.g. with `Agentic Function Calling Architecture` and `Context-Driven Operation Modes`) actually correct?**
  _`HACHI Agentic AI Voice Assistant` has 11 INFERRED edges - model-reasoned connections that need verification._
- **What connects `setup.bat Installer Script`, `PyWebView Desktop Framework`, `Flask REST API Backend` to the rest of the system?**
  _23 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `Speech & Web API` be split into smaller, more focused modules?**
  _Cohesion score 0.07188160676532769 - nodes in this community are weakly interconnected._
- **Should `Frontend UI & Voice JS` be split into smaller, more focused modules?**
  _Cohesion score 0.1021021021021021 - nodes in this community are weakly interconnected._