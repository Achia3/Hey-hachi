# Hachi Academic Studio

Academic Studio uses the shared `LAB_3` Python pipeline with your installed Ollama model. You do not need to retrain Hachi for this assignment.

## Open it

1. Open Ollama, or run `ollama serve` if its service is stopped.
2. Start or restart Hachi using your usual launcher.
3. Click **Academic Studio** in Hachi's toolbar. It opens a separate window; clicking the toolbar button again focuses that window.

For a lighter presentation without loading Hachi's voice and assistant services, run these commands from `Hey-hachi/Hey-hachi`:

```powershell
.\.venv\Scripts\python.exe scripts/run_academic_studio.py
```

Open **http://127.0.0.1:5055/academic** in your browser. Keep the terminal running. Run either this standalone server or the main Hachi app at a time: they share the same saved-run directory.

The existing Hachi environment provides Flask, requests, and Pydantic 2. The standalone launcher imports only the academic feature. Keep `LAB_3` alongside the outer `Hey-hachi` folder when moving this project.

## Generate and present

1. Enter the course code, title, and description, or choose **Use DSA example**.
2. Enter target PO numbers, such as `1, 2, 3`. These are identifiers; their official meanings are not invented.
3. Select an installed local model. `hachi-master:latest` is the default. Use **Refresh** after starting Ollama or installing a model.
4. Open **Grading & generation settings** if your lecturer uses different weights. Quiz, research, and lab percentages must total 100% *within class standing*. Class standing plus major exam must also total 100%.
5. Click **Generate syllabus**. The page reports the current stage, attempt number, and received character count.
6. Review the COs, open individual weeks, and inspect the CO-to-assessment matrix and grading formula. Week 7 is the midterm and Week 14 is the final.
7. Switch to **Validated JSON** to show the validated structure. Export outcomes for Lab 1.1, or the complete syllabus for Lab 1.2. In Hachi's desktop window, export opens a Save As dialog; in a browser it downloads a JSON file.

Generating twice creates two separate saved records, even with identical inputs. Select either entry under **Saved generations** to reopen it. **Use inputs** copies its settings into the form; the next generation creates another record. Generation jobs run one at a time to avoid competing for local model memory, with up to eight pending jobs.

## Autosave and recovery

Records are stored in `Hey-hachi/Hey-hachi/data/academic/runs/<unique-id>.json`. Each record includes inputs, progress, validated outcomes, and the final syllabus if complete. Writes use a temporary file and atomic replacement.

- Validated COs are saved immediately after Lab 1.1, before schedule generation.
- Closing only the Academic Studio window leaves generation running while Hachi stays open. The same applies to closing a browser tab while the standalone server stays open.
- Stopping the app/server interrupts generation. On restart, unfinished records are marked **Interrupted**.
- When a failed, cancelled, or interrupted record contains saved COs, **Continue saved outcomes** starts a new record using those COs and preserves the original record. If a full schedule draft was saved, it is revalidated and its rejected weeks can be repaired. Otherwise, a new schedule is generated. With only one attempt configured, it generates a fresh schedule.
- A partial token stream is never presented as validated JSON. If interruption occurs before any COs validate, use the saved inputs to start again.
- Completed records are rechecked against current rules when the app starts. If a later validation change rejects an older syllabus, its original data remains preserved and its draft becomes repairable; it is no longer offered as a validated export.
- **Cancel** takes effect when the current stream read returns. A stalled connection has a timeout, so cancellation may not be immediate.

To back up everything, stop generation and copy the entire `data/academic/runs` folder. Restore it while the app is closed. Exported syllabus JSON contains the academic document; the internal run record also contains recovery metadata.

## Assignment coverage

| Requirement | Implementation |
|---|---|
| Pydantic data models | `LAB_3/obe_schemas.py` |
| CO generator | `LAB_3/lab1_1_generator.py`; CLI alias `obe_json_generator.py` |
| Chained schedule generator | `LAB_3/lab1_2_pipeline.py` |
| JSON mode and streaming | Initial generation uses Ollama `/api/chat` with `format="json"` and streamed content parsing. Targeted repairs use an explicit JSON schema to restrict the returned week numbers and array length. |
| Automatic correction | JSON/schema errors are sent back to the model, up to the configured attempt limit per stage. When validation identifies particular weeks, only those weeks are regenerated and merged, then the full syllabus is validated again. |
| 4–5 measurable COs | Count, consecutive IDs, leading Bloom verb, matching Bloom group, and supplied PO references checked |
| 14-week alignment | Ordered weeks 1–14; exam placement; known CO IDs; every CO referenced at least once |
| Hands-on activities | Each non-exam week must include a laboratory/practical activity keyword; each week includes K/S/A learning outcomes |
| Assessment and grading | Assessment task and evidence per week mapped to CO; grading percentages checked for bounds and totals |
| Sample JSON | `LAB_3/sample_output_syllabus_live.json` is the verified live Hachi export; the original `sample_output_syllabus.json` is also retained. Each successful GUI run can be exported. |

Exports use the assignment names `co_description`, `mapped_po`, `topic`, and `teaching_learning_activity`. Existing LAB_3 files using `description`, `mapped_plos`, `topics`, and `tla_activity` remain accepted. `topic` is an array so a week can contain multiple topics. Bloom levels retain LAB_3's three paired groups: 1–2, 3–4, and 5–6.

Thinking is disabled in the academic request (`think=false`), with compact JSON, bounded output, and targeted weekly corrections when possible. This does not modify Hachi's model or its chat behavior elsewhere. Local generation speed still depends on your hardware, model, and document length; CPU-only generation can take several minutes.

## What still needs your review

Validation guarantees the enforced structure, references, and arithmetic; it does not certify the academic quality of model-written content. Check that topics, activities, assessments, and Bloom verbs fit the course. The grading defaults come from the existing LAB_3 project and should be checked against your lecturer's policy.

PO numbers alone cannot prove semantic alignment. When you have official descriptions, expand **PO descriptions** and enter one per line:

```text
1: Paste the official description of PO 1 here.
2: Paste the official description of PO 2 here.
```

Only descriptions matching selected PO numbers are accepted. They are supplied to the CO prompt; review the resulting mapping yourself.

The optional schema-constrained correction uses Ollama's documented [structured outputs](https://docs.ollama.com/capabilities/structured-outputs). Drafts and raw model responses remain internal diagnostics; exports include only validated outcomes or a validated syllabus.

## Troubleshooting

- **Ollama unavailable:** start Ollama and refresh the model list. Use `ollama list` to check installed names.
- **Model not found:** select a model actually installed on this computer. The app does not automatically download models.
- **Needs attention:** read the saved error. Repeated schema errors may need a more precise course description or another local model. Continue saved COs when available.
- **Slow generation:** a full 14-week syllabus is much larger than a chat answer. Wait for the character count to advance; avoid generating chat replies at the same time. Cancel if you need to free the model.
- **Teacher requires stock Qwen:** select an installed Qwen model rather than Hachi. Both use the same pipeline and checks.
