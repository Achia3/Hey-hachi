import sqlite3
import os
import re
import threading
from datetime import datetime
from contextlib import closing

DB_PATH = os.path.join(os.path.dirname(__file__), "hachi_memory.db")

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
                mode TEXT DEFAULT 'default'
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                task_description TEXT NOT NULL,
                status TEXT NOT NULL,
                action_taken TEXT
            )
        """)
        # Indexes for faster date + content searches
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_conv_timestamp ON conversations(timestamp)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_tasks_timestamp ON tasks(timestamp)
        """)
        conn.commit()


def add_message(role: str, content: str, mode: str = "default"):
    """Log a user or assistant message with timestamp."""
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with _write_conn_lock:
        try:
            conn = _get_write_conn()
            conn.execute(
                "INSERT INTO conversations (timestamp, role, content, mode) VALUES (?, ?, ?, ?)",
                (now_str, role, content, mode)
            )
            conn.commit()
        except sqlite3.Error as e:
            # Fallback: fresh connection in case the shared one is broken
            try:
                with closing(get_connection()) as conn2:
                    conn2.execute(
                        "INSERT INTO conversations (timestamp, role, content, mode) VALUES (?, ?, ?, ?)",
                        (now_str, role, content, mode)
                    )
                    conn2.commit()
            except sqlite3.Error:
                pass
            logging_error(e)


def add_task(task_description: str, status: str, action_taken: str = ""):
    """Log a task or system action executed by Hachi."""
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with _write_conn_lock:
        try:
            conn = _get_write_conn()
            conn.execute(
                "INSERT INTO tasks (timestamp, task_description, status, action_taken) VALUES (?, ?, ?, ?)",
                (now_str, task_description, status, action_taken)
            )
            conn.commit()
        except sqlite3.Error as e:
            try:
                with closing(get_connection()) as conn2:
                    conn2.execute(
                        "INSERT INTO tasks (timestamp, task_description, status, action_taken) VALUES (?, ?, ?, ?)",
                        (now_str, task_description, status, action_taken)
                    )
                    conn2.commit()
            except sqlite3.Error:
                pass
            logging_error(e)


def _like_escape(term: str) -> str:
    """Escape LIKE wildcards so user input is matched literally."""
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _valid_date(date_str: str) -> bool:
    """Accept only YYYY-MM-DD; anything else is treated as no date filter."""
    return bool(date_str and re.fullmatch(r"\d{4}-\d{2}-\d{2}", date_str.strip()))


def search_history(query: str = None, date_str: str = None, limit: int = 10):
    """
    Search conversation and task history by text query and/or specific date (YYYY-MM-DD).
    Text queries search BOTH conversations and tasks. LIKE wildcards are escaped.
    Fetches N most recent rows (DESC), then reverses for chronological display.
    Returns formatted summary string for LLM context.
    """
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


def get_recent_messages(limit: int = 8):
    """Return the most recent conversation turns as [{'role','content'}, ...]
    in chronological order — used to preload cross-session memory so the model
    can 'remember' past chats. limit is the number of turns (default 8)."""
    try:
        limit = max(2, min(int(limit or 8), 30))
    except (TypeError, ValueError):
        limit = 8
    msgs = []
    with closing(get_connection()) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT role, content FROM conversations "
            "WHERE content <> '' AND role IN ('user','assistant') "
            "ORDER BY id DESC LIMIT ?",
            (limit,)
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
