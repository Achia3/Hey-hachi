"""Offline dataset, assistant masking and recovery transport checks; no GPU training."""
import ast
import json
from pathlib import Path
import zipfile

import pytest

from hachi_evaluation import score_output
from training_conversation_v1 import recovery
from training_conversation_v1 import build_package as build
from training_conversation_v1.tokenization import training_examples, verify_gguf_vocabulary

PACKAGE = Path(__file__).resolve().parents[1] / "training_conversation_v1"


def fake_run(tmp_path, step=5):
    run = tmp_path / "run"
    checkpoint = run / f"checkpoint-{step}"
    checkpoint.mkdir(parents=True)
    for name in recovery.REQUIRED:
        (checkpoint / name).write_bytes(b"synthetic-test-state")
    recovery.atomic_json(checkpoint / "trainer_state.json", {"global_step": step, "max_steps": 64})
    (run / "package").mkdir()
    recovery.atomic_json(run / "package/package-manifest.json", {"schema": "hachi-conversation-package-v1", "files": {}})
    identity = {"source_sha256": "test", "package_sha256": recovery.digest(run / "package/package-manifest.json")}
    recovery.atomic_json(run / "run-identity.json", identity)
    (run / "requirements.lock.txt").write_text("torch==test\n")
    return run, checkpoint, identity


def test_recovery_round_trip_and_incomplete_newer_checkpoint(tmp_path):
    run, checkpoint, identity = fake_run(tmp_path)
    (run / "checkpoint-10").mkdir()
    (run / "checkpoint-10/adapter_model.safetensors").write_bytes(b"partial")
    assert recovery.latest_complete(run) == checkpoint
    archive = tmp_path / "recovery.zip"
    recovery.publish_recovery(checkpoint, run, archive)
    restored = tmp_path / "extracted"
    recovery.safe_extract(archive, restored)
    assert recovery.validate_recovery(restored, identity)["step"] == 5
    resumed = recovery.restore_checkpoint(restored, tmp_path / "next-run", identity)
    assert recovery.checkpoint_step(resumed) == 5
    for name in recovery.REQUIRED:
        assert (resumed / name).read_bytes() == (checkpoint / name).read_bytes()
    with pytest.raises(ValueError, match="configuration"):
        recovery.validate_recovery(restored, {"different": True})
    (restored / "checkpoint/optimizer.pt").write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="checksum"):
        recovery.validate_recovery(restored)


def test_failed_publication_preserves_existing_backup(tmp_path, monkeypatch):
    run, checkpoint, _ = fake_run(tmp_path)
    archive = tmp_path / "recovery.zip"
    recovery.publish_recovery(checkpoint, run, archive)
    original = archive.read_bytes()
    def disk_failure(*args, **kwargs):
        raise OSError("simulated full disk")
    monkeypatch.setattr(zipfile.ZipFile, "write", disk_failure)
    with pytest.raises(OSError, match="full disk"):
        recovery.publish_recovery(checkpoint, run, archive)
    assert archive.read_bytes() == original


def test_previous_backup_and_missing_scaler(tmp_path):
    run, checkpoint, _ = fake_run(tmp_path)
    archive = tmp_path / "recovery.zip"
    recovery.publish_recovery(checkpoint, run, archive)
    original = archive.read_bytes()
    (checkpoint / "adapter_model.safetensors").write_bytes(b"updated")
    recovery.publish_recovery(checkpoint, run, archive)
    assert (tmp_path / "recovery-previous.zip").read_bytes() == original
    (checkpoint / "scaler.pt").unlink()
    assert recovery.latest_complete(run) is None
    with pytest.raises(ValueError, match="scaler"):
        recovery.publish_recovery(checkpoint, run, archive)


@pytest.mark.parametrize("name", ["../escape", "/absolute", "C:/absolute", "folder\\escape"])
def test_archive_path_rejected(tmp_path, name):
    archive = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(archive, "w") as z:
        entry = zipfile.ZipInfo("entry")
        entry.filename = name  # Preserve malicious backslashes even on Windows.
        z.writestr(entry, "bad")
    with pytest.raises(ValueError, match="Unsafe"):
        recovery.safe_extract(archive, tmp_path / "destination")


def test_data_splits_replay_targets_and_provenance():
    splits = {s: build.read_jsonl(PACKAGE / f"data/{s}.jsonl") for s in ("train", "validation", "test")}
    stats = build.validate_splits(splits)
    assert [stats[s]["records"] for s in splits] == [159, 24, 31]
    replay = [r for r in splits["train"] if r["category"] == "tool_replay"]
    assert len(replay) == 53
    old = PACKAGE.parent / "training_master_v2/data"
    held = {build.family_key(r) for s in ("validation", "test") for r in build.read_jsonl(old / f"{s}.jsonl")}
    for row in replay:
        assert row["family"].removeprefix("replay_") not in held
        assert score_output(row["expected"], row["messages"][-1]["content"])["correct"] is True
    assert (PACKAGE / "data/legacy_test.jsonl").read_bytes() == (old / "test.jsonl").read_bytes()
    for rows in splits.values():
        for row in rows:
            assert "Axeil Escabal and Beomarc Cartoneros" in row["messages"][0]["content"]


class CharacterTokenizer:
    def apply_chat_template(self, messages, add_generation_prompt, **kwargs):
        assert kwargs["enable_thinking"] is False
        rendered = "".join(m["role"] + ":" + m["content"] + "|" for m in messages)
        return rendered + ("assistant:" if add_generation_prompt else "")

    def __call__(self, text, **kwargs):
        return {"input_ids": [ord(c) for c in text], "offset_mapping": [(i, i + 1) for i in range(len(text))]}


def test_assistant_only_labels_and_no_silent_truncation():
    row = {"id": "two-turn", "messages": [{"role": "system", "content": "rules"},
        {"role": "user", "content": "hello"}, {"role": "assistant", "content": "Hi"},
        {"role": "user", "content": "bye"}, {"role": "assistant", "content": "Bye"}]}
    examples = training_examples(row, CharacterTokenizer(), 1000)
    assert ["".join(chr(t) for t in x["labels"] if t != -100) for x in examples] == ["Hi|", "Bye|"]
    with pytest.raises(ValueError, match="no truncation"):
        training_examples(row, CharacterTokenizer(), 3)


def test_all_sources_and_notebook_cells_compile():
    for path in PACKAGE.glob("*.py"):
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    notebook = json.loads((PACKAGE / "hachi_conversation_v1_kaggle.ipynb").read_text())
    for cell in notebook["cells"]:
        if cell["cell_type"] == "code":
            compile("".join(cell["source"]), "notebook", "exec")
    launch = ast.parse("".join(notebook["cells"][2]["source"]))
    source_node = next(n for n in launch.body if isinstance(n, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "embedded_sources" for t in n.targets))
    for name, source in ast.literal_eval(source_node.value).items():
        assert source == (PACKAGE / name).read_text(encoding="utf-8")


def test_input_package_hashes_and_zip():
    manifest = json.loads((PACKAGE / "package-manifest.json").read_text())
    for name, expected in manifest["files"].items():
        assert recovery.digest(PACKAGE / name) == expected
    with zipfile.ZipFile(PACKAGE / "input/hachi-conversation-v1-input.zip") as z:
        assert z.testzip() is None
        for name in manifest["files"]:
            assert z.read(name) == (PACKAGE / name).read_bytes()


def test_actual_qwen_template_when_tokenizer_cache_available():
    cache = PACKAGE.parent / ".pytest_cache/qwen-tokenizer"
    if not cache.exists():
        pytest.skip("Optional real-tokenizer check needs the local Qwen tokenizer cache")
    transformers = pytest.importorskip("transformers")
    tokenizer = transformers.AutoTokenizer.from_pretrained(str(cache), local_files_only=True)
    source = PACKAGE / "input/hachi-master-current.gguf"
    if source.is_file():
        pytest.importorskip("gguf")
        assert verify_gguf_vocabulary(source, tokenizer) == 248320
    count = 0
    for split in ("train", "validation", "test"):
        for row in build.read_jsonl(PACKAGE / f"data/{split}.jsonl"):
            for example in training_examples(row, tokenizer, 3072):
                target = tokenizer.decode([t for t in example["labels"] if t != -100])
                assert "<think>" not in target
                assert any(t == -100 for t in example["labels"])
                count += 1
    assert count == 332
