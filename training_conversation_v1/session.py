"""Notebook subprocess driver. Setup failures leave prior recovery downloadable."""
import argparse
import importlib.metadata
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time
import traceback

from recovery import atomic_json, digest, latest_complete, publish_recovery, safe_extract, validate_recovery


def one(paths, description):
    paths = sorted(set(Path(p).resolve() for p in paths))
    if len(paths) != 1:
        raise ValueError(f"Expected exactly one {description}, found {len(paths)}: {paths}. Set the explicit path in cell 1.")
    return paths[0]


def run_session(settings):
    inputs = Path("/kaggle/input")
    working = Path("/kaggle/working")
    stage = working / ".hachi-stage"
    run = working / "hachi-run"
    backup = working / "hachi-conversation-v1-recovery.zip"
    if stage.exists() or run.exists():
        raise ValueError("This session already has Hachi output. Download it and start a fresh session before rerunning.")
    stage.mkdir()
    deadline = settings["session_start"] + settings["session_hours"] * 3600
    if not 0 < settings["session_hours"] <= 8:
        raise ValueError("Use a session budget greater than 0 and at most 8 hours")

    def command(argv, reserve_seconds=120):
        remaining = deadline - time.time() - reserve_seconds
        if remaining <= 0:
            raise TimeoutError("Session budget exhausted; keep the last complete recovery ZIP")
        subprocess.run([str(x) for x in argv], check=True, timeout=remaining)

    attached = list(inputs.rglob("hachi-conversation-v1-recovery.zip"))
    attached += [p.parent for p in inputs.rglob("recovery-info.json")]
    resume = None
    if settings["start_new_run"]:
        if attached or settings["resume_from"] or settings["export_only"]:
            raise ValueError("Fresh mode conflicts with attached recovery or export-only. Set START_NEW_RUN=False to resume.")
        supplied = settings["package_from"]
        candidates = [Path(supplied)] if supplied else list(inputs.rglob("hachi-conversation-v1-input.zip"))
        if not candidates:
            candidates = [p.parent for p in inputs.rglob("package-manifest.json")]
        chosen = one(candidates, "input package")
        if chosen.is_file():
            package = stage / "package"
            safe_extract(chosen, package)
        else:
            package = chosen
    else:
        chosen = one([settings["resume_from"]] if settings["resume_from"] else attached, "recovery ZIP or folder")
        if chosen.is_file():
            resume = stage / "recovery"
            safe_extract(chosen, resume)
        else:
            resume = chosen
        validate_recovery(resume)
        package = resume / "package"
        # Publish an independent copy before dependency installation or GPU setup.
        if chosen.is_file():
            shutil.copyfile(chosen, backup)
        else:
            import zipfile
            with zipfile.ZipFile(backup, "w", zipfile.ZIP_DEFLATED, compresslevel=1) as z:
                for item in resume.rglob("*"):
                    if item.is_file():
                        z.write(item, item.relative_to(resume).as_posix())

    # Verify every packaged source before importing it or installing its requirements.
    manifest = json.loads((package / "package-manifest.json").read_text())
    if manifest.get("schema") != "hachi-conversation-package-v1":
        raise ValueError("Wrong package version")
    for name, sha in manifest["files"].items():
        item = (package / name).resolve()
        if not item.is_relative_to(package.resolve()) or digest(item) != sha:
            raise ValueError("Package checksum mismatch: " + name)
    source_info = json.loads((package / "source_model.json").read_text())
    source = one([settings["source_from"]] if settings["source_from"] else inputs.rglob(source_info["filename"]), "original Hachi GGUF")
    if digest(source) != source_info["sha256"]:
        raise ValueError("Wrong base weights; reattach hachi-master-current.gguf from this package")
    requirements = resume / "requirements.lock.txt" if resume else package / "requirements.txt"
    if not requirements.is_file():
        raise ValueError("Missing dependency lock; cannot safely resume")
    command([sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "-r", requirements])
    torch_version = importlib.metadata.version("torch")
    if tuple(int(n) for n in torch_version.split("+")[0].split(".")[:2]) < (2, 6):
        raise RuntimeError("Select a Kaggle GPU image with CUDA PyTorch >=2.6")
    export_only = settings["export_only"]
    if resume:
        state = json.loads((resume / "checkpoint/trainer_state.json").read_text())
        if state["global_step"] >= state["max_steps"]:
            export_only = True
            print("Checkpoint has finished the training schedule; continuing directly to export.", flush=True)
    if not export_only:
        argv = [sys.executable, package / "train.py", "--package", package, "--source", source,
                "--run", run, "--deadline", deadline, "--pilot-steps", settings["pilot_steps"], "--reserve-minutes", 20]
        if resume:
            argv += ["--resume", resume]
        command(argv)
        summary = json.loads((run / "run-summary.json").read_text())
        if summary["status"] != "training_complete":
            print("PILOT/SESSION PAUSED. Download recovery ZIP and use resume mode in a fresh session.", flush=True)
            return
    if settings["export_result"] or export_only:
        export_recovery = stage / "export-recovery"
        safe_extract(backup, export_recovery)
        command([sys.executable, package / "export.py", "--recovery", export_recovery,
                 "--source", source, "--output", working / "hachi-export", "--deadline", deadline])
    else:
        print("Training complete. Download recovery; enable EXPORT_ONLY in a fresh session to convert.", flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--settings", required=True)
    args = parser.parse_args()
    settings = json.loads(args.settings)
    status = {"status": "started"}
    try:
        run_session(settings)
        status = {"status": "finished_without_error", "note": "Read hachi-run/run-summary.json for paused versus complete."}
    except BaseException as exc:
        traceback.print_exc()
        status = {"status": "failed", "error": str(exc)}
        run = Path("/kaggle/working/hachi-run")
        try:
            checkpoint = latest_complete(run)
            if checkpoint and (run / "run-identity.json").is_file():
                publish_recovery(checkpoint, run, run.parent / "hachi-conversation-v1-recovery.zip")
        except Exception:
            traceback.print_exc()
        print("RUN FAILED. Any existing recovery ZIP is the last complete state, not proof of training success.", flush=True)
    finally:
        atomic_json(Path("/kaggle/working/hachi-session-status.json"), status)
    return 1 if status["status"] == "failed" else 0


if __name__ == "__main__":
    sys.exit(main())
