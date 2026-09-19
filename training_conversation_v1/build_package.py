"""Build deterministic, family-separated conversation data and a small upload ZIP."""
import ast
from collections import Counter, defaultdict
import json
from pathlib import Path
import random
import re
import shutil
import sys
import zipfile

HERE = Path(__file__).resolve().parent
APP = HERE.parent
sys.path.insert(0, str(HERE))
from seeds import CREATORS, SYSTEM, conversations
from recovery import atomic_json, digest


def read_jsonl(path):
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def write_jsonl(path, rows):
    Path(path).write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")


def family_key(record):
    return re.sub(r"_v\d+$", "", record["family"])


def runtime_catalog():
    module = ast.parse((APP / "hachi_tools.py").read_text(encoding="utf-8"))
    node = next(n for n in module.body if isinstance(n, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == "AVAILABLE_TOOLS" for t in n.targets))
    wanted = {"control_smart_home", "get_smart_home_state", "manage_app", "manage_mode", "run_routine",
              "media", "manage_productivity", "web_research", "get_weather", "system_control"}
    return [t for t in ast.literal_eval(node.value) if t["function"]["name"] in wanted]


def select_replay(old, catalog, limit):
    held = {family_key(r) for split in ("validation", "test") for r in old[split]}
    schemas = {t["function"]["name"]: t["function"]["parameters"] for t in catalog}
    candidates = defaultdict(list)
    for r in old["train"]:
        exp = r["expected"]
        if family_key(r) in held or exp["outcome"] != "tool_call":
            continue
        schema = schemas[exp["tool"]]
        args = exp.get("arguments", {})
        if any(k not in args for k in schema.get("required", [])):
            continue
        if any(v not in schema["properties"][k]["enum"] for k, v in args.items()
               if k in schema["properties"] and "enum" in schema["properties"][k]):
            continue
        if exp["tool"] == "manage_productivity" and args.get("action") == "complete" and args.get("type") != "todo":
            continue
        candidates[(r["category"], r["language"])].append(r)
    rng = random.Random(1057)
    for group in candidates.values():
        rng.shuffle(group)
    chosen, seen = [], set()
    while len(chosen) < limit and any(candidates.values()):
        for key in sorted(candidates):
            if not candidates[key] or len(chosen) >= limit:
                continue
            r = candidates[key].pop()
            prompt = re.sub(r"\s*\(v\d+\)\s*", " ", r["user"]).strip()
            normalized = re.sub(r"\W+", " ", prompt.lower()).strip()
            if normalized in seen:
                continue
            seen.add(normalized)
            chosen.append({"id": "replay_" + r["id"], "family": "replay_" + family_key(r),
                "language": r["language"], "category": "tool_replay", "source_category": r["category"],
                "source_id": r["id"], "review_status": "existing_schema_validated_draft",
                "tools": catalog, "expected": r["expected"],
                "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt},
                             r["messages"][-1]]})
    if len(chosen) < limit:
        raise ValueError("Not enough supported, held-out-family-disjoint replay examples")
    return chosen


def validate_splits(splits):
    ids, family_owner, prompts = set(), {}, {}
    for split, rows in splits.items():
        for r in rows:
            if r["id"] in ids:
                raise ValueError("Duplicate ID")
            ids.add(r["id"])
            previous = family_owner.setdefault(r["family"], split)
            if previous != split:
                raise ValueError("Family leakage")
            messages = r["messages"]
            if messages[0]["role"] != "system" or messages[-1]["role"] != "assistant":
                raise ValueError("Invalid conversation roles")
            for i, message in enumerate(messages[1:]):
                if message["role"] != ("user" if i % 2 == 0 else "assistant") or not message["content"].strip():
                    raise ValueError("Invalid or empty conversation turn")
                if message["role"] == "assistant" and "<think>" in message["content"]:
                    raise ValueError("Thinking trace in target data")
            prompt = " ".join(m["content"].lower() for m in messages if m["role"] == "user")
            normalized = re.sub(r"\W+", " ", prompt).strip()
            if normalized in prompts and prompts[normalized] != split:
                raise ValueError("Prompt leakage")
            prompts[normalized] = split
    return {s: {"records": len(rows), "families": len({r['family'] for r in rows}),
                "languages": dict(Counter(r['language'] for r in rows)),
                "categories": dict(Counter(r['category'] for r in rows)),
                "multi_turn": sum(len(r['messages']) > 3 for r in rows)} for s, rows in splits.items()}


def main():
    data = HERE / "data"
    data.mkdir(exist_ok=True)
    rows = conversations()
    families = sorted({r["family"] for r in rows})
    # Fixed category-spanning evaluation families, including short and long replies.
    val = {"base_identity", "yes_no", "sources", "index_error", "missing_code", "referent",
           "invitation", "lesson_loops", "lesson_checkpoints"}
    test = {"identity_correction", "stop", "screen", "format_change", "summary", "quoted_instruction",
            "math_correction", "lesson_sql_joins", "lesson_percentages", "lesson_precision_and_recall",
            "choice", "frustration"}
    assert not val & test and val | test <= set(families)
    splits = {s: [] for s in ("train", "validation", "test")}
    for r in rows:
        split = "validation" if r["family"] in val else "test" if r["family"] in test else "train"
        splits[split].append(r)
    source = APP / "training_master_v2/data"
    old = {s: read_jsonl(source / f"{s}.jsonl") for s in splits}
    catalog = runtime_catalog()
    replay = select_replay(old, catalog, max(1, len(splits["train"]) // 2))
    splits["train"].extend(replay)
    random.Random(1057).shuffle(splits["train"])
    stats = validate_splits(splits)
    for split, records in splits.items():
        write_jsonl(data / f"{split}.jsonl", records)
    # Preserve the original test exactly, as a regression set, never SFT input.
    (data / "legacy_test.jsonl").write_bytes((source / "test.jsonl").read_bytes())
    atomic_json(data / "runtime_tools.json", catalog)
    manifest = {"schema": "hachi-conversation-data-v1", "seed": 1057,
        "creators": CREATORS, "creator_attribution": "confirmed_by_user",
        "conversation_records": len(rows), "replay_records": len(replay), "splits": stats,
        "human_language_review_complete": False,
        "provenance": "Authored synthetic dialogues; replay from existing Master V2 train only. No private chats.",
        "replay_filter": "Strip _vN family suffix; exclude old validation/test families and unsupported action enums.",
        "legacy_test_caveat": "Historical set may contain old cross-split template overlap; it is a regression check, not new generalization evidence.",
        "files": {p.name: digest(p) for p in sorted(data.iterdir()) if p.suffix in (".jsonl", ".json") and p.name != "manifest.json"}}
    atomic_json(data / "manifest.json", manifest)
    dist = HERE / "input"
    dist.mkdir(exist_ok=True)
    ollama_root = Path.home() / ".ollama/models"
    installed = json.loads((ollama_root / "manifests/registry.ollama.ai/library/hachi-master/latest").read_text())
    layer = next(x for x in installed["layers"] if x["mediaType"] == "application/vnd.ollama.image.model")
    checksum = layer["digest"].removeprefix("sha256:")
    source_model = ollama_root / "blobs" / ("sha256-" + checksum)
    if digest(source_model) != checksum:
        raise ValueError("Installed Hachi blob does not match its Ollama manifest")
    model = dist / "hachi-master-current.gguf"
    if not model.is_file() or digest(model) != checksum:
        shutil.copyfile(source_model, model)
    if digest(model) != checksum:
        raise ValueError("Source weight copy verification failed")
    atomic_json(HERE / "source_model.json", {"mode": "gguf", "filename": model.name,
        "bytes": model.stat().st_size, "sha256": checksum, "base_family": "Qwen3.5-2B",
        "tokenizer_repo": "Qwen/Qwen3.5-2B", "ollama_model": "hachi-master:latest",
        "weights_are_current_hachi": True})
    sources = [p for p in HERE.iterdir() if p.is_file() and p.suffix in (".py", ".json", ".txt", ".md")]
    sources += list(data.iterdir())
    package_files = {p.relative_to(HERE).as_posix(): digest(p) for p in sources if p.name != "package-manifest.json"}
    atomic_json(HERE / "package-manifest.json", {"schema": "hachi-conversation-package-v1", "files": package_files})
    with zipfile.ZipFile(dist / "hachi-conversation-v1-input.zip", "w", zipfile.ZIP_DEFLATED) as z:
        for name in sorted(package_files):
            z.write(HERE / name, name)
        z.write(HERE / "package-manifest.json", "package-manifest.json")
    print(json.dumps({"conversation_records": len(rows), "replay_records": len(replay), "splits": stats}, indent=2))


if __name__ == "__main__":
    main()
