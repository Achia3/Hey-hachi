import sqlite3
import os
import re
import threading
import shutil
from datetime import datetime
from contextlib import closing


def _default_db_path() -> str:
    """Keep mutable user data outside the source checkout.

    Older Hachi versions wrote a tracked ``hachi_memory.db`` next to the code.
    On the first run of this version, copy that database into the user's local
    application-data directory so existing conversations are retained.  The
    copy is deliberately non-destructive: the legacy file remains untouched.
    """
    app_dir = os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "Hachi")
    path = os.path.join(app_dir, "hachi_memory.db")
    legacy = os.path.join(os.path.dirname(__file__), "hachi_memory.db")
    try:
        if not os.path.exists(path):
            os.makedirs(app_dir, exist_ok=True)
            if os.path.exists(legacy):
                shutil.copy2(legacy, path)
    except OSError:
        # A read-only profile should not prevent the application from opening.
        return legacy
    return path


DB_PATH = _default_db_path()

# Shared write connection (WAL) + lock — avoids open/close + fsync per message.
_write_conn = None
_write_conn_lock = threading.Lock()
_CONN_LOCK_TIMEOUT = 5.0


def get_connection():
    """
    Fresh read connection. WAL journal mode enables concurrent reads.
    Callers MUST wrap with contextlib.closing(...) — this connection is never closed by `with`.
    """
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _get_write_conn():
    """Lazily create the single shared write connection (safe under _write_conn_lock)."""
    global _write_conn
    if _write_conn is None:
        _write_conn = sqlite3.connect(DB_PATH, timeout=_CONN_LOCK_TIMEOUT, check_same_thread=False)
        _write_conn.row_factory = sqlite3.Row
        _write_conn.execute("PRAGMA journal_mode=WAL")
        _write_conn.execute("PRAGMA busy_timeout=5000")
    return _write_conn


def init_db():
    """
    Initialize database tables and indexes if they do not exist.
    Called ONCE at startup (not on every operation).
    """
    with closing(get_connection()) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                mode TEXT DEFAULT 'default',
                conversation_id TEXT NOT NULL DEFAULT 'default'
            )
        """)
        # Safe schema migration for databases made by earlier Hachi versions.
        columns = {row["name"] for row in cursor.execute("PRAGMA table_info(conversations)")}
        if "conversation_id" not in columns:
            cursor.execute("ALTER TABLE conversations ADD COLUMN conversation_id TEXT NOT NULL DEFAULT 'default'")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                task_description TEXT NOT NULL,
                status TEXT NOT NULL,
                action_taken TEXT,
                conversation_id TEXT NOT NULL DEFAULT 'default'
            )
        """)
        task_columns = {row["name"] for row in cursor.execute("PRAGMA table_info(tasks)")}
        if "conversation_id" not in task_columns:
            cursor.execute("ALTER TABLE tasks ADD COLUMN conversation_id TEXT NOT NULL DEFAULT 'default'")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL DEFAULT 'local',
                agent_id TEXT NOT NULL DEFAULT 'hachi',
                category TEXT NOT NULL,
                subject TEXT NOT NULL,
                content TEXT NOT NULL,
                embedding TEXT,
                confidence REAL NOT NULL DEFAULT 1.0,
                source TEXT NOT NULL DEFAULT 'explicit',
                status TEXT NOT NULL DEFAULT 'active',
                supersedes_id INTEGER,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS reminders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                due_at TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL,
                fired_at TEXT
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS assignments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                course TEXT DEFAULT '',
                due_at TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS todos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                due_at TEXT,
                created_at TEXT NOT NULL,
                completed_at TEXT
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS assistant_state (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        # Indexes for faster date + content searches
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_conv_timestamp ON conversations(timestamp)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_conv_conversation_timestamp
            ON conversations(conversation_id, timestamp, id)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_tasks_timestamp ON tasks(timestamp)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_tasks_conversation_timestamp
            ON tasks(conversation_id, timestamp, id)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_memory_scope_subject
            ON memories(user_id, agent_id, category, subject, status)
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_reminders_due ON reminders(status, due_at)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_assignments_due ON assignments(status, due_at)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_notes_created ON notes(created_at)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_todos_status ON todos(status, due_at)")
        conn.commit()


def add_message(role: str, content: str, mode: str = "default", conversation_id: str = "default"):
    """Log a user or assistant message with timestamp."""
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with _write_conn_lock:
        try:
            conn = _get_write_conn()
            conn.execute(
                "INSERT INTO conversations (timestamp, role, content, mode, conversation_id) VALUES (?, ?, ?, ?, ?)",
                (now_str, role, content, mode, _conversation_id(conversation_id))
            )
            conn.commit()
        except sqlite3.Error as e:
            # Fallback: fresh connection in case the shared one is broken
            try:
                with closing(get_connection()) as conn2:
                    conn2.execute(
                        "INSERT INTO conversations (timestamp, role, content, mode, conversation_id) VALUES (?, ?, ?, ?, ?)",
                        (now_str, role, content, mode, _conversation_id(conversation_id))
                    )
                    conn2.commit()
            except sqlite3.Error:
                pass
            logging_error(e)


def add_task(task_description: str, status: str, action_taken: str = "", conversation_id: str = "default"):
    """Log a task or system action executed by Hachi."""
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with _write_conn_lock:
        try:
            conn = _get_write_conn()
            conn.execute(
                "INSERT INTO tasks (timestamp, task_description, status, action_taken, conversation_id) VALUES (?, ?, ?, ?, ?)",
                (now_str, task_description, status, action_taken, _conversation_id(conversation_id))
            )
            conn.commit()
        except sqlite3.Error as e:
            try:
                with closing(get_connection()) as conn2:
                    conn2.execute(
                        "INSERT INTO tasks (timestamp, task_description, status, action_taken, conversation_id) VALUES (?, ?, ?, ?, ?)",
                        (now_str, task_description, status, action_taken, _conversation_id(conversation_id))
                    )
                    conn2.commit()
            except sqlite3.Error:
                pass
            logging_error(e)


def _like_escape(term: str) -> str:
    """Escape LIKE wildcards so user input is matched literally."""
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _conversation_id(value: object) -> str:
    """Constrain an external UI identifier before persisting it."""
    clean = re.sub(r"[^a-zA-Z0-9_-]", "", str(value or ""))[:80]
    return clean or "default"


def _valid_date(date_str: str) -> bool:
    """Accept only YYYY-MM-DD; anything else is treated as no date filter."""
    return bool(date_str and re.fullmatch(r"\d{4}-\d{2}-\d{2}", date_str.strip()))


def search_history(query: str = None, date_str: str = None, limit: int = 10, conversation_id: str = None):
    """
    Search conversation and task history by text query and/or specific date (YYYY-MM-DD).
    Text queries search BOTH conversations and tasks. LIKE wildcards are escaped.
    Fetches N most recent rows (DESC), then reverses for chronological display.
    Returns formatted summary string for LLM context.
    """
    init_db()
    try:
        limit = max(1, min(int(limit or 10), 50))
    except (TypeError, ValueError):
        limit = 10

    query = (query or "").strip()
    date_str = (date_str or "").strip()
    if not _valid_date(date_str):
        date_str = ""

    like_term = f"%{_like_escape(query)}%" if query else None
    results = []

    with closing(get_connection()) as conn:
        cursor = conn.cursor()

        # ── Conversations ──────────────────────────────────────────────────
        sql = "SELECT timestamp, role, content, mode FROM conversations"
        params = []
        where = []
        if conversation_id is not None:
            where.append("conversation_id = ?")
            params.append(_conversation_id(conversation_id))
        if date_str:
            where.append("timestamp LIKE ?")
            params.append(f"{date_str}%")
        if like_term:
            where.append("content LIKE ? ESCAPE '\\'")
            params.append(like_term)
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY id DESC LIMIT ?"
        params.append(limit)

        cursor.execute(sql, params)
        rows = cursor.fetchall()
        # reversed() puts DESC-fetched rows back into chronological (ASC) order
        for r in reversed(rows):
            content = (r["content"] or "").strip()
            if not content:      # skip malformed empty rows
                continue
            results.append(f"[{r['timestamp']}] ({r['mode']}) {r['role'].capitalize()}: {content}")

        # ── Tasks (searched for text queries too — symmetric with conversations) ──
        t_sql = "SELECT timestamp, task_description, status, action_taken FROM tasks"
        t_params = []
        t_where = []
        if conversation_id is not None:
            t_where.append("conversation_id = ?")
            t_params.append(_conversation_id(conversation_id))
        if date_str:
            t_where.append("timestamp LIKE ?")
            t_params.append(f"{date_str}%")
        if like_term:
            t_where.append("task_description LIKE ? ESCAPE '\\'")
            t_params.append(like_term)
        if t_where:
            t_sql += " WHERE " + " AND ".join(t_where)
        t_sql += " ORDER BY id DESC LIMIT ?"
        t_params.append(limit)

        cursor.execute(t_sql, t_params)
        task_rows = cursor.fetchall()
        if task_rows:
            if results:
                results.append("")
            results.append("Tasks:")
            for t in reversed(task_rows):
                results.append(
                    f"[{t['timestamp']}] Task: {t['task_description']} | Status: {t['status']} | Action: {t['action_taken']}"
                )

    if not results:
        return f"No history found matching query='{query}' date='{date_str}'."
    return "\n".join(results)


def get_recent_messages(limit: int = 8, conversation_id: str = "default"):
    """Return the most recent conversation turns as [{'role','content'}, ...]
    in chronological order — used to preload cross-session memory so the model
    can 'remember' past chats. limit is the number of turns (default 8)."""
    init_db()
    try:
        limit = max(2, min(int(limit or 8), 30))
    except (TypeError, ValueError):
        limit = 8
    msgs = []
    with closing(get_connection()) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT role, content FROM conversations "
            "WHERE content <> '' AND role IN ('user','assistant') AND conversation_id = ? "
            "ORDER BY id DESC LIMIT ?",
            (_conversation_id(conversation_id), limit),
        )
        rows = cursor.fetchall()
        # reverse to chronological
        for r in reversed(rows):
            content = (r["content"] or "").strip()
            if content:
                msgs.append({"role": r["role"], "content": content})
    return msgs


def logging_error(e):
    """Best-effort error logging without importing logging at module top."""
    try:
        import logging
        logging.error(f"hachi_db write error: {e}")
    except Exception:
        pass


if __name__ == "__main__":
    init_db()
    print("SQLite memory database initialized successfully.")
