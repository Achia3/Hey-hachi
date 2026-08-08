# Hachi Reference Solutions Audit

Date: 2026-08-07

Scope: local repositories under `references/`, compared with Hachi's current voice, agent, memory, search, and Windows automation code.

## Executive recommendation

Do not transplant a complete reference assistant into Hachi. Use the references as focused implementation sources:

| Hachi problem | Primary repository | Supporting repository | What Hachi should adopt |
|---|---|---|---|
| Voice recognition and long-form listening | `vui` | `ai-jarvis`, `jarvis` | Tiered end-of-turn detection, longer command buffering, microphone diagnostics |
| "Stop" does not interrupt speech | `vui` | `jarvis` | One cancellation signal propagated through generation, TTS, playback, and UI; deterministic stop-word path |
| Hachi cuts the user off | `vui` | `ai-jarvis` | Cancel pending endpoint when speech resumes; punctuation-aware commit; 2.5-second silence option and 30-second command cap |
| Stuck speaking state | `jarvis` | `vui` | Clear speaking state in `finally`; completion callbacks only after non-interrupted playback |
| Multiple apps / multiple commands | `row-bot` | `argo`, `ai-jarvis` | Execute every tool call in one model response; sequential workflow support; reliable Windows app resolution |
| Web lookup routing | `khoj` | `jarvis` | Generate focused subqueries, search concurrently, cascade providers, fall back to original query |
| Search-result cleanup and answer quality | `jarvis` | `khoj` | URL deduplication, query-overlap relevance gate, parallel page fetch, bounded cleanup and provenance |
| Memory drift and weak recall | `khoj` | `row-bot`, `jarvis` | Semantic retrieval plus deterministic deduplication, contradiction/supersession handling, and guarded consolidation |
| Malformed tool-call recovery | `argo` | `row-bot` | JSON repair, schema validation feedback, known-tool filtering, and tool-message history repair |
| Model/provider fallback | `row-bot` | `py-gpt` | Classify failures, bounded retry/failover, stream-to-nonstream recovery, deterministic router fallback |
| Desktop automation reliability | `ai-jarvis` | `row-bot` | Enumerate Start apps by AppID, fuzzy match names, then verify the resulting PID/window before reporting success |

## Priority order

1. Fix the shared voice turn-state and cancellation path. This addresses talking over the user, ignored stop commands, cutoffs, and stuck speaking together.
2. Replace heuristic command splitting with a real multi-action execution loop, then improve app resolution and verification.
3. Harden tool-call parsing and provider failover. These protect every tool and prevent partially completed multi-command requests.
4. Upgrade search routing and result cleanup.
5. Add semantic memory and conflict-aware memory writes.

## 1. Voice recognition and understanding

### What Hachi does now

- `templates/index.html::listenOneTurn` uses browser `SpeechRecognition` and commits a turn after a short fixed silence window.
- `hachi_speech.py` configures a basic recognizer with `pause_threshold`, `phrase_threshold`, and `non_speaking_duration`.
- The browser path has no acoustic microphone health report, no transcript confidence policy, and no robust continuation mechanism for long pauses.

The main failure is not only speech-to-text quality. Hachi is deciding that a turn ended too early, so incomplete audio reaches the language model and appears to be an understanding failure.

### Best solution sources

#### Primary: `vui`

Relevant files:

- `references/vui/src/vui/serving/stream/voice_turn.py`
- `references/vui/src/vui/serving/stream/server.py`
- `references/vui/src/vui/serving/stream/drains.py`
- `references/vui/src/vui/serving/stream/index.html`

Patterns to adopt:

- Tiered endpointing: VAD first detects silence, then the system waits briefly for ASR to settle.
- Fast commit when the transcript ends in punctuation; a longer grace period when it does not.
- If speech resumes during that grace period, cancel the pending commit and keep the same turn alive.
- Treat short utterances ending in fillers such as "uh" or "um" as incomplete.
- Add a press-and-hold "hold the floor" mode for deliberate thinking pauses.

This is the most complete solution to Hachi cutting off long-form speech.

#### Supporting: `ai-jarvis`

Relevant file:

- `references/ai-jarvis/voice/stt.py`

Patterns to adopt:

- Keep recording until about 2.5 seconds of silence after speech begins.
- Allow a command to last up to about 30 seconds.
- Run VAD checks at small intervals and preserve a small tail after the last speech frame.
- Log the recognized transcript and microphone-health diagnostics so recognition failures can be distinguished from endpoint failures.

This is easier to adapt if Hachi keeps its current architecture before a full streaming voice pipeline is introduced.

#### Supporting: `jarvis`

Relevant files:

- `references/jarvis/src/jarvis/listening/listener.py`
- `references/jarvis/src/jarvis/listening/listening.spec.md`

Patterns to adopt:

- Pre-roll audio so the beginning of a phrase is not clipped.
- Use a rolling transcript buffer.
- Separate ordinary end-of-turn silence from the shorter path used only to detect interruption commands while TTS is active.
- Apply layered echo detection so Hachi's own voice is not transcribed as the user.

### Recommendation

Use `vui` for the target design and `ai-jarvis` for an incremental first implementation. Use `jarvis` for echo suppression and diagnostics. Do not try to solve this only by changing the speech recognizer's language model.

## 2. "Stop" does not stop speech and Hachi talks over the user

### What Hachi does now

The browser now has an interrupt recognizer and aborts the active voice response/playback. That is useful, but cancellation is still fragmented: UI playback, HTTP streaming, language-model generation, TTS generation, and server speaking state do not all share one request-scoped cancellation token.

### Best solution sources

#### Primary: `vui`

Relevant files:

- `references/vui/src/vui/serving/stream/drains.py`
- `references/vui/src/vui/serving/stream/server.py`
- `references/vui/src/vui/serving/stream/voice_turn.py`

The barge-in path performs one coordinated transition:

1. Cancel the pending endpoint task.
2. Reset the voice phase.
3. Flush queued playback.
4. Set generation cancellation.
5. Set TTS cancellation.
6. Rewind/cancel the TTS queue.
7. Restart ASR cleanly for the user's continuing speech.

Hachi should have the same request-scoped cancellation object checked by the DeepSeek/Qwen stream loop, sentence-to-TTS producer, audio endpoint, and browser queue.

#### Supporting: `jarvis`

Relevant files:

- `references/jarvis/src/jarvis/output/tts.py`
- `references/jarvis/src/jarvis/listening/listener.py`
- `references/jarvis/evals/test_listener_integration.py`

Patterns to adopt:

- Use a thread-safe interrupt event checked before synthesis, between synthesis and playback, and repeatedly during playback.
- Play small audio blocks and check cancellation for every block, not only between sentences.
- Detect stop words on a deterministic fast path during TTS and do not forward them as a new assistant query.
- Clear speaking state in `finally`.
- Invoke a normal completion callback only if playback was not interrupted.

The integration test that asserts "stop during TTS interrupts immediately and does not produce a query" should be reproduced for Hachi.

### Recommendation

Use `vui` for end-to-end cancellation and `jarvis` for TTS implementation details and regression tests. Avoid a substring-only stop test: words such as "don't stop" or "stopwatch" must not accidentally cancel speech.

## 3. Hachi cuts the user off during long-form speech

This shares the endpointing root cause with voice recognition, but needs its own acceptance criteria.

Use these `vui` behaviors:

- Silence begins a pending commit; it does not immediately finalize the turn.
- New voice activity cancels the pending commit.
- A transcript without terminal punctuation gets a longer continuation window.
- Filler-ended fragments remain open.
- A hold-floor control explicitly defers endpointing.

Use these `ai-jarvis` defaults as a practical starting point:

- End silence: approximately 2.0-2.5 seconds for long-form voice mode.
- Maximum utterance: approximately 30 seconds.
- Preserve pre-roll and a short post-speech tail.

Do not apply the long silence threshold to stop detection while Hachi is talking. Stop/barge-in needs its own fast path.

## 4. Stuck speaking state

### Best solution sources

#### Primary: `jarvis`

Relevant file:

- `references/jarvis/src/jarvis/output/tts.py`

The crucial pattern is ownership of state:

- Set speaking immediately before playback owns the audio device.
- Clear it in a `finally` block regardless of synthesis errors, playback errors, or interruption.
- Treat interruption and normal completion as different terminal outcomes.

#### Supporting: `vui`

Relevant file:

- `references/vui/src/vui/serving/stream/voice_turn.py`

`voice_respond` temporarily changes session readiness and restores it in `finally`. Hachi should apply that same invariant to all voice state flags.

### Recommendation

Create one explicit state machine: `idle -> listening -> thinking -> speaking -> idle`, with `interrupting` or `cancelled` as a transition rather than a second independent set of booleans. Every terminal branch must return to `idle` or `listening` in `finally`.

## 5. Multiple apps and multi-command prompts

### What Hachi does now

`hachi_agent.py::split_into_subrequests` uses regular expressions around words such as "and" and "then." This can miss commands, split natural language incorrectly, and recursively sends each fragment through a complete agent turn. It is not equivalent to a model returning several structured actions.

### Best solution sources

#### Primary: `row-bot`

Relevant files:

- `references/row-bot/src/row_bot/agent.py`
- `references/row-bot/src/row_bot/tasks.py`
- `references/row-bot/tests/subsystem/agents/test_execution_budget.py`

Patterns to adopt:

- Accept and execute every tool call in one assistant message as one batch.
- Charge/track the batch as one model iteration, not one iteration per application.
- Return one tool result for each tool call before asking the model for a final summary.
- For dependent jobs, use an explicit ordered step list with per-step output, retry count, and `stop`/`skip` failure behavior.

#### Supporting: `argo`

Relevant file:

- `references/argo/backend/core/agent/output_parser/tools.py`

`MultiActionAgentOutputParser` returns a list of actions instead of silently keeping only the first tool call. This is the correct parser contract for "open Discord, Spotify, and Chrome."

#### Windows execution: `ai-jarvis`

Relevant files:

- `references/ai-jarvis/tools/windows_apps.py`
- `references/ai-jarvis/tools/windows_state.py`

Patterns to adopt:

- Enumerate installed Start applications with `Get-StartApps`.
- Cache display-name-to-AppID mappings.
- Match exact name, prefix, substring, then fuzzy name.
- Launch packaged apps using `shell:AppsFolder\\<AppID>`.
- Enumerate visible windows and confirm/focus the result.

### Recommendation

Use `row-bot` for orchestration, `argo` for multi-action parsing, and `ai-jarvis` for Windows app resolution. Keep regex splitting only as a last-resort fallback for models that cannot produce tool calls.

## 6. Web search and lookup routing

### What Hachi does now

`hachi_tools.py::search_web` uses one DuckDuckGo provider and returns up to six snippets. `_qwen_summarize_search` may fetch one selected page. There is no provider cascade, query decomposition, URL deduplication, or strong content relevance check.

### Best solution source: `khoj`

Relevant files:

- `references/khoj/src/khoj/processor/tools/online_search.py`
- `references/khoj/src/khoj/routers/helpers.py`

Patterns to adopt:

- Generate at most three focused subqueries from the current question, recent conversation, location, and useful memories.
- Run the subqueries concurrently.
- Cascade through configured providers until a provider returns useful results.
- Deduplicate organic results by canonical URL across subqueries.
- Fall back to the original user query if structured subquery generation fails.
- Optionally fetch and read the top pages only after routing/ranking.

### Recommendation

Use `khoj` for deciding what to search and how to distribute the search. Keep the initial Hachi implementation small: original query plus at most two generated subqueries, a strict total deadline, and a two-provider cascade.

## 7. Search-result cleanup and answer quality

### Primary: `jarvis`

Relevant file:

- `references/jarvis/src/jarvis/tools/builtin/web_search.py`

Patterns to adopt:

- Enforce an overall search deadline and shorter per-page fetch deadlines.
- Fetch a small number of top results concurrently.
- Remove scripts, navigation, forms, cookie banners, repeated lines, and other boilerplate.
- Reject extracted pages with no meaningful token overlap with the query.
- Revalidate redirects and block unsafe/private targets before fetching.
- Preserve source title and URL as provenance passed into answer synthesis.
- Fall back across DuckDuckGo, Brave, and Wikipedia rather than returning a vague failure after one provider.

### Supporting: `khoj`

Use `deduplicate_organic_results` in `online_search.py` as the pattern for cross-query URL deduplication.

### Recommendation

Use `jarvis` for content fetch/cleanup and `khoj` for result aggregation/deduplication. The answer model should receive a compact list of source records, not one large unstructured string.

## 8. Memory drift and weak long-term recall

### What Hachi does now

`hachi_db.py::search_history` performs literal SQL `LIKE` matching over conversation/task text and loads a small number of recent messages. It has no semantic embeddings, memory categories, confidence, contradictions, supersession, or consolidation.

### Best solution sources

#### Retrieval: `khoj`

Relevant file:

- `references/khoj/src/khoj/database/adapters/__init__.py` (`UserMemoryAdapters`)

Patterns to adopt:

- Embed durable memories and retrieve them with cosine similarity.
- Scope memory by user and agent.
- Separate recent medium-term recall from semantic long-term recall.
- Apply a confidence threshold instead of injecting every approximate match.

#### Write hygiene: `row-bot`

Relevant file:

- `references/row-bot/src/row_bot/tools/memory_tool.py`

Patterns to adopt:

- Normalize category and subject before saving.
- Deduplicate same-subject facts deterministically.
- Replace a narrower memory when the new memory is a verified superset.
- Flag contradictions for review instead of blindly merging them.
- Return source, status, confidence, tier, and supersession metadata with recalls.

#### Consolidation safety: `jarvis`

Relevant files:

- `references/jarvis/src/jarvis/memory/recall_gate.py`
- `references/jarvis/src/jarvis/memory/graph_ops.py`
- `references/jarvis/src/jarvis/memory/graph.spec.md`

Patterns to adopt:

- Gate recall with deterministic content-word coverage and fresh tool results.
- Consolidate duplicates and represent supersession explicitly.
- Reject consolidation that invents facts or erases valid memory.
- Fail open to append when an LLM-based merge is invalid.

### Recommendation

Use `khoj` for semantic retrieval, but do not copy its whole database layer. Add a small Hachi `memories` table and embedding index. Use `row-bot` and `jarvis` rules before any new memory is committed. Conversation logs should remain separate from curated durable memories.

## 9. Tool-call parsing and malformed output recovery

### What Hachi does now

`hachi_agent.py::_parse_tool_args` tries strict JSON, appends a quote/brace, then extracts quoted string pairs. It cannot reliably repair arrays, numbers, booleans, nested objects, or multiple actions. Empty repaired arguments may then reach a tool and cause a misleading failure.

### Best solution sources

#### Primary: `argo`

Relevant files:

- `references/argo/backend/core/agent/output_parser/tools.py`
- `references/argo/backend/core/agent/langgraph_agent/utils/json_utils.py`

Patterns to adopt:

- Strip Markdown/TypeScript code fences.
- Use `json-repair` for bounded structural repair.
- Normalize repaired JSON through a real parser.
- Return every valid action.
- Raise a typed parse error if repair is not possible.

#### Supporting: `row-bot`

Relevant files:

- `references/row-bot/src/row_bot/providers/tool_protocol.py`
- `references/row-bot/src/row_bot/agent.py`
- `references/row-bot/src/row_bot/providers/transports/openai_compatible.py`

Patterns to adopt:

- Validate arguments against the tool's schema.
- On validation error, tell the model exactly which required fields are missing and ask it to retry the same tool call.
- Recover textual/XML-like tool envelopes only when normal structured tool calls are absent.
- Filter recovered calls to known tool names and deduplicate them.
- Repair chat history so each assistant tool call has a matching tool result, including after cancellation.

### Recommendation

Use `argo` for syntax repair and `row-bot` for semantic/schema repair. Never silently convert an unparseable tool call to `{}` and execute it.

## 10. Fallback routing when a model path fails

### What Hachi does now

Hachi has several Qwen/DeepSeek branches and broad exception fallbacks. The behavior varies by branch, and there is no shared failure taxonomy or idempotency key protecting already-executed tools during retry/failover.

### Primary: `row-bot`

Relevant files:

- `references/row-bot/src/row_bot/providers/errors.py`
- `references/row-bot/src/row_bot/providers/transports/openai_compatible.py`

Patterns to adopt:

- Normalize failures into authentication, quota, rate limit, unavailable model, unsupported feature, context overflow, timeout, and outage.
- Attach a next action to the normalized error.
- If a streaming response is empty, retry the same provider once in non-stream mode.
- Only switch provider/model for retryable availability failures.
- Record which tool calls already completed so failover cannot launch an application twice.

### Supporting: `py-gpt`

Relevant file:

- `references/py-gpt/src/pygpt_net/core/agents/custom/runner.py`

If router output is invalid, PyGPT chooses a deterministic configured route rather than stalling. Hachi should likewise have a fixed default route for malformed classifier output.

### Recommendation

Create one shared `run_with_fallback` policy used by both streaming and non-streaming paths. Use `row-bot` as the main reference. `ai-jarvis` is not the right primary reference here; it offers selectable backends but not the same runtime failure classification and recovery depth.

## 11. Desktop automation reliability

### What Hachi does now

`hachi_tools.py::launch_app` has a useful chain of paths, aliases, Start Menu shortcuts, protocols, and `os.startfile`. It returns as soon as a launch call does not throw. It generally does not verify that the intended process/window appeared, and a multi-launch request receives no structured per-app outcome.

### Primary for app discovery: `ai-jarvis`

Relevant files:

- `references/ai-jarvis/tools/windows_apps.py`
- `references/ai-jarvis/tools/windows_state.py`

Use its `Get-StartApps`/AppID lookup and visible-window enumeration patterns.

### Primary for verification and safe control: `row-bot`

Relevant files:

- `references/row-bot/src/row_bot/computer_use/service.py`
- `references/row-bot/src/row_bot/computer_use/policy.py`

`launch_app` registers returned windows, falls back to listing windows if needed, and captures the selected target. Other service logic ties targets to PID/window identity and treats stale observations or disconnected input sessions explicitly. This prevents "reported success but nothing opened" and avoids blindly repeating side-effecting input.

### Recommendation

Keep Hachi's existing launch fallback chain, add `Get-StartApps` before filesystem globbing, and add a bounded post-launch verifier. Return a batch result such as:

```json
{
  "requested": ["Discord", "Spotify", "Chrome"],
  "opened": ["Discord", "Spotify"],
  "failed": [{"app": "Chrome", "reason": "window_not_observed"}]
}
```

Hachi should speak only the verified summary.

## Repository selection notes

### Repositories to use first

- `vui`: voice turn-taking, endpointing, barge-in, coordinated cancellation.
- `jarvis`: deterministic stop behavior, interruptible TTS, echo handling, search cleanup, memory consolidation rules.
- `row-bot`: multi-tool execution, task steps, provider failure handling, schema repair, reliable automation verification.
- `argo`: compact and strong multi-action/JSON repair patterns.
- `ai-jarvis`: practical Windows app discovery and simple long-form VAD recording.
- `khoj`: search routing and semantic memory retrieval.
- `py-gpt`: deterministic agent-router fallback only.

### Repositories not needed as primary sources for these fixes

- `agent_cortex_v2`, `MemoryWebAssistant`, `AI-Intelligent-Assistant`, and `EVA` may contain useful ideas, but the named primary repositories above contain clearer, testable implementations for the listed failures.
- `ai-jarvis` should not be the primary model-failover source.
- `khoj` should not be copied wholesale just to add memory; its AGPL license and larger architecture make a small clean-room adaptation of the behavior safer and easier to maintain.

## License caution

Reference behavior can be studied, but copying source must respect each repository's license:

- Apache-2.0: `vui`, `row-bot`.
- MIT: `ai-jarvis`, `py-gpt`, `agent_cortex_v2`, `AI-Intelligent-Assistant`.
- AGPL-3.0: `khoj`; direct code reuse can impose significant distribution obligations.
- Custom licenses: `jarvis` and `argo`; review their complete license terms before copying code.
- No root license found during this audit: `EVA`, `MemoryWebAssistant`, `Friday-Local-Ai-Assistant-V1`, `Horizon.ai`; treat these as study-only unless ownership/license is clarified.

The recommendations in this document are architectural patterns. Prefer independently implementing those patterns in Hachi and preserving required notices for any copied licensed code.
