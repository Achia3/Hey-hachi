"""Merge the recovered adapter onto the same Hachi GGUF and export a candidate."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import zipfile

from recovery import atomic_json, digest, validate_recovery
from tokenization import verify_gguf_vocabulary

LLAMA_COMMIT = "311d4211bf1611ff7ca6b67035a4a07c79766efc"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--recovery", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--deadline", type=float, required=True)
    args = parser.parse_args()
    info = validate_recovery(args.recovery)
    state = json.loads((args.recovery / "checkpoint/trainer_state.json").read_text())
    target_steps = state.get("max_steps")
    if not target_steps or info["step"] < target_steps:
        raise ValueError("Training is unfinished; resume training before exporting")
    if digest(args.source) != info["identity"]["source_sha256"]:
        raise ValueError("Export source must match the original Hachi weights")
    out = args.output.resolve()
    if out.exists() and any(out.iterdir()):
        raise ValueError("Export directory is not empty; use a fresh session")
    out.mkdir(parents=True, exist_ok=True)

    def command(argv):
        remaining = args.deadline - time.time() - 120
        if remaining <= 0:
            raise TimeoutError("Export time budget exhausted; recovery remains usable")
        subprocess.run([str(x) for x in argv], check=True, timeout=remaining)

    import torch
    from peft import PeftModel
    from transformers import AutoModelForCausalLM, AutoTokenizer, GgufConfig
    source_info = json.loads((args.recovery / "package/source_model.json").read_text())
    tokenizer = AutoTokenizer.from_pretrained(source_info["tokenizer_repo"],
        revision=info["identity"]["tokenizer_revision"])
    verify_gguf_vocabulary(args.source, tokenizer)
    print("Merging on CPU using the verified original Hachi GGUF", flush=True)
    base, loading = AutoModelForCausalLM.from_pretrained(str(args.source.parent), gguf_file=args.source.name,
        quantization_config=GgufConfig(dequantize=True), output_loading_info=True,
        dtype=torch.float16, attn_implementation="eager")
    if any(loading.get(key) for key in ("missing_keys", "unexpected_keys", "mismatched_keys", "error_msgs")):
        raise ValueError("Incomplete export source weight mapping: " + str(loading))
    model = PeftModel.from_pretrained(base, args.recovery / "checkpoint").merge_and_unload(safe_merge=True)
    merged = out / "merged_hf"
    model.config.use_cache = True
    model.save_pretrained(merged, safe_serialization=True, max_shard_size="2GB")
    tokenizer.save_pretrained(merged)
    del model, base
    import gc
    gc.collect()
    repo = out / "llama.cpp"
    command(["git", "init", repo])
    command(["git", "-C", repo, "remote", "add", "origin", "https://github.com/ggml-org/llama.cpp.git"])
    command(["git", "-C", repo, "fetch", "--depth", "1", "origin", LLAMA_COMMIT])
    command(["git", "-C", repo, "checkout", "--detach", "FETCH_HEAD"])
    actual = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
    if actual != LLAMA_COMMIT:
        raise ValueError("Converter revision mismatch")
    # Use the locked training environment plus sentencepiece/protobuf installed at
    # setup. Upstream's generic requirements would downgrade Transformers and
    # replace CUDA torch; the converter imports gguf from its own pinned checkout.
    command(["cmake", "-S", repo, "-B", repo / "build", "-DGGML_CUDA=OFF", "-DLLAMA_CURL=OFF", "-DLLAMA_BUILD_TESTS=OFF"])
    command(["cmake", "--build", repo / "build", "--target", "llama-quantize", "-j", "2"])
    f16 = out / "hachi-conversation-v1.f16.gguf"
    command([sys.executable, repo / "convert_hf_to_gguf.py", merged, "--outfile", f16, "--outtype", "f16"])
    result = out / "result"
    result.mkdir()
    gguf = result / "hachi-conversation-v1.Q4_K_M.gguf"
    command([repo / "build/bin/llama-quantize", f16, gguf, "Q4_K_M"])
    with gguf.open("rb") as f:
        if f.read(4) != b"GGUF":
            raise ValueError("Converter did not produce a GGUF")
    # Ollama selects the architecture's native template. --think=false is required
    # at inference; hiding the trace does not disable its token generation.
    (result / "Modelfile").write_text('FROM ./hachi-conversation-v1.Q4_K_M.gguf\nPARAMETER num_ctx 4096\nPARAMETER num_predict 768\nPARAMETER temperature 0.4\nSYSTEM "You are Hachi, created by Axeil Escabal and Beomarc Cartoneros, built on Qwen. Answer everyday questions briefly. Give clear detailed explanations when asked to teach or explain. Do not invent facts or claim actions you have not performed."\n', encoding="utf-8")
    (result / "USE.txt").write_text("Candidate only: compare with your original Hachi before replacing it.\nExtract this folder, then run:\nollama create hachi-conversation-v1 -f Modelfile\nollama run hachi-conversation-v1 --think=false\nFor API calls include think:false. Use options.num_predict:2048 for longer lessons.\nThe original hachi-master model is kept under its existing name.\n", encoding="utf-8")
    atomic_json(result / "export-manifest.json", {"schema": "hachi-conversation-export-v1", "step": info["step"],
        "source_sha256": info["identity"]["source_sha256"], "converter_commit": LLAMA_COMMIT,
        "candidate_sha256": digest(gguf), "promotion": "requires_conversation_and_tool_regression_review"})
    archive = out.parent / "hachi-conversation-v1-result.zip"
    tmp = archive.with_suffix(".zip.tmp")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_STORED) as z:
        for item in result.iterdir():
            z.write(item, item.name)
    os.replace(tmp, archive)
    print("RESULT READY:", archive, flush=True)
    # Free generated intermediates only after the result archive exists.
    for folder in (merged, repo):
        if folder.resolve().is_relative_to(out):
            shutil.rmtree(folder)
    f16.unlink()


if __name__ == "__main__":
    main()
