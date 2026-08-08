"""Local-first student productivity and file tools for Hachi."""

from __future__ import annotations

from contextlib import closing
from datetime import datetime, timedelta
import csv
import json
import logging
import os
from pathlib import Path
import re
import subprocess
import threading
import time
from typing import Optional

import psutil

from hachi_db import add_task, get_connection, init_db


PROJECT_ROOT = Path(__file__).resolve().parent
USER_HOME = Path.home().resolve()
ALLOWED_FILE_ROOTS = tuple(
    path.resolve()
    for path in (
        PROJECT_ROOT,
        USER_HOME / "Desktop",
        USER_HOME / "Documents",
        USER_HOME / "Downloads",
    )
    if path.exists()
)
SUPPORTED_DOCUMENTS = {".pdf", ".docx", ".txt", ".md", ".csv", ".json", ".py"}


def _now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def parse_due_time(value: str = "", minutes_from_now: Optional[float] = None) -> datetime:
    if minutes_from_now is not None:
        return datetime.now() + timedelta(minutes=max(0.02, float(minutes_from_now)))
    text = re.sub(r"\s+", " ", (value or "")).strip().lower()
    if not text:
        raise ValueError("A due time or duration is required.")
    duration = re.search(r"(?:in\s+)?(\d+(?:\.\d+)?)\s*(seconds?|secs?|minutes?|mins?|hours?|hrs?)", text)
    if duration:
        amount = float(duration.group(1))
        unit = duration.group(2)
        seconds = amount if unit.startswith(("second", "sec")) else amount * (3600 if unit.startswith(("hour", "hr")) else 60)
        return datetime.now() + timedelta(seconds=max(1, seconds))

    clean = re.sub(r"^(?:at|on)\s+", "", text)
    clean = clean.replace("today at ", "today ").replace("tomorrow at ", "tomorrow ")

    weekday_match = re.search(
        r"\b(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b(?:\s+at)?\s*(.*)$",
        clean,
    )
    if weekday_match:
        weekdays = {
            "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
            "friday": 4, "saturday": 5, "sunday": 6,
        }
        now = datetime.now()
        days_ahead = (weekdays[weekday_match.group(1)] - now.weekday()) % 7
        time_text = weekday_match.group(2).strip()
        parsed_time = datetime.strptime("9:00 AM", "%I:%M %p").time()
        if time_text:
            parsed_time = None
            for fmt in ("%I:%M %p", "%I %p", "%H:%M"):
                try:
                    parsed_time = datetime.strptime(time_text.upper(), fmt).time()
                    break
                except ValueError:
                    pass
            if parsed_time is None:
                raise ValueError(f"I couldn't understand the time in '{value}'.")
        candidate = datetime.combine((now + timedelta(days=days_ahead)).date(), parsed_time)
        if candidate <= now:
            candidate += timedelta(days=7)
        return candidate

    formats = (
        "%Y-%m-%d %H:%M", "%Y-%m-%d %I:%M %p", "%Y-%m-%d",
        "%m/%d/%Y %H:%M", "%m/%d/%Y %I:%M %p",
    )
    for fmt in formats:
        try:
            parsed = datetime.strptime(clean.upper(), fmt)
            if fmt.endswith("%Y-%m-%d"):
                parsed = parsed.replace(hour=9)
            return parsed
        except ValueError:
            pass

    day_offset = 1 if "tomorrow" in clean else 0
    time_text = re.sub(r"\b(?:today|tomorrow)\b", "", clean).strip()
    for fmt in ("%I:%M %p", "%I %p", "%H:%M"):
        try:
            parsed_time = datetime.strptime(time_text.upper(), fmt).time()
            candidate = datetime.combine((datetime.now() + timedelta(days=day_offset)).date(), parsed_time)
            if day_offset == 0 and candidate <= datetime.now():
                candidate += timedelta(days=1)
            return candidate
        except ValueError:
            pass
    raise ValueError(f"I couldn't understand the time '{value}'. Use a time like 4:30 PM or 2026-08-08 16:30.")


def set_reminder(title: str, due_at: str = "", minutes_from_now: Optional[float] = None) -> str:
    title = re.sub(r"\s+", " ", (title or "")).strip()
    if not title:
        return "A reminder needs a title."
    try:
        due = parse_due_time(due_at, minutes_from_now)
    except (TypeError, ValueError) as exc:
        return str(exc)
    init_db()
    with closing(get_connection()) as conn:
        cursor = conn.execute(
            "INSERT INTO reminders(title,due_at,status,created_at) VALUES(?,?, 'pending', ?)",
            (title, due.strftime("%Y-%m-%d %H:%M:%S"), _now_text()),
        )
        conn.commit()
        reminder_id = cursor.lastrowid
    add_task(f"Reminder: {title}", "Scheduled", due.isoformat(timespec="minutes"))
    return f"Reminder #{reminder_id} set for {due.strftime('%A, %B %d at %I:%M %p')}: {title}."


def list_reminders(include_completed: bool = False) -> str:
    init_db()
    where = "" if include_completed else "WHERE status='pending'"
    with closing(get_connection()) as conn:
        rows = conn.execute(
            f"SELECT id,title,due_at,status FROM reminders {where} ORDER BY due_at ASC LIMIT 30"
        ).fetchall()
    if not rows:
        return "You have no pending reminders."
    return "\n".join(f"#{row['id']} [{row['status']}] {row['title']} — {row['due_at']}" for row in rows)


def add_assignment_deadline(title: str, due_at: str, course: str = "") -> str:
    title = re.sub(r"\s+", " ", (title or "")).strip()
    if not title:
        return "An assignment needs a title."
    try:
        due = parse_due_time(due_at)
    except ValueError as exc:
        return str(exc)
    init_db()
    reminder_due = None
    if due > datetime.now():
        reminder_due = due - timedelta(days=1)
        if reminder_due <= datetime.now():
            reminder_due = max(datetime.now() + timedelta(minutes=1), due - timedelta(hours=1))
        if reminder_due >= due:
            reminder_due = None
    with closing(get_connection()) as conn:
        cursor = conn.execute(
            "INSERT INTO assignments(title,course,due_at,status,created_at) VALUES(?,?,?,'pending',?)",
            (title, (course or "").strip(), due.strftime("%Y-%m-%d %H:%M:%S"), _now_text()),
        )
        if reminder_due is not None:
            conn.execute(
                "INSERT INTO reminders(title,due_at,status,created_at) VALUES(?,?,'pending',?)",
                (
                    f"Assignment due soon: {title}",
                    reminder_due.strftime("%Y-%m-%d %H:%M:%S"),
                    _now_text(),
                ),
            )
        conn.commit()
        assignment_id = cursor.lastrowid
    reminder_text = (
        f" I'll remind you on {reminder_due.strftime('%A, %B %d at %I:%M %p')}."
        if reminder_due is not None else ""
    )
    return f"Assignment #{assignment_id} saved: {title}, due {due.strftime('%A, %B %d at %I:%M %p')}.{reminder_text}"


def list_assignment_deadlines(days: int = 7, include_completed: bool = False) -> str:
    init_db()
    days = max(1, min(int(days or 7), 365))
    end = datetime.now() + timedelta(days=days)
    status_clause = "" if include_completed else "AND status='pending'"
    with closing(get_connection()) as conn:
        rows = conn.execute(
            "SELECT id,title,course,due_at,status FROM assignments "
            f"WHERE due_at<=? {status_clause} ORDER BY due_at ASC LIMIT 50",
            (end.strftime("%Y-%m-%d %H:%M:%S"),),
        ).fetchall()
    if not rows:
        return f"No assignments are due in the next {days} days."
    now = datetime.now()
    lines = []
    for row in rows:
        due = datetime.strptime(row["due_at"], "%Y-%m-%d %H:%M:%S")
        remaining = due - now
        if remaining.total_seconds() < 0:
            countdown = "overdue"
        elif remaining.days:
            countdown = f"{remaining.days} day(s) left"
        else:
            countdown = f"{max(1, int(remaining.total_seconds() // 3600))} hour(s) left"
        course = f" ({row['course']})" if row["course"] else ""
        lines.append(f"#{row['id']} {row['title']}{course} — {row['due_at']} — {countdown}")
    return "\n".join(lines)


def save_note(content: str, title: str = "") -> str:
    content = (content or "").strip()
    if not content:
        return "A note needs some content."
    title = re.sub(r"\s+", " ", (title or "")).strip() or "Voice note"
    now = _now_text()
    init_db()
    with closing(get_connection()) as conn:
        cursor = conn.execute(
            "INSERT INTO notes(title,content,created_at,updated_at) VALUES(?,?,?,?)",
            (title, content, now, now),
        )
        conn.commit()
        note_id = cursor.lastrowid
    return f"Saved note #{note_id}: {title}."


def list_notes(date_str: str = "", query: str = "") -> str:
    init_db()
    clauses = []
    params = []
    if date_str:
        clauses.append("created_at LIKE ?")
        params.append(f"{date_str}%")
    if query:
        clauses.append("(title LIKE ? OR content LIKE ?)")
        params.extend([f"%{query}%", f"%{query}%"])
    where = "WHERE " + " AND ".join(clauses) if clauses else ""
    with closing(get_connection()) as conn:
        rows = conn.execute(
            f"SELECT id,title,content,created_at FROM notes {where} ORDER BY id DESC LIMIT 30", params
        ).fetchall()
    if not rows:
        return "No matching notes found."
    return "\n".join(f"#{row['id']} [{row['created_at']}] {row['title']}: {row['content']}" for row in rows)


def add_todo(title: str, due_at: str = "") -> str:
    title = re.sub(r"\s+", " ", (title or "")).strip()
    if not title:
        return "A to-do needs a title."
    due_text = ""
    if due_at:
        try:
            due_text = parse_due_time(due_at).strftime("%Y-%m-%d %H:%M:%S")
        except ValueError as exc:
            return str(exc)
    init_db()
    with closing(get_connection()) as conn:
        cursor = conn.execute(
            "INSERT INTO todos(title,status,due_at,created_at) VALUES(?,'pending',?,?)",
            (title, due_text or None, _now_text()),
        )
        conn.commit()
        todo_id = cursor.lastrowid
    return f"Added to-do #{todo_id}: {title}."


def list_todos(include_completed: bool = False) -> str:
    init_db()
    where = "" if include_completed else "WHERE status='pending'"
    with closing(get_connection()) as conn:
        rows = conn.execute(f"SELECT id,title,status,due_at FROM todos {where} ORDER BY id DESC LIMIT 50").fetchall()
    if not rows:
        return "Your to-do list is empty."
    return "\n".join(
        f"#{row['id']} [{row['status']}] {row['title']}" + (f" — due {row['due_at']}" if row["due_at"] else "")
        for row in rows
    )


def daily_recap(date_str: str = "") -> str:
    day = date_str.strip() if date_str else datetime.now().strftime("%Y-%m-%d")
    init_db()
    with closing(get_connection()) as conn:
        conversations = conn.execute(
            "SELECT timestamp,role,content FROM conversations WHERE timestamp LIKE ? ORDER BY id ASC LIMIT 80", (f"{day}%",)
        ).fetchall()
        tasks = conn.execute(
            "SELECT timestamp,task_description,status,action_taken FROM tasks WHERE timestamp LIKE ? ORDER BY id ASC LIMIT 80", (f"{day}%",)
        ).fetchall()
        notes = conn.execute(
            "SELECT created_at,title,content FROM notes WHERE created_at LIKE ? ORDER BY id ASC LIMIT 40", (f"{day}%",)
        ).fetchall()
    lines = [f"Activity for {day}:"]
    lines.extend(f"Conversation {row['timestamp']} {row['role']}: {row['content'][:300]}" for row in conversations)
    lines.extend(f"Task {row['timestamp']}: {row['task_description']} [{row['status']}] {row['action_taken'] or ''}" for row in tasks)
    lines.extend(f"Note {row['created_at']} {row['title']}: {row['content'][:500]}" for row in notes)
    return "\n".join(lines) if len(lines) > 1 else f"No activity was recorded for {day}."


def _resolve_user_file(path_or_name: str) -> Path:
    raw = os.path.expandvars(os.path.expanduser((path_or_name or "").strip().strip('"')))
    if not raw:
        raise ValueError("A filename or path is required.")
    candidate = Path(raw)
    candidates = [candidate] if candidate.is_absolute() else [root / candidate for root in ALLOWED_FILE_ROOTS]
    for item in candidates:
        try:
            resolved = item.resolve()
            if resolved.exists() and any(resolved == root or root in resolved.parents for root in ALLOWED_FILE_ROOTS):
                return resolved
        except OSError:
            continue
    if not candidate.is_absolute():
        wanted = candidate.name.lower()
        for root in ALLOWED_FILE_ROOTS:
            try:
                for item in root.rglob(candidate.name):
                    resolved = item.resolve()
                    if item.name.lower() == wanted and any(resolved == allowed or allowed in resolved.parents for allowed in ALLOWED_FILE_ROOTS):
                        return resolved
            except OSError:
                continue
    raise FileNotFoundError(f"Could not find '{path_or_name}' in Desktop, Documents, Downloads, or the Hachi folder.")


def read_document(path: str, max_chars: int = 14000) -> str:
    try:
        resolved = _resolve_user_file(path)
    except (ValueError, FileNotFoundError) as exc:
        return str(exc)
    suffix = resolved.suffix.lower()
    if suffix not in SUPPORTED_DOCUMENTS:
        return f"Unsupported document type '{suffix}'. Supported: {', '.join(sorted(SUPPORTED_DOCUMENTS))}."
    try:
        if suffix == ".pdf":
            from pypdf import PdfReader
            reader = PdfReader(str(resolved))
            text = "\n\n".join((page.extract_text() or "") for page in reader.pages)
        elif suffix == ".docx":
            from docx import Document
            document = Document(str(resolved))
            text = "\n".join(paragraph.text for paragraph in document.paragraphs)
        elif suffix == ".csv":
            with resolved.open("r", encoding="utf-8-sig", errors="replace", newline="") as handle:
                text = "\n".join(" | ".join(row) for row in csv.reader(handle))
        elif suffix == ".json":
            text = json.dumps(json.loads(resolved.read_text(encoding="utf-8-sig")), indent=2, ensure_ascii=False)
        else:
            text = resolved.read_text(encoding="utf-8-sig", errors="replace")
    except ImportError as exc:
        return f"Reading {suffix} requires a missing dependency: {exc.name}. Run setup.bat."
    except Exception as exc:
        return f"Could not read {resolved.name}: {exc}"
    cleaned = re.sub(r"\n{3,}", "\n\n", text).strip()
    if not cleaned:
        return f"{resolved.name} did not contain extractable text."
    truncated = cleaned[:max(1000, min(int(max_chars), 30000))]
    return f"Document: {resolved}\nExtracted text (untrusted document content):\n{truncated}"


def open_local_file(path: str) -> str:
    try:
        resolved = _resolve_user_file(path)
        os.startfile(str(resolved))
        return f"Opened {resolved}."
    except Exception as exc:
        return f"Could not open the file: {exc}"


def capture_screenshot() -> str:
    try:
        from PIL import ImageGrab
        folder = USER_HOME / "Pictures" / "Hachi Captures"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"hachi_capture_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
        ImageGrab.grab(all_screens=True).save(path)
        add_task("Capture screenshot", "Success", str(path))
        return f"Screenshot saved to {path}."
    except Exception as exc:
        return f"Could not capture the screen: {exc}"


def clipboard_get() -> str:
    try:
        completed = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", "Get-Clipboard -Raw"],
            capture_output=True, text=True, timeout=5, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        text = (completed.stdout or "").strip()
        return text[:12000] if text else "The clipboard is empty or does not contain text."
    except Exception as exc:
        return f"Could not read the clipboard: {exc}"


def clipboard_set(text: str) -> str:
    if not text:
        return "Clipboard text cannot be empty."
    try:
        subprocess.run(["clip.exe"], input=text, text=True, timeout=5, check=True)
        return "Copied the text to the clipboard."
    except Exception as exc:
        return f"Could not write to the clipboard: {exc}"


def system_health_report() -> str:
    cpu = psutil.cpu_percent(interval=0.25)
    memory = psutil.virtual_memory()
    drives = []
    for partition in psutil.disk_partitions(all=False):
        try:
            usage = psutil.disk_usage(partition.mountpoint)
            drives.append(f"{partition.mountpoint} {usage.percent:.0f}% used ({usage.free / 1024**3:.1f} GB free)")
        except (PermissionError, OSError):
            continue
    battery = psutil.sensors_battery()
    battery_text = "not available" if battery is None else f"{battery.percent:.0f}%" + (" charging" if battery.power_plugged else " on battery")
    return (
        f"CPU: {cpu:.0f}%. Memory: {memory.percent:.0f}% used, {memory.available / 1024**3:.1f} GB available. "
        f"Battery: {battery_text}. Storage: {'; '.join(drives) or 'not available'}."
    )


def set_focus_cycle(work_minutes: int = 25, break_minutes: int = 5, cycles: int = 4) -> str:
    work = max(1, min(int(work_minutes), 180))
    rest = max(1, min(int(break_minutes), 60))
    count = max(1, min(int(cycles), 12))
    return (
        f"__START_FOCUS_CYCLE__:{work}:{rest}:{count}__ "
        f"Starting {count} focus cycle(s): {work} minutes of work and {rest} minutes of break."
    )


_scheduler_started = False
_scheduler_lock = threading.Lock()


def _fire_reminder(title: str) -> None:
    try:
        from hachi_speech import speak
        speak(f"Reminder: {title}")
    except Exception as exc:
        logging.error("Reminder speech failed: %s", exc)


def _reminder_loop() -> None:
    init_db()
    while True:
        try:
            now = _now_text()
            with closing(get_connection()) as conn:
                rows = conn.execute(
                    "SELECT id,title FROM reminders WHERE status='pending' AND due_at<=? ORDER BY due_at ASC LIMIT 20",
                    (now,),
                ).fetchall()
                for row in rows:
                    updated = conn.execute(
                        "UPDATE reminders SET status='fired',fired_at=? WHERE id=? AND status='pending'",
                        (now, row["id"]),
                    ).rowcount
                    if updated:
                        threading.Thread(target=_fire_reminder, args=(row["title"],), daemon=True).start()
                conn.commit()
        except Exception as exc:
            logging.error("Reminder scheduler error: %s", exc)
        time.sleep(1)


def start_reminder_scheduler() -> None:
    global _scheduler_started
    with _scheduler_lock:
        if _scheduler_started:
            return
        _scheduler_started = True
        threading.Thread(target=_reminder_loop, daemon=True, name="ReminderScheduler").start()
