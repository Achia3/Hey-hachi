# Continue Hachi's conversation training

This package prepares a small, conservative conversation fine-tune on your **current registered `hachi-master:latest` model**. It is ready for a Kaggle pilot; GPU training, numerical resume equivalence and final GGUF conversion have not been run or verified here. It does not claim the model has already improved.

## What is included

- **161 authored synthetic conversation records** in English, Filipino and Taglish: correct attribution to **Axeil Escabal and Beomarc Cartoneros**, short everyday replies, context and corrections, appropriate uncertainty, and detailed teaching when requested.
- **53 existing tool-call records** for rehearsal, filtered against the current tool schemas. Rehearsal reduces the risk of forgetting tool use; it cannot guarantee retention.
- Family-separated splits: **159 training records** (106 conversations + 53 tool records), **24 validation**, **31 test**. Translations and lesson variants stay in the same split. There are **332 assistant targets** across all three splits.
- The original **550-record Master V2 test** is copied unchanged as `data/legacy_test.jsonl` for regression checking. Its historical template overlap means it is not independent evidence of generalization.
- A Kaggle notebook, trainer, GGUF export script, and full-state recovery ZIP handling.

These are synthetic training drafts, not scraped private conversations. Creator spelling is user-confirmed. The dataset manifest marks human language review as incomplete. Inspect `seeds.py` and the JSONL files before a serious run; this small set is an initial style-tuning experiment, not broad new knowledge training.

## Files to upload

Import `hachi_conversation_v1_kaggle.ipynb` into a Kaggle notebook. Make a **private** input dataset with these two files from `input/` and attach it:

1. `hachi-conversation-v1-input.zip` — code, dataset, hashes and configuration.
2. `hachi-master-current.gguf` — approximately 2.08 GB, copied from the model actually registered in Ollama.

Kaggle may expand the ZIP automatically; the notebook also recognizes an extracted package. The original project export at `gguf/v5/Qwen3.5-2B.Q4_K_M.gguf` has a different checksum, so it is deliberately not used here. Keep the original upload available for every resume.

Expected original model SHA-256:

`f5f5293ccae2b0b10da72cddd04cb9859080003a5c9b57f5549bfc983d5d2d4e`

The training process explicitly dequantizes those GGUF weights into a dense FP16 model, then trains a new LoRA adapter. Dequantization cannot restore information already lost during the original quantization. It never downloads a stock base-model weight checkpoint as a fallback. It downloads Qwen's tokenizer at a recorded revision and checks for incomplete weight mapping. An original full-precision Hachi checkpoint would be preferable if you recover one later; that would require a separately configured run.

## First: two-step pilot

1. Select a Kaggle GPU and enable Internet. The trainer uses **one GPU**, including when the accelerator exposes two. Use the same GPU type and runtime when resuming.
2. Leave the first settings cell at `START_NEW_RUN=True`, `PILOT_STEPS=2`, `SESSION_HOURS=8`. This sets a budget, not an assumed Kaggle quota; reduce it if your session has less available time.
3. Use **Save Version → Save & Run All**. Let the notebook finish and inspect its output.
4. A successful pilot shows `TOKENIZATION OK`, trainable LoRA parameters, finite training loss, `BACKUP READY`, and `run-summary.json` with `status: paused`, `step: 2`.
5. Download `hachi-conversation-v1-recovery.zip` from saved output. Check `hachi-session-status.json` too: `failed` means inspect the error even if the notebook version is green.

If GGUF loading, CUDA memory, dependency installation or model training fails, preserve the error and any recovery file. An error before the first completed checkpoint cannot produce a resumable training backup. There is no automatic substitution with stock Qwen. The modest dataset and two-step default avoid spending a full session before compatibility is known.

## Resume from the downloaded backup

1. Start a **fresh** notebook session using the same notebook. Attach the downloaded recovery ZIP and the **same original `hachi-master-current.gguf`**.
2. Set `START_NEW_RUN=False`. The original small input ZIP is optional because recovery contains the frozen package and dataset.
3. Leave `PILOT_STEPS=2` for one resume test. Logs should show `RESUME CHECK: continuing after optimizer step 2`, then a new recovery at step 4. Verify that the learning-rate schedule continues rather than restarts.
4. For the full remainder, start fresh again with the newest backup, set `START_NEW_RUN=False` and `PILOT_STEPS=0`.
5. If multiple backups are attached, put the exact desired ZIP or extracted directory in `RESUME_FROM`. Never select a checkpoint based solely on a large filename number; the notebook validates its contents.

Pilot and full runs use the **same total optimizer-step schedule**. The pilot only pauses it. Resume restores adapter parameters, optimizer, scheduler, FP16 scaler, RNG and Trainer step/data position; it also requires matching data/configuration, source checksum, tokenizer revision, recorded package versions, Python/CUDA and GPU type. Floating-point nondeterminism can still prevent bit-for-bit equivalence.

The recipe uses rank-16 LoRA, learning rate `2e-5`, two scheduled epochs, batch size 1, accumulation 8, and a 3,072-token limit. Assistant-only loss masks the system and user text. All 214 records were checked with the actual Qwen tokenizer; the longest example was 2,300 tokens. Oversized examples cause an error instead of silently losing their answers.

## What autosave can recover

Every **5 completed optimizer steps**, at a pilot pause and at training completion, the notebook writes a full checkpoint and publishes a checksummed recovery ZIP. It keeps the previous published ZIP separately. Training also requests a save when 20 minutes remain in the configured session budget. A catchable error republishes the last complete checkpoint. An incomplete newer checkpoint is ignored.

The ZIP includes the adapter, optimizer, scheduler, scaler, random states, Trainer state, frozen dataset/code, identity, dependency lock and available run summaries. It **does not include the 2.08 GB original model**; reattach that file when resuming.

An atomic ZIP write protects the last published archive from an interrupted replacement. It does **not** make Kaggle's temporary filesystem permanent. A forced shutdown, GPU reset or kernel kill can lose work since the last checkpoint, and can lose every local file if no saved output or download survives. Download successful saved output before ending the session. No external automatic backup service or scheduled restart is configured.

## Download the trained result

After the full schedule finishes, `EXPORT_RESULT=True` merges the adapter onto the same original Hachi weights and converts a new Q4_K_M GGUF using a pinned llama.cpp revision. Download `hachi-conversation-v1-result.zip` **and** the recovery ZIP.

If export fails or runs out of time, resume the completed recovery in a fresh session. The notebook detects a completed schedule and goes straight to export. You can also set `START_NEW_RUN=False`, `EXPORT_ONLY=True`. It refuses to export an unfinished schedule.

Extract the result ZIP and run these commands from its folder:

```powershell
ollama create hachi-conversation-v1 -f Modelfile
ollama run hachi-conversation-v1 --think=false
```

If Ollama is not on PATH, use `C:\Users\Beo\AppData\Local\Programs\Ollama\ollama.exe` instead. The new name keeps your existing `hachi-master` available for comparison.

**Disable thinking at inference too.** Training on concise answers alone cannot guarantee that every external client disables the model's thinking mode. Use `think: false` in Ollama API requests; hiding thinking text only hides its display. The included Modelfile uses a 768-token default answer budget. For a longer lesson, request `options: {"num_predict": 2048}` while keeping `think: false`.

Example API body:

```json
{"model":"hachi-conversation-v1","messages":[{"role":"user","content":"Teach me recursion with examples."}],"think":false,"options":{"num_predict":2048},"stream":false}
```

## Decide whether the candidate is better

Compare the original and candidate with identical prompts, hardware, context, thinking setting and generation budget. Review every conversation in `data/test.jsonl`, including follow-up turns. Compare correct attribution, directness, appropriate answer length, factual accuracy, natural Filipino/Taglish and whether it follows corrections. A short answer must still answer the question; a teaching answer must still explain enough.

Measure first visible answer latency, answer token count, thinking tokens/text and answers that hit their token limit. Keep model-load time separate from warm response latency. Test both ordinary Ollama chat and Hachi's app tool flow. Use the existing `hachi_evaluation.py` strict scorer on generated legacy tool outputs; it does not execute tools. Check regressions before changing the app's model name. Lower validation loss or a successful export alone does not establish better conversations or faster responses.

## Rebuild locally

From the Hachi app directory:

```powershell
.\.venv\Scripts\python.exe training_conversation_v1/make_notebook.py
.\.venv\Scripts\python.exe training_conversation_v1/build_package.py
```

The builder reads the existing Master V2 source data and current Ollama model manifest. Rebuilding after editing data/configuration produces a new package identity: start a new training run instead of mixing it with an old recovery. Preserve the frozen package inside an existing recovery when continuing that run.

Local verification covers split isolation, creator spelling, replay targets, actual-template token masking and lengths, ZIP checksums, incomplete/corrupt checkpoints, path validation, previous-backup retention, failed writes and compiled notebook cells. It does not execute GPU training or assert numerical checkpoint equivalence.

## API references checked while preparing this package

- [Transformers GGUF loading and dequantization](https://huggingface.co/docs/transformers/main/quantization/gguf).
- [Trainer checkpoint/resume arguments](https://huggingface.co/docs/transformers/en/main_classes/trainer).
- [Qwen3.5's chat template](https://huggingface.co/Qwen/Qwen3.5-2B/blob/main/chat_template.jinja).
- [Ollama thinking controls](https://docs.ollama.com/capabilities/thinking).
- [Pinned llama.cpp converter](https://github.com/ggml-org/llama.cpp/blob/311d4211bf1611ff7ca6b67035a4a07c79766efc/convert_hf_to_gguf.py).
