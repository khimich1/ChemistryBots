import os
import sqlite3

from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
DEFAULT_USERS_DB = os.path.join(PROJECT_ROOT, "shared", "users.db")
USERS_DB = os.getenv("USERS_DB", DEFAULT_USERS_DB)


def init_users_db(path: str = USERS_DB) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with sqlite3.connect(path) as conn:
        c = conn.cursor()
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tg_id INTEGER UNIQUE,
                parent_name TEXT,
                child_nick TEXT
            )
            """
        )
        conn.commit()


def upsert_user(tg_id: int, parent_name: str | None = None, child_nick: str | None = None) -> None:
    with sqlite3.connect(USERS_DB) as conn:
        c = conn.cursor()
        c.execute("SELECT tg_id FROM users WHERE tg_id=?", (tg_id,))
        exists = c.fetchone()
        if exists:
            if parent_name is not None:
                c.execute("UPDATE users SET parent_name=? WHERE tg_id=?", (parent_name, tg_id))
            if child_nick is not None:
                c.execute("UPDATE users SET child_nick=? WHERE tg_id=?", (child_nick, tg_id))
        else:
            c.execute(
                "INSERT INTO users (tg_id, parent_name, child_nick) VALUES (?, ?, ?)",
                (tg_id, parent_name or "", child_nick or ""),
            )
        conn.commit()


def get_user(tg_id: int):
    with sqlite3.connect(USERS_DB) as conn:
        c = conn.cursor()
        c.execute("SELECT parent_name, child_nick FROM users WHERE tg_id=?", (tg_id,))
        row = c.fetchone()
        return (row[0], row[1]) if row else None


