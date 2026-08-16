# Hachi Local Model Training Plan

## Decision summary

Hachi now uses the stock Ollama model `qwen3.5:2b` as its default local model. We will measure that baseline before training anything.

If the stock model does not meet the acceptance targets below—or if the class must demonstrate model training—we will fine-tune **one Qwen3.5-0.8B LoRA adapter locally** for smart-home intent and tool selection. We will not train a language model from scratch, automatically train on private conversations, or depend on a paid/cloud notebook.

The trained 0.8B specialist remains experimental until it meets the held-out accuracy targets and improves smart-home latency. Stock Qwen3.5-2B remains Hachi's general/default model and smart-home fallback. Hachi's Pydantic validation and deterministic executor remain mandatory because model training cannot guarantee safe or correct actions.

## Goal

Given natural English, Filipino, or Taglish, the model should choose exactly one of these outcomes:

1. Call `control_smart_home` with one or more valid actions.
2. Call `get_smart_home_state` for a state question.
3. Ask one short clarification when an essential detail is ambiguous.
4. Decline to call a home tool when the request is unrelated or unsafe.

The model is responsible for understanding the need. Application code remains responsible for validation, execution, logging, and verification.

## Why this is the practical training scope

- It is narrow enough to train and evaluate within the project deadline.
- It demonstrates supervised machine learning rather than keyword-only matching.
- The current smart-home tools already provide a stable output contract.
- It does not risk damaging Hachi's general conversation, memory, web, or productivity behavior.
- The same dataset can compare stock 0.8B, locally trained 0.8B, stock 2B, and stock 4B fairly.

## Hardware and free software plan

The development laptop has an RTX 2050 with 4 GB VRAM and approximately 16 GB system RAM. Qwen3.5-2B inference is appropriate for it, but local 2B BF16 LoRA training is not expected to fit reliably: the current published estimate is about 5 GB VRAM before desktop and training overhead. Qwen3.5-0.8B BF16 LoRA is estimated at about 3 GB, making it the only realistic Qwen3.5 LoRA target for this laptop, although the margin remains tight.

Use the following free components:

| Component | Purpose |
|---|---|
| Qwen/Qwen3.5-0.8B-Base | Official small base weights for the local specialist |
| Unsloth local Windows/WSL installation | LoRA supervised fine-tuning and GGUF export |
| RTX 2050 4 GB | Local training GPU; no account, payment, or cloud runtime |
| Ollama | Local deployment and comparison with the stock model |
| Pydantic and pytest | Output validation and repeatable evaluation |
| Git/GitHub | Version the dataset, training configuration, tests, and report—not large model weights |

Training must be performed locally. Before training, close Hachi, Ollama, games, browsers using GPU acceleration, and other GPU-heavy applications. Start with the lowest-memory settings in this plan. If 0.8B still runs out of memory, do not force CPU offloading for the deadline; use the CPU-trained classifier fallback described below and retain stock Qwen3.5-2B for final tool selection.

## Dataset specification

### Target size

Prepare approximately **900 reviewed examples**:

| Category | Target examples |
|---|---:|
| Direct single-device commands | 120 |
| Indirect needs and paraphrases | 160 |
| Multiple actions in one request | 100 |
| State questions | 80 |
| Truly ambiguous requests requiring clarification | 100 |
| Invalid, unsafe, out-of-range, or prompt-injection requests | 100 |
| Unrelated negative examples that must not call a home tool | 120 |
| Filipino and Taglish examples across all categories | 120 |
| **Total** | **900** |

Each action example should be generated under several starting states so the model does not memorize one default house configuration.

### Allowed actions and targets

Use only the contracts already implemented in Hachi:

- Lights: `turn_on`, `turn_off`
- Thermostat: `set_temperature`, `increase_temperature`, `decrease_temperature`
- Front-door lock: `lock`, `unlock`
- Entertainment: `play_media`, `pause_media`, `stop_media`
- State inspection: `get_smart_home_state`

Do not add imaginary rooms, devices, action names, or parameters to the training data.

### Training-record format

Store reviewed source examples as JSONL with these fields:

```json
{
  "id": "indirect_en_001",
  "category": "indirect_multi_action",
  "language": "en",
  "initial_state": {
    "living_room_light": {"on": false},
    "living_room_thermostat": {"temperature_c": 20}
  },
  "user": "It is getting dark and I am freezing.",
  "expected": {
    "tool": "control_smart_home",
    "arguments": {
      "goal": "Make the living room brighter and warmer",
      "actions": [
        {"action": "turn_on", "target": "living_room_light"},
        {"action": "increase_temperature", "target": "living_room_thermostat", "value": 2}
      ]
    }
  }
}
```

The training preparation script must convert this review-friendly record into Qwen's official chat/tool-call template using `tokenizer.apply_chat_template`. Do not teach a second, incompatible action format.

### Data-quality rules

- Every example must be reviewed by one partner and spot-checked by the other.
- Never include API keys, private conversations, names, addresses, or actual user-memory records.
- Split by paraphrase family, not randomly by individual sentence, to prevent near-duplicate leakage.
- Limit mechanical templates to at most 40% of the dataset.
- Include misspellings and natural speech-transcription errors, but keep the expected action unambiguous.
- Include negative pairs such as general questions about light, films, weather temperature, or kitchen recipes.
- Record the reason for every correction made after an evaluation failure.

## Dataset split

- Training: 70% or about 630 examples
- Validation: 15% or about 135 examples
- Held-out test: 15% or about 135 examples

The held-out test file must be frozen before the first training run. Neither partner should move failed test examples into training without creating a new, separately versioned evaluation set.

## Baseline evaluation before training

Run the frozen evaluation set against:

1. Stock `qwen3.5:0.8b` with thinking disabled and only the two home tools exposed.
2. Stock `qwen3.5:2b` using the same prompt, state, tools, and generation settings.
3. Stock `qwen3.5:4b` as the slower quality comparison.

Capture:

- Exact tool-choice accuracy
- Exact action-and-target match
- Temperature-value accuracy
- Multi-action exact-set accuracy
- Clarification accuracy
- False activation rate on unrelated requests
- Invalid-output rejection rate
- Median and 95th-percentile response time
- Number of malformed tool calls

This baseline determines whether fine-tuning is actually necessary and provides evidence for the teacher's comparison.

## Acceptance targets

The trained 0.8B specialist may handle the smart-home path only if it achieves all of the following on the held-out set:

| Metric | Required result |
|---|---:|
| Direct single-action accuracy | At least 95% |
| Indirect-request accuracy | At least 90% |
| Multi-action exact-set accuracy | At least 90% |
| State-question tool accuracy | At least 95% |
| Correct clarification on ambiguous requests | At least 90% |
| False activation on unrelated requests | At most 2% |
| Invalid or unsafe action executed | 0% after validation |
| Malformed tool-call output | At most 1% |
| Median latency | Faster than stock 2B and the current 4B baseline |

If the adapter improves training accuracy but fails these held-out targets, it is overfitting and must not be used in the final demonstration.

## Fine-tuning method

Use supervised fine-tuning with LoRA, not full-parameter training and not reinforcement learning.

Starting configuration for the first local experiment:

| Setting | Initial value |
|---|---|
| Base model | `Qwen/Qwen3.5-0.8B-Base` |
| Training type | Text-only supervised LoRA |
| Maximum sequence length | 256 tokens initially; 512 only if VRAM permits |
| LoRA rank | 8 |
| LoRA alpha | 16 |
| LoRA dropout | 0.05 |
| Batch size | 1 |
| Gradient accumulation | 8 |
| Learning rate | `2e-4` |
| Epochs | 2 initially; maximum 3 |
| Warm-up ratio | 0.05 |
| Evaluation | At least once per epoch |
| Checkpoint selection | Best validation exact-action score |

Treat these as starting values, not guaranteed optimal settings. Stop early if validation loss rises while training loss continues falling.

## Training procedure

1. Freeze and version `train.jsonl`, `validation.jsonl`, and `test.jsonl`.
2. Validate every expected action with Hachi's existing Pydantic models.
3. Run and save the stock 2B and 4B baselines.
4. Install Unsloth in an isolated local Windows/WSL environment and adapt its official Qwen3.5-0.8B notebook/script.
5. Disable vision training and keep the sequence length small.
6. Load the reviewed training and validation splits.
7. Train LoRA for two epochs and save metrics and the best checkpoint.
8. Evaluate the untouched test split with deterministic decoding.
9. If needed, correct the dataset—not the test answers—and run one controlled retraining experiment.
10. Merge/export the selected adapter to GGUF and create an Ollama model such as `hachi-home-qwen3.5:0.8b`.
11. Run the same Hachi integration tests against stock and trained models.
12. Promote the trained model only when it meets every acceptance target.

## Ollama integration and rollback

Keep these two model choices available:

- General/default fallback: `qwen3.5:2b`
- Experimental local smart-home specialist: `hachi-home-qwen3.5:0.8b`

The specialist name should be configurable rather than hard-coded. Load it only for smart-home requests; do not try to keep the 0.8B specialist and 2B general model fully resident in 4 GB VRAM simultaneously. If the specialist is missing, slow, or fails evaluation, Hachi must automatically continue with stock `qwen3.5:2b`.

## Local fallback if 0.8B LoRA does not fit

Train a compact supervised intent router on CPU using TF-IDF features and logistic regression or a similarly lightweight open-source classifier. It should predict only:

- `smart_home_control`
- `smart_home_state_question`
- `needs_clarification`
- `not_smart_home`

This classifier can be trained in seconds or minutes and provides a genuine rule-versus-machine-learning comparison for the report. It must not execute devices or invent parameters. After it routes a smart-home request, stock Qwen3.5-2B still selects the structured tool actions, which Pydantic validates before execution.

This is the deadline-safe fallback, not a claim that the classifier itself is a complete agent.

Do not commit GGUF files, merged weights, Ollama blobs, or model caches to Git. Commit only:

- Dataset source and split manifests
- Dataset validation script
- Training configuration and notebook link
- Evaluation runner and expected-result files
- Aggregate metrics and failure analysis
- Model checksum and exact export instructions

## Five-day schedule

### Day 1 — Baseline and schema

- Confirm stock 2B inference and record latency.
- Freeze the two smart-home tool schemas.
- Build the dataset validator and evaluation runner.
- Write the first 200 reviewed examples.

### Day 2 — Dataset completion

- Complete approximately 900 examples.
- Validate all actions automatically.
- Deduplicate and split by paraphrase family.
- Freeze the held-out test set.
- Run stock 2B and 4B baselines.

### Day 3 — First training run

- Install and verify the isolated local Unsloth environment.
- Close Ollama and other GPU-heavy applications.
- Run the local Qwen3.5-0.8B LoRA experiment.
- Save training and validation curves.
- Export the best checkpoint.
- Run the frozen evaluation suite.

### Day 4 — One improvement cycle

- Categorize failures: wrong tool, missing action, wrong value, false activation, malformed output, or unnecessary clarification.
- Correct gaps in training data without editing the frozen test answers.
- Perform at most one planned retraining run.
- Export and integrate the best model.

### Day 5 — Freeze and rehearse

- Run the complete application and model evaluation suites.
- Compare stock 0.8B, locally trained 0.8B, stock 2B, and stock 4B in one results table.
- Freeze configuration and model checksum.
- Rehearse direct, indirect, multi-action, ambiguous, Filipino/Taglish, and rejected-command demonstrations.
- Keep stock 2B ready as the immediate rollback.

## Partner responsibilities

### Partner A — Data and evaluation

- Own the dataset schema, review process, splitting, and validation.
- Maintain the frozen test set and failure-analysis table.
- Prepare the teacher-facing accuracy and latency comparison.

### Partner B — Training and deployment

- Own the isolated local Unsloth environment, LoRA configuration, checkpoints, and metrics.
- Export the chosen checkpoint to GGUF/Ollama.
- Document the model checksum and reproduction steps.

Both partners must review at least 20% of the other partner's labeled examples and sign off before training.

## Expected time

- Dataset and evaluation preparation: 4–10 hours
- First local 0.8B LoRA run: approximately 2–6 hours after setup
- Export and Ollama packaging: 1–2 hours
- Evaluation and one correction cycle: 6–12 hours
- Local environment setup and troubleshooting: 2–6 hours
- Realistic end-to-end effort: 2–3 working days

VRAM limits, Windows/CUDA setup, model download, laptop cooling, and evaluation—not just the training loop—are the main schedule risks. Training-time estimates are planning ranges and must be replaced with measured times from the first run.

## Final demonstration evidence

Prepare one table containing:

| Model | Direct accuracy | Indirect accuracy | Multi-action accuracy | False activation | Median latency | P95 latency |
|---|---:|---:|---:|---:|---:|---:|
| Stock Qwen3.5-0.8B | TBD | TBD | TBD | TBD | TBD | TBD |
| Locally trained Qwen3.5-0.8B LoRA | TBD | TBD | TBD | TBD | TBD | TBD |
| Stock Qwen3.5-2B | TBD | TBD | TBD | TBD | TBD | TBD |
| Stock Qwen3.5-4B | TBD | TBD | TBD | TBD | TBD | TBD |

Show at least one success and one safe rejection. Explain that Qwen interprets the request, while the validated tool layer guarantees that only supported simulated actions can execute.

## Go/no-go rule

Proceed with local training only after the baseline dataset and evaluator work. Use the trained 0.8B specialist in the final demo only if it passes every acceptance target. If it does not fit or does not pass, use the small CPU classifier experiment for the machine-learning comparison, demonstrate stock 2B for tool selection, and keep the validated simulator working reliably.

## Official references

- Qwen3.5-2B model and evaluation card: https://huggingface.co/Qwen/Qwen3.5-2B
- Qwen3.5-0.8B Base model for local fine-tuning: https://huggingface.co/Qwen/Qwen3.5-0.8B-Base
- Ollama Qwen3.5 model tags and quantizations: https://ollama.com/library/qwen3.5/tags
- Unsloth Qwen3.5 fine-tuning guide and VRAM estimates: https://unsloth.ai/docs/models/qwen3.5/fine-tune
- Unsloth local Windows installation guide: https://unsloth.ai/docs/get-started/install-and-update/windows-installation
