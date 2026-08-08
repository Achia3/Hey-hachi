# Hachi Agentic Features — Implemented

Date: 2026-08-07

This is the completion map for the requested fixes and additions. The design patterns were independently adapted from the repositories in `references/`; no reference assistant was transplanted wholesale.

## Fixes

| Requested problem | Implementation | Repositories used for the design |
|---|---|---|
| "Close both of them" forgets the opened apps | Every successful `launch_app` records the resolved app. The recent list is persisted in SQLite and `close_recent_apps` resolves "both", "them", and "those apps" to the actual apps. | `row-bot` for action state/results; `ai-jarvis` for Windows process/app identity |
| Qwen/DeepSeek does not know an answer | The Qwen agent loop detects unsupported/unknown answers and calls `search_web`; DeepSeek informational paths synthesize from an automatically injected search result when they return no usable tool/answer. | `khoj` for search routing; `py-gpt` and `row-bot` for deterministic fallback |
| Gaming Mode does not use Steam Big Picture | Gaming Mode launches `steam://open/bigpicture`, verifies Steam/window state, then launches Discord and reports each result truthfully. | `ai-jarvis` for Windows/protocol launching; `row-bot` for verification |
| "Stop" is ignored while Hachi speaks | Browser playback now has a simultaneous raw microphone monitor. It sends short WAV chunks to a dedicated interrupt endpoint, checks exact stop phrases, cancels the model turn, flushes queued audio/TTS, and returns to listening. Browser SpeechRecognition remains a fallback. | `vui` for coordinated cancellation; `jarvis` for interruptible TTS and deterministic stop handling |
| Long speech is cut off | Final and interim ASR fragments are combined, speech restarts retain the same utterance, automatic pause grace is longer, filler endings keep the floor, the cap is 60 seconds, and holding the orb keeps the floor open. | `vui` for turn endpointing; `ai-jarvis` for longer VAD capture; `jarvis` for echo/barge-in separation |
| Stuck speaking state | Playback and turn cleanup release speaking state on normal completion, cancellation, disconnect, synthesis error, or model error. | `jarvis`, then `vui` |
| Multiple commands in one prompt | Qwen may emit all independent calls in a round. Hachi executes every call, appends each result, and lets Qwen call another tool in the next round before producing one final response. | `row-bot` for execution; `argo` for multi-action parsing |
| Malformed tool output | Arguments go through structural JSON repair, registered-tool checks, required-field/type validation, and a bounded correction retry. | `argo` for JSON repair; `row-bot` for schema/history rules |
| Provider/model failure | Turn-scoped action idempotency prevents already completed tools from repeating across provider fallback; errors are classified and retries are bounded. | `row-bot`; `py-gpt` |
| Search quality | Focused searches run concurrently, URLs are canonicalized/deduplicated, Wikipedia is a fallback, page fetches are bounded and cleaned, unsafe/private URLs are blocked, and full-page summarization recognizes the current untrusted-content envelope. | `khoj` for routing/deduplication; `jarvis` for fetch cleanup |
| Weak long-term memory | Durable facts use scoped hybrid semantic/lexical retrieval, confidence/source metadata, duplicate detection, and explicit supersession. Conversation logs remain separate from curated facts. | `khoj` for semantic recall; `row-bot` and `jarvis` for write hygiene |
| Desktop automation reliability | Hachi resolves Start apps/AppIDs, detects ambiguous names, verifies visible processes/windows, records each app result, and avoids claiming that an unverified launch definitely succeeded. | `ai-jarvis`; `row-bot` |

## New tools and example requests

| Tool/feature | Example request | Implementation |
|---|---|---|
| Document/PDF/DOCX summarizer | "Read lecture1.pdf on my Desktop and summarize it." | Extracts local text with `pypdf`/`python-docx`; Qwen summarizes the returned evidence. |
| Reminder/alarm | "Remind me to submit the AI assignment at 4:30 PM." / "Set an alarm for 45 minutes." | Persistent SQLite scheduler; due reminders speak aloud. |
| Assignment deadlines | "I have an assignment called AI project due Friday at 5 PM." | Saves the deadline, shows remaining time, and creates an advance spoken reminder automatically. |
| Deep memory search | "What did I tell you about my project idea?" | Searches durable semantic memories and dated conversation/task history. |
| Dictated notes | "Take a note: buy rice, milk, and eggs." | Qwen can clean the dictation, then SQLite stores it; `show my notes from today` retrieves it. |
| Personal facts | "Remember that I'm allergic to peanuts." | Stores an explicit structured durable fact and retrieves it semantically later. |
| Daily recap | "Summarize my day." | Retrieves today's conversations, actions, and notes; Qwen organizes the timeline. |
| Custom focus cycle | "Work for 50 minutes, break for 10 minutes, for 3 cycles." | Starts a configurable browser Pomodoro cycle and auto-advances work/break stages. |
| Screenshot | "Capture my screen." | Saves all displays to `Pictures/Hachi Captures`. |
| System health | "How's my laptop health?" | Returns CPU, memory, battery, and per-drive free storage for Qwen to explain. |
| Local files | "Open the file report.docx." | Restricts file lookup to the Hachi project, Desktop, Documents, and Downloads. |
| Clipboard | "What's on my clipboard?" / "Copy this text to my clipboard." | Reads or writes Windows text clipboard content. |
| To-do list | "Add review citations to my todo list." | Persists and lists local to-do items. |

## Main implementation files

- `hachi_agent.py`: model-first decisions, bounded multi-step loop, automatic unknown-answer search, fallbacks, and schemas.
- `hachi_tools.py`: app state/closing, Steam Big Picture, search, Windows automation, and productivity tool dispatch.
- `hachi_productivity.py`: reminders, assignments, notes, to-dos, document/file tools, screenshots, clipboard, focus cycles, health, and recap.
- `hachi_runtime.py`: cancellation and idempotent per-turn actions.
- `hachi_memory.py`: durable scoped hybrid memory.
- `hachi_web.py`: streaming cancellation and independent interrupt transcription endpoint.
- `hachi_speech.py`: exact stop phrases, interruptible native TTS, and long-form recognizer tuning.
- `templates/index.html`: long-form browser ASR, barge-in microphone capture, queue flushing, and custom Pomodoro UI.
- `hachi_db.py`: persistent data tables and indexes.
- `tests/test_reliability_fixes.py`: regression coverage.

## Exact reference files inspected for the added features

- Documents/PDF/DOCX: `references/row-bot/src/row_bot/documents.py`, `references/khoj/src/khoj/processor/content/pdf/pdf_to_entries.py`, `references/py-gpt/src/pygpt_net/provider/loaders/file_pdf.py`, and `references/AI-Intelligent-Assistant/services/extractors.py`.
- Reminders and scheduled workflows: `references/row-bot/bundled_skills/task_automation/SKILL.md` and `references/row-bot/tool_guides/calendar_guide/SKILL.md`.
- Dictation/clipboard: `references/jarvis/src/jarvis/dictation/dictation_engine.py` and its dictation tests/specification.
- Local files: `references/row-bot/src/row_bot/tools/filesystem_tool.py`.
- Windows state and screenshots/automation: `references/ai-jarvis/tools/windows_state.py`, `references/ai-jarvis/tools/windows_apps.py`, and Row-Bot's computer-use service/policy.
- Search, memory, malformed tools, failover, and voice references are enumerated in `REFERENCE_SOLUTIONS_AUDIT.md`.
- No focused Pomodoro implementation was found in the scanned references, so the custom cycle is a small deterministic Hachi timer rather than an adaptation from an unrelated project.

## Verification performed

- Python compilation passed for all application modules.
- Inline JavaScript syntax validation passed.
- All 27 automated regression tests passed.
- Installed the active Python 3.11 dependencies for PDF/DOCX/image support.

Hardware-dependent microphone echo, installed application names, live search providers, Qwen availability, and DeepSeek credentials still need an end-to-end run on the target laptop because automated tests cannot reproduce the room acoustics or external services.
