"""Continue the registered Hachi GGUF on one Kaggle GPU with full-state recovery."""
from __future__ import annotations

import argparse
import importlib.metadata
import json
import math
import os
import platform
from pathlib import Path
import shutil
import signal
import sys
import time
import traceback

from recovery import atomic_json, checkpoint_step, digest, latest_complete, publish_recovery, restore_checkpoint, validate_recovery
from tokenization import training_examples, verify_gguf_vocabulary


def read_jsonl(path):
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def verify_package(package):
    manifest = json.loads((package / "package-manifest.json").read_text())
    if manifest["schema"] != "hachi-conversation-package-v1":
        raise ValueError("Wrong input package")
    for name, expected in manifest["files"].items():
        p = (package / name).resolve()
        if not p.is_relative_to(package.resolve()) or not p.is_file() or digest(p) != expected:
            raise ValueError("Input checksum mismatch: " + name)
    return manifest


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--package", type=Path, required=True)
    p.add_argument("--source", type=Path, required=True)
    p.add_argument("--run", type=Path, required=True)
    p.add_argument("--resume", type=Path)
    p.add_argument("--pilot-steps", type=int, default=2, help="Pause after this many NEW steps; 0 removes the pilot cap")
    p.add_argument("--deadline", type=float, required=True, help="Unix deadline including notebook setup")
    p.add_argument("--reserve-minutes", type=float, default=20)
    args = p.parse_args()
    if args.pilot_steps < 0 or args.reserve_minutes < 1:
        p.error("Invalid session limits")
    package, run = args.package.resolve(), args.run.resolve()
    verify_package(package)
    config = json.loads((package / "training_config.json").read_text())
    source_info = json.loads((package / "source_model.json").read_text())
    if digest(args.source) != source_info["sha256"]:
        raise ValueError("Wrong source weights: attach the exact registered Hachi GGUF")
    if run.exists() and any(run.iterdir()):
        raise ValueError("Run folder already contains files; use a fresh Kaggle session to avoid overwriting progress")
    if time.time() + args.reserve_minutes * 60 >= args.deadline:
        raise RuntimeError("Not enough session budget remains for training setup")
    run.mkdir(parents=True, exist_ok=True)
    shutil.copytree(package, run / "package", ignore=shutil.ignore_patterns("__pycache__"))
    recovery_zip = run.parent / "hachi-conversation-v1-recovery.zip"
    previous = validate_recovery(args.resume) if args.resume else None

    os.environ["CUDA_VISIBLE_DEVICES"] = "0"
    import torch
    from datasets import Dataset
    from huggingface_hub import HfApi
    from peft import LoraConfig, TaskType, get_peft_model
    from transformers import AutoModelForCausalLM, AutoTokenizer, GgufConfig, Trainer, TrainerCallback, TrainingArguments, set_seed
    if not torch.cuda.is_available():
        raise RuntimeError("Run this training on a Kaggle GPU; local CPU training is disabled")
    versions = {name: importlib.metadata.version(name) for name in
                ("torch", "transformers", "peft", "accelerate", "datasets", "gguf", "tokenizers", "safetensors", "huggingface-hub", "numpy", "sentencepiece", "protobuf")}
    if versions["transformers"] != config["transformers_version"]:
        raise ValueError("Use the package's pinned API version of Transformers")
    revision = previous["identity"]["tokenizer_revision"] if previous else HfApi().model_info(source_info["tokenizer_repo"]).sha
    identity = {"schema": "hachi-conversation-run-v1", "source_sha256": source_info["sha256"],
                "package_sha256": digest(package / "package-manifest.json"),
                "config": config, "tokenizer_revision": revision, "versions": versions,
                "runtime": {"python": platform.python_version(), "cuda": torch.version.cuda,
                            "gpu": torch.cuda.get_device_name(0)}}
    if previous and previous["identity"] != identity:
        raise ValueError("Configuration/data/source/tokenizer/dependency mismatch; refusing non-equivalent resume")
    atomic_json(run / "run-identity.json", identity)
    (run / "requirements.lock.txt").write_text("\n".join(f"{n}=={v}" for n, v in versions.items()) + "\n")
    checkpoint = restore_checkpoint(args.resume, run, identity) if args.resume else None
    if checkpoint:
        publish_recovery(checkpoint, run, recovery_zip)
        print(f"RESUME CHECK: continuing after optimizer step {checkpoint_step(checkpoint)}", flush=True)
    set_seed(config["seed"])
    tokenizer = AutoTokenizer.from_pretrained(source_info["tokenizer_repo"], revision=revision, use_fast=True)
    if not tokenizer.is_fast:
        raise RuntimeError("A fast tokenizer with offset mappings is required for assistant-only labels")
    verify_gguf_vocabulary(args.source, tokenizer)
    tokenizer.padding_side = "right"
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token = tokenizer.eos_token

    train_rows, val_rows = read_jsonl(package / "data/train.jsonl"), read_jsonl(package / "data/validation.jsonl")
    train_data = [e for r in train_rows for e in training_examples(r, tokenizer, config["max_sequence_length"])]
    val_data = [e for r in val_rows for e in training_examples(r, tokenizer, config["max_sequence_length"])]
    print(f"TOKENIZATION OK: {len(train_data)} train targets; longest={max(len(x['input_ids']) for x in train_data)}", flush=True)
    print("Loading the existing Hachi GGUF. This dequantization path requires the cloud smoke test.", flush=True)
    # No stock-model fallback: every loaded weight must originate in this GGUF.
    model, loading = AutoModelForCausalLM.from_pretrained(str(args.source.parent), gguf_file=args.source.name,
             quantization_config=GgufConfig(dequantize=True), output_loading_info=True,
             dtype=torch.float16, attn_implementation="eager")
    if any(loading.get(key) for key in ("missing_keys", "unexpected_keys", "mismatched_keys", "error_msgs")):
        raise ValueError("Incomplete source weight mapping; refusing partial/random weights: " + str(loading))
    if "qwen3_5" not in model.config.model_type:
        raise ValueError("Loaded architecture is not Qwen3.5")
    if len(tokenizer) > model.get_input_embeddings().num_embeddings:
        raise ValueError("Tokenizer vocabulary does not fit the source model")
    model.config.use_cache = False
    model = get_peft_model(model, LoraConfig(task_type=TaskType.CAUSAL_LM, r=config["lora_rank"],
        lora_alpha=config["lora_alpha"], lora_dropout=config["lora_dropout"],
        target_modules=config["target_modules"], bias="none"))
    model.enable_input_require_grads()
    model.print_trainable_parameters()

    def collate(features):
        length = max(len(f["input_ids"]) for f in features)
        return {key: torch.tensor([f[key] + [fill] * (length - len(f[key])) for f in features], dtype=torch.long)
                for key, fill in (("input_ids", tokenizer.pad_token_id), ("attention_mask", 0), ("labels", -100))}

    start_step = checkpoint_step(checkpoint) if checkpoint else 0
    stop_requested = {"value": False}
    def request_stop(_signum, _frame):
        stop_requested["value"] = True
        print("Stop requested; saving at the next completed optimizer step.", flush=True)
    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)

    class SaveAndPause(TrainerCallback):
        def on_log(self, arguments, state, control, logs=None, **kwargs):
            for name in ("loss", "grad_norm", "eval_loss"):
                if name in (logs or {}) and not math.isfinite(float(logs[name])):
                    raise RuntimeError("Non-finite " + name + "; keep the last complete checkpoint")
            return control

        def on_step_end(self, arguments, state, control, **kwargs):
            pilot_done = args.pilot_steps and state.global_step - start_step >= args.pilot_steps
            budget_done = time.time() + args.reserve_minutes * 60 >= args.deadline
            if pilot_done or budget_done or stop_requested["value"]:
                control.should_save = True
                control.should_training_stop = True
            # Always save at the final step even if it isn't a save_steps multiple.
            if state.global_step >= state.max_steps:
                control.should_save = True
            return control

        def on_save(self, arguments, state, control, **kwargs):
            current = run / f"checkpoint-{state.global_step}"
            atomic_json(run / "run-summary.json", {"status": "checkpointed", "step": state.global_step,
                "target_steps": state.max_steps, "source_sha256": identity["source_sha256"]})
            publish_recovery(current, run, recovery_zip)
            return control

    # Total schedule never changes between pilot and resume sessions.
    total_steps = math.ceil(len(train_data) / (config["batch_size"] * config["gradient_accumulation_steps"])) * config["epochs"]
    if start_step >= total_steps:
        raise ValueError("Training schedule already complete; use EXPORT_ONLY=True")
    arguments = TrainingArguments(output_dir=str(run), max_steps=total_steps,
        per_device_train_batch_size=config["batch_size"], per_device_eval_batch_size=1,
        gradient_accumulation_steps=config["gradient_accumulation_steps"],
        learning_rate=config["learning_rate"], warmup_steps=config["warmup_steps"],
        lr_scheduler_type="linear", weight_decay=0.01, optim="adamw_torch",
        fp16=True, bf16=False, gradient_checkpointing=True,
        gradient_checkpointing_kwargs={"use_reentrant": False},
        save_strategy="steps", save_steps=config["save_steps"], save_total_limit=2, save_only_model=False,
        eval_strategy="no", logging_steps=1, logging_nan_inf_filter=False,
        report_to="none", seed=config["seed"], data_seed=config["seed"],
        max_grad_norm=config["max_grad_norm"], dataloader_num_workers=0, ignore_data_skip=False,
        load_best_model_at_end=False, remove_unused_columns=False)
    trainer = Trainer(model=model, args=arguments, train_dataset=Dataset.from_list(train_data),
        eval_dataset=Dataset.from_list(val_data), data_collator=collate, processing_class=tokenizer,
        callbacks=[SaveAndPause()])
    try:
        if not checkpoint:
            baseline = trainer.evaluate()
            atomic_json(run / "baseline.json", baseline)
        elif (args.resume / "baseline.json").is_file():
            shutil.copyfile(args.resume / "baseline.json", run / "baseline.json")
        if time.time() + args.reserve_minutes * 60 >= args.deadline:
            raise RuntimeError("Budget exhausted during setup; no new optimizer steps started")
        trainer.train(resume_from_checkpoint=str(checkpoint) if checkpoint else None)
        done = trainer.state.global_step >= total_steps
        status = "training_complete" if done else "paused"
        summary = {"status": status, "step": trainer.state.global_step, "target_steps": total_steps,
                   "source_sha256": identity["source_sha256"], "checkpoint_complete": True,
                   "promotion": "not_evaluated_for_deployment"}
        atomic_json(run / "run-summary.json", summary)
        complete = latest_complete(run)
        if complete is None:
            raise RuntimeError("Trainer returned without a complete recoverable checkpoint")
        publish_recovery(complete, run, recovery_zip)
        if done:
            # Save deployable weights separately from the resumable optimizer state.
            trainer.save_model(str(run / "final_adapter"))
            tokenizer.save_pretrained(run / "final_adapter")
            summary["validation"] = trainer.evaluate()
            atomic_json(run / "run-summary.json", summary)
            publish_recovery(complete, run, recovery_zip)
            print("TRAINING COMPLETE. Full checkpoint and final adapter saved; run export cell next.", flush=True)
        else:
            print("PAUSED. Download recovery ZIP; resume with the same source weights and package.", flush=True)
    except BaseException as exc:
        complete = latest_complete(run)
        atomic_json(run / "run-summary.json", {"status": "failed", "error": str(exc),
            "target_steps": total_steps,
            "last_complete_step": checkpoint_step(complete) if complete else 0,
            "note": "Only the last complete checkpoint is resumable; unfinished updates are discarded."})
        if complete:
            publish_recovery(complete, run, recovery_zip)
        raise


if __name__ == "__main__":
    try:
        main()
    except BaseException:
        traceback.print_exc()
        sys.exit(1)
