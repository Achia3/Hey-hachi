import sqlite3
import os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), "hachi_memory.db")


def get_connection():
    """
    Connect to SQLite database.
    check_same_thread=False allows Flask's threaded server to share connections.
    WAL journal mode is enabled for better concurrent write performance.
    """
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    """
    Initialize database tables and indexes if they do not exist.
    Called ONCE at startup (not on every operation).
    """
    with get_connection() as conn:
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
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO conversations (timestamp, role, content, mode) VALUES (?, ?, ?, ?)",
            (now_str, role, content, mode)
        )
        conn.commit()


def add_task(task_description: str, status: str, action_taken: str = ""):
    """Log a task or system action executed by Hachi."""
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO tasks (timestamp, task_description, status, action_taken) VALUES (?, ?, ?, ?)",
            (now_str, task_description, status, action_taken)
        )
        conn.commit()


def search_history(query: str = None, date_str: str = None, limit: int = 10):
    """
    Search conversation and task history by text query or specific date (YYYY-MM-DD).
    Fetches N most recent rows (DESC), then reverses for chronological display.
    Returns formatted summary string for LLM context.
    """
    results = []
    with get_connection() as conn:
        cursor = conn.cursor()

        # Search conversations
        if date_str and query:
            cursor.execute(
                "SELECT timestamp, role, content, mode FROM conversations WHERE timestamp LIKE ? AND content LIKE ? ORDER BY id DESC LIMIT ?",
                (f"{date_str}%", f"%{query}%", limit)
            )
        elif date_str:
            cursor.execute(
                "SELECT timestamp, role, content, mode FROM conversations WHERE timestamp LIKE ? ORDER BY id DESC LIMIT ?",
                (f"{date_str}%", limit)
            )
        elif query:
            cursor.execute(
                "SELECT timestamp, role, content, mode FROM conversations WHERE content LIKE ? ORDER BY id DESC LIMIT ?",
                (f"%{query}%", limit)
            )
        else:
            cursor.execute(
                "SELECT timestamp, role, content, mode FROM conversations ORDER BY id DESC LIMIT ?",
                (limit,)
            )

        rows = cursor.fetchall()
        # reversed() puts DESC-fetched rows back into chronological (ASC) order
        for r in reversed(rows):
            results.append(f"[{r['timestamp']}] ({r['mode']}) {r['role'].capitalize()}: {r['content']}")

        # Also fetch tasks for date search
        if date_str:
            cursor.execute(
                "SELECT timestamp, task_description, status, action_taken FROM tasks WHERE timestamp LIKE ? ORDER BY id DESC LIMIT ?",
                (f"{date_str}%", limit)
            )
            task_rows = cursor.fetchall()
            if task_rows:
                results.append("\nTasks Executed on this Date:")
                for t in reversed(task_rows):
                    results.append(f"[{t['timestamp']}] Task: {t['task_description']} | Status: {t['status']} | Action: {t['action_taken']}")

    if not results:
        return f"No history found matching query='{query}' date='{date_str}'."
    return "\n".join(results)


if __name__ == "__main__":
    init_db()
    print("SQLite memory database initialized successfully.")
