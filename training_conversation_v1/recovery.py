"""Atomic, checksummed recovery bundles. This module has no ML dependencies."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import zipfile

SCHEMA = "hachi-conversation-recovery-v1"
REQUIRED = {"adapter_config.json", "adapter_model.safetensors", "trainer_state.json",
            "optimizer.pt", "scheduler.pt", "rng_state.pth", "scaler.pt"}


def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(value, f, indent=2, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def checkpoint_step(checkpoint):
    checkpoint = Path(checkpoint)
    missing = [name for name in REQUIRED if not (checkpoint / name).is_file() or (checkpoint / name).stat().st_size == 0]
    if missing:
        raise ValueError("Incomplete training checkpoint: " + ", ".join(sorted(missing)))
    step = json.loads((checkpoint / "trainer_state.json").read_text(encoding="utf-8"))["global_step"]
    if type(step) is not int or step < 1 or checkpoint.name != f"checkpoint-{step}":
        raise ValueError("Checkpoint directory and training step disagree")
    return step


def latest_complete(run):
    candidates = []
    for path in Path(run).glob("checkpoint-*"):
        if path.is_dir():
            try:
                candidates.append((checkpoint_step(path), path))
            except (ValueError, KeyError, json.JSONDecodeError):
                pass
    return max(candidates, default=(0, None))[1]


def publish_recovery(checkpoint, run, destination):
    """Publish only a complete checkpoint; failed writes preserve the prior ZIP."""
    checkpoint, run, destination = Path(checkpoint), Path(run), Path(destination)
    step = checkpoint_step(checkpoint)
    identity = json.loads((run / "run-identity.json").read_text(encoding="utf-8"))
    files = {f"checkpoint/{p.relative_to(checkpoint).as_posix()}": p
             for p in checkpoint.rglob("*") if p.is_file()}
    for p in run.joinpath("package").rglob("*"):
        if p.is_file() and "__pycache__" not in p.parts:
            files[f"package/{p.relative_to(run / 'package').as_posix()}"] = p
    files["run-identity.json"] = run / "run-identity.json"
    for name in ("requirements.lock.txt", "run-summary.json", "baseline.json"):
        if (run / name).is_file():
            files[name] = run / name
    manifest = {"schema": SCHEMA, "step": step, "identity": identity,
                "files": {name: {"sha256": digest(p), "bytes": p.stat().st_size} for name, p in files.items()},
                "base_weights_included": False,
                "note": "Reattach the original Hachi weights; their SHA-256 must match run-identity.json."}
    destination.parent.mkdir(parents=True, exist_ok=True)
    tmp = destination.with_suffix(".zip.tmp")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED, compresslevel=1) as z:
        for name, p in files.items():
            if p.is_symlink():
                raise ValueError("Refusing symlink in recovery")
            z.write(p, name)
        z.writestr("recovery-info.json", json.dumps(manifest, indent=2))
    with zipfile.ZipFile(tmp) as z:
        if z.testzip() is not None:
            raise ValueError("Recovery ZIP failed CRC validation")
    with tmp.open("r+b") as f:
        os.fsync(f.fileno())
    # The last known-good archive is retained independently of checkpoint pruning.
    if destination.exists():
        previous = destination.with_name(destination.stem + "-previous.zip")
        shutil.copyfile(destination, previous.with_suffix(".zip.tmp"))
        os.replace(previous.with_suffix(".zip.tmp"), previous)
    os.replace(tmp, destination)
    print(f"BACKUP READY: optimizer step {step}; {destination}", flush=True)
    return manifest


def safe_extract(archive, destination, max_bytes=8 * 1024**3):
    destination = Path(destination).resolve()
    with zipfile.ZipFile(archive) as z:
        seen = set()
        total = 0
        for item in z.infolist():
            # ZipInfo normalizes backslashes on Windows; inspect its original
            # member name so validation behaves the same on Kaggle and Windows.
            name = item.orig_filename
            path = PurePosixPath(name)
            total += item.file_size
            if (name in seen or "\x00" in name or "\\" in name or ":" in name or path.is_absolute()
                    or ".." in path.parts or stat.S_ISLNK(item.external_attr >> 16)
                    or not (destination / name).resolve().is_relative_to(destination)):
                raise ValueError("Unsafe archive entry: " + name)
            if total > max_bytes:
                raise ValueError("Archive exceeds recovery size limit")
            seen.add(name)
        if z.testzip() is not None:
            raise ValueError("Corrupt archive")
        destination.mkdir(parents=True, exist_ok=True)
        z.extractall(destination)


def validate_recovery(folder, expected_identity=None):
    folder = Path(folder).resolve()
    info = json.loads((folder / "recovery-info.json").read_text(encoding="utf-8"))
    if info.get("schema") != SCHEMA:
        raise ValueError("Wrong Hachi recovery version")
    if expected_identity is not None and info["identity"] != expected_identity:
        raise ValueError("Run configuration, source weights or dataset changed; refusing resume")
    for name, record in info["files"].items():
        if ".." in PurePosixPath(name).parts or "\\" in name or ":" in name:
            raise ValueError("Unsafe manifest path")
        p = (folder / name).resolve()
        if not p.is_relative_to(folder) or p.is_symlink() or not p.is_file():
            raise ValueError("Missing or unsafe recovery asset: " + name)
        if p.stat().st_size != record["bytes"] or digest(p) != record["sha256"]:
            raise ValueError("Recovery checksum mismatch: " + name)
    identity = json.loads((folder / "run-identity.json").read_text(encoding="utf-8"))
    if identity != info["identity"]:
        raise ValueError("Recovery identity mismatch")
    for name in ("run-identity.json", "requirements.lock.txt", "package/package-manifest.json"):
        if name not in info["files"]:
            raise ValueError("Recovery missing required run asset: " + name)
    if digest(folder / "package/package-manifest.json") != identity["package_sha256"]:
        raise ValueError("Recovery package identity mismatch")
    for name in REQUIRED:
        if "checkpoint/" + name not in info["files"]:
            raise ValueError("Recovery missing required checkpoint asset: " + name)
    state = json.loads((folder / "checkpoint/trainer_state.json").read_text(encoding="utf-8"))
    if type(info["step"]) is not int or info["step"] < 1 or state["global_step"] != info["step"]:
        raise ValueError("Recovery step mismatch")
    return info


def restore_checkpoint(folder, run, expected_identity):
    folder, run = Path(folder), Path(run)
    info = validate_recovery(folder, expected_identity)
    checkpoint = run / f"checkpoint-{info['step']}"
    if checkpoint.exists():
        raise ValueError("Restore destination exists; use a fresh run folder")
    shutil.copytree(folder / "checkpoint", checkpoint)
    checkpoint_step(checkpoint)
    return checkpoint
