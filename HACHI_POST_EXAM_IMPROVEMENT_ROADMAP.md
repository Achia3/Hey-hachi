# Hachi Post-Exam Improvement Roadmap

## Purpose

This roadmap collects the broader Hachi improvements discussed previously. It begins only after the smart-home exam build is stable and submission-ready.

The goal is not to make Hachi a basic tool-calling assistant. The goal is a capable, local-first agent for students and office workers that can plan, act, verify, recover, research, remember, and resume work without sacrificing user control.

## Current foundation to preserve

Version `v0.1.10.1` already contains useful foundations:

- A local Qwen/Ollama path.
- A bounded multi-step model-to-tool loop.
- Deterministic filtering of the large tool catalog for Qwen requests.
- Request cancellation and duplicate-action protection.
- Concurrent web search and source fetching.
- Trafilatura with BeautifulSoup fallback.
- Playwright-based browser navigation and page reading.
- Per-conversation database IDs and isolated chat history.
- Explicit durable memory with duplicate and supersession handling.
- LocalAppData database-path support.
- Tool capability and safety metadata.
- A growing automated test collection.

These pieces should be strengthened rather than replaced wholesale.

## Immediate stabilization after the exam

### 1. Browser navigation and exit

Problem: Hachi can enter its controlled browser workflow but has no exposed back, forward, home, or close operation.

Add:

- `back`
- `forward`
- `home`
- `refresh`
- `close`

These should be available both as visible UI controls and validated high-level browser actions. Closing must call the existing internal browser shutdown function and release Playwright resources cleanly.

### 2. Remove cloud dependence

Short-term:

- Set `use_deepseek` to false.
- Remove the local DeepSeek API key.
- Route voice and text through Qwen.
- Make offline TTS the default rather than the fallback.

After regression testing:

- Remove unused DeepSeek request branches.
- Remove cloud-specific status labels and configuration.
- Keep a provider interface so another user-selected model can be added later without hardwiring it into the agent.

### 3. Reproducible Python environment

- Use one supported Python version and virtual environment.
- Pin tested dependency ranges.
- Add setup verification for Ollama, model availability, microphone, browser runtime, and TTS.
- Run the full automated test suite in CI and on the target Windows laptop.
- Keep generated databases, browser profiles, logs, bytecode, and Graphify output out of Git.

### 4. Recover and migrate memory safely

The old tracked database must be restored from Git if its conversations are still needed, then copied into `%LOCALAPPDATA%\Hachi\` before normal startup. Migration needs a backup, row-count verification, and restart test.

## Model strategy

### Primary model

Test `qwen3.5:2b` as the primary local model with a deliberately small context window, and retain 4B as a quality comparison. Measure:

- Tool-call accuracy.
- Structured JSON validity.
- First-token latency.
- Complete response latency.
- RAM and VRAM usage.
- Voice-turn responsiveness.

Keep a smaller Qwen fallback for low-memory machines and simple voice commands.

### What will and will not be trained

Train small task-specific policies where they provide measurable value:

- Tool-family routing.
- Smart-home intent classification.
- Search-result relevance ranking.
- Clarification prediction.
- Risk/permission classification.

Do not continuously train Qwen on raw user conversations. User memory belongs in a reviewed local memory and retrieval system, not in unsafe automatic weight updates.

Qwen LoRA fine-tuning remains optional research after the application has strong datasets and evaluation. It is not a prerequisite for a useful agent.

## Shared agent runtime

The long-term runtime should follow:

```text
User goal
   -> learned/deterministic router
   -> structured planner
   -> permission-aware executor
   -> result verifier
   -> retry or replan
   -> grounded response
   -> selected memory update
```

### Tool router

Improve the current keyword router into a hybrid system:

1. Deterministic safety and explicit-command rules.
2. A locally trained tool-family classifier.
3. Qwen selection from only the top relevant families.
4. Confidence-based fallback to a wider but still bounded catalog.

The model should normally see four to eight tools rather than all available tools.

### Structured planner

For multi-step goals, represent each step with:

- Step ID.
- Description.
- Required capability.
- Dependencies.
- Read/write safety level.
- Success condition.
- Status: pending, running, completed, failed, skipped.
- Retry count and error category.

Simple one-step commands should bypass planning overhead.

### Standard tool-result envelope

Wrap existing tool outputs as:

```json
{
  "success": true,
  "data": {},
  "message": "Human-readable result",
  "error": null,
  "retryable": false,
  "evidence": [],
  "side_effect": "none",
  "verification": {}
}
```

Compatibility wrappers can preserve old routine names while new code consumes the standard result.

### Verification and bounded recovery

Verification must be capability-specific:

- Application: confirm the process/window exists.
- Reminder/note/todo: read the created record back from SQLite.
- Browser: inspect the resulting URL and visible page state.
- File action: confirm the exact target exists or changed.
- Research: confirm claims have supporting source records.

Retries must be bounded and must never repeat a completed side effect. Typed errors should distinguish invalid arguments, timeout, unavailable provider, permission denial, and non-retryable failure.

### Permission policy

Use enforced permissions rather than informational labels.

| Level | Examples | Behavior |
|---|---|---|
| Read-only | Search, page reading, list notes | May run automatically |
| Clear user intent | Open app, create note, set reminder | Run only when directly requested |
| Preview required | Multi-step writes, file organization | Show intended changes first |
| Immediate confirmation | Submit, send, publish, delete, purchase | Confirm immediately before execution |
| Blocked | Password storage, payment handling, unrestricted shell | Do not provide autonomously |

## Tool consolidation

Working implementations remain, but related model-visible tools should be grouped behind clearer action-based interfaces.

| Current tools | Consolidated capability |
|---|---|
| Voice dictionary add/list | `voice_dictionary(action=...)` |
| Routine list/run/create/disable | `manage_routine(action=...)` |
| Mode launch/close/status | `manage_mode(action=...)` |
| App launch/close/recent/status | `manage_app(action=...)` |
| Spotify/YouTube/media controls | `media(action=...)` |
| Quick/deep web search | `web_research(mode=...)` |
| Reminder create/list/complete/cancel | `manage_reminders(action=...)` |
| Assignment create/list/update/complete | `manage_assignments(action=...)` |
| Note create/list/search/update/delete | `manage_notes(action=...)` |
| Todo create/list/update/complete/delete | `manage_todos(action=...)` |
| Clipboard read/write | `clipboard(action=...)` |
| Browser read/actions/navigation | `browser(action=...)` with permission checks |

Keep old names as internal aliases until routines and tests are migrated.

Hide or disable by default:

- Raw `fetch_url` as a model-visible tool; the research layer should own fetching.
- Duplicate system-stat tools after consolidation.
- Cloud reasoning delegation.
- Unrestricted or destructive operations.

## Web research improvements

### Desired research loop

```text
Plan focused queries
-> search multiple providers
-> normalize and deduplicate results
-> rank primary/official sources
-> fetch strongest pages concurrently
-> extract structured evidence
-> detect missing or conflicting support
-> perform one bounded follow-up search
-> answer with claim-level citations
```

### Improvements over the current implementation

- Keep Trafilatura and BeautifulSoup fallback.
- Preserve query and page-fetch concurrency.
- Store evidence as structured source records instead of one long string.
- Add semantic reranking with a small local embedding model or trained ranker.
- Map factual claims to supporting sources, not merely check that `[1]` appears.
- Cache results with source timestamps.
- Prefer official documentation, government, academic, and primary sources.
- Treat all page text as untrusted data, never agent instructions.
- Add an optional local SearXNG provider only after basic research is reliable.

## Persistent local memory

### Memory types

- Short-term: recent turns isolated by conversation ID.
- Episodic: summaries of prior conversations, projects, and unfinished work.
- Durable: user-approved facts, preferences, goals, constraints, and corrections.
- Decision journal: what was chosen, why, and which evidence supported it.

### Required improvements

- Restore and verify the existing database before further migration.
- Keep mutable data in `%LOCALAPPDATA%\Hachi\`.
- Add provenance: source message, conversation, timestamp, and extraction method.
- Store only user-grounded facts; never promote assistant guesses.
- Support view, edit, forget, and clear operations.
- Handle corrections by superseding older facts while retaining audit history.
- Add automatic conversation summaries only after reviewed thresholds.
- Use SQLite FTS5 plus local semantic retrieval.
- Add prompt-injection, contradiction, cross-chat isolation, and restart tests.
- Never store passwords, payment data, or browser authentication secrets.

## Browser and vision roadmap

### Browser order of preference

```text
Structured API or search
-> HTTP page extraction
-> Playwright DOM/accessibility interaction
-> visual browser reasoning only when necessary
```

Read-only navigation can be automatic. Filling ordinary fields requires clear user intent. Submitting forms, sending messages, publishing, deleting, logging in, or purchasing requires immediate confirmation.

DOM and accessibility-tree interaction should remain the default for the 4B model because it is cheaper and more reliable than continuous screenshots.

Vision can later support:

- Screenshot explanation.
- Diagram and photographed-note reading.
- UI-state verification.
- Document image/OCR fallback.

## Student capabilities

Prioritize workflows that combine existing tools rather than merely adding isolated functions:

- Deep research with reliable citations.
- PDF and research-paper comparison.
- Course/project workspaces.
- Lecture transcription and summarized notes.
- Flashcards, quizzes, and reviewers from documents.
- Assignment and examination planning.
- Deadline reminders and daily briefings.
- Citation extraction and bibliography generation.
- Unsupported-claim detection.
- Research export to notes, reports, and presentations.
- Resume unfinished project steps across sessions.

Example target workflow:

> Research three local speech-recognition libraries, compare official Windows support and licenses, recommend one for my AI project, save the decision, create implementation tasks, and remind me before Friday.

## Office-worker capabilities

- Meeting transcription, summaries, and action items.
- Document and contract summarization.
- Spreadsheet interpretation and report generation.
- Email and memo drafting.
- Daily briefings from tasks, notes, and deadlines.
- Finding information across local documents.
- File organization with preview and confirmation.
- Reusable routines.
- Decision and responsibility tracking.
- Calendar-event and message drafts with confirmation before sending.
- Converting notes into formal documents and presentations.

## Easier agentic additions

After stabilization, these provide good value without full browser autonomy:

- Smart clarification for missing required fields.
- Action preview for multi-step writes.
- Undo for notes, todos, reminders, and reversible state changes.
- Continue the previous workflow with new input.
- Project/course workspaces.
- Pending/running/failed/completed task queue.
- Resume interrupted plans.
- Teach-a-routine from natural language with preview.
- Daily briefing.
- Decision journal.
- Research export.
- Current-context commands using a selected file, clipboard, or screenshot.
- Capability-specific result verification.

## User-visible activity timeline

The interface should make agency understandable without exposing hidden chain-of-thought. Show concise operational events such as:

```text
Planning three research queries
Searching two providers
Reading four sources
Checking unsupported claims
Saving the approved recommendation
Creating two tasks
Completed
```

Users should be able to cancel a running plan, inspect errors, retry a failed step, and see which operations changed local data.

## Evaluation strategy

Maintain a golden suite of realistic student, office, research, browser, memory, and voice tasks.

Measure:

- Correct capability selection.
- Valid tool arguments.
- End-to-end task completion.
- Unnecessary calls.
- Duplicate side effects.
- Recovery from failures.
- Citation support.
- Memory retrieval and cross-chat isolation.
- Confirmation-policy compliance.
- Latency and resource use.

Every major change needs a before/after comparison and a feature flag or rollback path until it proves reliable.

## Free and open-source component policy

Preferred components discussed for future evaluation:

- Qwen through Ollama for local inference.
- Qwen-Agent patterns for function calling and agent organization.
- Trafilatura for article extraction.
- Playwright for deterministic browser control.
- SearXNG as an optional local metasearch provider.
- SQLite and FTS5 for durable local storage and retrieval.
- A small local Qwen embedding model when semantic retrieval is justified.
- Scikit-learn for lightweight routers, classifiers, and ranking experiments.

Avoid paid APIs as core dependencies. Components with restrictive licenses should be studied for architecture only, not copied into the project.

## What Hachi should avoid

- Multi-agent swarms without a measured benefit.
- Unrestricted shell or filesystem access.
- Sending every tool to a small model on every request.
- Treating webpages as trusted instructions.
- Autonomous purchases, submissions, emails, or destructive actions.
- Loading multiple large models simultaneously on the current laptop.
- Replacing the entire application with a large framework.
- Adding capabilities without regression and safety tests.
- Training on raw conversations without review.

## Recommended implementation order

1. Finish and submit the smart-home exam application.
2. Fix browser back/home/close.
3. Disable and then remove DeepSeek dependencies.
4. Establish a reproducible environment and passing test suite.
5. Restore and validate local memory migration.
6. Benchmark Qwen 3.5 4B and select the final local-model configuration.
7. Train and integrate the hybrid tool-family router.
8. Add structured planning, standard results, verification, and recovery.
9. Consolidate model-visible tools with compatibility aliases.
10. Improve research evidence and citation validation.
11. Complete durable and episodic memory controls.
12. Add project workspaces and student/office workflow packs.
13. Expand controlled browser and vision capabilities.
14. Add resumable proactive routines and the polished activity timeline.

The guiding rule is simple: each new capability must make Hachi more useful and more reliable, not merely give Qwen another tool name.
