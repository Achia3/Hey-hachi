"""Generate the self-contained Kaggle launcher from reviewed Python sources."""
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent


def cell(kind, source):
    value = {"cell_type": kind, "metadata": {}, "source": source.splitlines(keepends=True)}
    if kind == "code":
        value.update(execution_count=None, outputs=[])
    return value


def main():
    intro = """# Hachi conversation improvement — pilot, resume, export
Continues your **registered hachi-master** weights. Creators: **Axeil Escabal and Beomarc Cartoneros**.

Enable a GPU and Internet in Kaggle. Attach the input package and `hachi-master-current.gguf`.
The first run deliberately pauses after **2 optimizer steps**. Download the recovery ZIP,
reattach it with the same original GGUF in a fresh session, and set `START_NEW_RUN=False`.
Keep `PILOT_STEPS=2` for one resume test; set it to `0` once both tests pass.

Use **Save Version → Save & Run All** to produce saved notebook output. A local autosave
does not survive every forced shutdown: download successful saved output before ending a session.
Setup/training errors are shown below and recorded in `hachi-session-status.json`; a green
notebook version alone does not mean training succeeded. See `START_HERE.md` for full instructions.
"""
    settings = """import time
SESSION_START = time.time()
START_NEW_RUN = True
PILOT_STEPS = 2          # Number of NEW optimizer steps this session; 0 runs the remaining schedule.
SESSION_HOURS = 8        # Budget measured from this cell; training reserves the final 20 minutes.
EXPORT_RESULT = True    # After the full training schedule, merge and create an Ollama GGUF.
EXPORT_ONLY = False     # Use a completed recovery to retry conversion without training again.
RESUME_FROM = ""        # Optional exact /kaggle/input/... recovery ZIP or extracted folder.
PACKAGE_FROM = ""       # Optional exact initial ZIP or extracted package folder (fresh runs only).
SOURCE_FROM = ""        # Optional exact path to hachi-master-current.gguf.
"""
    embedded = {n: (HERE / n).read_text(encoding="utf-8") for n in ("recovery.py", "session.py")}
    launch = """import json
from pathlib import Path
import subprocess
import sys
if not Path('/kaggle/input').is_dir():
    raise RuntimeError('This notebook is intended for Kaggle; training is not started locally.')
bootstrap = Path('/kaggle/working/hachi-bootstrap')
bootstrap.mkdir(exist_ok=True)
""" + "embedded_sources = " + repr(embedded) + "\n" + """for name, source in embedded_sources.items():
    (bootstrap / name).write_text(source, encoding='utf-8')
settings = dict(session_start=SESSION_START, start_new_run=START_NEW_RUN,
    pilot_steps=PILOT_STEPS, session_hours=SESSION_HOURS, export_result=EXPORT_RESULT,
    export_only=EXPORT_ONLY, resume_from=RESUME_FROM, package_from=PACKAGE_FROM, source_from=SOURCE_FROM)
completed = subprocess.run([sys.executable, str(bootstrap / 'session.py'), '--settings', json.dumps(settings)])
print('Driver exit code:', completed.returncode)
if completed.returncode:
    print('FAILED: inspect the error above. The download cell can still expose the last valid backup.')
"""
    downloads = """from IPython.display import display, FileLink
import json
from pathlib import Path
working = Path('/kaggle/working')
for name in ('hachi-session-status.json', 'hachi-run/run-summary.json'):
    p = working / name
    if p.is_file():
        print(name, p.read_text())
for name in ('hachi-conversation-v1-recovery.zip', 'hachi-conversation-v1-recovery-previous.zip', 'hachi-conversation-v1-result.zip'):
    p = working / name
    if p.is_file():
        print(f'{name}: {p.stat().st_size / 1024**2:.1f} MiB')
        display(FileLink(str(p)))
if not (working / 'hachi-conversation-v1-recovery.zip').exists():
    print('NO RECOVERY YET: no complete optimizer checkpoint has been published.')
print('Download saved notebook output. Resume needs the recovery ZIP plus the SAME original Hachi GGUF.')
"""
    notebook = {"nbformat": 4, "nbformat_minor": 5,
        "metadata": {"kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
                     "language_info": {"name": "python", "version": "3.11"}},
        "cells": [cell("markdown", intro), cell("code", settings), cell("code", launch), cell("code", downloads)]}
    for i, c in enumerate(notebook["cells"]):
        c["id"] = f"hachi-{i}"
    (HERE / "hachi_conversation_v1_kaggle.ipynb").write_text(json.dumps(notebook, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
