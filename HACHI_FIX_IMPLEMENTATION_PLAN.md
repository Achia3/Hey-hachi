# Hachi Fix Implementation Plan

Date: 2026-08-07

Companion audit: `REFERENCE_SOLUTIONS_AUDIT.md`

## Implementation status

Implemented on 2026-08-07:

- Unified request-scoped cancellation from the browser through Flask, model streaming, tool execution, TTS production, cached audio, and browser playback.
- Idempotent tool execution across Qwen/DeepSeek failover so a completed side effect is not repeated with a different provider call ID.
- Tiered browser endpointing with a 3.4-second long-form continuation window, filler handling, recognition restart without transcript loss, combined final/interim transcripts, a 60-second cap, and press-and-hold floor control.
- Exact stop-phrase handling with negative-phrase protection, native non-browser TTS stop monitoring, and an independent raw-microphone/browser-to-backend interrupt recognizer during audio playback.
- Speaking-state cleanup on playback completion, interruption, and failure.
- One terminal streaming event for multi-command prompts, plus direct multi-application batch execution and per-app results.
- Model-first tool decisions with a bounded three-round model -> tools -> model loop. Regex commands now run only as an offline/missed-action fallback.
- Automatic live web search when Qwen or DeepSeek has no supported informational answer.
- Windows `Get-StartApps`/AppID resolution, conservative fuzzy matching, ambiguity detection, visible-window verification, and truthful unverified results.
- Persistent recently-opened-app state for "close both/them", plus Steam Big Picture protocol launch for Gaming Mode.
- Optional full JSON structural repair (installed in the active Python environment), schema validation, bounded DeepSeek argument retry, registered-tool filtering, and missing-required-field rejection.
- Provider failure classification, empty-stream detection, Qwen/DeepSeek fallback, and action-result reuse during failover.
- Concurrent focused search queries, DuckDuckGo-to-Wikipedia fallback, canonical URL deduplication, relevance ranking, provenance, bounded page retrieval, redirect revalidation, SSRF protection, and boilerplate/duplicate-line cleanup.
- Scoped durable memory storage with feature embeddings, hybrid retrieval, explicit-only writes, duplicate detection, supersession, confidence/source metadata, and separation from conversation logs.
- Persistent student/productivity tools: PDF/DOCX/text extraction and summarization, spoken reminders/alarms, deadline tracking with advance reminders, notes/dictation, to-dos, daily recap, configurable focus cycles, screenshots, clipboard access, local file open/read, and battery/storage health.
- A 27-test regression suite covering multi-round tools, unknown-answer web search, multi-command completion, cancellation, audio interruption, idempotency, malformed tools, search deduplication, structured durable/personal-fact memory, memory-topic retrieval, productivity persistence, app resolution, Steam Big Picture, recent-app closing, URL safety, and stop phrases.

Environment-dependent validation still required on the target machine: microphone/acoustic tuning, real speaker echo behavior, installed-app/window-name coverage, live provider credentials, and live search-provider availability. These are hardware/service checks rather than missing implementation paths.

## Desired end state

Hachi should:

- listen through natural pauses without truncating long-form speech;
- stop audio and response generation promptly when the user interrupts;
- never remain stuck in a speaking state;
- execute all independent commands in one prompt and report each result;
- repair or retry malformed tool calls safely;
- fail over between model paths without duplicating side effects;
- route searches through relevant subqueries/providers and produce clean, sourced answers;
- retrieve durable memories semantically without allowing contradictions to silently overwrite facts;
- verify Windows automation before claiming success.

## Phase 0: Add observability before changing behavior

Target files:

- `hachi_agent.py`
- `hachi_web.py`
- `hachi_speech.py`
- `templates/index.html`

Add one request/turn identifier to logs and events. Record timestamps for:

- microphone started;
- first voice activity;
- last voice activity;
- interim/final transcript;
- endpoint scheduled/cancelled/committed;
- model request started/first token/completed/cancelled;
- TTS queued/started/first audio/completed/cancelled;
- browser playback started/stopped;
- final voice state.

This makes it possible to tell whether a failure is caused by STT, endpointing, model latency, TTS, or browser playback.

Acceptance check:

- A single voice turn can be reconstructed from logs using one turn ID.
- Logs contain no raw audio and redact secrets.

## Phase 1: Unified voice state and cancellation

Reference repositories: `vui` first, `jarvis` second.

Target files/functions:

- `hachi_web.py::voice_stream`
- `hachi_agent.py::process_agent_request_stream`
- `templates/index.html::runVoiceTurn`
- `templates/index.html::doInterrupt`
- `templates/index.html` audio queue/playback functions
- `hachi_speech.py` TTS playback path if the desktop/non-browser voice path remains supported

### 1.1 Introduce a request-scoped cancellation object

Create one cancellation token/event per voice turn. It must be checked:

- before and during model streaming;
- before every tool call;
- between tool calls in a batch;
- before TTS synthesis;
- while producing/streaming audio;
- before the browser starts each queued sentence.

On interruption:

1. mark the turn cancelled;
2. abort the active browser fetch/SSE reader;
3. stop and clear the browser audio queue;
4. cancel pending TTS work;
5. close/stop model iteration as soon as supported;
6. do not execute later tools from the cancelled turn;
7. return voice state to listening.

### 1.2 Replace independent booleans with state transitions

Use an explicit state enum:

```text
idle -> listening -> thinking -> speaking -> listening
                         |           |
                         +-> cancelled <-+
```

Only the state owner can transition it. All error/cancel branches restore the state in `finally`.

### 1.3 Make stop detection deterministic

During TTS, run a small fast recognizer path for interruption phrases. Match normalized complete phrases/tokens, not arbitrary substrings. Examples:

- accept: `stop`, `hachi stop`, `quiet`, `cancel`, `that's enough`;
- reject: `don't stop`, `stopwatch`, `the bus stop is nearby`.

The accepted stop utterance must not become a new assistant question.

Tests to add:

- stop during the first sentence halts playback within the chosen latency budget;
- stop between sentences prevents the next sentence from starting;
- stop before a tool executes prevents that tool;
- stop after one tool in a batch prevents remaining tools and reports cancellation;
- stop utterance does not appear in conversation memory as a normal query;
- speaking state clears after TTS exception, client disconnect, and model exception.

## Phase 2: Long-form listening and recognition reliability

Reference repositories: `vui`, then `ai-jarvis`, with `jarvis` for echo suppression.

Target files/functions:

- `templates/index.html::listenOneTurn`
- browser speech-recognition event handlers
- `hachi_speech.py` recognizer setup

### 2.1 Replace the fixed short commit timer

Implement a pending endpoint:

- VAD/speech recognition observes a pause.
- Wait for the final transcript to settle.
- If the transcript has terminal punctuation, commit sooner.
- If it lacks punctuation, wait longer.
- If speech restarts, cancel the commit and continue the same utterance.
- If the transcript is a short filler-ended fragment, keep the floor open.

Starting tuning values, to be measured rather than treated as final:

- normal pause grace: 1.2-1.8 seconds;
- long-form mode pause grace: 2.0-2.5 seconds;
- maximum command duration: 30 seconds;
- short ASR settle delay: about 100-200 milliseconds.

### 2.2 Preserve the beginning and end of speech

- Maintain a small microphone pre-roll buffer.
- Preserve a short post-speech tail.
- Do not discard interim transcript text when recognition restarts.

### 2.3 Add hold-floor UI

Add press-and-hold behavior to the voice orb: while held, Hachi must not commit the turn even if the speaker pauses. Release returns control to normal endpointing.

### 2.4 Add echo and microphone diagnostics

- Compare recognized text with recent Hachi speech to detect playback echo.
- Keep non-echo words rather than dropping a mixed echo/user utterance entirely.
- Report input device, observed audio level, VAD transitions, recognized language, and transcript confidence where the API exposes them.

Tests to add:

- 15-30 second utterance with two 1.5-second thinking pauses is captured as one turn;
- speech resumed during pending endpoint cancels the commit;
- "um" followed by a pause does not immediately submit;
- first syllable is preserved;
- Hachi's own spoken sentence is not treated as a new command;
- mixed echo plus "stop" still interrupts.

## Phase 3: Structured multi-command execution

Reference repositories: `row-bot` for execution, `argo` for parsing, `ai-jarvis` for Windows launching.

Target files/functions:

- `hachi_agent.py::split_into_subrequests`
- Qwen and DeepSeek tool-call loops in `hachi_agent.py`
- `hachi_tools.py::execute_tool_call`
- `hachi_tools.py::launch_app`

### 3.1 Treat one model response as an action list

Normalize all model tool output to:

```python
actions = [
    {"id": "...", "name": "launch_app", "arguments": {"app_name": "Discord"}},
    {"id": "...", "name": "launch_app", "arguments": {"app_name": "Spotify"}},
]
```

Do not discard calls after the first one. Validate every action before execution.

### 3.2 Separate independent batches from dependent steps

- Independent: opening three applications can be executed as one controlled batch.
- Dependent: "open Notepad, write this text, then save it" must execute sequentially because later steps depend on earlier state.

Add an execution record for each action:

```text
pending -> running -> succeeded | failed | cancelled | skipped
```

The final answer should summarize each result. A partial failure must not be reported as total success.

### 3.3 Demote regex splitting to fallback

Keep `split_into_subrequests` only when the selected model genuinely cannot return structured tool calls. Never split a normal sentence merely because it contains "and."

Tests to add:

- "Open Discord, Spotify, and Chrome" produces three launch calls and one final summary.
- One missing app does not hide the two successful launches.
- "Open Chrome and search for cats and dogs" does not become three unrelated commands.
- Cancellation after the first action prevents the second and third actions.
- Re-running a failed model request does not repeat a completed launch.

## Phase 4: Reliable Windows application launching

Reference repositories: `ai-jarvis` for discovery, `row-bot` for verification.

Target file:

- `hachi_tools.py::launch_app`

### 4.1 Add installed-app enumeration

Build and periodically refresh a cache from Windows `Get-StartApps`. Resolve names using:

1. exact normalized match;
2. prefix match;
3. substring match;
4. conservative fuzzy match with a minimum score and ambiguity detection.

Launch packaged applications through `shell:AppsFolder\\<AppID>`.

### 4.2 Verify launch outcome

After calling a launch mechanism, poll for a bounded time for:

- the expected process; or
- a visible window whose process/name matches the resolved app.

Return structured data, including the resolution method and verification result. Do not say "Opening X" merely because `Popen` or `start` returned without an exception.

### 4.3 Avoid unsafe duplicate retries

If a driver disconnects after an input/launch request, first observe whether the side effect occurred. Do not automatically repeat the input.

Tests to add:

- Win32 executable, Start shortcut, UWP app, protocol app, fuzzy app name;
- ambiguous name prompts for clarification rather than opening a random match;
- launch process succeeds but no target window/process appears;
- batch results retain per-app status.

## Phase 5: Tool-call syntax, schema, and history repair

Reference repositories: `argo` then `row-bot`.

Target files/functions:

- `hachi_agent.py::_parse_tool_args`
- all Qwen/DeepSeek tool-call loops
- message-history update code

### 5.1 Bounded JSON repair

Use a maintained JSON repair library or a small bounded repair stage. It must support nested values, lists, numbers, booleans, and code-fenced JSON. Preserve the raw value in debug logs.

### 5.2 Validate with the existing tool schema

After parsing:

- confirm tool name is registered;
- confirm arguments form an object;
- validate required properties and types;
- reject unexpected dangerous fields where appropriate.

If validation fails, send a compact tool-specific correction back to the same model once. Do not execute `{}` as a repaired call.

### 5.3 Maintain valid tool history

Every assistant tool-call ID must have exactly one corresponding tool result, including a synthetic cancelled/error result when a turn is interrupted. Remove or repair orphaned tool messages before sending history to another provider.

Tests to add:

- missing closing brace;
- fenced JSON;
- list of three tool calls;
- nested argument object;
- missing required `app_name`;
- unknown tool name;
- cancelled action produces a matching cancelled tool result;
- duplicate recovered call is executed once.

## Phase 6: Central model fallback policy

Reference repositories: `row-bot`, with `py-gpt` for deterministic router fallback.

Target files/functions:

- `hachi_agent.py::call_deepseek_chat`
- `hachi_agent.py::_qwen_tool_decide`
- `hachi_agent.py::process_agent_request`
- `hachi_agent.py::process_agent_request_stream`

### 6.1 Normalize errors

Define failure kinds:

- authentication;
- quota/rate limited;
- model unavailable;
- unsupported tools/streaming;
- context exceeded;
- timeout;
- provider outage;
- invalid response;
- local runtime unavailable.

Each kind should define whether to retry the same path, switch mode/provider, reduce context, or return an actionable error.

### 6.2 Use a bounded matrix

Recommended example:

| Failure | First action | Second action | Never do |
|---|---|---|---|
| Empty streaming response | Same provider once, non-stream | Alternate model | Infinite stream retries |
| Timeout before any tool | Alternate model once | User-facing timeout | Repeat indefinitely |
| Timeout after a tool | Resume with recorded result | Summarize partial completion | Re-execute the tool blindly |
| Authentication/quota | Alternate configured provider | Explain configuration problem | Retry same credentials repeatedly |
| Invalid router output | Deterministic default route | Log raw router output | Stall without a route |
| Context exceeded | Trim/summarize context once | Alternate larger-context model | Drop tool results silently |

### 6.3 Add idempotency

Key every action by turn ID plus tool-call ID. Keep completed action results across a model failover. The alternate model receives those results and decides only what remains.

Tests to add:

- Qwen timeout before any action;
- DeepSeek rate limit;
- empty stream recovered via non-stream;
- provider failure after first of three apps;
- invalid router JSON follows the configured default route;
- no tool executes more than once per turn/call ID.

## Phase 7: Search routing and cleanup

Reference repositories: `khoj` for routing, `jarvis` for fetching and cleanup.

Target files/functions:

- `hachi_tools.py::search_web`
- `hachi_tools.py::fetch_url`
- `hachi_agent.py::_qwen_summarize_search`

### 7.1 Return structured search records

Replace formatted bullet strings inside the search pipeline with records:

```python
{
    "title": "...",
    "url": "...",
    "snippet": "...",
    "provider": "...",
    "published_at": None,
    "query": "...",
}
```

Formatting belongs only at the final UI/answer boundary.

### 7.2 Add focused query routing

- Generate zero to two additional focused subqueries.
- Fall back to the original query when generation/parsing fails.
- Execute queries concurrently under one overall deadline.
- Deduplicate canonical URLs.

### 7.3 Add provider cascade and relevance gates

- Try configured providers in a fixed order.
- Use short provider and page-fetch deadlines.
- Fetch only a few top pages concurrently.
- Clean boilerplate and repeated lines.
- Reject content with insufficient query-token overlap.
- Preserve URL/title/provider in synthesis context.

### 7.4 Treat web content as untrusted

Block private/local addresses and revalidate redirects. Clearly delimit fetched content so instructions inside a page cannot become agent instructions.

Tests to add:

- primary provider fails, fallback returns results;
- duplicate URL from two subqueries appears once;
- cookie-only page is rejected;
- relevant lower-ranked page beats irrelevant top page;
- private/loopback URL is not fetched;
- total deadline is honored;
- final answer retains source provenance.

## Phase 8: Durable semantic memory without drift

Reference repositories: `khoj` for retrieval, `row-bot` and `jarvis` for write/consolidation safety.

Target files:

- `hachi_db.py`
- a new focused module such as `hachi_memory.py`
- memory routing in `hachi_agent.py`

### 8.1 Separate logs from durable memories

Keep `conversations` as an audit/history log. Add curated durable memory records with fields similar to:

```text
id, user_id, agent_id, category, subject, content, embedding,
confidence, source_turn_id, status, supersedes_id, created_at, updated_at
```

### 8.2 Add a write gate

Only store durable facts/preferences/tasks that are useful beyond the current turn. Before inserting:

- normalize category and subject;
- compare same-subject memories;
- skip duplicates;
- supersede verified outdated facts;
- quarantine contradictions for clarification/review;
- never let an LLM erase valid memory because its merge output is malformed.

### 8.3 Add hybrid recall

Retrieve from:

- recent messages;
- semantic memory similarity;
- exact keyword/date history when appropriate.

Rerank and inject only a small number of high-confidence memories with source metadata. Do not present inferred or uncertain memory as a confirmed user fact.

Tests to add:

- paraphrased recall succeeds without exact keyword overlap;
- another user's/agent's memory cannot leak;
- duplicate preference is not stored twice;
- changed preference supersedes the old one;
- contradictory statements are not silently merged;
- irrelevant memories are excluded from the prompt;
- invalid consolidation cannot delete stored memory.

## Suggested implementation sequence by file

| Order | Hachi file | Main changes | Main references |
|---|---|---|---|
| 1 | `templates/index.html` | Endpointing, hold-floor, stop recognition, unified browser playback state | `vui`, `jarvis` |
| 2 | `hachi_web.py` | Turn IDs, cancellation registry, disconnect cleanup | `vui` |
| 3 | `hachi_agent.py` | Cancellation checks, multi-action loop, parser/schema repair, centralized failover | `row-bot`, `argo`, `py-gpt` |
| 4 | `hachi_tools.py` | AppID discovery/verification; structured search and safe fetch | `ai-jarvis`, `row-bot`, `jarvis`, `khoj` |
| 5 | `hachi_speech.py` | Interruptible playback, speaking-state `finally`, diagnostics | `jarvis`, `ai-jarvis` |
| 6 | `hachi_db.py` and new `hachi_memory.py` | Durable memory schema, semantic retrieval, conflict/supersession rules | `khoj`, `row-bot`, `jarvis` |
| 7 | tests | Deterministic regression coverage for every failure above | Reference test suites |

## Definition of done

The fixes are complete only when all of these are demonstrated:

- A long utterance with natural pauses arrives as one transcript.
- Saying "stop" cancels audible playback promptly and prevents queued speech/actions.
- Voice state recovers after cancellation, disconnect, model failure, and TTS failure.
- One prompt can open several applications, with a verified status for each.
- Malformed tool JSON is repaired or rejected with a bounded schema retry; it is never silently executed with empty arguments.
- Provider failover does not duplicate a completed side effect.
- Search returns deduplicated, relevant, provenance-preserving evidence under a total deadline.
- Semantic memory recalls paraphrases, isolates users/agents, and represents changed or conflicting facts safely.

## Immediate first implementation slice

The highest-value, lowest-sprawl slice is:

1. request-scoped cancellation through browser, server stream, model loop, and TTS queue;
2. tiered endpoint commit with speech-resume cancellation and a long-form silence threshold;
3. execute all structured tool calls in a response;
4. resolve apps through `Get-StartApps` and verify their windows;
5. add the corresponding stop, long-form, three-app, and no-duplicate tests.

That slice directly addresses the four user-visible failures while laying the foundation for parser, fallback, search, and memory hardening.
