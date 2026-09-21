import sqlite3
from pathlib import Path
from datetime import datetime

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "copilot.db"


def get_connection():
    DB_PATH.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_connection()

    conn.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            zone TEXT,
            created_at TEXT NOT NULL
        )
    """)

    conn.commit()
    conn.close()


def save_message(conversation_id, role, content, zone=None):
    conn = get_connection()

    conn.execute(
        """
        INSERT INTO messages
        (conversation_id, role, content, zone, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            conversation_id,
            role,
            content,
            zone,
            datetime.utcnow().isoformat()
        )
    )

    conn.commit()
    conn.close()


def get_history(conversation_id, limit=12):
    conn = get_connection()

    rows = conn.execute(
        """
        SELECT role, content
        FROM messages
        WHERE conversation_id = ?
        ORDER BY id DESC
        LIMIT ?
        """,
        (conversation_id, limit)
    ).fetchall()

    conn.close()

    return [
        {
            "role": row["role"],
            "content": row["content"]
        }
        for row in reversed(rows)
    ]