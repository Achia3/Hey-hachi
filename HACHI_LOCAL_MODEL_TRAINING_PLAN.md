# Hachi Local Model Training Plan

## Decision summary

Hachi now uses the stock Ollama model `qwen3.5:2b` as its default local model. We will measure that baseline before training anything.

If the stock model does not meet the acceptance targets below—or if the class must demonstrate model training—we will fine-tune **one Qwen3.5-0.8B LoRA adapter on a private free Kaggle GPU notebook** for smart-home intent and tool selection. We will not train a language model from scratch, automatically train on private conversations, use either laptop for sustained LLM training, or depend on paid compute.

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

Both development laptops have only 4 GB VRAM. They are suitable for quantized inference but must not be used for sustained LLM training because of memory and thermal risk. The verified private Kaggle notebook provides two Tesla T4 GPUs with 15 GB VRAM each. This experiment deliberately uses only one T4; Qwen3.5-0.8B BF16/FP16 LoRA is estimated at about 3 GB VRAM.

Use the following free components:

| Component | Purpose |
|---|---|
| Qwen/Qwen3.5-0.8B-Base | Official small base weights for the local specialist |
| Unsloth in a private Kaggle notebook | LoRA supervised fine-tuning and GGUF export |
| One Kaggle Tesla T4 15 GB | Free training GPU; no credit card or local thermal load |
| Ollama | Local deployment and comparison with the stock model |
| Pydantic and pytest | Output validation and repeatable evaluation |
| Git/GitHub | Version the dataset, training configuration, tests, and report—not large model weights |

Training must be performed in the private Kaggle notebook, not on either laptop GPU. Upload only the training package—never Hachi's database, conversations, `.env`, or secrets. Start with the two-step smoke run, then restart the Kaggle session and perform the full run. Stop the Kaggle session immediately after downloading outputs. If the notebook still fails, do not use local CPU/GPU offloading for the deadline; use the CPU-trained classifier fallback described below and retain stock Qwen3.5-2B for final tool selection.

## Dataset specification

### Target size

The first experiment uses **300 schema-validated draft examples**. Human language review remains required before claiming the dataset is reviewed:

| Category | Target examples |
|---|---:|
| Direct single-device commands | 95 |
| Indirect needs and paraphrases | 35 |
| Multiple actions in one request | 35 |
| State questions | 30 |
| Truly ambiguous requests requiring clarification | 35 |
| Invalid, unsafe, out-of-range, or prompt-injection requests | 30 |
| Unrelated negative examples that must not call a home tool | 40 |
| **Total** | **300** |

English, Filipino, and Taglish examples appear across every split. The generated package contains 180 English, 60 Filipino, and 60 Taglish records.

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

- Training: 70% or 210 examples
- Validation: 15% or 45 examples
- Held-out test: 15% or 45 examples

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
| Median latency | Faster than stock 2B |

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
3. Run and save the stock 0.8B and 2B baselines; treat 4B as an optional comparison only.
4. Import `training/hachi_qwen35_08b_kaggle.ipynb` into a private Kaggle notebook and attach `training/hachi-smart-home-data.zip`.
5. Disable vision training and keep the sequence length small.
6. Load the reviewed training and validation splits.
7. Run the two-step smoke test first. After it succeeds, restart the session and train LoRA for two epochs.
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
- Review the first 100 schema-validated draft examples.

### Day 2 — Dataset completion

- Complete human review of the 300-example dataset.
- Validate all actions automatically.
- Deduplicate and split by paraphrase family.
- Freeze the held-out test set.
- Run stock 0.8B and 2B baselines.

### Day 3 — First training run

- Import and verify the private Kaggle/Unsloth notebook.
- Run the two-step T4 smoke test and inspect peak memory.
- Restart the Kaggle session and run the full Qwen3.5-0.8B LoRA experiment.
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

- Own the private Kaggle/Unsloth notebook, LoRA configuration, checkpoints, and metrics.
- Export the chosen checkpoint to GGUF/Ollama.
- Document the model checksum and reproduction steps.

Both partners must review at least 20% of the other partner's labeled examples and sign off before training.

## Expected time

- Dataset language review and evaluation preparation: 3–8 hours
- First Kaggle 0.8B LoRA run: approximately 1–3 hours after setup, including kernel compilation
- Export and Ollama packaging: 1–2 hours
- Evaluation and one correction cycle: 6–12 hours
- Kaggle environment setup and troubleshooting: 1–3 hours
- Realistic end-to-end effort: 1–2 working days

Kaggle availability, package compatibility, model download, kernel compilation, and evaluation—not just the training loop—are the main schedule risks. Training-time estimates are planning ranges and must be replaced with measured times from the first run. Neither laptop should perform sustained LLM training.

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

Proceed with Kaggle training only after the baseline dataset and evaluator work. Use the trained 0.8B specialist in the final demo only if it passes every acceptance target. If it does not run or does not pass, use the small CPU classifier experiment for the machine-learning comparison, demonstrate stock 2B for tool selection, and keep the validated simulator working reliably.

## Official references

- Qwen3.5-2B model and evaluation card: https://huggingface.co/Qwen/Qwen3.5-2B
- Qwen3.5-0.8B Base model for local fine-tuning: https://huggingface.co/Qwen/Qwen3.5-0.8B-Base
- Ollama Qwen3.5 model tags and quantizations: https://ollama.com/library/qwen3.5/tags
- Unsloth Qwen3.5 fine-tuning guide and VRAM estimates: https://unsloth.ai/docs/models/qwen3.5/fine-tune
- Unsloth local Windows installation guide: https://unsloth.ai/docs/get-started/install-and-update/windows-installation
- Kaggle free-GPU usage guidance: https://www.kaggle.com/docs/efficient-gpu-usage
