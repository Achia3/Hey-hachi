"""Persistent, isolated OBE runs using the shared LAB_3 pipeline."""
from __future__ import annotations

from queue import Queue
from datetime import datetime, timezone
import io
import json
import os
from pathlib import Path
import re
import sys
import threading
import time
import uuid

from flask import Blueprint, jsonify, render_template, request, send_file
from pydantic import Field, ValidationError, field_validator, model_validator
import requests

WORKSPACE = Path(__file__).resolve().parents[2]
if str(WORKSPACE) not in sys.path:
    sys.path.insert(0, str(WORKSPACE))
from LAB_3.obe_schemas import CourseOutcomeSchema, GradingBreakdown, StrictModel, PositiveId, OBESyllabusPayload
from LAB_3.lab1_1_generator import default_ollama_caller, generate_course_outcomes
from LAB_3.lab1_2_pipeline import generate_syllabus_pipeline


class AcademicRequest(StrictModel):
    course_code: str = Field(min_length=1, max_length=40)
    course_title: str = Field(min_length=1, max_length=200)
    course_description: str = Field(min_length=10, max_length=6000)
    target_pos: list[PositiveId] = Field(min_length=1, max_length=20)
    po_descriptions: dict[str, str] = Field(default_factory=dict)
    model: str = Field(default="hachi-master:latest", min_length=1, max_length=150, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/-]*$")
    grading: GradingBreakdown = Field(default_factory=GradingBreakdown)
    max_retries: int = Field(default=3, ge=1, le=5, strict=True)

    @model_validator(mode="after")
    def distinct_pos(self):
        if len(set(self.target_pos)) != len(self.target_pos):
            raise ValueError("Target PO numbers must be unique")
        if any(k not in {str(x) for x in self.target_pos} or not v.strip() or len(v) > 1000 for k, v in self.po_descriptions.items()):
            raise ValueError("PO descriptions must be nonempty and match the supplied target numbers")
        return self


def utc_now():
    return datetime.now(timezone.utc).isoformat()


class LazyAcademicService:
    """Importing the chat app must not touch or recover academic run files."""
    def __init__(self, root):
        self.root = root
        self._service = None
        self._init_lock = threading.Lock()

    def __getattr__(self, name):
        with self._init_lock:
            if self._service is None:
                self._service = AcademicService(self.root)
        return getattr(self._service, name)


class AcademicService:
    def __init__(self, root, caller=None):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.caller = caller
        self.lock = threading.RLock()
        self.queue = Queue()
        self.worker = None
        self.cancels = {}
        # Only persisted, unfinished work is marked interrupted on a fresh process.
        for path in self.root.glob("*.json"):
            try:
                item = json.loads(path.read_text(encoding="utf-8"))
                if item["status"] in {"queued", "running"}:
                    item.update(status="interrupted", message="Hachi stopped before this run finished. Start a new run or continue its saved outcomes.", updated_at=utc_now())
                    self._save(item)
                elif item['status'] == 'completed':
                    try:
                        OBESyllabusPayload.model_validate(item.get('syllabus'))
                    except ValidationError:
                        previous = item.get('syllabus')
                        item.update(status='failed', previous_syllabus=previous, syllabus=None,
                            schedule_draft=json.dumps({'weekly_schedule':previous.get('weekly_schedule', [])}) if isinstance(previous, dict) else None,
                            message='This saved syllabus needs repair under the current validation rules. Continue saved outcomes to revalidate its draft.', updated_at=utc_now())
                        self._save(item)
            except (OSError, ValueError, KeyError):
                continue

    def _path(self, run_id):
        if not re.fullmatch(r"[a-f0-9]{32}", str(run_id)):
            raise ValueError("Invalid generation ID")
        return self.root / (run_id + ".json")

    def _save(self, record):
        path = self._path(record["id"])
        temp = path.with_suffix(".json.tmp")
        with temp.open("w", encoding="utf-8") as f:
            json.dump(record, f, ensure_ascii=False, indent=2, allow_nan=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp, path)

    def get(self, run_id):
        with self.lock:
            return json.loads(self._path(run_id).read_text(encoding="utf-8"))

    def list(self):
        with self.lock:
            items = []
            for path in self.root.glob("*.json"):
                try:
                    r = json.loads(path.read_text(encoding="utf-8"))
                    items.append({k: r[k] for k in ("id", "created_at", "updated_at", "status", "stage", "message", "inputs")})
                except (OSError, ValueError, KeyError):
                    continue
            return sorted(items, key=lambda x: x["created_at"], reverse=True)

    def update(self, run_id, **values):
        with self.lock:
            item = self.get(run_id)
            item.update(values, updated_at=utc_now())
            self._save(item)
            return item

    def start(self, data, source_run_id=None):
        with self.lock:
            if sum(x["status"] in {"queued", "running"} for x in self.list()) >= 8:
                raise RuntimeError("Eight generations are already queued. Wait for one to finish.")
            outcomes = None
            if source_run_id:
                source = self.get(source_run_id)
                if not source.get("outcomes"):
                    raise ValueError("This run has no validated outcomes to continue")
                data, outcomes = source["inputs"], source["outcomes"]
            inputs = AcademicRequest.model_validate(data)
            run_id = uuid.uuid4().hex
            record = {"id": run_id, "created_at": utc_now(), "updated_at": utc_now(),
                "status": "queued", "stage": "queued", "message": "Waiting for the local model",
                "inputs": inputs.model_dump(mode="json"), "outcomes": outcomes, "syllabus": None,
                "source_run_id": source_run_id, "attempt": 0, "characters": 0, "events": [],
                "review_note": "Structural checks do not replace academic review. PO numbers alone cannot establish semantic PO alignment."}
            self._save(record)
            event = threading.Event()
            self.cancels[run_id] = event
            if self.worker is None:
                self.worker = threading.Thread(target=self._work, daemon=True, name="AcademicWorker")
                self.worker.start()
            self.queue.put((run_id, inputs, outcomes, event))
            return record

    def _work(self):
        while True:
            task = self.queue.get()
            if task is None:
                return
            self._run(*task)

    def close(self):
        with self.lock:
            for event in self.cancels.values():
                event.set()
            self.queue.put(None)

    def cancel(self, run_id):
        with self.lock:
            item = self.get(run_id)
            if item["status"] not in {"queued", "running"}:
                return item
            self.cancels[run_id].set()
            return self.update(run_id, message="Cancellation requested; waiting for the current stream read to return")

    def _run(self, run_id, inputs, saved_outcomes, cancelled):
        started = time.monotonic()
        last_publish = [0.0]
        def progress(stage, attempt):
            if cancelled.is_set():
                raise InterruptedError("Generation cancelled")
            with self.lock:
                r = self.get(run_id)
                events = r["events"] + [{"stage": stage, "attempt": attempt, "at": utc_now()}]
                self.update(run_id, status="running", stage=stage, attempt=attempt, characters=0,
                    message=("Generating course outcomes" if stage == "outcomes" else "Building the 14-week schedule") + f" · attempt {attempt}/{inputs.max_retries}", events=events)
        def chunk(size):
            if time.monotonic() - last_publish[0] >= 0.8:
                self.update(run_id, characters=size)
                last_publish[0] = time.monotonic()
        def call(messages, model, json_mode):
            if cancelled.is_set():
                raise InterruptedError("Generation cancelled")
            if self.caller:
                return self.caller(messages, model, json_mode)
            output = default_ollama_caller(messages, model=model, format_json=json_mode,
                on_chunk=chunk, cancelled=cancelled.is_set, num_predict=7000)
            self.update(run_id, last_model_response=output)
            # Preserve diagnostics in the internal record, never in validated exports.
            try:
                json.loads(output)
            except ValueError as exc:
                self.update(run_id, last_invalid_response=output, last_validation_error=str(exc))
            return output
        try:
            if cancelled.is_set():
                raise InterruptedError("Generation cancelled")
            self.update(run_id, status="running")
            co = CourseOutcomeSchema.model_validate(saved_outcomes) if saved_outcomes else generate_course_outcomes(
                inputs.course_code, inputs.course_title, inputs.course_description, inputs.target_pos,
                model=inputs.model, max_retries=inputs.max_retries, llm_caller=call,
                on_progress=progress, po_descriptions=inputs.po_descriptions)
            self.update(run_id, outcomes=co.model_dump(mode="json", by_alias=True), message="Validated course outcomes saved")
            draft = None
            source_id = self.get(run_id).get('source_run_id')
            if source_id and inputs.max_retries > 1:
                source = self.get(source_id)
                candidate = source.get('schedule_draft') or source.get('last_model_response')
                try:
                    parsed = json.loads(candidate or 'null')
                    weeks = parsed.get('weekly_schedule') if isinstance(parsed, dict) else parsed
                    if isinstance(weeks, list) and len(weeks) == 14:
                        draft = candidate
                except ValueError:
                    pass
            syllabus = generate_syllabus_pipeline(co, model=inputs.model, max_retries=inputs.max_retries,
                llm_caller=call, on_progress=progress, grading=inputs.grading, initial_response=draft,
                on_draft=lambda value: self.update(run_id, schedule_draft=value))
            if cancelled.is_set():
                raise InterruptedError("Generation cancelled")
            self.update(run_id, status="completed", stage="complete", syllabus=syllabus.model_dump(mode="json", by_alias=True),
                elapsed_seconds=round(time.monotonic() - started, 1), message="Syllabus saved · ready for academic review")
        except InterruptedError:
            self.update(run_id, status="cancelled", message="Generation cancelled. Any validated outcomes remain saved.")
        except Exception as exc:
            self.update(run_id, status="failed", message=str(exc), elapsed_seconds=round(time.monotonic() - started, 1))
        finally:
            with self.lock:
                self.cancels.pop(run_id, None)

    def export(self, run_id, kind="syllabus"):
        if kind not in {"syllabus", "outcomes"}:
            raise ValueError("Unknown export type")
        record = self.get(run_id)
        if not record.get(kind):
            raise ValueError("No validated " + kind + " is available for this run")
        schema = OBESyllabusPayload if kind == 'syllabus' else CourseOutcomeSchema
        return schema.model_validate(record[kind]).model_dump_json(indent=2, by_alias=True)


def create_academic_blueprint(service):
    bp = Blueprint("academic", __name__)

    @bp.get("/academic")
    def academic_page():
        return render_template("academic.html")

    @bp.get("/api/academic/models")
    def models():
        try:
            response = requests.get("http://127.0.0.1:11434/api/tags", timeout=3)
            response.raise_for_status()
            return jsonify(models=[m["name"] for m in response.json().get("models", [])], available=True)
        except (requests.RequestException, ValueError, KeyError):
            return jsonify(models=[], available=False, message="Ollama is unavailable. Open Ollama and refresh the model list.")

    @bp.get("/api/academic/runs")
    def runs():
        return jsonify(runs=service.list())

    @bp.post("/api/academic/runs")
    def start():
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return jsonify(error="Send one JSON object with course details"), 400
        try:
            source = data.pop("source_run_id", None)
            result = service.start(data, source)
            return jsonify(result), 202
        except ValidationError as exc:
            return jsonify(error="; ".join(".".join(map(str, e["loc"])) + ": " + e["msg"] for e in exc.errors())), 400
        except (ValueError, FileNotFoundError) as exc:
            return jsonify(error=str(exc)), 400
        except RuntimeError as exc:
            return jsonify(error=str(exc)), 409

    @bp.get("/api/academic/runs/<run_id>")
    def detail(run_id):
        try:
            return jsonify(service.get(run_id))
        except (ValueError, FileNotFoundError):
            return jsonify(error="Generation not found"), 404

    @bp.post("/api/academic/runs/<run_id>/cancel")
    def cancel(run_id):
        try:
            return jsonify(service.cancel(run_id))
        except (ValueError, FileNotFoundError):
            return jsonify(error="Generation not found"), 404

    @bp.get("/api/academic/runs/<run_id>/download")
    def download(run_id):
        try:
            kind = request.args.get("kind", "syllabus")
            output = service.export(run_id, kind)
            return send_file(io.BytesIO(output.encode("utf-8")), mimetype="application/json",
                             as_attachment=True, download_name=f"{kind}-{run_id[:8]}.json")
        except (ValueError, FileNotFoundError) as exc:
            return jsonify(error=str(exc)), 404

    return bp
