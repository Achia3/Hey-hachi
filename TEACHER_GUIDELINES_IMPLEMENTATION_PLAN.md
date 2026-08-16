# Hachi Prelim Guidelines Implementation Plan

## Direction agreed on August 16, 2026

The exam features will reuse Hachi's Flask backend, local Ollama agent, local Whisper/faster-whisper transcription, voice loop, and capability system. The simulated house is displayed in a **separate PyWebView desktop window**, so the normal Hachi chat and its past conversations remain visible and unchanged. We will not build a second Tkinter codebase, train Qwen, or train a separate intent classifier for this five-day deadline.

The pair will create the project-report PDF themselves. Hachi will generate the runtime log, timings, state changes, and screenshots that can be used as evidence.

## Required end-to-end result

```text
Microphone -> local Whisper/faster-whisper -> local Qwen 3.5 4B
           -> structured tool call -> Pydantic validation
           -> deterministic smart-home simulator -> live GUI update
           -> offline Windows SAPI voice confirmation
```

Qwen is responsible for understanding flexible user language and deciding the intended action. Python is responsible only for validating and safely executing the action. This is an agentic model-and-tool loop, not keyword-only command handling.

## Implementation status

| Guideline area | Implementation in Hachi | Status |
|---|---|---|
| Offline STT | Reuse `hachi_whisper.py` and the existing browser microphone pipeline | Runtime installed; `small` model cached locally |
| Local intent extraction | Ollama with `qwen3.5:2b` as the new default | Configured; model download still required |
| Structured actions | Qwen-visible `control_smart_home` action envelope | Implemented |
| Validation | Pydantic models with allow-listed actions, targets, and temperature limits | Implemented |
| Home simulation | Thread-safe lights, thermostat, lock, and entertainment state in `hachi_home.py` | Implemented |
| Live GUI | Separate animated Smart Home PyWebView simulation window | Implemented |
| Execution evidence | JSON-lines `assistant_execution.log` containing transcript, actions, state, verification, and timing | Implemented |
| Offline TTS | Existing Windows SAPI path; Edge TTS skipped when `offline_tts_only` is enabled | Configured |
| Cloud removal | DeepSeek remains dormant for compatibility but `use_deepseek` is disabled | Configured |
| Automated verification | State-machine tests plus app integration and offline rehearsal | Automated suite and separate-window smoke test required after each change |

## Smart-home capability

The initial demo state is deliberately predictable:

```json
{
  "living_room_light": {"on": false},
  "kitchen_light": {"on": true},
  "living_room_thermostat": {"temperature_c": 20},
  "front_door_lock": {"locked": false},
  "entertainment": {"status": "stopped", "title": ""}
}
```

| Device | Actions |
|---|---|
| Living-room and kitchen lights | `turn_on`, `turn_off` |
| Living-room thermostat | `set_temperature`, `increase_temperature`, `decrease_temperature` |
| Front-door lock | `lock`, `unlock` |
| Entertainment | `play_media`, `pause_media`, `stop_media` |

Thermostat results are restricted to 16–30 °C. A command may contain up to six actions. The whole command is validated before state is committed, so an invalid later action cannot leave an earlier action partially applied.

Manual simulator buttons and Qwen both use the same validated state machine. This lets the pair test the GUI without the model while still proving that AI-generated actions use the identical execution path.

## How flexible language works without training

For a smart-home request from either Hachi or the simulator window, focused local Qwen receives only:

- The current home state.
- The two home capabilities.
- The user’s current request and short conversation context.
- Instructions to infer needs, call tools, verify results, and clarify genuine ambiguity.

Examples Qwen should interpret:

- “It is getting dark in here” -> turn on the living-room light.
- “I am freezing” -> raise the thermostat by a reasonable small amount.
- “I’m going to bed” plus a security request -> lock the front door and turn off requested lights.
- “Set it to 24 and play study music” -> set the thermostat and start entertainment in one turn.

The phrases above are evaluation examples, not hard-coded command templates. A small deterministic detector only decides when to route a request to the focused home interpreter; Qwen decides which device actions satisfy the request.

## GUI demonstration

The normal Hachi interface contains no Smart Home button or embedded simulator. When text or voice input is recognized as a smart-home request, Hachi automatically opens a separate native simulation window before Qwen selects an action. Another related request focuses the existing simulator instead of creating duplicates. The simulator shows:

- Two live light cards.
- Current thermostat temperature.
- Locked/unlocked front-door state.
- Entertainment status and title.
- Latest transcript or goal.
- Validated state changes.
- Verification result, engine, execution time, total time, and revision.
- Initial values beside current values so observers can understand every change.
- Manual controls and a reset-to-demo-state button.
- A dedicated local-Qwen command box and clear Ollama/model readiness indicator.
- Animated bulb glow, thermostat movement, lock movement, entertainment equalizer, card confirmation pulse, screen flash, and activity-panel transition.

The normal Hachi chat remains fully usable while the simulator polls shared state in its own window. Smart-home commands typed or spoken in Hachi and commands entered directly in the simulator all use the same focused local-Qwen interpreter and validated actuator. If Ollama is stopped or the configured model is missing, both paths return an explicit setup error instead of silently failing.

## Execution log

Every successful state change records one JSON object in `assistant_execution.log` with timestamp, revision, original transcript, goal, engine, validated actions, state before/after, changes, verification, and timing.

The log is intentionally ignored by Git because it may contain spoken user text. Generate it fresh during the final rehearsal and include it only where the teacher requires it.

## What remains before submission

1. Download `qwen3.5:2b` through Ollama and confirm it loads on the laptop.
2. On another machine, install `requirements.txt`; Pydantic is the only new code dependency and faster-whisper remains the existing offline STT engine.
3. Test the three text commands through the downloaded Qwen model.
4. Test the complete microphone -> local STT -> Qwen -> GUI -> offline TTS loop.
5. Disconnect the internet and repeat the three demo commands.
6. Record response times, resource use, screenshots, and a clean execution log for the pair’s PDF.

## Suggested live demo

Starting state:

```text
Living-room light OFF | Kitchen light ON | Thermostat 20 °C
Front door UNLOCKED | Entertainment STOPPED
```

1. “Hachi, it is getting dark in here and I am freezing.”
   Expected: living-room light on and thermostat raised.
2. “I’m going to sleep. Secure the front door and switch off the kitchen light.”
   Expected: door locked and kitchen light off.
3. “Set the thermostat to 24 degrees and play study music.”
   Expected: thermostat at 24 °C and entertainment playing Study Music.

For each command, point out the transcription, live card changes, validation/verification panel, spoken reply, and new execution-log row.

## Training decision

No model training is required to meet the guideline’s local-LLM intent-extraction objective. The working stock 2B model remains the project fallback while a separate, measurable local training experiment is developed according to `HACHI_LOCAL_MODEL_TRAINING_PLAN.md`. The trained model must outperform the stock baseline before it becomes part of the demonstration.

## Scope postponed until after the exam

- Unvalidated Qwen fine-tuning or LoRA in the critical demo path.
- A separately loaded classifier that increases memory use without beating the 2B baseline.
- Autonomous browser form submission.
- Full long-term memory consolidation.
- Multi-agent orchestration.
- SearXNG hosting.
- Broad student and office workflow expansion.
