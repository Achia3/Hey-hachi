# Hachi Master V2 — Installation and Evaluation Guide

Hachi Master V2 is a Qwen3.5-2B LoRA model exported as Q4_K_M GGUF and configured in Hachi as `hachi-master`. The model selects tools; Python handlers perform the actions.

## What the saved benchmark establishes

The historical training-notebook evaluator reported 548/550 correct (99.64%), versus 354/550 (64.36%) for the base model. That evaluator counted any response with no recognized tool call as a correct conversational answer. It did not execute desktop tools, assess answer quality, or measure laptop inference.

The strict offline rescore of the saved post-training outputs reports:

| Measurement | Result |
|---|---:|
| Correct tool name and arguments | 493/495 (99.60%) |
| Conversational/refusal records with no tool call | 55/55 |
| Conversational answer quality | Not scored; human review required |
| End-to-end application task completion | Not measured by this benchmark |
| Local GGUF/Ollama latency | Not measured by this benchmark |

The two tool-call mismatches concern the exact content of Filipino note requests. The recorded 4.02 seconds per record is an average from the training environment, not a desktop latency promise. Original baseline raw outputs are absent from the historical result file, so the baseline has not been rescored.

Source artifacts: `gguf/v5/evaluation_results_master_v2.json`, `training_master_v2/evaluation_strict_v1.json`, and the versioned scorer `hachi_evaluation.py`. Preserve the historical result file.

The dataset manifest lists 3,675 examples: 2,575 training, 550 validation, and 550 test. It still marks review as required. These results do not establish broad generalization, zero hallucinations, or complete support for every advertised capability.

## Runtime capabilities and limits

The router now exposes the consolidated tools used in training: smart home, apps, modes, routines, media, productivity, web research, weather, and system utilities. Additional browser/document tools remain available for those workflows. Legacy tool names remain internal compatibility paths.

Todo completion updates SQLite, reads the result back, and requires a specific ID when titles are ambiguous. Unsupported actions return an explicit failure instead of a success message. Absolute volume setting, brightness adjustment, PC locking, deletion of productivity items, and live mode status are not implemented in the consolidated handlers. Training examples that assume these features should be reviewed before another training run.

## Install the model

From the application folder containing `hachi_agent.py`, provide these files:

- `gguf/v5/Qwen3.5-2B.Q4_K_M.gguf`
- `gguf/v5/Modelfile`

With Ollama installed and running, register the model:

```powershell
cd gguf/v5
ollama create hachi-master -f Modelfile
ollama list
```

Set `model_name` to `hachi-master` in `config.json`, then launch the application with `run.bat` from the application folder. The current config disables DeepSeek but does not force offline TTS; offline model inference does not mean every optional feature is offline.

## Evaluate future changes

Run the automated suite with the project dependencies installed:

```powershell
python -m pytest -q
```

Rescore saved outputs without executing tools or loading a model:

```powershell
python hachi_evaluation.py gguf/v5/evaluation_results_master_v2.json training_master_v2/evaluation_strict_v1.json
```

When changing the scorer, synchronize the standalone Kaggle notebook and run the scorer tests:

```powershell
python scripts/sync_master_evaluator.py
python -m pytest -q tests/test_model_evaluation.py
```

Re-upload the updated notebook before another Kaggle run. The dataset and weights have not been changed. The notebook now reports tool accuracy separately from no-tool compliance and leaves conversational quality and application task completion unscored.

Before claiming an improved model, evaluate the exported GGUF through Ollama with realistic unseen English, Filipino, and Taglish requests. Measure actual task results, errors, clarification, conversational quality, and median/P95 latency separately from the saved training benchmark.
