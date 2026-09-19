# Hachi Qwen3.5-2B Master Brain V2 (Full 3,675-Sample Package)

This package contains the **Full-Scale 3,675-Sample Unified Master Dataset (735 Distinct Families)** with examples across the areas below. Dataset coverage does not establish that every action is implemented or reliable; use the manifest for split/category counts:

1. **🏠 Smart Home:** Full V3 depth — Lights, thermostat (16–30°C, offsets), locks, entertainment media, ambient indirect scenes (freezing/dark, bedtime, leaving home, arrival), and safety refusals.
2. **🎮 Assistant Modes:** Gaming, Study, Movie, and Focus Pomodoro (`manage_mode`).
3. **📋 Multi-Step Routines:** Daily briefing, Study sprint, Gaming setup, Research brief (`run_routine`).
4. **⛅ Live Weather:** Live forecast retrieval for 13+ global and local cities (`get_weather`).
5. **🧠 Memory & Academic Deadlines:** Long-term memory storage, search, and school deadlines with course codes (`manage_productivity`).
6. **📝 Notes, Todos & Reminders:** SQLite notes, tasks, relative and absolute reminders (`manage_productivity`).
7. **📸 System, Screen & Clipboard:** Screenshot capture, clipboard read/write, dictation toggle, CPU/RAM/Battery stats, brightness, volume, and workstation lock (`system_control`).
8. **💻 Windows Desktop Apps:** Launch & close Blender, VS Code, Discord, Chrome, Steam, OBS, Notepad, Calculator, VLC, Figma, Terminal, Explorer, etc. (`manage_app`).
9. **🎵 Media & Music:** Spotify tracks/artists/playlists, YouTube searches, system multimedia keys (`media`).
10. **🌐 Web Research:** Live search queries and page extraction (`web_research`).
11. **💬 Conversational Chat:** General QA, coding explanations, math, and humor without triggering tools.

---

## 📊 Split Distribution:
* **Train Split:** 2,575 records (515 families)
* **Validation Split:** 550 records (110 families)
* **Held-Out Test Benchmark:** 550 records (110 families)

---

## 🚀 How to Run on Kaggle:

1. **Upload Dataset:**
   * Go to [Kaggle Datasets](https://www.kaggle.com/datasets) → **New Dataset**.
   * Upload: `hachi-master-3500-data.zip` from `training_master_v2/`.
   * Name: `hachi-master-3500-data` (Private).

2. **Import Notebook:**
   * In Kaggle Code, click **File** → **Import Notebook**.
   * Upload: `hachi_qwen35_2b_kaggle_master_v2.ipynb` from `training_master_v2/`.
   * Click **+ Add Input**, select `hachi-master-3500-data`.

3. **Train:**
   * Accelerator: `GPU T4 x2` (or `GPU T4 x1`). Internet: `On`.
   * Run **Cell 1** (`%pip install...`), click **Restart & Clear Cell Outputs**.
   * Select **Cell 2** and click **Run current and after**.


## Evaluation correction

The original 99.64% score used a permissive evaluator and is retained only as historical evidence. The strict rescore reports 493/495 correct tool calls (99.60%) and 55/55 no-tool responses. Conversational quality and end-to-end desktop success remain unscored. The recorded 4.02 seconds per record came from the training notebook, not local Ollama.

The notebook now embeds the tested scorer from `hachi_evaluation.py`. It rejects malformed/unknown calls, additional calls and extra arguments, and preserves raw baseline outputs for future rescoring. Run `python scripts/sync_master_evaluator.py` from the application folder after changing the scorer, then re-upload this notebook to Kaggle.

Data, split manifests, and model weights remain unchanged. The manifest still requires human review. Review examples for unsupported runtime actions (absolute volume, brightness, PC locking and productivity deletion) before another training run. See `MODEL_V5_MASTER_INSTALLATION_GUIDE.md` for current capability limits and reproduction commands.
